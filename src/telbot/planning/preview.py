"""Phase 0+1: window + config snapshot + weather block; optional JSON save."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telbot.config import Settings
from telbot.planning.phase0_config import planning_phase0_snapshot
from telbot.planning.weather import fetch_weather_for_window
from telbot.planning.window import observer_timezone, resolve_plan_window
from telbot.repo_paths import plans_dir


def build_plan_preview_payload(
    s: Settings,
    from_ts: str | None,
    to_ts: str | None,
) -> dict[str, Any]:
    """Resolve window, attach phase-0 snapshot and phase-1 weather (per Settings)."""
    w = resolve_plan_window(s, from_ts, to_ts)
    tz = observer_timezone(s)
    weather = fetch_weather_for_window(s, w.start_utc, w.end_utc)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "telbot.plan_preview.v1",
        "generated_at_utc": generated_at,
        "window": {
            "mode": w.mode,
            "start_utc": w.start_utc.isoformat(),
            "end_utc": w.end_utc.isoformat(),
            "duration_hours": round(w.duration_hours(), 4),
            "sun_altitude_threshold_deg": w.sun_altitude_threshold_deg,
            "start_local": w.start_utc.astimezone(tz).isoformat(),
            "end_local": w.end_utc.astimezone(tz).isoformat(),
        },
        "phase0_config": planning_phase0_snapshot(s),
        "weather": weather,
        "plans_dir": str(plans_dir().resolve()),
    }


def save_plan_preview_json(payload: dict[str, Any], root: Path | None = None) -> Path:
    """Write UTF-8 JSON under data/plans/ with UTC timestamp in filename."""
    base = root if root is not None else plans_dir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = base / f"plan_preview_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
