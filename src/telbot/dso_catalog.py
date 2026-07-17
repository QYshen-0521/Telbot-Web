"""
OpenNGC (NGC/IC/Messier) CSV: offline DSO positions for GOTO.

Download: telbot catalog download-openngc
CSV: semicolon-separated; RA/Dec sexagesimal J2000.
"""

from __future__ import annotations

import csv
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telbot.catalog import CACHE_DIR, _norm

OPENNGC_CSV_URL = (
    "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv"
)
OPENNGC_FILENAME = "openngc_ngc.csv"


def openngc_csv_path() -> Path:
    return CACHE_DIR / OPENNGC_FILENAME


def download_openngc_catalog(url: str = OPENNGC_CSV_URL, *, timeout: float = 600.0) -> Path:
    """Download OpenNGC NGC.csv into ~/.cache/telbot/catalog/."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = openngc_csv_path()
    req = urllib.request.Request(url, headers={"User-Agent": "Telbot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    return dest


def _sex_ra_to_ra_deg(ra: str) -> float:
    ra = (ra or "").strip()
    parts = ra.split(":")
    if len(parts) != 3:
        raise ValueError(f"bad RA: {ra!r}")
    h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    hours = h + m / 60.0 + s / 3600.0
    return hours * 15.0


def _sex_dec_to_dec_deg(dec: str) -> float:
    dc = (dec or "").strip()
    if not dc:
        raise ValueError("empty Dec")
    sign = -1.0 if dc.startswith("-") else 1.0
    dc = dc.lstrip("+-")
    parts = dc.split(":")
    if len(parts) != 3:
        raise ValueError(f"bad Dec: {dec!r}")
    d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    return sign * (d + m / 60.0 + s / 3600.0)


def _messier_m_keys(m_raw: str) -> list[str]:
    m_raw = (m_raw or "").strip()
    if not m_raw:
        return []
    try:
        n = int(m_raw)
    except ValueError:
        return []
    if n <= 0:
        return []
    out = [f"m{n}", f"m {n}", f"messier{n}", f"messier {n}"]
    if n < 1000:
        out.append(f"m{n:03d}")
        out.append(f"m {n:03d}")
    return [_norm(x) for x in out]


def _name_column_keys(name: str) -> list[str]:
    """Keys from OpenNGC Name column (e.g. NGC0224, IC0001)."""
    name = (name or "").strip()
    if not name:
        return []
    keys: list[str] = [_norm(name)]
    m = re.match(r"(?i)NGC(\d+)$", name)
    if m:
        n = int(m.group(1))
        keys.extend(
            [
                _norm(f"NGC{n}"),
                _norm(f"NGC {n}"),
                _norm(f"NGC{n:04d}"),
            ]
        )
    m = re.match(r"(?i)IC(\d+)$", name)
    if m:
        n = int(m.group(1))
        keys.extend(
            [
                _norm(f"IC{n}"),
                _norm(f"IC {n}"),
                _norm(f"IC{n:04d}"),
            ]
        )
    return list(dict.fromkeys(k for k in keys if k))


def _common_name_keys(common: str) -> list[str]:
    if not (common or "").strip():
        return []
    out: list[str] = []
    for part in common.split(","):
        p = part.strip()
        if len(p) < 2:
            continue
        out.append(_norm(p))
    return out


def _build_openngc_index(rows: list[dict[str, Any]]) -> tuple[dict[str, tuple[float, float, str]], dict[str, float]]:
    """normalized key -> (ra_deg, dec_deg J2000, label). Prefer row with better V-Mag when duplicate."""
    by_key: dict[str, tuple[float, float, str, float]] = {}
    for row in rows:
        ra_s = (row.get("RA") or "").strip()
        dec_s = (row.get("Dec") or "").strip()
        if not ra_s or not dec_s:
            continue
        try:
            ra_deg = _sex_ra_to_ra_deg(ra_s)
            dec_deg = _sex_dec_to_dec_deg(dec_s)
        except (ValueError, IndexError):
            continue
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        common = (row.get("Common names") or "").strip()
        label = f"{name}" + (f" ({common.split(',')[0].strip()})" if common else "")
        try:
            vmag = float((row.get("V-Mag") or "").strip() or "99")
        except ValueError:
            vmag = 99.0

        keys: set[str] = set()
        keys.update(_name_column_keys(name))
        keys.update(_messier_m_keys((row.get("M") or "").strip()))
        keys.update(_common_name_keys(common))
        for k in keys:
            if not k:
                continue
            prev = by_key.get(k)
            if prev is None or vmag < prev[3]:
                by_key[k] = (ra_deg, dec_deg, label, vmag)

    vmags = {k: v[3] for k, v in by_key.items()}
    slim = {k: (v[0], v[1], v[2]) for k, v in by_key.items()}
    return slim, vmags


_openngc_index: dict[str, tuple[float, float, str]] | None = None
_openngc_vmags: dict[str, float] = {}


def load_openngc_index() -> dict[str, tuple[float, float, str]]:
    global _openngc_index, _openngc_vmags
    if _openngc_index is not None:
        return _openngc_index
    path = openngc_csv_path()
    if not path.is_file():
        raise FileNotFoundError(
            "OpenNGC 未下载：请运行  telbot catalog download-openngc  （约数 MB，需联网一次）"
        )
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows.extend(reader)
    _openngc_index, _openngc_vmags = _build_openngc_index(rows)
    return _openngc_index


def openngc_visual_magnitude_for_query(name: str) -> float | None:
    """Best-effort V magnitude from OpenNGC index keys matching query."""
    load_openngc_index()
    key = _norm(name.strip())
    if key in _openngc_vmags:
        v = _openngc_vmags[key]
        return None if v >= 99.0 else float(v)
    for k, v in _openngc_vmags.items():
        if key in k or k in key:
            return None if v >= 99.0 else float(v)
    return None


def find_dso(name: str) -> tuple[float, float, str]:
    """
    Resolve NGC/IC/Messier/common name to (ra_deg, dec_deg J2000, label).
    """
    raw = name.strip()
    if not raw:
        raise KeyError("empty name")

    idx = load_openngc_index()
    key = _norm(raw)
    if key in idx:
        ra, dec, lab = idx[key]
        return ra, dec, lab

    for k, (ra, dec, lab) in idx.items():
        if key in k or k in key:
            return ra, dec, lab

    raise KeyError(
        f"深空未找到：{name!r}。可 telbot catalog download-openngc 后重试；或核对 NGC/IC/M 编号。"
    )


@dataclass(frozen=True)
class PlanCandidate:
    """OpenNGC row for observing-plan phase 2 (J2000 RA/Dec in degrees)."""

    catalog_id: str
    label: str
    ra_j2000_deg: float
    dec_j2000_deg: float
    vmag: float | None
    kind: str  # "messier" | "ngc"


def _parse_vmag_cell(raw: str | None) -> float | None:
    v = (raw or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def list_plan_candidates(
    *,
    sources: str,
    ngc_max_vmag: float,
    limit: int,
) -> list[PlanCandidate]:
    """
    Enumerate DSOs from local OpenNGC CSV for planning.

    sources:
      - messier: rows with non-empty M column
      - ngc_bright: NGC* rows with V-Mag <= ngc_max_vmag (excludes rows already counted as Messier duplicates)
      - messier_ngc: union (deduped by Name)
    """
    mode = (sources or "").strip().lower()
    if mode not in ("messier", "ngc_bright", "messier_ngc"):
        raise ValueError(
            f"sources 必须是 messier | ngc_bright | messier_ngc 之一，当前为 {sources!r}"
        )

    path = openngc_csv_path()
    if not path.is_file():
        raise FileNotFoundError(
            "OpenNGC 未下载：请运行  telbot catalog download-openngc  （约数 MB，需联网一次）"
        )

    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as f:
        rows.extend(csv.DictReader(f, delimiter=";"))

    messier_by_name: dict[str, PlanCandidate] = {}
    ngc_bright_by_name: dict[str, PlanCandidate] = {}

    for row in rows:
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        ra_s = (row.get("RA") or "").strip()
        dec_s = (row.get("Dec") or "").strip()
        if not ra_s or not dec_s:
            continue
        try:
            ra_deg = _sex_ra_to_ra_deg(ra_s)
            dec_deg = _sex_dec_to_dec_deg(dec_s)
        except (ValueError, IndexError):
            continue

        vmag = _parse_vmag_cell(row.get("V-Mag"))
        common = (row.get("Common names") or "").strip()
        label = name + (f" ({common.split(',')[0].strip()})" if common else "")

        m_raw = (row.get("M") or "").strip()
        if m_raw:
            try:
                mn = int(m_raw)
            except ValueError:
                mn = 0
            if mn > 0:
                cid = f"M{mn}"
                messier_by_name[name] = PlanCandidate(
                    catalog_id=cid,
                    label=label,
                    ra_j2000_deg=ra_deg,
                    dec_j2000_deg=dec_deg,
                    vmag=vmag,
                    kind="messier",
                )

        uname = name.upper()
        if uname.startswith("NGC") and vmag is not None and vmag <= ngc_max_vmag:
            ngc_bright_by_name[name] = PlanCandidate(
                catalog_id=name,
                label=label,
                ra_j2000_deg=ra_deg,
                dec_j2000_deg=dec_deg,
                vmag=vmag,
                kind="ngc",
            )

    out: list[PlanCandidate] = []
    if mode == "messier":
        out = sorted(messier_by_name.values(), key=lambda c: int(c.catalog_id[1:]))
    elif mode == "ngc_bright":
        out = sorted(ngc_bright_by_name.values(), key=lambda c: (c.vmag or 99.0, c.catalog_id))
    else:
        messier_names = set(messier_by_name.keys())
        out = sorted(messier_by_name.values(), key=lambda c: int(c.catalog_id[1:]))
        for name, c in sorted(ngc_bright_by_name.items(), key=lambda x: (x[1].vmag or 99.0, x[0])):
            if name in messier_names:
                continue
            out.append(c)

    if limit > 0 and len(out) > limit:
        out = out[:limit]
    return out
