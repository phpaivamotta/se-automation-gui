"""Dialogs: template browser, preview/confirm, settings, help."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from .. import naming
from ..templates import Template, TemplateLibrary
from .widgets import PAD, PlaceholderEntry, labeled_path_entry


def _center(win: tk.Toplevel, parent: tk.Misc) -> None:
    win.update_idletasks()
    top = parent.winfo_toplevel()
    x = top.winfo_rootx() + (top.winfo_width() - win.winfo_width()) // 2
    y = top.winfo_rooty() + (top.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def show_text_dialog(parent: tk.Misc, title: str, text: str, ok_text: str | None = "OK",
                     cancel_text: str = "Cancel") -> bool:
    """A scrollable message with OK/Cancel. Returns True for OK."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    win.minsize(520, 200)
    result = {"ok": False}
    body = ttk.Frame(win, padding=PAD * 2)
    body.pack(fill="both", expand=True)
    lines = text.count("\n") + 1
    box = tk.Text(body, wrap="none", width=min(max(len(max(text.splitlines() or [""], key=len)) + 2, 60), 130),
                  height=min(max(lines, 4), 28), font=("Consolas", 9), relief="solid", borderwidth=1)
    box.insert("1.0", text)
    box.configure(state="disabled")
    xs = ttk.Scrollbar(body, orient="horizontal", command=box.xview)
    ys = ttk.Scrollbar(body, command=box.yview)
    box.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
    box.grid(row=0, column=0, sticky="nsew")
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    body.rowconfigure(0, weight=1)
    body.columnconfigure(0, weight=1)
    buttons = ttk.Frame(win, padding=(PAD * 2, 0, PAD * 2, PAD * 2))
    buttons.pack(fill="x")

    def close(ok: bool):
        result["ok"] = ok
        win.destroy()

    if ok_text:
        ok = ttk.Button(buttons, text=ok_text, command=lambda: close(True))
        ok.pack(side="right")
        ttk.Button(buttons, text=cancel_text, command=lambda: close(False)).pack(side="right", padx=PAD)
        ok.focus_set()
    else:
        ttk.Button(buttons, text="Close", command=lambda: close(False)).pack(side="right")
    win.bind("<Escape>", lambda e: close(False))
    win.protocol("WM_DELETE_WINDOW", lambda: close(False))
    _center(win, parent)
    win.grab_set()
    win.wait_window()
    return result["ok"]


class TemplatePicker(tk.Toplevel):
    """Browse the template library: pick a style, then one or more sizes."""

    def __init__(self, parent: tk.Misc, library: TemplateLibrary, on_add: Callable[[list[Template]], None]):
        super().__init__(parent)
        self.title("Browse templates")
        self.transient(parent.winfo_toplevel())
        self.library = library
        self.on_add = on_add
        self._sizes: list[Template] = []
        self.minsize(560, 420)

        frame = ttk.Frame(self, padding=PAD * 2)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Library: {library.root}", foreground="#555555").grid(
            row=0, column=0, columnspan=2, sticky="w")
        search = ttk.Frame(frame)
        search.grid(row=1, column=0, sticky="ew", pady=PAD)
        ttk.Label(search, text="Find style:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._fill_styles())
        entry = PlaceholderEntry(search, "e.g. P10", textvariable=self.filter_var, width=14)
        entry.pack(side="left", padx=4)
        entry.focus_set()

        ttk.Label(frame, text="Style").grid(row=2, column=0, sticky="w")
        ttk.Label(frame, text="Size (select one or more, double-click to add)").grid(row=2, column=1, sticky="w",
                                                                                      padx=(PAD, 0))
        self.styles = tk.Listbox(frame, exportselection=False, height=18, width=24)
        self.styles.grid(row=3, column=0, sticky="nsew")
        self.sizes = tk.Listbox(frame, exportselection=False, selectmode="extended", height=18, width=36)
        self.sizes.grid(row=3, column=1, sticky="nsew", padx=(PAD, 0))
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(1, weight=1)
        self.styles.bind("<<ListboxSelect>>", lambda e: self._fill_sizes())
        self.sizes.bind("<Double-1>", lambda e: self._add())
        self.sizes.bind("<Return>", lambda e: self._add())

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        self.status = ttk.Label(buttons, text="", foreground="#555555")
        self.status.pack(side="left")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Add selected", command=self._add).pack(side="right", padx=PAD)
        self.bind("<Escape>", lambda e: self.destroy())
        self._fill_styles()
        _center(self, parent)

    def _fill_styles(self) -> None:
        text = self.filter_var.get().strip().lower()
        self.styles.delete(0, "end")
        for s in self.library.styles():
            if not text or s.lower().startswith(text):
                self.styles.insert("end", s)
        if self.styles.size() == 1 or (text and self.styles.size()):
            self.styles.selection_set(0)
            self._fill_sizes()

    def _fill_sizes(self) -> None:
        sel = self.styles.curselection()
        self.sizes.delete(0, "end")
        self._sizes = []
        if not sel:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            self._sizes = self.library.sizes(self.styles.get(sel[0]))
        finally:
            self.configure(cursor="")
        for t in self._sizes:
            self.sizes.insert("end", t.code)
        if not self._sizes:
            self.sizes.insert("end", "(no size folders with a draft)")

    def _add(self) -> None:
        picked = [self._sizes[i] for i in self.sizes.curselection() if i < len(self._sizes)]
        if not picked:
            return
        self.on_add(picked)
        self.status.configure(text="Added " + ", ".join(t.code for t in picked))


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, settings, on_saved: Callable[[], None]):
        super().__init__(parent)
        self.title("Settings")
        self.transient(parent.winfo_toplevel())
        self.settings = settings
        self.on_saved = on_saved
        s = settings
        self.vars = {
            "template_root": tk.StringVar(value=s["template_root"]),
            "browse_start": tk.StringVar(value=s["browse_start"]),
            "start_number": tk.StringVar(value=naming.format_number(int(s["start_number"]))),
            "fab_subfolder": tk.StringVar(value=s["fab_subfolder"]),
            "ga_subfolder": tk.StringVar(value=s["ga_subfolder"]),
        }
        f = ttk.Frame(self, padding=PAD * 2)
        f.pack(fill="both", expand=True)
        labeled_path_entry(f, "Template library:", self.vars["template_root"], "Template library",
                           placeholder="the folder that holds the style folders (D6, P10, S2, ...)").pack(fill="x")
        labeled_path_entry(f, "Jobs folder (where Browse starts):", self.vars["browse_start"], "Jobs folder",
                           placeholder=r"e.g. F:\MAS\Jobs").pack(fill="x", pady=PAD)
        grid = ttk.Frame(f)
        grid.pack(fill="x", pady=PAD)
        rows = (("First drawing number for a new job:", "start_number", 10, "e.g. 0101"),
                ("Fabricator PDFs (inside the job folder):", "fab_subfolder", 40,
                 r"e.g. Submittal\Fab Latest Revision"),
                ("Customer PDFs (inside the job folder):", "ga_subfolder", 40, r"e.g. Submittal\GA Latest Revision"))
        for r, (label, key, width, hint) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", pady=2)
            PlaceholderEntry(grid, hint, textvariable=self.vars[key], width=width).grid(
                row=r, column=1, sticky="w", padx=4)
        ttk.Label(f, foreground="#555555", wraplength=520, justify="left",
                  text="Title block defaults (your initials, revision, ...) are saved from the Title Block tab "
                       "with \"Save as my defaults\".").pack(anchor="w", pady=PAD)
        buttons = ttk.Frame(f)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=PAD)
        self.bind("<Escape>", lambda e: self.destroy())
        self.minsize(620, 0)
        _center(self, parent)
        self.grab_set()

    def _save(self) -> None:
        number = naming.parse_number(self.vars["start_number"].get())
        if number is None:
            messagebox.showerror("Settings", "The first drawing number must be between 0001 and 9999.", parent=self)
            return
        if not Path(self.vars["template_root"].get()).is_dir():
            if not messagebox.askyesno("Settings", "The template library folder can't be found. Save anyway?",
                                       parent=self):
                return
        for key in ("template_root", "browse_start", "fab_subfolder", "ga_subfolder"):
            self.settings[key] = self.vars[key].get().strip()
        self.settings["start_number"] = number
        self.settings.save()
        self.on_saved()
        self.destroy()


