"""The company's pipe support template library (style folders -> size folders -> draft)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .jobfolder import drafts_in


@dataclass(frozen=True)
class Template:
    code: str        # "P10-8"
    folder: Path
    dft: Path


def _natural_key(text: str):
    """Sort "P10-2" before "P10-10" and "S2-1.5" between S2-1 and S2-2."""
    return [(0, float(part), "") if part.replace(".", "", 1).isdigit() else (1, 0.0, part.lower())
            for part in re.split(r"(\d+(?:\.\d+)?)", text) if part]


def _pick_draft(folder: Path) -> Path | None:
    drafts = drafts_in(folder)
    for d in drafts:
        if d.stem.lower() == folder.name.lower():
            return d
    return drafts[0] if len(drafts) == 1 else None


class TemplateLibrary:
    def __init__(self, root: Path):
        self.root = root
        self._styles: list[str] | None = None

    def available(self) -> bool:
        return self.root.is_dir()

    def styles(self) -> list[str]:
        if self._styles is None:
            try:
                self._styles = sorted((p.name for p in self.root.iterdir() if p.is_dir()), key=_natural_key)
            except OSError:
                self._styles = []
        return self._styles

    def sizes(self, style: str) -> list[Template]:
        folder = self.root / style
        try:
            subfolders = [p for p in folder.iterdir() if p.is_dir()]
        except OSError:
            return []
        found = []
        for sub in subfolders:
            dft = _pick_draft(sub)
            if dft:
                found.append(Template(sub.name, sub, dft))
        return sorted(found, key=lambda t: _natural_key(t.code))

    def find(self, code: str) -> Template | None:
        """Look up "P10-8" -> <root>\\P10\\P10-8\\P10-8.dft (case-insensitive)."""
        code = code.strip()
        if not code:
            return None
        style = code.rsplit("-", 1)[0] if "-" in code else code
        candidates = [s for s in self.styles() if s.lower() == style.lower()]
        candidates += [s for s in self.styles() if s not in candidates]   # fall back to every style
        for style_name in candidates:
            style_dir = self.root / style_name
            try:
                match = next((p for p in style_dir.iterdir()
                              if p.is_dir() and p.name.lower() == code.lower()), None)
            except OSError:
                continue
            if match:
                dft = _pick_draft(match)
                if dft:
                    return Template(match.name, match, dft)
        return None


def split_codes(text: str) -> list[str]:
    """ "D6-36, P10-8; P20-20" -> ["D6-36", "P10-8", "P20-20"] """
    return [c for c in re.split(r"[,;\s]+", text) if c]
