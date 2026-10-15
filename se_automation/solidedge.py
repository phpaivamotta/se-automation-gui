"""Solid Edge, Design Manager and file-property operations."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pywintypes
import win32api
import win32con
import win32gui
import win32process

from .com import ComObject, describe_error

SE_PROGID = "SolidEdge.Application"
DM_PROGID = "DesignManager.Application"
FILE_PROPS_PROGID = "SolidEdge.FileProperties"

# Application.SetGlobalParameter ids for "Save as PDF" sheet selection.
_PDF_SHEET_OPTION = 172      # 1 = all sheets, 2 = sheet range
_PDF_SHEET_RANGE = 173       # e.g. "1,2"
# Design Manager action "Save All As" (copies the draft and every linked file).
_DM_SAVE_ALL_AS = 2

PropertyValues = dict[tuple[str, str], str]   # (property set, property name) -> value
Log = Callable[[str], None]


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class SolidEdge:
    """A Solid Edge session. Attaches to a running Solid Edge or starts one."""

    def __init__(self, log: Log = print):
        self.log = log
        self._app: ComObject | None = None
        self._pdf_option_before: Any = None

    @property
    def app(self) -> ComObject:
        if self._app is None:
            app = ComObject.running(SE_PROGID)
            if app is None:
                self.log("Starting Solid Edge (this can take a minute)...")
                app = ComObject.create(SE_PROGID)
            app.set("Visible", True)
            self._app = app
        return self._app

    @staticmethod
    def open_documents_if_running() -> list[str]:
        """Full paths of documents open in Solid Edge, without starting it."""
        app = ComObject.running(SE_PROGID)
        if app is None:
            return []
        paths = []
        try:
            for doc in app.get("Documents"):
                try:
                    paths.append(doc.get("FullName"))
                except pywintypes.com_error:
                    pass
        except pywintypes.com_error:
            pass
        return paths

    def find_open(self, path: Path) -> ComObject | None:
        target = _norm(path)
        for doc in self.app.get("Documents"):
            try:
                if _norm(doc.get("FullName")) == target:
                    return doc
            except pywintypes.com_error:
                continue
        return None

    def open(self, path: Path) -> tuple[ComObject, bool]:
        """Open a document. Returns (document, was_already_open)."""
        doc = self.find_open(path)
        if doc is not None:
            return doc, True
        return self.app.get("Documents").call("Open", str(path)), False

    @staticmethod
    def set_properties(doc: ComObject, values: PropertyValues) -> list[str]:
        """Set document properties. Returns the ones the document doesn't have."""
        return _apply_properties(doc.get("Properties"), values)

    @staticmethod
    def save(doc: ComObject) -> None:
        doc.call("Save")

    @staticmethod
    def close(doc: ComObject) -> None:
        doc.call("Close", False)

    # --- PDF -----------------------------------------------------------------

    def begin_pdf_batch(self) -> None:
        """Remember the user's PDF sheet setting so it can be restored afterwards."""
        try:
            self._pdf_option_before = self.app.call_with_out_param("GetGlobalParameter", _PDF_SHEET_OPTION)
        except pywintypes.com_error:
            self._pdf_option_before = None

    def end_pdf_batch(self) -> None:
        """Put the PDF sheet setting back (the old script left it on "sheets 1,2")."""
        if self._app is None:
            return
        value = self._pdf_option_before if self._pdf_option_before in (1, 2) else 1
        try:
            self.app.call("SetGlobalParameter", _PDF_SHEET_OPTION, value)
        except pywintypes.com_error as e:
            self.log(f"Couldn't restore Solid Edge's PDF sheet setting: {describe_error(e)}")

    def export_pdf(self, doc: ComObject, out_path: Path, sheets: str | None) -> None:
        """Save ``doc`` as PDF. ``sheets`` is a range like "1,2", or None for all sheets."""
        if sheets:
            self.app.call("SetGlobalParameter", _PDF_SHEET_OPTION, 2)
            self.app.call("SetGlobalParameter", _PDF_SHEET_RANGE, sheets)
        else:
            self.app.call("SetGlobalParameter", _PDF_SHEET_OPTION, 1)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 0x27 is what the original script passed; it overwrites an existing PDF.
        doc.call("SaveAs", str(out_path), 0x27)

    @staticmethod
    def activate_first_sheet(doc: ComObject) -> bool:
        sheets = doc.get("Sections").get("WorkingSection").get("Sheets")
        if sheets.get("Count") < 1:
            return False
        sheets.call("Item", 1).call("Activate")
        return True


