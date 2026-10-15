"""Main window."""

from __future__ import annotations

import logging
import logging.handlers
import os
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import APP_NAME, __version__, com, naming, titleblock
from ..jobfolder import list_drafts, scan_drawings_folder
from ..settings import Settings, log_dir
from .dialogs import HELP_TEXT, SettingsDialog, show_text_dialog
from .drawings_tab import DrawingsTab
from .pdf_tab import PdfTab
from .titleblock_tab import TitleBlockTab
from .widgets import PAD, LogPanel, PlaceholderEntry, TaskRunner

log = logging.getLogger("se_automation")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = Settings()
        self.folder: Path | None = None
        self.job: naming.JobInfo | None = None
        self.last_changed: list[Path] = []
        self._auto_prefix = ""
        self._suspend_traces = False
        self._refresh_pending = False

        root.title(f"{APP_NAME} - Pipe Support Jobs   (v{__version__})")
        root.minsize(1080, 700)
        if self.settings["geometry"]:
            try:
                root.geometry(self.settings["geometry"])
            except tk.TclError:
                pass
        else:
            root.geometry("1280x860")
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        self.bg = style.lookup("TFrame", "background") or "SystemButtonFace"
        style.configure("Treeview", rowheight=24)

        self.folder_var = tk.StringVar()
        self.job_var = tk.StringVar()
        self.prefix_var = tk.StringVar()
        self.start_var = tk.StringVar()

        self._build_menu()
        self._build_header()
        self.log_panel = LogPanel(root, on_cancel=lambda: self.runner.cancel())
        self.log_panel.pack(side="bottom", fill="x", padx=PAD * 2, pady=(0, PAD * 2))
        self.runner = TaskRunner(root, self.log_panel, self._set_busy)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=PAD * 2, pady=PAD)
        self.drawings_tab = DrawingsTab(self.notebook, self)
        self.titleblock_tab = TitleBlockTab(self.notebook, self)
        self.pdf_tab = PdfTab(self.notebook, self)
        self.notebook.add(self.drawings_tab, text="  1  Drawings  ")
        self.notebook.add(self.titleblock_tab, text="  2  Title Block  ")
        self.notebook.add(self.pdf_tab, text="  3  Print PDFs  ")

        self.job_var.trace_add("write", self._on_job_changed)
        self.prefix_var.trace_add("write", self._on_prefix_changed)
        self.start_var.trace_add("write", lambda *_: self._schedule_refresh())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<Control-o>", lambda e: self.choose_folder())
        root.bind_all("<F5>", lambda e: self.reload_folder(keep_title_block=True))

        self.drawings_tab.refresh()
        self.log(f"{APP_NAME} {__version__} ready. Choose a drawings folder to begin (File > Open, or Browse).")

    # --- layout ----------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file = tk.Menu(menu, tearoff=False)
        file.add_command(label="Open drawings folder...", accelerator="Ctrl+O", command=self.choose_folder)
        self.recent_menu = tk.Menu(file, tearoff=False, postcommand=self._fill_recent)
        file.add_cascade(label="Recent folders", menu=self.recent_menu)
        file.add_command(label="Refresh", accelerator="F5", command=lambda: self.reload_folder(keep_title_block=True))
        file.add_separator()
        file.add_command(label="Exit", command=self.close)
        menu.add_cascade(label="File", menu=file)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Settings...", command=self.open_settings)
        tools.add_command(label="Open log folder", command=self.open_log_folder)
        tools.add_separator()
        tools.add_command(label="Clear pywin32 gen_py cache (fix for older scripts)...", command=self.clear_gen_py)
        menu.add_cascade(label="Tools", menu=tools)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="How to use", command=lambda: show_text_dialog(
            self.root, "How to use", HELP_TEXT, ok_text=None))
        help_menu.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", f"{APP_NAME} {__version__}\n\nSets up, renumbers and prints Solid Edge pipe support "
                     f"drawings.\n\nLogs: {log_dir()}"))
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.configure(menu=menu)

    def _build_header(self) -> None:
        head = ttk.LabelFrame(self.root, text="Job", padding=PAD)
        head.pack(fill="x", padx=PAD * 2, pady=(PAD * 2, 0))
        ttk.Label(head, text="Drawings folder:").grid(row=0, column=0, sticky="w")
        entry = PlaceholderEntry(head, "Click Browse... to choose the job's Working Drawings folder "
                                       r"(or paste a path like F:\MAS\Jobs\20274080\Working Drawings and press Enter)",
                                 textvariable=self.folder_var)
        entry.grid(row=0, column=1, columnspan=7, sticky="ew", padx=4)
        entry.bind("<Return>", lambda e: self.open_folder(Path(self.folder_var.get().strip())))
        self.browse_button = ttk.Button(head, text="Browse...", command=self.choose_folder)
        self.browse_button.grid(row=0, column=8)
        self.recent_button = ttk.Menubutton(head, text="Recent")
        recent = tk.Menu(self.recent_button, tearoff=False, postcommand=lambda: self._fill_recent(recent))
        self.recent_button.configure(menu=recent)
        self.recent_button.grid(row=0, column=9, padx=4)
        self.refresh_button = ttk.Button(head, text="Refresh", command=lambda: self.reload_folder(keep_title_block=True))
        self.refresh_button.grid(row=0, column=10)

        ttk.Label(head, text="Job number:").grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        self.job_entry = PlaceholderEntry(head, "e.g. 20274080", textvariable=self.job_var, width=16)
        self.job_entry.grid(row=1, column=1, sticky="w", padx=4, pady=(PAD, 0))
        ttk.Label(head, text="Drawing prefix:").grid(row=1, column=2, sticky="e", padx=(PAD * 2, 0), pady=(PAD, 0))
        self.prefix_entry = PlaceholderEntry(head, "e.g. 4080", textvariable=self.prefix_var, width=12)
        self.prefix_entry.grid(row=1, column=3, sticky="w", padx=4, pady=(PAD, 0))
        ttk.Label(head, text="First number:").grid(row=1, column=4, sticky="e", padx=(PAD * 2, 0), pady=(PAD, 0))
        self.start_entry = PlaceholderEntry(head, "e.g. 0101", textvariable=self.start_var, width=9)
        self.start_entry.grid(row=1, column=5, sticky="w", padx=4, pady=(PAD, 0))
        self.example = ttk.Label(head, text="", foreground="#555555")
        self.example.grid(row=1, column=6, columnspan=5, sticky="w", padx=(PAD * 2, 0), pady=(PAD, 0))
        self.job_label = ttk.Label(head, text="", foreground="#555555")
        self.job_label.grid(row=2, column=0, columnspan=11, sticky="w", pady=(4, 0))
        head.columnconfigure(7, weight=1)

    def _fill_recent(self, menu: tk.Menu | None = None) -> None:
        menu = menu or self.recent_menu
        menu.delete(0, "end")
        recent = self.settings["recent_folders"]
        if not recent:
            menu.add_command(label="(none yet)", state="disabled")
        for folder in recent:
            menu.add_command(label=folder, command=lambda f=folder: self.open_folder(Path(f), interactive=False))

    # --- helpers used by the tabs --------------------------------------------------------

    def log(self, message: str, level: str = "info") -> None:
        self.log_panel.write(message, level)

    def set_cursor(self, cursor: str) -> None:
        self.root.configure(cursor=cursor)
        self.root.update_idletasks()

    def titleblock_fields(self):
        return titleblock.FIELDS

    def remember_changed(self, drafts: list[Path]) -> None:
        """Drafts created/renumbered this session (offered later on the Print PDFs tab)."""
        known = {str(p).lower() for p in self.last_changed}
        self.last_changed += [p for p in drafts if str(p).lower() not in known]

    def _set_busy(self, busy: bool) -> None:
        widgets = [self.browse_button, self.refresh_button, self.recent_button, self.job_entry, self.prefix_entry,
                   self.start_entry, *self.drawings_tab.busy_widgets(), *self.titleblock_tab.busy_widgets(),
                   *self.pdf_tab.busy_widgets()]
        for w in widgets:
            w.state(["disabled"] if busy else ["!disabled"])
        if not busy:
            self.drawings_tab.refresh()

    # --- folder handling -----------------------------------------------------------------

    def choose_folder(self) -> None:
        if self.runner.busy:
            return
        start = str(self.folder) if self.folder else self.settings["browse_start"]
        chosen = filedialog.askdirectory(title="Choose the drawings folder (e.g. the job's Working Drawings)",
                                         initialdir=start if Path(start).is_dir() else None, mustexist=True)
        if chosen:
            self.open_folder(Path(chosen))

    def open_folder(self, path: Path, interactive: bool = True) -> None:
        if self.runner.busy:
            return
        if not path.is_dir():
            messagebox.showerror("Folder not found", f"This folder doesn't exist or can't be opened:\n{path}")
            return
        if self.drawings_tab.plan and self.drawings_tab.plan.has_changes and not messagebox.askyesno(
                "Unapplied changes", "You have changes that haven't been applied. Open another folder anyway?"):
            return
        working = path / "Working Drawings"
        if interactive and working.is_dir() and not scan_drawings_folder(path).drawings:
            if messagebox.askyesno("Working Drawings", f"Use the Working Drawings folder inside it?\n\n{working}"):
                path = working
        self.folder = path
        self.folder_var.set(str(path))
        self.job = naming.detect_job(path)
        self.settings.add_recent(path)
        self.settings.save()
        self._load(reset_title=True)

    def reload_folder(self, keep_title_block: bool = False) -> None:
        if self.folder is None or self.runner.busy:
            return
        if not self.folder.is_dir():
            messagebox.showerror("Folder not found", f"The folder is no longer available:\n{self.folder}")
            return
        self._load(reset_title=not keep_title_block)

    def _load(self, reset_title: bool) -> None:
        folder = self.folder
        self.set_cursor("watch")
        try:
            job_number = self.job.job_number if self.job else ""
            default = naming.default_prefix(job_number)
            scan = scan_drawings_folder(folder, default or None)
            prefix = scan.common_prefix or default
            start = scan.first_number or int(self.settings["start_number"])
            self._suspend_traces = True
            try:
                self.job_var.set(job_number)
                self.prefix_var.set(prefix)
                self.start_var.set(naming.format_number(start))
            finally:
                self._suspend_traces = False
            self._auto_prefix = default
            self._update_labels()
            self.drawings_tab.load(scan)
            drafts = list_drafts(folder)
            self.titleblock_tab.set_drafts(drafts, folder)
            self.pdf_tab.set_drafts(drafts, folder)
            self.pdf_tab.set_job(self.job.job_root if self.job else None, folder)
        finally:
            self.set_cursor("")
        self.log(f"Opened {folder}  ({len(scan.drawings)} drawing(s)).")
        if reset_title:
            self.titleblock_tab.reset_for_job(job_number, prefix)
            first = next((d.dft for d in scan.drawings if d.dft), None)
            if first is not None:
                self.titleblock_tab.load_from_drawing(first, only_empty=True, quiet=True)

    def _update_labels(self) -> None:
        prefix = self.prefix_var.get().strip() or "????"
        start = naming.parse_number(self.start_var.get()) or 101
        self.example.configure(text=f"First drawing will be named like:  {naming.format_name(prefix, start, 'P10-8')}")
        if self.job:
            self.job_label.configure(text=f"Job folder: {self.job.job_root}", foreground="#555555")
        elif self.folder:
            self.job_label.configure(text="No job number found in this folder's path - type the job number and "
                                          "drawing prefix above.", foreground="#a15c00")

    def _on_job_changed(self, *_):
        if self._suspend_traces:
            return
        new_default = naming.default_prefix(self.job_var.get())
        if self.prefix_var.get().strip() in ("", self._auto_prefix):
            self.prefix_var.set(new_default)
        self._auto_prefix = new_default
        self.titleblock_tab.follow("job_no", self.job_var.get().strip())

    def _on_prefix_changed(self, *_):
        if self._suspend_traces:
            return
        self.titleblock_tab.follow("doc_no", self.prefix_var.get().strip())
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._suspend_traces or self._refresh_pending:
            return
        self._refresh_pending = True

        def run():
            self._refresh_pending = False
            self._update_labels()
            self.drawings_tab.refresh()

        self.root.after(150, run)

    # --- menu actions ---------------------------------------------------------------------

    def open_settings(self) -> None:
        SettingsDialog(self.root, self.settings, on_saved=lambda: self.log("Settings saved."))

    def open_log_folder(self) -> None:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def clear_gen_py(self) -> None:
        path = com.gen_py_cache_dir()
        if not messagebox.askyesno("Clear gen_py cache",
                                   f"Delete pywin32's generated cache?\n\n{path}\n\nThis fixes the gen_py error in "
                                   "older scripts. It's safe: pywin32 rebuilds it when needed."):
            return
        path, removed = com.clear_gen_py_cache()
        self.log(f"gen_py cache {'deleted' if removed else 'was not there (nothing to delete)'}: {path}")

    def close(self) -> None:
        if self.runner.busy and not messagebox.askyesno(
                "Task running", "A task is still running. Close anyway? (Solid Edge may be left mid-way.)"):
            return
        if self.drawings_tab.plan and self.drawings_tab.plan.has_changes and not self.runner.busy:
            if not messagebox.askyesno("Unapplied changes", "You have changes that haven't been applied. Exit anyway?"):
                return
        self.settings["geometry"] = self.root.geometry()
        self.settings.save()
        self.root.destroy()


def _setup_logging() -> None:
    folder = log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(folder / "se_automation.log", maxBytes=2_000_000,
                                                       backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    except OSError:
        pass
    log.setLevel(logging.INFO)


def main() -> None:
    _setup_logging()
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # crisp text on scaled displays
    except (AttributeError, OSError):
        pass
    root = tk.Tk()

    def report(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error(text)
        messagebox.showerror("Unexpected error", f"{com.describe_error(exc)}\n\nDetails were saved in the log "
                                                 f"folder:\n{log_dir()}")

    root.report_callback_exception = report
    try:
        App(root)
    except Exception as e:
        report(type(e), e, e.__traceback__)
        root.destroy()
        return
    root.mainloop()
