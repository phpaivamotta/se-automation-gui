"""The long-running jobs the GUI starts: apply a drawing plan, set title blocks, print PDFs.

Everything that talks to Solid Edge is passed in, so the file handling can be
tested without it.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from . import naming
from .com import describe_error
from .plan import Plan, PlannedRow
from .titleblock import DRAWING_NUMBER

PropertyValues = dict[tuple[str, str], str]


class Cancelled(Exception):
    pass


class Reporter(Protocol):
    def log(self, message: str, level: str = "info") -> None: ...
    def progress(self, done: int, total: int, text: str = "") -> None: ...
    def cancelled(self) -> bool: ...


class PrintReporter:
    """Console reporter (handy for scripts and tests)."""

    def log(self, message: str, level: str = "info") -> None:
        print(f"[{level}] {message}")

    def progress(self, done: int, total: int, text: str = "") -> None:
        pass

    def cancelled(self) -> bool:
        return False


class PropertyWriter(Protocol):
    def write(self, dft: Path, values: PropertyValues, leave_open: bool) -> list[str]: ...


class DraftPropertyWriter:
    """Writes title block properties.

    Drafts that aren't open are written directly to the file (fast; Solid Edge
    shows the new values the next time the draft is opened). Drafts already open
    in Solid Edge are updated and saved through Solid Edge instead.
    """

    def __init__(self, se, write_file=None, open_documents=None):
        from . import solidedge
        self.se = se
        self._write_file = write_file or solidedge.write_file_properties
        self._open_documents = open_documents or solidedge.SolidEdge.open_documents_if_running

    def write(self, dft: Path, values: PropertyValues, leave_open: bool) -> list[str]:
        target = os.path.normcase(os.path.abspath(dft))
        if any(os.path.normcase(os.path.abspath(d)) == target for d in self._open_documents()):
            doc, _ = self.se.open(dft)
            missing = self.se.set_properties(doc, values)
            self.se.save(doc)
            return missing
        missing = self._write_file(dft, values)
        if leave_open:
            self.se.open(dft)
        return missing


Copier = Callable[[Path, Path], Path]   # (source draft, destination folder) -> copied draft


@dataclass
class ApplyResult:
    renamed: list[tuple[str, str]] = field(default_factory=list)   # (old name, new name)
    copied: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    property_problems: list[str] = field(default_factory=list)
    changed_drafts: list[Path] = field(default_factory=list)       # need new PDFs
    stale_pdfs: list[Path] = field(default_factory=list)


# --- file helpers --------------------------------------------------------------

_LOCK_HINT = ("A file in it is probably open in Solid Edge, a File Explorer preview, or by "
              "another user. Close it and try again.")


def _rename(src: Path, dst: Path, attempts: int = 6) -> None:
    for attempt in range(attempts):
        try:
            os.rename(src, dst)
            return
        except PermissionError as e:
            # Explorer thumbnails / antivirus hold files briefly; give them a moment.
            if attempt == attempts - 1:
                raise PermissionError(f"Windows wouldn't rename \"{src.name}\". {_LOCK_HINT}") from e
            time.sleep(0.5)


def _open_under(folders: Iterable[Path], open_docs: Iterable[str]) -> list[str]:
    roots = [os.path.normcase(str(f)) + os.sep for f in folders]
    return [d for d in open_docs if any(os.path.normcase(d).startswith(r) for r in roots)]


# --- apply a drawing plan ------------------------------------------------------

def rename_existing(plan: Plan, reporter: Reporter) -> list[tuple[PlannedRow, Path]]:
    """Rename/renumber existing drawing folders and drafts.

    Folders are first moved to temporary names and then to their final names, so
    shifting 0103 -> 0104 never collides with the old 0104. Any failure puts every
    folder back where it was.
    """
    renames = plan.renames
    if not renames:
        return []
    token = uuid.uuid4().hex[:6]
    done: list[tuple[Path, Path]] = []
    results: list[tuple[PlannedRow, Path]] = []
    try:
        staged: dict[int, Path] = {}
        for i, p in enumerate(renames):
            current = p.row.existing.folder
            if p.folder_changes:
                tmp = plan.target / f"~renumber-{token}-{i:04d}"
                _rename(current, tmp)
                done.append((current, tmp))
                staged[p.row.uid] = tmp
            else:
                staged[p.row.uid] = current
        for p in renames:
            final = plan.target / p.name
            if staged[p.row.uid] != final:
                _rename(staged[p.row.uid], final)
                done.append((staged[p.row.uid], final))
            new_dft = final / f"{p.name}.dft"
            old_dft = p.row.existing.dft
            if old_dft is not None:
                old_dft = final / old_dft.name
                if old_dft.name != new_dft.name:
                    if new_dft.exists() and not os.path.samefile(old_dft, new_dft):
                        raise FileExistsError(f"{final.name} already contains a draft named {new_dft.name}.")
                    _rename(old_dft, new_dft)
                    done.append((old_dft, new_dft))
                results.append((p, new_dft))
            else:
                results.append((p, None))
            reporter.log(f"Renamed {p.old_name}  ->  {p.name}")
    except Exception:
        reporter.log("Renaming failed - putting everything back the way it was...", "warning")
        for src, dst in reversed(done):
            try:
                os.rename(dst, src)
            except OSError as undo_error:
                reporter.log(f"COULD NOT UNDO: rename \"{dst}\" back to \"{src.name}\" by hand "
                             f"({undo_error}).", "error")
        raise
    return results


def apply_plan(plan: Plan, *, copier: Copier, writer: PropertyWriter | None,
               title_values: PropertyValues, fill_title_block: bool, leave_new_open: bool,
               open_documents: Callable[[], list[str]], pdf_folders: list[Path],
               reporter: Reporter) -> ApplyResult:
    if not plan.ok:
        raise ValueError("The plan has errors:\n" + "\n".join(plan.errors))
    result = ApplyResult()

    # 1. Make room: renumber/rename existing drawings (all-or-nothing).
    if plan.renames:
        busy = _open_under([p.row.existing.folder for p in plan.renames], open_documents())
        if busy:
            raise RuntimeError("These drawings are open in Solid Edge and need to be renamed. "
                               "Save and close them first:\n" + "\n".join(busy))
        reporter.log(f"Renaming {len(plan.renames)} existing drawing(s)...")
        renamed = rename_existing(plan, reporter)
        for p, new_dft in renamed:
            result.renamed.append((p.old_name, p.name))
            if p.number_changes and new_dft is not None:
                result.changed_drafts.append(new_dft)
            for folder in pdf_folders:
                stale = folder / f"{p.old_name}.pdf"
                if stale.exists():
                    result.stale_pdfs.append(stale)
    else:
        renamed = []

    # 2. Copy new drawings in with Design Manager.
    copies = plan.copies
    new_drafts: list[tuple[PlannedRow, Path]] = []
    for i, p in enumerate(copies):
        if reporter.cancelled():
            result.failed.extend(c.name for c in copies[i:])
            reporter.log("Cancelled - remaining new drawings were not copied.", "warning")
            break
        reporter.progress(i, len(copies), f"Copying {p.name}")
        dest = plan.target / p.name
        try:
            dest.mkdir(exist_ok=True)
            if any(dest.iterdir()):
                raise FileExistsError(f"{dest} already has files in it.")
            reporter.log(f"Copying {p.row.source_dft}  ->  {p.name}")
            copied = copier(p.row.source_dft, dest)
            final = dest / f"{p.name}.dft"
            if copied.name != final.name:
                _rename(copied, final)
            new_drafts.append((p, final))
            result.copied.append(p.name)
            result.changed_drafts.append(final)
        except Exception as e:  # keep going with the other drawings
            result.failed.append(p.name)
            reporter.log(f"Could not copy {p.name}: {describe_error(e)}", "error")
            try:
                if dest.exists() and not any(dest.iterdir()):
                    dest.rmdir()
            except OSError:
                pass
    reporter.progress(len(copies), len(copies))

    # 3. Title block / drawing number properties.
    if writer is not None:
        updates: list[tuple[Path, PropertyValues, bool]] = []
        for p, dft in new_drafts:
            values = dict(title_values) if fill_title_block else {}
            values[DRAWING_NUMBER] = naming.format_number(p.number)
            updates.append((dft, values, leave_new_open))
        for p, dft in renamed:
            if p.number_changes and dft is not None:
                updates.append((dft, {DRAWING_NUMBER: naming.format_number(p.number)}, False))
        result.property_problems += write_properties(writer, updates, reporter)
    return result


def write_properties(writer: PropertyWriter, updates: list[tuple[Path, PropertyValues, bool]],
                     reporter: Reporter) -> list[str]:
    problems: list[str] = []
    missing_all: set[str] = set()
    for i, (dft, values, leave_open) in enumerate(updates):
        if reporter.cancelled():
            problems.append(f"Cancelled before updating {len(updates) - i} drawing(s).")
            break
        reporter.progress(i, len(updates), f"Title block: {dft.name}")
        try:
            missing = writer.write(dft, values, leave_open)
            missing_all.update(missing)
            reporter.log(f"Updated title block: {dft.name}")
        except Exception as e:
            problems.append(f"{dft.name}: {describe_error(e)}")
            reporter.log(f"Could not update {dft.name}: {describe_error(e)}", "error")
    reporter.progress(len(updates), len(updates))
    if missing_all:
        msg = "These properties don't exist in some drawings and were skipped: " + ", ".join(sorted(missing_all))
        reporter.log(msg, "warning")
        problems.append(msg)
    return problems


# --- title block on any drawings ---------------------------------------------------

def apply_title_block(writer: PropertyWriter, drafts: list[Path], values: PropertyValues,
                      set_drawing_number: bool, leave_open: bool, reporter: Reporter) -> list[str]:
    updates = []
    for dft in drafts:
        per_file = dict(values)
        if set_drawing_number:
            number = naming.drawing_number_from_name(dft.stem)
            if number:
                per_file[DRAWING_NUMBER] = number
            else:
                reporter.log(f"{dft.name}: can't tell the drawing number from the name; left as is.", "warning")
        if per_file:
            updates.append((dft, per_file, leave_open))
    return write_properties(writer, updates, reporter)


# --- PDFs -------------------------------------------------------------------------

@dataclass
class PdfOutput:
    label: str
    folder: Path
    sheets: str | None     # None = all sheets


def print_pdfs(se, drafts: list[Path], outputs: list[PdfOutput], close_after: bool,
               reporter: Reporter) -> list[str]:
    problems: list[str] = []
    se.begin_pdf_batch()
    try:
        for i, dft in enumerate(drafts):
            if reporter.cancelled():
                problems.append(f"Cancelled - {len(drafts) - i} drawing(s) not printed.")
                break
            reporter.progress(i, len(drafts), f"PDF: {dft.name}")
            try:
                doc, was_open = se.open(dft)
                try:
                    if not se.activate_first_sheet(doc):
                        problems.append(f"{dft.name}: no sheets to print")
                        continue
                    for out in outputs:
                        pdf = out.folder / f"{dft.stem}.pdf"
                        se.export_pdf(doc, pdf, out.sheets)
                        reporter.log(f"{out.label}: {pdf}")
                finally:
                    if close_after and not was_open:
                        se.close(doc)
            except Exception as e:
                problems.append(f"{dft.name}: {describe_error(e)}")
                reporter.log(f"Could not print {dft.name}: {describe_error(e)}", "error")
    finally:
        se.end_pdf_batch()
    reporter.progress(len(drafts), len(drafts))
    return problems
