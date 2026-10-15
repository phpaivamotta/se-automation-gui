"""Reading what's already in a drawings folder."""

from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import naming


@dataclass
class ExistingDrawing:
    folder: Path
    dft: Path | None          # the draft that carries the folder's name (renamed with it)
    prefix: str
    number: int
    description: str
    note: str = ""


@dataclass
class ScanResult:
    drawings: list[ExistingDrawing] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)   # sub-folders that aren't drawings

    @property
    def common_prefix(self) -> str | None:
        counts = Counter(d.prefix for d in self.drawings)
        return counts.most_common(1)[0][0] if counts else None

    @property
    def first_number(self) -> int | None:
        return min((d.number for d in self.drawings), default=None)


def _is_draft(name: str) -> bool:
    return name.lower().endswith(".dft") and not name.startswith(("~", "."))


def drafts_in(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and _is_draft(p.name))
    except OSError:
        return []


def main_draft(folder: Path) -> tuple[Path | None, str]:
    """The draft that is named after its folder (or the only draft in it)."""
    drafts = drafts_in(folder)
    for d in drafts:
        if d.stem.lower() == folder.name.lower():
            return d, ""
    if len(drafts) == 1:
        return drafts[0], ""
    if not drafts:
        return None, "no draft (.dft) in folder"
    return None, f"{len(drafts)} drafts and none named after the folder; drafts won't be renamed"


def scan_drawings_folder(target: Path, prefix_hint: str | None = None) -> ScanResult:
    """List the support folders directly inside ``target``, sorted by drawing number."""
    result = ScanResult()
    try:
        subfolders = sorted(p for p in target.iterdir() if p.is_dir())
    except OSError:
        return result
    for folder in subfolders:
        parsed = naming.parse_name(folder.name, prefix_hint)
        if not parsed:
            result.ignored.append(folder.name)
            continue
        dft, note = main_draft(folder)
        if dft is None and not drafts_in(folder):
            result.ignored.append(folder.name)
            continue
        result.drawings.append(ExistingDrawing(folder, dft, parsed.prefix, parsed.number,
                                               parsed.description, note))
    result.drawings.sort(key=lambda d: (d.number, d.folder.name.lower()))
    return result


def list_drafts(root: Path, max_depth: int = 2, limit: int = 5000, time_budget: float = 15.0) -> list[Path]:
    """Drafts under ``root`` (used by the title block and PDF tabs).

    Depth 2 covers "Working Drawings\\<drawing>\\x.dft" and
    "Working Drawings\\Area 2\\<drawing>\\x.dft". Depth, count and time are capped so
    picking a huge folder by mistake (e.g. F:\\MAS\\Jobs) doesn't crawl the network share.
    """
    found: list[Path] = []
    if not root.is_dir():
        return found
    base_depth = len(root.parts)
    deadline = time.monotonic() + time_budget
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base_depth
        if depth >= max_depth:
            dirnames.clear()
        dirnames.sort(key=str.lower)
        found.extend(Path(dirpath, f) for f in sorted(filenames, key=str.lower) if _is_draft(f))
        if len(found) >= limit or time.monotonic() > deadline:
            break
    return found[:limit]
