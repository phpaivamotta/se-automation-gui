"""Per-user settings, stored in %APPDATA%\\SE Automation\\settings.json."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from . import APP_NAME

DEFAULTS: dict = {
    "template_root": r"F:\MAS\Solid Edge Parts Library\Pipe Support Templates - Updated",
    "browse_start": r"F:\MAS\Jobs",
    "recent_folders": [],
    "start_number": 101,
    "fab_subfolder": r"Submittal\Fab Latest Revision",
    "ga_subfolder": r"Submittal\GA Latest Revision",
    "ga_sheets": "1,2",
    "leave_new_open": True,
    "fill_title_block": True,
    "close_after_pdf": True,
    "title_defaults": {
        "wo": "-",
        "revision": "A",
        "company_address": "PALMETTO, FLORIDA",
        "drawn_by": "",
        "checked_by": "",
        "approved_by": "",
    },
    "geometry": "",
}

MAX_RECENT = 12


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "logs"


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "settings.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(self.data.get(key), dict):
                self.data[key].update(value)
            else:
                self.data[key] = value

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass   # settings are a convenience; never fail a job over them

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def add_recent(self, folder: Path) -> None:
        text = str(folder)
        recent = [r for r in self.data["recent_folders"] if r.lower() != text.lower()]
        self.data["recent_folders"] = [text, *recent][:MAX_RECENT]
