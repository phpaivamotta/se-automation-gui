"""Tab 2: title block values - used for new drawings and to update existing ones."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .. import operations as ops, titleblock
from ..com import describe_error
from ..solidedge import SolidEdge, read_file_properties
from .dialogs import show_text_dialog
from .widgets import PAD, DraftChecklist, PlaceholderEntry, run_in_background

if TYPE_CHECKING:
    from .app import App


class TitleBlockTab(ttk.Frame):
    def __init__(self, master, app: "App"):
        super().__init__(master, padding=PAD)
        self.app = app
        self.vars = {f.key: tk.StringVar() for f in titleblock.FIELDS}
        self._auto = {"job_no": "", "doc_no": ""}
        self._build()

    def _build(self) -> None:
        form = ttk.LabelFrame(self, text="Title block values", padding=PAD)
        form.pack(side="left", fill="y")
        for r, f in enumerate(titleblock.FIELDS):
            ttk.Label(form, text=f.label + ":").grid(row=r, column=0, sticky="w", pady=2)
            cell = ttk.Frame(form)
            cell.grid(row=r, column=1, sticky="w", padx=4, pady=2)
            PlaceholderEntry(cell, f.hint, textvariable=self.vars[f.key], width=f.width).pack(side="left")
            if f.key == "date":
                ttk.Button(cell, text="Today", width=7,
                           command=lambda: self.vars["date"].set(titleblock.today())).pack(side="left", padx=4)
        r = len(titleblock.FIELDS)
        ttk.Label(form, foreground="#555555", wraplength=420, justify="left",
                  text="Blank fields (gray examples) are left unchanged. The Drawing Number is always taken from "
                       "each drawing's name (e.g. 4080-0103-P10-8 -> 0103).").grid(row=r, column=0, columnspan=3, sticky="w",
                                                                    pady=(PAD, 0))
        buttons = ttk.Frame(form)
        buttons.grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(PAD, 0))
        self.load_button = ttk.Button(buttons, text="Load from a drawing", command=self.load_from_selected)
        self.load_button.pack(side="left")
        ttk.Button(buttons, text="Save as my defaults", command=self.save_defaults).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left")
        ttk.Label(form, foreground="#555555", wraplength=420, justify="left",
                  text="\"Load from a drawing\" copies the values from the drawing selected on the right. "
                       "\"Save as my defaults\" remembers your initials, revision, W.O. and company address."
                  ).grid(row=r + 2, column=0, columnspan=3, sticky="w", pady=(PAD, 0))

        right = ttk.LabelFrame(self, text="Update existing drawings", padding=PAD)
        right.pack(side="left", fill="both", expand=True, padx=(PAD, 0))
        self.checklist = DraftChecklist(right)
        self.checklist.pack(fill="both", expand=True)
        self.set_number_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Also set the Drawing Number from each file name",
                        variable=self.set_number_var).pack(anchor="w", pady=(PAD, 0))
        self.apply_button = ttk.Button(right, text="Update title blocks of checked drawings...",
                                       command=self.apply)
        self.apply_button.pack(anchor="e", pady=(PAD, 0))

    def busy_widgets(self):
        return [self.apply_button, self.load_button]

    # --- values --------------------------------------------------------------------

    def values(self) -> dict[str, str]:
        return {k: v.get().strip() for k, v in self.vars.items()}

    def property_values(self):
        return titleblock.to_property_values(self.values())

    def reset_for_job(self, job_number: str, prefix: str) -> None:
        defaults = self.app.settings["title_defaults"]
        for f in titleblock.FIELDS:
            self.vars[f.key].set(defaults.get(f.key, "") if f.remember else "")
        self.vars["date"].set(titleblock.today())
        self.vars["job_no"].set(job_number)
        self.vars["doc_no"].set(prefix)
        self._auto = {"job_no": job_number, "doc_no": prefix}

    def follow(self, key: str, value: str) -> None:
        """Keep MSS job no. / document number in step with the header, unless edited by hand."""
        if self.vars[key].get() in ("", self._auto[key]):
            self.vars[key].set(value)
        self._auto[key] = value

    def fill(self, values: dict[str, str], only_empty: bool) -> int:
        count = 0
        for key, value in values.items():
            if key in self.vars and (not only_empty or not self.vars[key].get().strip()):
                self.vars[key].set(value)
                count += 1
        return count

    def clear(self) -> None:
        for var in self.vars.values():
            var.set("")

    def save_defaults(self) -> None:
        defaults = self.app.settings["title_defaults"]
        for f in titleblock.FIELDS:
            if f.remember:
                defaults[f.key] = self.vars[f.key].get().strip()
        self.app.settings.save()
        self.app.log("Saved your title block defaults (initials, revision, W.O., company address).")

    # --- loading from a drawing ------------------------------------------------------

    def load_from_selected(self) -> None:
        dft = self.checklist.first_selected()
        if dft is None:
            messagebox.showinfo("Load from a drawing", "There are no drawings in this folder to load from.")
            return
        self.load_from_drawing(dft, only_empty=False)

    def load_from_drawing(self, dft: Path, only_empty: bool, quiet: bool = False) -> None:
        folder_at_start = self.app.folder

        def done(props):
            if self.app.folder != folder_at_start:
                return   # user moved on to another folder
            values = titleblock.from_file_properties(props)
            # The job number / document number come from the header, not an old drawing.
            if only_empty:
                values.pop("job_no", None)
                values.pop("doc_no", None)
            n = self.fill(values, only_empty)
            self.app.log(f"Title block: filled {n} field(s) from {dft.name}.")

        def failed(exc):
            if not quiet:
                messagebox.showerror("Load from a drawing", f"Couldn't read {dft.name}:\n{describe_error(exc)}")
            self.app.log(f"Couldn't read title block from {dft.name}: {describe_error(exc)}", "warning")

        run_in_background(self, lambda: read_file_properties(dft), done, failed)

    # --- apply -------------------------------------------------------------------------

    def set_drafts(self, drafts: list[Path], base: Path | None) -> None:
        self.checklist.set_drafts(drafts, base, checked=False)

    def apply(self) -> None:
        drafts = self.checklist.checked()
        if not drafts:
            messagebox.showinfo("Update title blocks", "Check the drawings to update first.")
            return
        values = self.property_values()
        set_number = self.set_number_var.get()
        if not values and not set_number:
            messagebox.showinfo("Update title blocks", "All fields are blank - nothing to change.")
            return
        labels = {(f.prop_set, f.prop_name): f.label for f in titleblock.FIELDS}
        lines = [f"Update {len(drafts)} drawing(s):"] + [f"    {d.name}" for d in drafts[:15]]
        if len(drafts) > 15:
            lines.append(f"    ... and {len(drafts) - 15} more")
        lines += ["", "With these values:"] + [f"    {labels[k]}: {v}" for k, v in values.items()]
        if set_number:
            lines.append("    Drawing Number: from each file name")
        lines += ["", "Drawings open in Solid Edge are updated and saved there; the others are updated "
                      "directly in the file."]
        if not show_text_dialog(self, "Update title blocks", "\n".join(lines), ok_text="Update"):
            return

        def work(reporter):
            writer = ops.DraftPropertyWriter(SolidEdge(reporter.log))
            return ops.apply_title_block(writer, drafts, values, set_number, False, reporter)

        def done(problems):
            if problems:
                messagebox.showwarning("Update title blocks", "Finished with problems:\n\n" + "\n".join(problems))
            else:
                messagebox.showinfo("Update title blocks", f"Updated {len(drafts)} drawing(s).")

        self.app.runner.run("Update title blocks", work, done)
