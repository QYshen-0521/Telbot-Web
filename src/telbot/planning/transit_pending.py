"""Pending state for multi-turn exoplanet transit selection."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from telbot.repo_paths import pending_dir

PENDING_FILENAME = "last_exoplanet_transits.json"


def pending_transits_path(root: Path | None = None) -> Path:
    base = root if root is not None else pending_dir()
    return base / PENDING_FILENAME


def save_pending_transits(
    payload: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    """Persist latest exoplanet_transits report for follow-up plan selection."""
    base = root if root is not None else pending_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = pending_transits_path(base)
    out = {
        "saved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "window": payload.get("window"),
        "events": payload.get("events") or [],
        "count": payload.get("count", 0),
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_pending_transits(
    *,
    root: Path | None = None,
    ttl_hours: float = 12.0,
) -> dict[str, Any] | None:
    path = pending_transits_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    saved = data.get("saved_at_utc")
    if saved and ttl_hours > 0:
        try:
            t = dt.datetime.fromisoformat(str(saved).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            age_h = (dt.datetime.now(dt.timezone.utc) - t.astimezone(dt.timezone.utc)).total_seconds() / 3600.0
            if age_h > ttl_hours:
                data["_expired"] = True
        except (ValueError, TypeError):
            pass
    return data


def resolve_event_from_pending(
    pending: dict[str, Any] | None,
    *,
    planet: str | None = None,
    event_index: int | None = None,
) -> dict[str, Any]:
    """
    Pick one event from pending list by 1-based index or planet name (case-insensitive).
    """
    if pending is None or pending.get("_expired"):
        raise ValueError(
            "无有效 pending 凌星列表（请先运行 telbot plan transits 或查询「今晚有哪些凌星」）。"
        )
    events = pending.get("events") or []
    if not events:
        raise ValueError("pending 凌星列表为空，请重新查询。")

    if event_index is not None:
        idx = int(event_index)
        if idx < 1 or idx > len(events):
            raise ValueError(f"事件序号 {idx} 超出范围（共 {len(events)} 个）。")
        return events[idx - 1]

    if planet:
        key = planet.strip().lower()
        for ev in events:
            if str(ev.get("planet", "")).lower() == key:
                return ev
            if key in str(ev.get("planet", "")).lower():
                return ev
            if key in str(ev.get("host", "")).lower():
                return ev
        raise ValueError(f"pending 列表中未找到行星 {planet!r}。")

    raise ValueError("请指定 planet 或 event_index（如「规划第 2 个凌星」）。")
