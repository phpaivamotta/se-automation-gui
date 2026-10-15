# SE Automation

A desktop app for starting and maintaining Solid Edge pipe support jobs:

- **Drawings**: copy support templates (or drawings from older jobs) into a job with Design Manager,
  name them `{prefix}-{number}-{style-size}`, insert supports anywhere in the list and renumber the
  ones after them.
- **Title Block**: fill or update the title block (project, client, P.O., date, initials, ...).
- **Print PDFs**: the fabricator set (all sheets) and the customer set (sheets 1,2).

## Starting it

Double-click **`SE Automation.bat`**.

- The first run takes about a minute. It sets up a private Python environment in
  `%LOCALAPPDATA%\SE Automation\venv` and installs `pywin32`. After that the app opens right away.
- Each PC needs **Python 3.9 or newer** from python.org (tick *Add python.exe to PATH* when installing).
  The `.bat` prints a message if Python is missing.
- To share the app, copy this whole folder somewhere everyone can reach (e.g. the F: drive) and have
  people make a desktop shortcut to `SE Automation.bat`.

Help > *How to use* inside the app has the step-by-step instructions.

## Where things are kept

| What | Where |
|---|---|
| Per-user settings (template library path, initials, recent folders) | `%APPDATA%\SE Automation\settings.json` |
| Log files | `%LOCALAPPDATA%\SE Automation\logs` (Tools > Open log folder) |

## For whoever maintains it

```
se_automation/
  naming.py       job-number detection, prefix, drawing-name parsing/formatting
  jobfolder.py    reads the drawings already in a folder
  plan.py         turns the ordered list into renames + copies, and validates it
  operations.py   applies a plan (two-step renames with rollback), title blocks, PDFs
  solidedge.py    Solid Edge / Design Manager / file-properties calls
  com.py          late-bound COM wrapper (no gen_py cache)
  templates.py    template library lookup
  titleblock.py   title block fields -> draft property names
  settings.py     per-user settings
  gui/            tkinter window (app.py) and its tabs/dialogs
tests/            run with:  .venv\Scripts\python -m unittest discover -s tests -t .
```

Things learned the hard way (also noted in the code):

- **gen_py errors**: `com.py` calls `IDispatch` directly, so the app never uses pywin32's `gen_py`
  cache and can't hit that error. Tools > *Clear pywin32 gen_py cache* fixes it for the older
  scripts in this folder.
- **Design Manager** silently does nothing unless the document returned by
  `OpenFileInDesignManager` is still referenced when `PerformAction` runs.
- Assemblies with repeated sub-assemblies (e.g. D6-36) make Design Manager ask
  *"Expand All: Populate Duplicates"*. The app answers **Hide**, which is the default and only
  affects what Design Manager displays.
- Title block properties are written straight into the `.dft` file (Solid Edge picks them up when
  the drawing is opened). Drawings that are already open in Solid Edge are updated through Solid
  Edge instead.
- Templates disagree on property names (`COMPANY ADDRESS` vs `COMPANY ADDRESS:`), so name matching
  ignores case and a trailing colon. If the templates change, update `titleblock.py`.

The older one-off scripts in this folder (`main.py`, `pdf_print.py`, ...) are untouched and still
work as before. The app replaces `main.py`, `update_properties.py`, `pdf_print.py` and
`reorder_supports.py`.
