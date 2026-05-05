"""Nessus CSV parser.

Accepts a standard Tenable Nessus CSV export. The file is expected to contain a
header row and a column named "Risk" (Critical/High/Medium/Low/None). Other
recognised columns include Plugin ID, CVE, CVSS v2.0 Base Score, Host, Name,
Synopsis, Description, Solution, See Also, and Plugin Output.

Returned summary structure (stored on Assessment.nessus_summary)::

    {
        "row_count": 1234,
        "severity_counts": {
            "Critical": 5, "High": 12, "Medium": 41, "Low": 67, "Informational": 88
        },
        "top_findings": [
            {
                "plugin_name": "...",
                "host": "...",
                "severity": "Critical",
                "cvss": 10.0,
                "cve": "CVE-2024-12345",
                "synopsis": "...",
            }, ...
        ],
        "priority_findings": [ ... same shape, only those with CVSS >= 9.0 ... ],
        "deduction_points": 12.5
    }

The parser is defensive: it tolerates BOM markers, mixed casing, and missing
optional columns. The only hard requirement is the presence of either a "Risk"
or "Severity" column.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd


SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Informational"]


# Map any expected Nessus column to a canonical name we use internally.
_COLUMN_ALIASES: Dict[str, str] = {
    "plugin id": "plugin_id",
    "plugin name": "plugin_name",
    "name": "plugin_name",
    "cve": "cve",
    "cvss": "cvss",
    "cvss v2.0 base score": "cvss",
    "cvss v3.0 base score": "cvss_v3",
    "cvss base score": "cvss",
    "risk": "severity",
    "severity": "severity",
    "host": "host",
    "ip address": "host",
    "synopsis": "synopsis",
    "description": "description",
    "solution": "solution",
    "see also": "see_also",
    "plugin output": "plugin_output",
}


_RISK_TO_SEVERITY = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "none": "Informational",
    "informational": "Informational",
    "info": "Informational",
}


class NessusParseError(ValueError):
    """Raised when the uploaded file does not look like a valid Nessus CSV."""


@dataclass
class NessusFinding:
    plugin_id: Optional[str]
    plugin_name: str
    host: str
    severity: str
    cvss: Optional[float]
    cve: Optional[str]
    synopsis: str
    description: str
    solution: str
    see_also: str

    def to_dict(self) -> Dict[str, Union[str, float, None]]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_name": self.plugin_name,
            "host": self.host,
            "severity": self.severity,
            "cvss": self.cvss,
            "cve": self.cve,
            "synopsis": self.synopsis,
            "description": self.description,
            "solution": self.solution,
            "see_also": self.see_also,
        }


def _normalise_columns(columns: List[str]) -> Dict[str, str]:
    """Return a mapping from the raw CSV column name -> canonical key."""
    out: Dict[str, str] = {}
    for col in columns:
        clean = col.strip().lstrip("\ufeff").lower()
        canonical = _COLUMN_ALIASES.get(clean)
        if canonical and canonical not in out.values():
            out[col] = canonical
    return out


def _coerce_severity(value: object) -> str:
    if value is None:
        return "Informational"
    text = str(value).strip().lower()
    return _RISK_TO_SEVERITY.get(text, "Informational")


def _coerce_cvss(value: object) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _safe_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def parse_nessus_csv(
    source: Union[str, Path, bytes, io.IOBase]
) -> Tuple[List[NessusFinding], Dict[str, int]]:
    """Parse a Nessus CSV into a list of findings and a severity counter."""
    try:
        if isinstance(source, (bytes, bytearray)):
            df = pd.read_csv(io.BytesIO(source), dtype=str, keep_default_na=False)
        elif isinstance(source, (str, Path)):
            df = pd.read_csv(source, dtype=str, keep_default_na=False)
        else:
            df = pd.read_csv(source, dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - guarded by route
        raise NessusParseError(f"Could not read CSV file: {exc}") from exc

    column_map = _normalise_columns(list(df.columns))
    if "severity" not in column_map.values():
        raise NessusParseError(
            "Uploaded file does not contain a 'Risk' or 'Severity' column. "
            "Please export from Nessus using the standard CSV format."
        )

    df = df.rename(columns=column_map)

    findings: List[NessusFinding] = []
    counts: Dict[str, int] = {sev: 0 for sev in SEVERITY_ORDER}

    for _, row in df.iterrows():
        severity = _coerce_severity(row.get("severity"))
        counts[severity] = counts.get(severity, 0) + 1

        cvss_v3 = _coerce_cvss(row.get("cvss_v3")) if "cvss_v3" in df.columns else None
        cvss_v2 = _coerce_cvss(row.get("cvss")) if "cvss" in df.columns else None
        cvss = cvss_v3 if cvss_v3 is not None else cvss_v2

        findings.append(
            NessusFinding(
                plugin_id=_safe_str(row.get("plugin_id")) or None,
                plugin_name=_safe_str(row.get("plugin_name")) or "(unnamed)",
                host=_safe_str(row.get("host")) or "(unknown host)",
                severity=severity,
                cvss=cvss,
                cve=_safe_str(row.get("cve")) or None,
                synopsis=_safe_str(row.get("synopsis")),
                description=_safe_str(row.get("description")),
                solution=_safe_str(row.get("solution")),
                see_also=_safe_str(row.get("see_also")),
            )
        )

    return findings, counts


def build_summary(
    findings: List[NessusFinding], counts: Dict[str, int]
) -> Dict[str, object]:
    """Build the JSON-serialisable summary that gets stored on the Assessment."""
    # Filter out informational rows from "top findings" - they are not actionable.
    actionable = [
        f for f in findings if f.severity not in ("Informational", "Low") or (f.cvss or 0) >= 4.0
    ]
    actionable.sort(
        key=lambda f: (
            -(f.cvss or 0.0),
            SEVERITY_ORDER.index(f.severity)
            if f.severity in SEVERITY_ORDER
            else len(SEVERITY_ORDER),
        )
    )
    top = [f.to_dict() for f in actionable[:10]]

    priority = [
        f.to_dict() for f in findings if (f.cvss or 0) >= 9.0
    ]
    priority.sort(key=lambda f: -(f["cvss"] or 0.0))

    # Compute deduction so the UI can show it before the report is generated.
    crit_deduct = min(counts.get("Critical", 0) * 1.5, 15.0)
    high_deduct = min(counts.get("High", 0) * 0.5, 10.0)
    deduction = round(crit_deduct + high_deduct, 1)

    return {
        "row_count": sum(counts.values()),
        "severity_counts": counts,
        "top_findings": top,
        "priority_findings": priority,
        "deduction_points": deduction,
    }


def parse_and_summarise(
    source: Union[str, Path, bytes, io.IOBase]
) -> Tuple[List[NessusFinding], Dict[str, object]]:
    """Convenience: parse the CSV and build the summary in one call."""
    findings, counts = parse_nessus_csv(source)
    return findings, build_summary(findings, counts)
