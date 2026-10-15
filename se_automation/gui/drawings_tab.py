"""Tab 1: the ordered drawing list - add, insert, reorder, rename, apply."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from .. import naming, operations as ops
from ..jobfolder import ScanResult, scan_drawings_folder
from ..plan import Plan, Row, build_plan
from ..solidedge import DesignManager, SolidEdge
from ..templates import TemplateLibrary, split_codes
from .dialogs import TemplatePicker, show_text_dialog
from .widgets import PAD, PlaceholderEntry

if TYPE_CHECKING:
    from .app import App


class DrawingsTab(ttk.Frame):
    COLUMNS = ("number", "name", "description", "status", "source")

    def __init__(self, master, app: "App"):
        super().__init__(master, padding=PAD)
        self.app = app
        self.rows: list[Row] = []
        self.scan = ScanResult()
        self.plan: Plan | None = None
        self._editor: ttk.Entry | None = None
        self._drag_uid: int | None = None
        self._build()

    # --- layout ------------------------------------------------------------------

    def _build(self) -> None:
        add = ttk.LabelFrame(self, text="Add supports", padding=PAD)
        add.pack(fill="x")
        row1 = ttk.Frame(add)
        row1.pack(fill="x")
        ttk.Label(row1, text="Style-size:").pack(side="left")
        self.quick_var = tk.StringVar()
        quick = PlaceholderEntry(row1, "e.g. D6-36, P10-8, P20-20", textvariable=self.quick_var, width=40)
        quick.pack(side="left", padx=4)
        quick.bind("<Return>", lambda e: self.quick_add())
        self.add_button = ttk.Button(row1, text="Add", command=self.quick_add)
        self.add_button.pack(side="left")
        ttk.Separator(row1, orient="vertical").pack(side="left", fill="y", padx=PAD * 2)
        self.browse_button = ttk.Button(row1, text="Browse templates...", command=self.open_template_picker)
        self.browse_button.pack(side="left")
        self.other_button = ttk.Button(row1, text="From another job / folder...", command=self.add_from_files)
        self.other_button.pack(side="left", padx=4)
        ttk.Label(add, foreground="#555555",
                  text="Type one or more template names separated by commas and press Enter.  "
                       "New supports go right below the selected row (or at the end if nothing is selected)."
                  ).pack(anchor="w", pady=(4, 0))

        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True, pady=PAD)
        table = ttk.Frame(middle)
        table.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=self.COLUMNS, show="headings", selectmode="extended")
        for col, title, width, stretch in (("number", "No.", 56, False), ("name", "Drawing / folder name", 230, True),
                                           ("description", "Description (double-click to edit)", 200, True),
                                           ("status", "Change", 190, True), ("source", "Copied from", 220, True)):
            self.tree.heading(col, text=title, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("new", background="#e3f4e1")
        self.tree.tag_configure("changed", background="#fff4d6")
        self.tree.tag_configure("problem", background="#fde2e2")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<F2>", lambda e: self.edit_description())
        self.tree.bind("<Delete>", lambda e: self.remove_new())
        self.tree.bind("<Control-Up>", lambda e: (self.move(-1), "break")[1])
        self.tree.bind("<Control-Down>", lambda e: (self.move(1), "break")[1])
        self.tree.bind("<Control-d>", lambda e: self.duplicate())
        self.tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_end, add="+")

        side = ttk.Frame(middle)
        side.pack(side="left", fill="y", padx=(PAD, 0))
        self.side_buttons = []
        for text, cmd in (("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1)),
                          ("Duplicate", self.duplicate), ("Edit description", self.edit_description),
                          ("Remove (new only)", self.remove_new)):
            b = ttk.Button(side, text=text, command=cmd, width=18)
            b.pack(fill="x", pady=2)
            self.side_buttons.append(b)
        ttk.Separator(side).pack(fill="x", pady=PAD)
        b = ttk.Button(side, text="Discard changes", command=self.discard, width=18)
        b.pack(fill="x", pady=2)
        self.side_buttons.append(b)
        ttk.Label(side, foreground="#555555", justify="left", wraplength=150,
                  text="Tip: drag rows to reorder.\nCtrl+Up/Down moves,\nCtrl+D duplicates,\nF2 edits.").pack(
            anchor="w", pady=PAD)

        self.messages = tk.Text(self, height=3, wrap="word", relief="flat", background=self.app.bg,
                                state="disabled", font=("Segoe UI", 9))
        self.messages.tag_configure("error", foreground="#b00020")
        self.messages.tag_configure("warning", foreground="#a15c00")
        self.messages.tag_configure("info", foreground="#555555")
        self.messages.pack(fill="x")

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(PAD, 0))
        s = self.app.settings
        self.fill_title_var = tk.BooleanVar(value=s["fill_title_block"])
        self.leave_open_var = tk.BooleanVar(value=s["leave_new_open"])
        ttk.Checkbutton(bottom, text="Fill the title block on new drawings (values from the Title Block tab)",
                        variable=self.fill_title_var).pack(anchor="w")
        ttk.Checkbutton(bottom, text="Leave new drawings open in Solid Edge afterwards",
                        variable=self.leave_open_var).pack(anchor="w")
        self.summary = ttk.Label(bottom, text="", font=("Segoe UI", 9, "bold"))
        self.summary.pack(side="left", pady=(PAD, 0))
        self.apply_button = ttk.Button(bottom, text="Preview & apply changes...", command=self.preview_and_apply)
        self.apply_button.pack(side="right", pady=(PAD, 0))

    def busy_widgets(self):
        return [self.add_button, self.browse_button, self.other_button, self.apply_button, *self.side_buttons]

    # --- loading -----------------------------------------------------------------

    def load(self, scan: ScanResult) -> None:
        self.scan = scan
        self.rows = [Row(d.description, existing=d) for d in scan.drawings]
        self.refresh()

    def discard(self) -> None:
        if self.plan and self.plan.has_changes and not messagebox.askyesno(
                "Discard changes", "Throw away the changes you haven't applied yet?"):
            return
        self.app.reload_folder(keep_title_block=True)

    # --- plan + table ------------------------------------------------------------

    def refresh(self, select_uids: list[int] | None = None) -> None:
        if select_uids is None:
            select_uids = [int(i) for i in self.tree.selection()]
        self.tree.delete(*self.tree.get_children())
        folder = self.app.folder
        if folder is None:
            self.plan = None
            self._show_messages([("info", "Choose a drawings folder at the top of the window to get started.")])
            self.summary.configure(text="")
            self.apply_button.state(["disabled"])
            return
        start = naming.parse_number(self.app.start_var.get()) or 0
        self.plan = build_plan(folder, self.rows, self.app.prefix_var.get(), start, self.scan.ignored)
        for item in self.plan.items:
            row = item.row
            tag = "new" if row.is_new else "changed" if item.is_rename else ""
            if naming.validate_name_part(row.description, "x"):
                tag = "problem"
            source = str(row.source_dft) if row.is_new else ""
            self.tree.insert("", "end", iid=str(row.uid), tags=(tag,),
                             values=(naming.format_number(item.number), item.name, row.description,
                                     item.status, source))
        keep = [str(u) for u in select_uids if self.tree.exists(str(u))]
        if keep:
            self.tree.selection_set(keep)
            self.tree.see(keep[-1])

        msgs = [("error", e) for e in self.plan.errors] + [("warning", w) for w in self.plan.warnings]
        if self.scan.ignored:
            msgs.append(("info", "Not listed (not drawing folders): " + ", ".join(self.scan.ignored)))
        if not self.rows:
            msgs.append(("info", "This folder has no drawings yet. Add supports above."))
        self._show_messages(msgs)
        n_new, n_ren = len(self.plan.copies), len(self.plan.renames)
        parts = []
        if n_new:
            parts.append(f"{n_new} new")
        if n_ren:
            parts.append(f"{n_ren} renamed/renumbered")
        self.summary.configure(text=("Pending: " + ", ".join(parts)) if parts else "No pending changes.")
        enabled = self.plan.ok and self.plan.has_changes and not self.app.runner.busy
        self.apply_button.state(["!disabled"] if enabled else ["disabled"])

    def _show_messages(self, msgs) -> None:
        self.messages.configure(state="normal")
        self.messages.delete("1.0", "end")
        for level, text in msgs:
            self.messages.insert("end", text + "\n", level)
        self.messages.configure(height=min(max(len(msgs), 1), 5), state="disabled")

    def _selected_rows(self) -> list[Row]:
        uids = {int(i) for i in self.tree.selection()}
        return [r for r in self.rows if r.uid in uids]

    def _insert_rows(self, new_rows: list[Row]) -> None:
        """Insert below the last selected row, or at the end."""
        selected = self._selected_rows()
        index = max(self.rows.index(r) for r in selected) + 1 if selected else len(self.rows)
        self.rows[index:index] = new_rows
        self.refresh(select_uids=[r.uid for r in new_rows])
        self.tree.focus(str(new_rows[-1].uid))

    # --- adding ------------------------------------------------------------------

    def _require_folder(self) -> bool:
        if self.app.folder is None:
            messagebox.showinfo("Choose a folder", "Choose the drawings folder first (top of the window).")
            return False
        return True

    def library(self) -> TemplateLibrary:
        return TemplateLibrary(Path(self.app.settings["template_root"]))

    def quick_add(self) -> None:
        if not self._require_folder():
            return
        codes = split_codes(self.quick_var.get())
        if not codes:
            return
        lib = self.library()
        if not lib.available():
            messagebox.showerror("Template library not found",
                                 f"Can't open the template library:\n{lib.root}\n\nCheck Tools > Settings.")
            return
        self.app.set_cursor("watch")
        try:
            found, missing = [], []
            for code in codes:
                template = lib.find(code)
                if template:
                    found.append(Row(template.code, source_dft=template.dft, source_label=f"template {template.code}"))
                else:
                    missing.append(code)
        finally:
            self.app.set_cursor("")
        if found:
            self._insert_rows(found)
            self.app.log(f"Added {', '.join(r.description for r in found)} from the template library.")
        if missing:
            messagebox.showwarning("Not found", "Not found in the template library:\n  " + "\n  ".join(missing)
                                   + "\n\nUse \"Browse templates...\" or \"From another job / folder...\".")
            self.quick_var.set(", ".join(missing))
        else:
            self.quick_var.set("")

    def open_template_picker(self) -> None:
        if not self._require_folder():
            return
        lib = self.library()
        if not lib.available():
            messagebox.showerror("Template library not found",
                                 f"Can't open the template library:\n{lib.root}\n\nCheck Tools > Settings.")
            return

        def add(templates):
            self._insert_rows([Row(t.code, source_dft=t.dft, source_label=f"template {t.code}") for t in templates])

        TemplatePicker(self, lib, add)

    def add_from_files(self) -> None:
        if not self._require_folder():
            return
        start = self.app.settings.data.get("last_other_folder") or self.app.settings["browse_start"]
        paths = filedialog.askopenfilenames(title="Choose the draft(s) to copy into this job",
                                            initialdir=start if Path(start).is_dir() else None,
                                            filetypes=[("Solid Edge draft", "*.dft")])
        if not paths:
            return
        paths = [Path(p) for p in paths]
        self.app.settings["last_other_folder"] = str(paths[0].parent.parent)
        rows = [Row(naming.guess_description(p), source_dft=p, source_label=f"copy of {p.stem}") for p in paths]
        self._insert_rows(rows)
        self.app.log("Added " + ", ".join(f"{r.description} (from {r.source_dft.stem})" for r in rows)
                     + ". Double-click a description to change it.")

    # --- editing -----------------------------------------------------------------

    def move(self, step: int) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        indices = sorted(self.rows.index(r) for r in selected)
        if (step < 0 and indices[0] == 0) or (step > 0 and indices[-1] == len(self.rows) - 1):
            return
        for i in (indices if step < 0 else reversed(indices)):
            self.rows[i], self.rows[i + step] = self.rows[i + step], self.rows[i]
        self.refresh(select_uids=[r.uid for r in selected])

    def duplicate(self) -> None:
        selected = self._selected_rows()
        if not selected:
            messagebox.showinfo("Duplicate", "Select the drawing(s) to duplicate first.")
            return
        for row in reversed(selected):
            if row.is_new:
                copy = Row(row.description, source_dft=row.source_dft, source_label=row.source_label)
            elif row.existing.dft is not None:
                copy = Row(row.description, source_dft=row.existing.dft,
                           source_label=f"copy of {row.existing.folder.name}")
            else:
                messagebox.showwarning("Duplicate", f"{row.existing.folder.name} doesn't have a single main draft "
                                                    "to copy.")
                continue
            self.rows.insert(self.rows.index(row) + 1, copy)
        self.refresh()

    def remove_new(self) -> None:
        selected = self._selected_rows()
        existing = [r for r in selected if not r.is_new]
        if existing:
            messagebox.showinfo("Remove", "Only drawings that haven't been created yet can be removed here.\n\n"
                                          "To take an existing drawing out of the job, move or delete its folder in "
                                          "File Explorer, then click Refresh. The numbers after it will close up "
                                          "the next time you apply changes.")
        for r in selected:
            if r.is_new:
                self.rows.remove(r)
        self.refresh()

    def edit_description(self) -> None:
        sel = self.tree.selection()
        if sel:
            self._start_editor(sel[0])

    def _on_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_region(event.x, event.y) == "cell":
            self._start_editor(iid)

    def _start_editor(self, iid: str) -> None:
        if self._editor is not None or self.app.runner.busy:
            return
        bbox = self.tree.bbox(iid, "description")
        if not bbox:
            return
        row = next(r for r in self.rows if str(r.uid) == iid)
        x, y, w, h = bbox
        var = tk.StringVar(value=row.description)
        entry = ttk.Entry(self.tree, textvariable=var)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        entry.select_range(0, "end")
        self._editor = entry

        def finish(save: bool):
            if self._editor is None:
                return
            self._editor = None
            entry.destroy()
            if save and var.get().strip() and var.get().strip() != row.description:
                row.description = var.get().strip()
                self.refresh()
            self.tree.focus_set()

        entry.bind("<Return>", lambda e: finish(True))
        entry.bind("<KP_Enter>", lambda e: finish(True))
        entry.bind("<Escape>", lambda e: finish(False))
        entry.bind("<FocusOut>", lambda e: finish(True))

    # drag to reorder
    def _drag_start(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        self._drag_uid = int(iid) if iid and self.tree.identify_region(event.x, event.y) == "cell" else None

    def _drag_motion(self, event) -> None:
        if self._drag_uid is None or self._editor is not None:
            return
        target = self.tree.identify_row(event.y)
        if not target or int(target) == self._drag_uid:
            return
        row = next((r for r in self.rows if r.uid == self._drag_uid), None)
        dest = next((r for r in self.rows if r.uid == int(target)), None)
        if row is None or dest is None:
            return
        index = self.rows.index(dest)   # the dragged row takes the place of the row under the cursor
        self.rows.remove(row)
        self.rows.insert(index, row)
        self.refresh(select_uids=[row.uid])
        self.tree.configure(cursor="sb_v_double_arrow")

    def _drag_end(self, event) -> None:
        self._drag_uid = None
        self.tree.configure(cursor="")

    # --- apply -------------------------------------------------------------------

    def preview_and_apply(self) -> None:
        self.refresh()
        plan = self.plan
        if plan is None or not plan.has_changes:
            return
        if not plan.ok:
            messagebox.showerror("Can't apply", "\n".join(plan.errors))
            return
        title_values = self.app.titleblock_tab.property_values() if self.fill_title_var.get() else {}
        lines = [f"Folder: {plan.target}", ""]
        if plan.renames:
            lines.append(f"Rename / renumber {len(plan.renames)} existing drawing(s):")
            for p in plan.renames:
                extra = f"   (Drawing Number {naming.format_number(p.row.existing.number)} -> " \
                        f"{naming.format_number(p.number)})" if p.number_changes else ""
                lines.append(f"    {p.old_name}  ->  {p.name}{extra}")
            lines.append("")
        if plan.copies:
            lines.append(f"Copy {len(plan.copies)} new drawing(s) with Design Manager:")
            for p in plan.copies:
                lines.append(f"    {p.name}   <-   {p.row.source_dft}")
            lines.append("")
            if self.fill_title_var.get():
                if title_values:
                    lines.append("Title block on the new drawings:")
                    labels = {(f.prop_set, f.prop_name): f.label for f in self.app.titleblock_fields()}
                    for key, value in title_values.items():
                        lines.append(f"    {labels.get(key, key[1])}: {value}")
                else:
                    lines.append("Title block: the Title Block tab is empty, so only the Drawing Number is set.")
            else:
                lines.append("Title block: only the Drawing Number is set on new drawings.")
            if self.leave_open_var.get():
                lines.append("New drawings will be left open in Solid Edge.")
        if plan.warnings:
            lines += ["", "Warnings:"] + [f"    {w}" for w in plan.warnings]
        if not show_text_dialog(self, "Preview changes", "\n".join(lines), ok_text="Apply"):
            return

        s = self.app.settings
        s["fill_title_block"] = self.fill_title_var.get()
        s["leave_new_open"] = self.leave_open_var.get()
        s.save()
        pdf_folders = self.app.pdf_tab.output_folders()
        fill, leave_open = self.fill_title_var.get(), self.leave_open_var.get()

        def work(reporter):
            se, dm = SolidEdge(reporter.log), DesignManager(reporter.log)
            try:
                return ops.apply_plan(plan, copier=dm.copy_draft, writer=ops.DraftPropertyWriter(se),
                                      title_values=title_values, fill_title_block=fill,
                                      leave_new_open=leave_open,
                                      open_documents=SolidEdge.open_documents_if_running,
                                      pdf_folders=pdf_folders, reporter=reporter)
            finally:
                dm.quit()

        self.app.runner.run("Apply changes", work, self._after_apply)

    def _after_apply(self, result: ops.ApplyResult) -> None:
        self.app.reload_folder(keep_title_block=True)
        self.app.remember_changed(result.changed_drafts)
        lines = []
        if result.copied:
            lines.append(f"Created {len(result.copied)} drawing(s).")
        if result.renamed:
            lines.append(f"Renamed/renumbered {len(result.renamed)} drawing(s).")
        if result.failed:
            lines.append("\nNOT created (see the log): " + ", ".join(result.failed)
                         + "\nThe numbers are reserved; add them again at the same position to fill the gap.")
        if result.stale_pdfs:
            lines.append("\nThese PDFs have the OLD drawing number and are now out of date. They were left as they "
                         "are - reprint those drawings from the Print PDFs tab once they're ready:\n  "
                         + "\n  ".join(str(p) for p in result.stale_pdfs))
        for line in lines:
            self.app.log(line.strip(), "warning" if line.startswith("\n") else "info")
        if result.property_problems:   # already in the log
            lines.append("\nTitle block issues:\n  " + "\n  ".join(result.property_problems))
        text = "\n".join(lines).strip() or "Done."
        if result.failed or result.property_problems or result.stale_pdfs:
            messagebox.showwarning("Changes applied", text)
        else:
            messagebox.showinfo("Changes applied", text)
