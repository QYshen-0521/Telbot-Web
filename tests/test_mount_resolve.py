"""mount_resolve + telescope name parsing (no live INDI)."""

from __future__ import annotations

import warnings

import pytest

from telbot.config import load_settings
from telbot.indi import telescope_device_names_from_getprop_stdout
from telbot.mount_resolve import tty_paths_by_device_from_getprop, resolve_telescope_device


def test_telescope_device_names_from_stdout() -> None:
    out = """Losmandy Gemini.EQUATORIAL_EOD_COORD.RA=1.0
Losmandy Gemini.EQUATORIAL_EOD_COORD.DEC=2.0
SBIG CCD.CCD_EXPOSURE.CCD_EXPOSURE_VALUE=1
"""
    assert telescope_device_names_from_getprop_stdout(out) == ["Losmandy Gemini"]


def test_tty_paths_by_device_from_getprop() -> None:
    out = """Losmandy Gemini.DEVICE_PORT.PORT=/dev/ttyACM0
SBIG CCD.CONNECTION.CONNECT=Off
"""
    m = tty_paths_by_device_from_getprop(out)
    assert m.get("Losmandy Gemini") == {"/dev/ttyACM0"}


def test_resolve_auto_off() -> None:
    s = load_settings().model_copy(
        update={"indi_device": "My Mount", "indi_device_auto": False},
    )
    assert resolve_telescope_device(s) == "My Mount"


def test_resolve_auto_mock_getprop(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings().model_copy(
        update={"indi_device": "Fallback", "indi_device_auto": True},
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "Losmandy Gemini.EQUATORIAL_EOD_COORD.RA=1\n"
            "Losmandy Gemini.EQUATORIAL_EOD_COORD.DEC=0\n"
            "Losmandy Gemini.DEVICE_PORT.PORT=/dev/ttyACM0\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    monkeypatch.setattr(
        "telbot.mount_resolve.list_usb_tty_paths",
        lambda: {"/dev/ttyACM0"},
    )
    assert resolve_telescope_device(s) == "Losmandy Gemini"


def test_resolve_auto_hint_match(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    hint = tmp_path / "hint"
    hint.write_text("Celestron GPS\n", encoding="utf-8")
    s = load_settings().model_copy(
        update={
            "indi_device": "Fallback",
            "indi_device_auto": True,
            "indi_device_hint_path": str(hint),
        },
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "Celestron GPS.EQUATORIAL_EOD_COORD.RA=1\n"
            "Losmandy Gemini.EQUATORIAL_EOD_COORD.RA=2\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    assert resolve_telescope_device(s) == "Celestron GPS"


def test_resolve_auto_hint_celestron_only_bus(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Only Celestron on bus + hint → Celestron GPS."""
    hint = tmp_path / "hint"
    hint.write_text("Celestron GPS\n", encoding="utf-8")
    s = load_settings().model_copy(
        update={
            "indi_device": "Losmandy Gemini",
            "indi_device_auto": True,
            "indi_device_hint_path": str(hint),
        },
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "Celestron GPS.EQUATORIAL_EOD_COORD.RA=1\n"
            "Celestron GPS.EQUATORIAL_EOD_COORD.DEC=0\n"
            "Celestron GPS.DEVICE_PORT.PORT=/dev/ttyUSB0\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    monkeypatch.setattr(
        "telbot.mount_resolve.list_usb_tty_paths",
        lambda: {"/dev/ttyUSB0"},
    )
    assert resolve_telescope_device(s) == "Celestron GPS"


def test_resolve_auto_hint_losmandy_only_bus(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Only Losmandy on bus + hint → Losmandy Gemini."""
    hint = tmp_path / "hint"
    hint.write_text("Losmandy Gemini\n", encoding="utf-8")
    s = load_settings().model_copy(
        update={
            "indi_device": "Celestron GPS",
            "indi_device_auto": True,
            "indi_device_hint_path": str(hint),
        },
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "Losmandy Gemini.EQUATORIAL_EOD_COORD.RA=1\n"
            "Losmandy Gemini.EQUATORIAL_EOD_COORD.DEC=0\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    assert resolve_telescope_device(s) == "Losmandy Gemini"


def test_resolve_auto_no_equatorial_uses_hint(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Celestron etc. may omit EQUATORIAL_EOD_COORD until CONNECT; hint still valid."""
    hint = tmp_path / "hint"
    hint.write_text("Celestron GPS\n", encoding="utf-8")
    s = load_settings().model_copy(
        update={
            "indi_device": "Losmandy Gemini",
            "indi_device_auto": True,
            "indi_device_hint_path": str(hint),
        },
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "Celestron GPS.CONNECTION.CONNECT=Off\n"
            "Celestron GPS.DEVICE_PORT.PORT=/dev/ttyUSB0\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    assert resolve_telescope_device(s) == "Celestron GPS"


def test_resolve_auto_no_equatorial_no_hint_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings().model_copy(
        update={"indi_device": "Fallback", "indi_device_auto": True},
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "Celestron GPS.CONNECTION.CONNECT=Off\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        name = resolve_telescope_device(s)
    assert name == "Fallback"
    assert w and "回退到 TELBOT_INDI_DEVICE" in str(w[0].message)


def test_resolve_auto_multi_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    s = load_settings().model_copy(
        update={"indi_device": "Fallback", "indi_device_auto": True},
    )

    def fake_getprop(*_a, **_k):
        from telbot.indi import IndiResult

        return IndiResult(
            0,
            "A.EQUATORIAL_EOD_COORD.RA=1\nB.EQUATORIAL_EOD_COORD.RA=2\n",
            "",
        )

    monkeypatch.setattr("telbot.mount_resolve.run_getprop", fake_getprop)
    monkeypatch.setattr("telbot.mount_resolve.list_usb_tty_paths", lambda: set())
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        name = resolve_telescope_device(s)
    assert name == "A"
    assert w and "多台" in str(w[0].message)
