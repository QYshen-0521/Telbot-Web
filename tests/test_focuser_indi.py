"""Oasis / generic INDI focuser helpers."""

import pytest

from telbot.focuser_indi import (
    focuser_connect,
    focuser_disconnect,
    focuser_move_absolute,
    focuser_move_relative,
)


def test_focuser_connect_dry_run() -> None:
    r = focuser_connect("Oasis Focuser", "127.0.0.1", 7624, dry_run=True)
    assert r.returncode == 0
    assert "Oasis Focuser.CONNECTION.CONNECT=On" in r.stdout


def test_focuser_disconnect_dry_run() -> None:
    r = focuser_disconnect("Oasis Focuser", "127.0.0.1", 7624, dry_run=True)
    assert "DISCONNECT=On" in r.stdout


def test_focuser_move_absolute_dry_run() -> None:
    r = focuser_move_absolute("Oasis Focuser", "127.0.0.1", 7624, 33400, dry_run=True)
    assert "FOCUS_ABSOLUTE_POSITION=33400" in r.stdout


def test_focuser_move_relative_dry_run() -> None:
    results = focuser_move_relative(
        "Oasis Focuser", "127.0.0.1", 7624, 50, "in", dry_run=True
    )
    assert len(results) == 2
    assert "FOCUS_RELATIVE_POSITION=50" in results[0].stdout
    assert "FOCUS_INWARD=On" in results[1].stdout


def test_focuser_move_relative_outward_dry_run() -> None:
    results = focuser_move_relative(
        "Oasis Focuser", "127.0.0.1", 7624, 50, "out", dry_run=True
    )
    assert "FOCUS_OUTWARD=On" in results[1].stdout


def test_focuser_move_relative_invalid_steps() -> None:
    with pytest.raises(ValueError, match="steps must be > 0"):
        focuser_move_relative("Oasis Focuser", "127.0.0.1", 7624, 0, "in", dry_run=True)
