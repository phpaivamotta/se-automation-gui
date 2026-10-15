"""Turn the ordered drawing list into concrete file operations.

The list shown in the GUI is the desired final order. Numbers are assigned
sequentially from the first number, so inserting a support pushes every
support after it down by one.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path

from . import naming
from .jobfolder import ExistingDrawing

_uids = itertools.count(1)

MAX_PATH_WARN = 240


@dataclass
class Row:
    """One support in the desired order (either already on disk or to be copied in)."""

    description: str
    existing: ExistingDrawing | None = None
    source_dft: Path | None = None      # new rows: draft to copy with Design Manager
    source_label: str = ""              # new rows: "template P10-8", "copy of 4080-0102-P10-8"...
    uid: int = field(default_factory=lambda: next(_uids))

    @property
    def is_new(self) -> bool:
        return self.existing is None


@dataclass
class PlannedRow:
    row: Row
    number: int
    name: str

    @property
    def folder_changes(self) -> bool:
        ex = self.row.existing
        return ex is not None and ex.folder.name != self.name

    @property
    def draft_changes(self) -> bool:
        ex = self.row.existing
        return ex is not None and ex.dft is not None and ex.dft.stem != self.name

    @property
    def is_rename(self) -> bool:
        return self.folder_changes or self.draft_changes

    @property
    def number_changes(self) -> bool:
        ex = self.row.existing
        return ex is not None and ex.number != self.number

    @property
    def old_name(self) -> str | None:
        return self.row.existing.folder.name if self.row.existing else None

    @property
    def status(self) -> str:
        row = self.row
        if row.is_new:
            return f"NEW - {row.source_label}" if row.source_label else "NEW"
        if self.number_changes:
            return f"renumber (was {naming.format_number(row.existing.number)})"
        if self.is_rename:
            return f"rename (was {self.old_name})" if self.folder_changes else "fix draft name"
        return row.existing.note or "no change"


@dataclass
class Plan:
    target: Path
    items: list[PlannedRow]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def renames(self) -> list[PlannedRow]:
        return [p for p in self.items if p.is_rename]

    @property
    def copies(self) -> list[PlannedRow]:
        return [p for p in self.items if p.row.is_new]

    @property
    def has_changes(self) -> bool:
        return bool(self.renames or self.copies)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_plan(target: Path, rows: list[Row], prefix: str, start: int,
               ignored_folders: list[str] = ()) -> Plan:
    plan = Plan(target, [])
    prefix = prefix.strip()

    err = naming.validate_name_part(prefix, "Drawing prefix")
    if err:
        plan.errors.append(err)
    if not 1 <= start <= naming.MAX_NUMBER:
        plan.errors.append("First number must be between 0001 and 9999.")
        start = 1
    if rows and start + len(rows) - 1 > naming.MAX_NUMBER:
        plan.errors.append("Too many drawings for 4-digit numbers starting at "
                           f"{naming.format_number(start)}.")

    for i, row in enumerate(rows):
        number = min(start + i, naming.MAX_NUMBER)
        plan.items.append(PlannedRow(row, number, naming.format_name(prefix, number, row.description)))
        err = naming.validate_name_part(row.description, f"Description of drawing {naming.format_number(number)}")
        if err:
            plan.errors.append(err)
        if row.is_new and (row.source_dft is None or not row.source_dft.is_file()):
            plan.errors.append(f"Source draft for {plan.items[-1].name} not found: {row.source_dft}")

    # Two drawings can't end up with the same name.
    seen: dict[str, str] = {}
    for p in plan.items:
        key = p.name.lower()
        if key in seen:
            plan.errors.append(f"Two drawings would both be named {p.name}.")
        seen[key] = p.name

    # Folders we don't manage must not be overwritten. Folders of drawings that
    # are in the list are moved out of the way first, so they don't count.
    blocked = {name.lower() for name in ignored_folders}
    for p in plan.items:
        if p.name.lower() in blocked:
            plan.errors.append(f"A folder named {p.name} already exists and isn't a drawing "
                               "folder this app recognizes. Rename or move it first.")

    for p in plan.items:
        dft_path = target / p.name / f"{p.name}.dft"
        if len(str(dft_path)) > MAX_PATH_WARN:
            plan.warnings.append(f"Path is very long ({len(str(dft_path))} characters) and may "
                                 f"fail on Windows: {dft_path}")
        if p.row.existing and p.row.existing.note and p.is_rename:
            plan.warnings.append(f"{p.row.existing.folder.name}: {p.row.existing.note}")

    return plan
