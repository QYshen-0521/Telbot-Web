"""Generic plan confirmation for timed / long observing runs."""

from __future__ import annotations

import datetime as dt
from typing import Any


def apply_plan_confirmation(payload: dict[str, Any], *, via: str) -> dict[str, Any]:
    """Set ``confirmation`` block (mutates and returns payload)."""
    payload["confirmation"] = {
        "confirmed_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "via": via,
    }
    return payload


def validate_plan_confirmation(
    payload: dict[str, Any],
    *,
    expected_schema_prefix: str,
    will_execute: bool,
    force: bool = False,
) -> None:
    """
    Require matching ``schema_version`` prefix and non-null ``confirmation`` for real execution.
    """
    if not will_execute or force:
        return
    sv = str(payload.get("schema_version") or "")
    if not sv.startswith(expected_schema_prefix):
        raise ValueError(
            f"计划 schema 须以 {expected_schema_prefix!r} 开头，当前为 {sv!r}。"
            "真机执行请加 --force（风险自负）。"
        )
    if not payload.get("confirmation"):
        raise ValueError(
            "计划缺少 confirmation。请先确认计划内容并写入 confirmation，或加 --force。"
        )
