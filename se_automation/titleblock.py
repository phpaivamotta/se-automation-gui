"""Title block fields and the draft properties they map to.

Property names were read from the current templates. Matching ignores letter case
and a trailing colon, because templates disagree (S2/S7 use "COMPANY ADDRESS:",
D/P styles use "COMPANY ADDRESS"). If the templates change, update them here.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    prop_set: str
    prop_name: str
    remember: bool = False       # value is saved as the user's default
    width: int = 40
    hint: str = ""               # gray example shown while the field is empty


FIELDS: list[Field] = [
    Field("project_name", "Project name", "ProjectInformation", "Project Name", width=60,
          hint="e.g. WRP REHABILITATION PROJECT"),
    Field("location", "Project location", "SummaryInformation", "Subject", hint="e.g. PHOENIX, AZ"),
    Field("client", "Client", "Custom", "CLIENT", hint="e.g. ABC STEEL FABRICATION"),
    Field("client_address", "Client address", "Custom", "CLIENT ADDRESS", hint="e.g. HOUSTON, TX"),
    Field("po", "Customer P.O.", "Custom", "Customer P.O.:", width=24, hint="e.g. 483-00012"),
    Field("wo", "Customer W.O.", "Custom", "Customer W.O.:", remember=True, width=24, hint="- if there is none"),
    Field("job_no", "MSS job no.", "Custom", "MSS Job No:", width=24, hint="e.g. 20274080"),
    Field("doc_no", "Document number", "ProjectInformation", "Document Number", width=24,
          hint="e.g. 4080 (= prefix)"),
    Field("revision", "Revision", "ProjectInformation", "Revision", remember=True, width=8, hint="e.g. A"),
    Field("date", "Date", "Custom", "DATE", width=12, hint="MM/DD/YY"),
    Field("drawn_by", "Drawn by", "Custom", "DRAWN BY:", remember=True, width=8, hint="initials"),
    Field("checked_by", "Checked by", "Custom", "CHECKED BY:", remember=True, width=8, hint="initials"),
    Field("approved_by", "Approved by", "Custom", "APPROVED BY:", remember=True, width=8, hint="initials"),
    Field("company_address", "Company address", "Custom", "COMPANY ADDRESS", remember=True,
          hint="e.g. PALMETTO, FLORIDA"),
]
FIELDS_BY_KEY = {f.key: f for f in FIELDS}

DRAWING_NUMBER = ("Custom", "Drawing Number:")

# Values the templates ship with; never copy these from a drawing into the form.
# (Every template still carries the client of the job it was originally made for.)
PLACEHOLDERS = {"", "XX", "XX/XX/XX", "XXXX", "PROJECT NAME", "PROJECT LOCATION",
                "MSS JOB NO", "CUST PO", "CUST WO", "DWG NO",
                "RPS COMPOSITES, INC.", "MAHONE BAY, NOVA SCOTIA"}


def _normalize(name: str) -> str:
    return name.strip().rstrip(":").strip().casefold()


def today() -> str:
    return _dt.date.today().strftime("%m/%d/%y")


def to_property_values(values: dict[str, str]) -> dict[tuple[str, str], str]:
    """Form values -> property values. Blank fields are skipped (left unchanged)."""
    out = {}
    for f in FIELDS:
        value = values.get(f.key, "").strip()
        if value:
            out[(f.prop_set, f.prop_name)] = value
    return out


def from_file_properties(props: dict[str, dict]) -> dict[str, str]:
    """Properties read from a draft -> form values (template placeholders dropped)."""
    out = {}
    for f in FIELDS:
        pset = props.get(f.prop_set, {})
        value = pset.get(f.prop_name)
        if value is None:
            value = next((v for k, v in pset.items() if _normalize(k) == _normalize(f.prop_name)), None)
        if value is None:
            continue
        value = str(value).strip()
        if value.upper() not in PLACEHOLDERS:
            out[f.key] = value
    return out
