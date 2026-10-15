"""Reusable GUI pieces: log panel, background task runner, drawing checklist."""

from __future__ import annotations

import datetime as dt
import logging
import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from .. import com

log = logging.getLogger("se_automation")

PAD = 6
HINT_COLOR = "#8c8c8c"


class PlaceholderEntry(ttk.Entry):
    """A ttk.Entry that shows a gray example while it's empty.

    The hint is drawn on top of the field, so it is never part of the value:
    ``textvariable.get()`` stays "" until the user types something.
    """

    def __init__(self, master, placeholder: str = "", textvariable: tk.StringVar | None = None, **kw):
        self.var = textvariable if textvariable is not None else tk.StringVar()
        super().__init__(master, textvariable=self.var, **kw)
        self._hint = tk.Label(self, text=placeholder, foreground=HINT_COLOR, background="SystemWindow",
                              font="TkTextFont", borderwidth=0, padx=0, pady=0, cursor="xterm")
        self._hint.bind("<Button-1>", lambda e: (self.focus_set(), self.icursor(0)))
        self._trace = self.var.trace_add("write", lambda *_: self._update())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._update()

    def _update(self) -> None:
        try:
            if self.var.get():
                self._hint.place_forget()
            else:
                self._hint.place(x=4, rely=0.5, anchor="w")
        except tk.TclError:   # widget already destroyed
            pass

    def _on_destroy(self, event) -> None:
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except tk.TclError:
                pass

    def state(self, statespec=None):
        result = super().state(statespec)
        if statespec is not None:
            self._hint.configure(background="SystemButtonFace" if self.instate(["disabled"]) else "SystemWindow")
        return result


class LogPanel(ttk.Frame):
    """Progress bar, Cancel button and a scrolling activity log."""

    def __init__(self, master, on_cancel: Callable[[], None]):
        super().__init__(master)
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.status = ttk.Label(top, text="Ready.")
        self.status.pack(side="left")
        self.cancel_button = ttk.Button(top, text="Cancel", command=on_cancel, state="disabled")
        self.cancel_button.pack(side="right")
        self.bar = ttk.Progressbar(top, length=220, mode="determinate")
        self.bar.pack(side="right", padx=PAD)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(4, 0))
        self.text = tk.Text(body, height=8, wrap="word", state="disabled", relief="solid", borderwidth=1,
                            font=("Consolas", 9))
        scroll = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text.tag_configure("warning", foreground="#a15c00")
        self.text.tag_configure("error", foreground="#b00020")
        self.text.tag_configure("time", foreground="#888888")

    def write(self, message: str, level: str = "info") -> None:
        getattr(log, level if level in ("warning", "error") else "info")(message)
        self.text.configure(state="normal")
        self.text.insert("end", dt.datetime.now().strftime("%H:%M:%S  "), "time")
        self.text.insert("end", message + "\n", level)
        self.text.see("end")
        self.text.configure(state="disabled")

    def set_progress(self, done: int, total: int, text: str = "") -> None:
        self.bar.configure(maximum=max(total, 1), value=done)
        if text:
            self.status.configure(text=text)


class _QueueReporter:
    """Reporter handed to worker threads; everything goes through a queue to the GUI."""

    def __init__(self, q: "queue.Queue", cancel_event: threading.Event):
        self._q = q
        self._cancel = cancel_event

    def log(self, message: str, level: str = "info") -> None:
        self._q.put(("log", message, level))

    def progress(self, done: int, total: int, text: str = "") -> None:
        self._q.put(("progress", done, total, text))

    def cancelled(self) -> bool:
        return self._cancel.is_set()


class TaskRunner:
    """Runs one long job at a time on a worker thread (with COM initialised)."""

    def __init__(self, root: tk.Misc, panel: LogPanel, on_busy: Callable[[bool], None]):
        self.root = root
        self.panel = panel
        self.on_busy = on_busy
        self.busy = False
        self._q: queue.Queue = queue.Queue()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        if self.busy:
            self._cancel.set()
            self.panel.write("Cancelling after the current drawing...", "warning")

    def run(self, title: str, work: Callable[[Any], Any],
            on_done: Callable[[Any], None] | None = None) -> None:
        if self.busy:
            messagebox.showinfo(title, "Please wait for the current task to finish.")
            return
        self.busy = True
        self._cancel.clear()
        self.on_busy(True)
        self.panel.cancel_button.configure(state="normal")
        self.panel.set_progress(0, 1, title + "...")
        self.panel.write(f"--- {title} ---")
        reporter = _QueueReporter(self._q, self._cancel)

        def target():
            try:
                with com.apartment():
                    result = work(reporter)
                self._q.put(("done", result))
            except BaseException as e:   # report everything, including COM errors
                self._q.put(("error", e, traceback.format_exc()))

        threading.Thread(target=target, daemon=True).start()
        self.root.after(100, lambda: self._poll(title, on_done))

    def _poll(self, title: str, on_done) -> None:
        finished = False
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.panel.write(item[1], item[2])
                elif kind == "progress":
                    self.panel.set_progress(item[1], item[2], item[3])
                elif kind == "done":
                    finished = True
                    self._finish(title, "Done.")
                    if on_done:
                        on_done(item[1])
                elif kind == "error":
                    finished = True
                    exc, tb = item[1], item[2]
                    log.error(tb)
                    self._finish(title, "Stopped with an error.")
                    self.panel.write(f"{title} failed: {com.describe_error(exc)}", "error")
                    messagebox.showerror(title, f"{title} failed:\n\n{com.describe_error(exc)}\n\n"
                                                "Details are in the log at the bottom of the window.")
        except queue.Empty:
            pass
        if not finished:
            self.root.after(100, lambda: self._poll(title, on_done))

    def _finish(self, title: str, status: str) -> None:
        self.busy = False
        self.on_busy(False)
        self.panel.cancel_button.configure(state="disabled")
        self.panel.status.configure(text=f"{title}: {status}")


