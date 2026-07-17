"""
HYG star catalog: download to cache and resolve names to equatorial positions.

CSV columns: `ra` is decimal hours (0–24), `dec` is degrees (epoch 2000.0); internally
we convert to degrees for Skyfield. HIP/HD/HR columns are indexed for catalog lookups.

Deep-sky (NGC/IC/Messier/…) uses OpenNGC via `telbot.dso_catalog` after
`telbot catalog download-openngc`.

User runs: telbot catalog download   (needs network once)
"""

from __future__ import annotations

import csv
import json
import re
import urllib.request
from importlib import resources
from pathlib import Path
from typing import Any

# Astronexus HYG (Hipparcos–Yale–Gliese; GitHub repo archived → HYG-Database)
# CSV: ra = decimal hours (0–24), dec = degrees (epoch/equinox 2000.0)
HYG_CSV_URL = (
    "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv"
)

CACHE_DIR = Path.home() / ".cache" / "telbot" / "catalog"
HYG_FILENAME = "hygdata_v41.csv"


def _zh_names() -> dict[str, str]:
    raw = resources.files("telbot.data").joinpath("star_names_zh.json").read_bytes()
    return json.loads(raw.decode("utf-8"))


def catalog_csv_path() -> Path:
    return CACHE_DIR / HYG_FILENAME


def download_hyg_catalog(url: str = HYG_CSV_URL, *, timeout: float = 600.0) -> Path:
    """Download HYG CSV into ~/.cache/telbot/catalog/. Returns path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = catalog_csv_path()
    req = urllib.request.Request(url, headers={"User-Agent": "Telbot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dest.write_bytes(resp.read())
    return dest


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _register_star_key(
    by_name: dict[str, tuple[float, float, str, float]],
    nk: str,
    ra_deg: float,
    dec: float,
    label: str,
    mag: float,
) -> None:
    if not nk:
        return
    prev = by_name.get(nk)
    if prev is None or mag < prev[3]:
        by_name[nk] = (ra_deg, dec, label, mag)


def _add_hip_hd_hr_keys(
    row: dict[str, Any],
    ra_deg: float,
    dec: float,
    label: str,
    mag: float,
    by_name: dict[str, tuple[float, float, str, float]],
) -> None:
    for col, prefix in (("hip", "hip"), ("hd", "hd"), ("hr", "hr")):
        v = (row.get(col) or "").strip()
        if not v or v == "0":
            continue
        try:
            num = int(float(v))
        except ValueError:
            continue
        if num <= 0:
            continue
        for nk in (_norm(f"{prefix}{num}"), _norm(f"{prefix} {num}")):
            _register_star_key(by_name, nk, ra_deg, dec, label, mag)


def _build_index(rows: list[dict[str, Any]]) -> tuple[dict[str, tuple[float, float, str]], dict[str, float]]:
    """Map normalized name -> (ra_deg, dec_deg, label). Prefer brighter (lower mag). Also label -> best mag."""
    by_name: dict[str, tuple[float, float, str, float]] = {}
    for row in rows:
        try:
            ra_hours = float(row["ra"])
            ra_deg = ra_hours * 15.0  # HYG: RA in decimal hours → degrees for Skyfield Star
            dec = float(row["dec"])
            mag = float(row.get("mag", "99") or "99")
        except (KeyError, ValueError):
            continue
        proper = (row.get("proper") or "").strip()
        bf = (row.get("bf") or "").strip()
        hip = row.get("hip", "")
        label = proper or bf or f"HIP{hip}"
        for key in (proper, bf):
            if not key:
                continue
            nk = _norm(key)
            if not nk:
                continue
            _register_star_key(by_name, nk, ra_deg, dec, label, mag)
        _add_hip_hd_hr_keys(row, ra_deg, dec, label, mag, by_name)
    label_mag: dict[str, float] = {}
    for _ra, _dec, lab, mag in by_name.values():
        prev = label_mag.get(lab)
        if prev is None or mag < prev:
            label_mag[lab] = mag
    slim = {k: (v[0], v[1], v[2]) for k, v in by_name.items()}
    return slim, label_mag


_index: dict[str, tuple[float, float, str]] | None = None
_hyg_label_mag: dict[str, float] = {}


def load_index() -> dict[str, tuple[float, float, str]]:
    global _index, _hyg_label_mag
    if _index is not None:
        return _index
    path = catalog_csv_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"星表未下载：请运行  telbot catalog download  （约数十 MB，需联网）"
        )
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows.extend(reader)
    _index, _hyg_label_mag = _build_index(rows)
    return _index


def hyg_visual_magnitude_for_label(label: str) -> float | None:
    """Johnson V magnitude from HYG row(s) matching catalog label, if available."""
    load_index()
    m = _hyg_label_mag.get(label.strip())
    if m is None or m >= 99.0:
        return None
    return float(m)


def find_star(name: str) -> tuple[float, float, str]:
    """
    Resolve star name to (ra_deg, dec_deg J2000, label).
    Tries: English as-is, Chinese from star_names_zh.json, fuzzy substring on index keys.
    """
    raw = name.strip()
    if not raw:
        raise KeyError("empty name")

    zh = _zh_names()
    if raw in zh:
        raw = zh[raw]
    # Chinese multi-char without mapping: try direct key match in zh values - already mapped

    idx = load_index()
    key = _norm(raw)
    if key in idx:
        ra, dec, lab = idx[key]
        return ra, dec, lab

    try:
        from telbot.dso_catalog import find_dso

        return find_dso(raw)
    except FileNotFoundError:
        pass
    except KeyError:
        pass

    # substring match on proper names (first match)
    for k, (ra, dec, lab) in idx.items():
        if key in k or k in key:
            return ra, dec, lab

    raise KeyError(
        f"星表未找到：{name!r}。恒星：telbot catalog download；"
        f"深空：telbot catalog download-openngc；或 telbot catalog search 片段"
    )


def search_stars(substr: str, *, limit: int = 20) -> list[str]:
    """Return up to `limit` catalog labels/names containing substring."""
    idx = load_index()
    sub = _norm(substr)
    out: list[str] = []
    seen: set[str] = set()
    for k, (_ra, _dec, lab) in idx.items():
        if sub in k or sub in _norm(lab):
            if lab not in seen:
                seen.add(lab)
                out.append(lab)
        if len(out) >= limit:
            break
    return out
