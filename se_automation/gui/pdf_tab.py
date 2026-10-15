"""Tab 3: print PDFs (fabricator set = all sheets, customer set = first sheets)."""

from __future__ import annotations

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .. import operations as ops
from ..solidedge import SolidEdge
from .dialogs import show_text_dialog
from .widgets import PAD, DraftChecklist, PlaceholderEntry, labeled_path_entry

if TYPE_CHECKING:
    from .app import App


def _expand_sheets(text: str) -> str:
    """ "1-3,5" -> "1,2,3,5" (Solid Edge is given a plain list of sheet numbers)."""
    sheets: list[int] = []
    for part in text.split(","):
        first, _, last = part.partition("-")
        for n in range(int(first), int(last or first) + 1):
            if n not in sheets:
                sheets.append(n)
    return ",".join(str(n) for n in sheets)


class PdfTab(ttk.Frame):
    def __init__(self, master, app: "App"):
        super().__init__(master, padding=PAD)
        self.app = app
        s = app.settings
        self.fab_on = tk.BooleanVar(value=True)
        self.ga_on = tk.BooleanVar(value=True)
        self.fab_dir = tk.StringVar()
        self.ga_dir = tk.StringVar()
        self.ga_sheets = tk.StringVar(value=s["ga_sheets"])
        self.close_after = tk.BooleanVar(value=s["close_after_pdf"])
        self._build()

    def _build(self) -> None:
        left = ttk.LabelFrame(self, text="Drawings to print", padding=PAD)
        left.pack(side="left", fill="both", expand=True)
        self.checklist = DraftChecklist(left)
        self.checklist.pack(fill="both", expand=True)
        self.changed_button = ttk.Button(left, text="Check only drawings created/renumbered since the app was opened",
                                         command=self.check_changed)
        self.changed_button.pack(anchor="w", pady=(PAD, 0))

        right = ttk.LabelFrame(self, text="PDF sets", padding=PAD)
        right.pack(side="left", fill="both", padx=(PAD, 0))
        ttk.Checkbutton(right, text="Fabricator set - all sheets", variable=self.fab_on).pack(anchor="w")
        labeled_path_entry(right, "Save to:", self.fab_dir, "Folder for fabricator PDFs", width=52,
                           placeholder=r"e.g. ...\20274080\Submittal\Fab Latest Revision").pack(
            fill="x", padx=(20, 0), pady=(2, PAD * 2))
        ga = ttk.Frame(right)
        ga.pack(anchor="w")
        ttk.Checkbutton(ga, text="Customer (GA) set - sheets", variable=self.ga_on).pack(side="left")
        PlaceholderEntry(ga, "e.g. 1,2", textvariable=self.ga_sheets, width=8).pack(side="left", padx=4)
        ttk.Label(ga, text="(e.g. 1,2  or  1-3)", foreground="#555555").pack(side="left")
        labeled_path_entry(right, "Save to:", self.ga_dir, "Folder for customer PDFs", width=52,
                           placeholder=r"e.g. ...\20274080\Submittal\GA Latest Revision").pack(
            fill="x", padx=(20, 0), pady=(2, PAD * 2))
        ttk.Checkbutton(right, text="Close drawings when done (ones you already had open stay open)",
                        variable=self.close_after).pack(anchor="w")
        ttk.Label(right, foreground="#555555", wraplength=380, justify="left",
                  text="PDFs are named after the drawing and replace an existing PDF with the same name. "
                       "Solid Edge's own PDF sheet setting is put back afterwards.").pack(anchor="w", pady=PAD)
        self.print_button = ttk.Button(right, text="Print PDFs...", command=self.print_pdfs)
        self.print_button.pack(anchor="e", pady=(PAD, 0))
        self.open_button = ttk.Button(right, text="Open output folder", command=self.open_output)
        self.open_button.pack(anchor="e", pady=(4, 0))

    def busy_widgets(self):
        return [self.print_button]

    def set_job(self, job_root: Path | None, folder: Path | None) -> None:
        s = self.app.settings
        base = job_root or (folder.parent if folder else None)
        self.fab_dir.set(str(base / s["fab_subfolder"]) if base else "")
        self.ga_dir.set(str(base / s["ga_subfolder"]) if base else "")

    def output_folders(self) -> list[Path]:
        return [Path(v.get()) for v in (self.fab_dir, self.ga_dir) if v.get().strip()]

    def set_drafts(self, drafts: list[Path], base: Path | None) -> None:
        self.checklist.set_drafts(drafts, base, checked=True)

    def check_changed(self) -> None:
        if not self.app.last_changed:
            messagebox.showinfo("Changed drawings",
                                "No drawings have been created or renumbered since the app was opened.")
            return
        self.checklist.check_only(self.app.last_changed)

    def open_output(self) -> None:
        for var in (self.fab_dir, self.ga_dir):
            if var.get() and Path(var.get()).is_dir():
                os.startfile(var.get())
                return
        messagebox.showinfo("Open output folder", "The output folder doesn't exist yet.")

    def print_pdfs(self) -> None:
        drafts = self.checklist.checked()
        if not drafts:
            messagebox.showinfo("Print PDFs", "Check the drawings to print first.")
            return
        outputs = []
        if self.fab_on.get():
            if not self.fab_dir.get().strip():
                messagebox.showerror("Print PDFs", "Choose a folder for the fabricator set.")
                return
            outputs.append(ops.PdfOutput("Fabricator", Path(self.fab_dir.get().strip()), None))
        if self.ga_on.get():
            sheets = self.ga_sheets.get().replace(" ", "")
            if not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", sheets):
                messagebox.showerror("Print PDFs", "Enter the customer sheets like  1,2  or  1-3.")
                return
            if not self.ga_dir.get().strip():
                messagebox.showerror("Print PDFs", "Choose a folder for the customer set.")
                return
            self.app.settings["ga_sheets"] = sheets
            outputs.append(ops.PdfOutput("Customer", Path(self.ga_dir.get().strip()), _expand_sheets(sheets)))
        if not outputs:
            messagebox.showinfo("Print PDFs", "Turn on at least one PDF set.")
            return
        lines = [f"Print {len(drafts)} drawing(s):"]
        for out in outputs:
            lines.append(f"    {out.label} ({'all sheets' if out.sheets is None else 'sheets ' + out.sheets})"
                         f"  ->  {out.folder}")
        if not show_text_dialog(self, "Print PDFs", "\n".join(lines), ok_text="Print"):
            return
        self.app.settings["close_after_pdf"] = self.close_after.get()
        self.app.settings.save()
        close_after = self.close_after.get()

        def work(reporter):
            return ops.print_pdfs(SolidEdge(reporter.log), drafts, outputs, close_after, reporter)

        def done(problems):
            if problems:
                messagebox.showwarning("Print PDFs", "Finished with problems:\n\n" + "\n".join(problems))
            else:
                messagebox.showinfo("Print PDFs", f"Printed {len(drafts)} drawing(s).")

        self.app.runner.run("Print PDFs", work, done)