HELP_TEXT = """\
SE AUTOMATION - HOW TO USE

1. CHOOSE THE DRAWINGS FOLDER (top of the window)
   Usually  F:\\MAS\\Jobs\\<job>\\Working Drawings,  but any folder works (a sub-folder of
   Working Drawings, a folder somewhere else, ...). If you pick the job folder itself, the app
   offers to use its Working Drawings folder.
   The job number, drawing prefix and first number are filled in automatically - check them:
       Job number      20274080      20223006-C
       Drawing prefix  4080          3006-C        (drawings are named  prefix-number-description)
       First number    0101          (or 0201, 0140, ...)
   If the folder already has drawings, the prefix and first number are taken from them.

2. DRAWINGS TAB - set up the list in the order you want (e.g. the PO order)
   - Type template names (D6-36, P10-8, P20-20) and click Add, or use "Browse templates...".
   - "From another job / folder..." copies a drawing from an old job. The description is set to
     just the style and size (3621-0101-S2-1 -> S2-1). Double-click it to change it.
   - New supports are inserted right below the selected row. To add a 2nd P10-8 right after
     the first one, select the P10-8 row and click Duplicate (copies the job's drawing, with
     any changes already made) or add the template again with that row selected.
   - Reorder with Move up / Move down or by dragging rows.
   - The table shows what each drawing will be called. Green = new, yellow = renamed/renumbered.
   - "Preview & apply changes..." shows exactly what will happen before anything is touched:
       * existing drawings that move are renamed (folder + draft) and get the new Drawing Number
       * new drawings are copied with Design Manager, renamed, and get the title block
   - If a renumbered drawing already had PDFs in Submittal, you'll get a list of those
     (now out-of-date) PDFs. They aren't touched; reprint when the drawings are ready.

3. TITLE BLOCK TAB
   - Values used for new drawings. Opening a folder that already has drawings fills in the
     project values from one of them automatically.
   - You can also update the title block of any existing drawings (check them on the right).
   - Blank fields are never changed.

4. PRINT PDFS TAB (whenever the models and drafts are ready - nothing prints automatically)
   - Fabricator set (all sheets) -> Submittal\\Fab Latest Revision
   - Customer set (sheets 1,2)  -> Submittal\\GA Latest Revision
   - "Check only drawings created/renumbered since the app was opened" picks just those.

GOOD TO KNOW
   - Save and close drawings in Solid Edge before renumbering them; the app checks this.
   - If anything fails while renaming, every folder is put back the way it was.
   - Design Manager's "Populate Duplicates" question is answered (Hide) automatically.
   - Everything that happens is written to the log at the bottom of the window and to
     %LOCALAPPDATA%\\SE Automation\\logs.
   - This app doesn't use pywin32's gen_py cache, so the old "delete the gen_py\\3.11 folder"
     error can't happen here. Tools > "Clear pywin32 gen_py cache" fixes it for older scripts.
"""