def run_in_background(root: tk.Misc, work: Callable[[], Any], on_done: Callable[[Any], None],
                      on_error: Callable[[BaseException], None] | None = None) -> None:
    """Short background job (e.g. reading properties) that doesn't block the window."""
    q: queue.Queue = queue.Queue()

    def target():
        try:
            with com.apartment():
                q.put((True, work()))
        except BaseException as e:
            log.exception("background task failed")
            q.put((False, e))

    def poll():
        try:
            ok, value = q.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        if ok:
            on_done(value)
        elif on_error:
            on_error(value)

    threading.Thread(target=target, daemon=True).start()
    root.after(100, poll)


class DraftChecklist(ttk.Frame):
    """A filterable list of drafts with check boxes."""

    CHECKED, UNCHECKED = "☑", "☐"

    def __init__(self, master, height: int = 14):
        super().__init__(master)
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._render())
        PlaceholderEntry(bar, "type part of a name", textvariable=self.filter_var, width=20).pack(
            side="left", padx=(4, PAD))
        ttk.Button(bar, text="Check all", command=lambda: self.check_visible(True)).pack(side="left")
        ttk.Button(bar, text="Uncheck all", command=lambda: self.check_visible(False)).pack(side="left", padx=4)
        self.count = ttk.Label(bar, text="")
        self.count.pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=("check", "name", "where"), show="headings", height=height)
        self.tree.heading("check", text="")
        self.tree.heading("name", text="Drawing", anchor="w")
        self.tree.heading("where", text="In sub-folder", anchor="w")
        self.tree.column("check", width=34, stretch=False, anchor="center")
        self.tree.column("name", width=260)
        self.tree.column("where", width=140)
        scroll = ttk.Scrollbar(body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", lambda e: self._toggle(self.tree.selection()))
        self.tree.bind("<Double-1>", lambda e: "break")

        self._drafts: list[Path] = []
        self._checked: set[Path] = set()
        self._base: Path | None = None

    def set_drafts(self, drafts: list[Path], base: Path | None, checked: bool = True) -> None:
        self._drafts = list(drafts)
        self._base = base
        self._checked = set(drafts) if checked else set()
        self._render()

    def checked(self) -> list[Path]:
        return [d for d in self._drafts if d in self._checked]

    def check_only(self, paths: list[Path]) -> None:
        wanted = {str(p).lower() for p in paths}
        self._checked = {d for d in self._drafts if str(d).lower() in wanted}
        self.filter_var.set("")
        self._render()

    def check_visible(self, value: bool) -> None:
        for d in self._visible():
            (self._checked.add if value else self._checked.discard)(d)
        self._render()

    def first_selected(self) -> Path | None:
        sel = self.tree.selection()
        if sel:
            return self._drafts[int(sel[0])]
        visible = self._visible()
        return visible[0] if visible else None

    def _visible(self) -> list[Path]:
        text = self.filter_var.get().strip().lower()
        return [d for d in self._drafts if text in d.name.lower()] if text else self._drafts

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for d in self._visible():
            i = self._drafts.index(d)
            where = ""
            if self._base is not None:
                try:
                    rel = d.parent.relative_to(self._base)
                    if d.parent.name.lower() == d.stem.lower():   # the drawing's own folder
                        rel = rel.parent
                    where = "" if str(rel) == "." else str(rel)
                except ValueError:
                    where = str(d.parent)
            mark = self.CHECKED if d in self._checked else self.UNCHECKED
            self.tree.insert("", "end", iid=str(i), values=(mark, d.stem, where))
        self.count.configure(text=f"{len(self.checked())} of {len(self._drafts)} checked")

    def _toggle(self, iids) -> None:
        for iid in iids:
            d = self._drafts[int(iid)]
            if d in self._checked:
                self._checked.discard(d)
            else:
                self._checked.add(d)
            self.tree.set(iid, "check", self.CHECKED if d in self._checked else self.UNCHECKED)
        self.count.configure(text=f"{len(self.checked())} of {len(self._drafts)} checked")

    def _on_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) == "#1":
            iid = self.tree.identify_row(event.y)
            if iid:
                self._toggle([iid])
                return "break"


def labeled_path_entry(master, label: str, var: tk.StringVar, browse_title: str, width: int = 20,
                       placeholder: str = "") -> ttk.Frame:
    from tkinter import filedialog
    frame = ttk.Frame(master)
    ttk.Label(frame, text=label).pack(side="left")
    entry = PlaceholderEntry(frame, placeholder, textvariable=var, width=width)
    entry.pack(side="left", fill="x", expand=True, padx=4)

    def browse():
        start = var.get() if Path(var.get()).is_dir() else None
        chosen = filedialog.askdirectory(title=browse_title, initialdir=start, mustexist=False)
        if chosen:
            var.set(str(Path(chosen)))

    ttk.Button(frame, text="Browse...", command=browse).pack(side="left")
    return frame