class DesignManager:
    """Copies a draft and all of its linked files with Design Manager's "Save All As"."""

    def __init__(self, log: Log = print):
        self.log = log
        self._dm: ComObject | None = None

    @property
    def dm(self) -> ComObject:
        if self._dm is None:
            self.log("Starting Design Manager...")
            self._dm = ComObject.create(DM_PROGID)
            self._dm.set("Visible", True)
        return self._dm

    def copy_draft(self, source_dft: Path, dest_folder: Path, timeout: float = 600) -> Path:
        """Copy ``source_dft`` (and its assembly/parts) into ``dest_folder``.

        Returns the path of the copied draft (it keeps the source's file name).
        """
        dm = self.dm
        with _DialogWatcher(self.log):
            # Keep a reference to the opened document until the action has run:
            # releasing it unloads the file and PerformAction silently does nothing.
            document = dm.call("OpenFileInDesignManager", str(source_dft))
            dm.call("SetActionForAllFiles", _DM_SAVE_ALL_AS, str(dest_folder))
            dm.call("PerformAction")
            del document
        copied = dest_folder / source_dft.name
        deadline = time.monotonic() + timeout
        while not copied.exists():
            if time.monotonic() > deadline:
                raise TimeoutError(f"Design Manager didn't create {copied}")
            time.sleep(0.5)
        return copied

    def quit(self) -> None:
        if self._dm is not None:
            try:
                self._dm.call("Quit")
            except pywintypes.com_error:
                pass
            self._dm = None


class _DialogWatcher:
    """Deals with Design Manager pop-ups while a copy runs (the COM call blocks until
    they're answered).

    "Expand All: Populate Duplicates" appears for assemblies with repeated
    sub-assemblies (e.g. D6-36). It only affects what Design Manager displays, so it
    is answered with its default, Hide. Any other dialog is left for the user, with
    a note in the log so they know to look at Design Manager.
    """

    _AUTO_ANSWER = {"Populate Duplicates": 1400}   # title text -> button id ("Hide")
    _NOTIFY_AFTER = 8.0

    def __init__(self, log: Log):
        self.log = log
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._answered: set[int] = set()
        self._first_seen: dict[int, float] = {}
        self._notified: set[int] = set()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(0.3):
            try:
                win32gui.EnumWindows(self._check, None)
            except Exception:   # never let the watcher break a copy
                pass

    def _check(self, hwnd: int, _) -> bool:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetClassName(hwnd) != "#32770":
            return True
        if not _is_design_manager_window(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        for needle, button_id in self._AUTO_ANSWER.items():
            if needle in title:
                button = win32gui.GetDlgItem(hwnd, button_id)
                if button:
                    win32gui.PostMessage(button, win32con.BM_CLICK, 0, 0)
                    if hwnd not in self._answered:
                        self._answered.add(hwnd)
                        self.log(f"Design Manager asked \"{title}\" - answered Hide.")
                return True
        first = self._first_seen.setdefault(hwnd, time.monotonic())
        if hwnd not in self._notified and time.monotonic() - first > self._NOTIFY_AFTER:
            self._notified.add(hwnd)
            self.log(f"Design Manager is waiting on a message (\"{title}\"). "
                     "Please answer it in the Design Manager window.")
        return True


def _is_design_manager_window(hwnd: int) -> bool:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            exe = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return False
    return os.path.basename(exe).lower() == "desmgr.exe"


def normalize_property_name(name: str) -> str:
    """Templates disagree on details like "COMPANY ADDRESS" vs "COMPANY ADDRESS:"."""
    return name.strip().rstrip(":").strip().casefold()


def _apply_properties(property_sets: ComObject, values: PropertyValues) -> list[str]:
    missing: list[str] = []
    by_set: dict[str, list[tuple[str, str]]] = {}
    for (set_name, prop_name), value in values.items():
        by_set.setdefault(set_name, []).append((prop_name, value))
    for set_name, props in by_set.items():
        try:
            pset = property_sets.call("Item", set_name)
        except pywintypes.com_error:
            missing.extend(f"{set_name} / {name}" for name, _ in props)
            continue
        available = {p.get("Name"): p for p in pset}
        folded = {normalize_property_name(name): p for name, p in available.items()}
        for name, value in props:
            prop = available.get(name) or folded.get(normalize_property_name(name))
            if prop is None:
                missing.append(f"{set_name} / {name}")
                continue
            prop.set("Value", value)
    return missing


def read_file_properties(path: Path) -> dict[str, dict[str, Any]]:
    """Read a draft's properties straight from the file (Solid Edge doesn't open)."""
    sets = ComObject.create(FILE_PROPS_PROGID)
    sets.call("Open", str(path), True)
    try:
        result: dict[str, dict[str, Any]] = {}
        for pset in sets:
            props: dict[str, Any] = {}
            for prop in pset:
                try:
                    props[prop.get("Name")] = prop.get("Value")
                except pywintypes.com_error:
                    pass
            result[pset.get("Name")] = props
        return result
    finally:
        sets.call("Close")


def write_file_properties(path: Path, values: PropertyValues) -> list[str]:
    """Write properties straight into the file (Solid Edge doesn't open)."""
    sets = ComObject.create(FILE_PROPS_PROGID)
    sets.call("Open", str(path), False)
    try:
        missing = _apply_properties(sets, values)
        sets.call("Save")
        return missing
    finally:
        sets.call("Close")
