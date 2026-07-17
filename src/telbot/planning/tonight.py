"""Phase 3: consolidated tonight plan JSON, terminal table, optional user confirmation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from telbot.config import Settings
from telbot.planning.phase2_schedule import build_phase2_payload
from telbot.planning.window import observer_timezone
from telbot.repo_paths import plans_dir
from telbot.scheduling.confirmation import apply_plan_confirmation

apply_confirmation = apply_plan_confirmation


def build_tonight_payload(
    s: Settings,
    from_ts: str | None,
    to_ts: str | None,
    *,
    include_weather: bool = True,
    catalog_sources: str | None = None,
    candidate_limit: int | None = None,
) -> dict[str, Any]:
    """Phase 2 payload plus tonight schema; `confirmation` starts as null."""
    p2 = build_phase2_payload(
        s,
        from_ts,
        to_ts,
        include_weather=include_weather,
        catalog_sources=catalog_sources,
        candidate_limit=candidate_limit,
    )
    out = dict(p2)
    out["phase2_schema_version"] = p2.get("schema_version")
    out["schema_version"] = "telbot.plan_tonight.v1"
    out["confirmation"] = None
    return out


def save_tonight_plan_json(payload: dict[str, Any], root: Path | None = None) -> Path:
    base = root if root is not None else plans_dir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = base / f"tonight_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def print_tonight_summary(console: Console, payload: dict[str, Any], s: Settings) -> None:
    """Rich table: schedule blocks + weather soft warnings + unscheduled targets."""
    tz = observer_timezone(s)
    weather = payload.get("weather")
    if isinstance(weather, dict):
        warns = weather.get("soft_warnings") or []
        if warns:
            console.print("[yellow]天气软警告（不自动否决观测）：[/yellow]")
            for w in warns:
                console.print(f"  • {w}")
            console.print()

    blocks = (payload.get("schedule") or {}).get("blocks") or []
    targets = payload.get("targets") or []
    by_id: dict[str, dict[str, Any]] = {}
    for t in targets:
        cid = t.get("catalog_id")
        if cid:
            by_id[str(cid)] = t

    table = Table(title="今夜观测排程（阶段 3，预览）")
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("目标", style="bold")
    table.add_column("开始（本地）", overflow="fold")
    table.add_column("结束（本地）", overflow="fold")
    table.add_column("最高高度°", justify="right")
    table.add_column("月亮降权", justify="center")

    if not blocks:
        table.add_row("—", "（无已排程块，可能夜窗过短或子午线策略排满）", "", "", "", "")
    else:
        for b in blocks:
            tid = str(b.get("target_id", ""))
            meta = by_id.get(tid, {})
            label = str(meta.get("label", tid))
            max_alt = meta.get("max_altitude_deg")
            alt_s = f"{max_alt:.1f}" if isinstance(max_alt, (int, float)) else "—"
            md = "是" if meta.get("moon_downrank") else "—"
            st_s = b.get("start_utc", "")
            en_s = b.get("end_utc", "")
            try:
                st = dt.datetime.fromisoformat(st_s.replace("Z", "+00:00"))
                en = dt.datetime.fromisoformat(en_s.replace("Z", "+00:00"))
                loc_st = st.astimezone(tz).strftime("%m-%d %H:%M")
                loc_en = en.astimezone(tz).strftime("%m-%d %H:%M")
            except (ValueError, TypeError):
                loc_st, loc_en = st_s, en_s
            table.add_row(
                str(b.get("order", "")),
                label,
                loc_st,
                loc_en,
                alt_s,
                md,
            )

    console.print(table)

    unsched = (payload.get("schedule") or {}).get("unscheduled_target_ids") or []
    if unsched:
        console.print(
            f"[dim]未纳入线性排程的目标（{len(unsched)}）：{', '.join(unsched[:30])}"
            + (" …" if len(unsched) > 30 else "")
            + "[/dim]"
        )

    adv = (payload.get("schedule") or {}).get("advanced_strategy_note")
    if adv:
        console.print(f"[dim]{adv}[/dim]")
