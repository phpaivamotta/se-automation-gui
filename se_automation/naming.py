"""Drawing naming rules.

Every support lives in a folder named ``{prefix}-{number}-{description}`` and the
draft inside it has the same name, e.g. ``4080-0103-P10-8\\4080-0103-P10-8.dft``.

* prefix       last 4 digits of the job number plus any job suffix
               (20274080 -> "4080", 20223006-C -> "3006-C")
* number       4-digit drawing number (0101, 0102, ...)
* description  support style and size ("P10-8"), editable per drawing
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NUMBER_WIDTH = 4
MAX_NUMBER = 10 ** NUMBER_WIDTH - 1

# A job folder name starts with the 8-digit job number, optionally followed by
# suffixes ("20223006-C", "20263767-1") and then free text ("20263756, Coogee").
_JOB_FOLDER_RE = re.compile(r"^(\d{8}(?:-[A-Za-z0-9]+)*)(?=$|[\s,_(])")
_DRAWING_NAME_RE = re.compile(r"^(?P<prefix>.+?)-(?P<number>\d{4})-(?P<desc>.+)$")
_INVALID_CHARS = set('<>:"/\\|?*')


@dataclass(frozen=True)
class JobInfo:
    job_number: str
    job_root: Path


@dataclass(frozen=True)
class DrawingName:
    prefix: str
    number: int
    description: str

    def __str__(self) -> str:
        return format_name(self.prefix, self.number, self.description)


def detect_job(path: Path) -> JobInfo | None:
    """Find the job folder (e.g. ``F:\\MAS\\Jobs\\20274080``) at or above ``path``."""
    for folder in (path, *path.parents):
        m = _JOB_FOLDER_RE.match(folder.name)
        if m:
            return JobInfo(m.group(1), folder)
    return None


def default_prefix(job_number: str) -> str:
    """20274080 -> 4080, 20223006-C -> 3006-C. Returns "" if it isn't a job number."""
    m = re.match(r"^\d{4}(\d{4})(.*)$", job_number.strip())
    return m.group(1) + m.group(2) if m else ""


def format_number(number: int) -> str:
    return f"{number:0{NUMBER_WIDTH}d}"


def parse_number(text: str) -> int | None:
    text = text.strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if 1 <= value <= MAX_NUMBER else None


def format_name(prefix: str, number: int, description: str) -> str:
    return f"{prefix}-{format_number(number)}-{description}"


def parse_name(name: str, prefix_hint: str | None = None) -> DrawingName | None:
    """Split "4080-0103-P10-8" into prefix, number and description.

    ``prefix_hint`` resolves names whose prefix itself contains a 4-digit part.
    """
    if prefix_hint:
        m = re.match(rf"^{re.escape(prefix_hint)}-(\d{{4}})-(.+)$", name, re.IGNORECASE)
        if m:
            return DrawingName(name[: len(prefix_hint)], int(m.group(1)), m.group(2))
    m = _DRAWING_NAME_RE.match(name)
    if not m:
        return None
    return DrawingName(m.group("prefix"), int(m.group("number")), m.group("desc"))


def drawing_number_from_name(name: str) -> str | None:
    """The value for the "Drawing Number:" property, e.g. "0103"."""
    parsed = parse_name(name)
    return format_number(parsed.number) if parsed else None


def guess_description(dft_path: Path) -> str:
    """Pick the style-size part of a draft that may come from another job.

    "P10-8.dft" (template)         -> "P10-8"
    "3621-0101-S2-1.dft"           -> "S2-1"
    "3006-0301-C-P10-2.dft"        -> "P10-2"  (when P10-2.asm sits next to it)
    """
    stem = dft_path.stem
    parsed = parse_name(stem)
    rest = parsed.description if parsed else stem
    # Design Manager keeps the assembly's template name, so it is the most
    # reliable hint for which part of the name is the style and size.
    try:
        assemblies = [p.stem for p in dft_path.parent.glob("*.asm")]
    except OSError:
        assemblies = []
    matches = [a for a in assemblies if rest.lower().endswith(a.lower()) and a]
    if matches:
        best = max(matches, key=len)
        return rest[len(rest) - len(best):]
    return rest


def validate_name_part(text: str, what: str) -> str | None:
    """Return an error message if ``text`` can't be used in a file name."""
    if not text.strip():
        return f"{what} is empty."
    bad = sorted({c for c in text if c in _INVALID_CHARS})
    if bad:
        return f"{what} \"{text}\" contains characters Windows doesn't allow: {' '.join(bad)}"
    if text != text.strip() or text.endswith("."):
        return f"{what} \"{text}\" can't start/end with a space or end with a period."
    return None
