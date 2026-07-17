"""Mount position parsing (EQUATORIAL_EOD / horizontal)."""

from __future__ import annotations

from telbot.indi import (
    parse_equatorial_eod_stdout,
    parse_horizontal_coord_stdout,
    read_equatorial_eod,
    read_horizontal_coord,
)


def test_parse_equatorial_eod_stdout() -> None:
    out = """PlaneWave.EQUATORIAL_EOD_COORD.RA=5.123456
PlaneWave.EQUATORIAL_EOD_COORD.DEC=-12.345678
"""
    parsed = parse_equatorial_eod_stdout(out)
    assert parsed == (5.123456, -12.345678)


def test_parse_horizontal_coord_stdout() -> None:
    out = """PlaneWave.TELESCOPE_HORIZONTAL_COORD.ALT=45.2
PlaneWave.TELESCOPE_HORIZONTAL_COORD.AZ=180.5
"""
    parsed = parse_horizontal_coord_stdout(out)
    assert parsed == (45.2, 180.5)


def test_read_equatorial_eod(monkeypatch) -> None:
    from telbot.indi import IndiResult

    def fake_getprop(host, port, pattern, timeout=1.0):
        _ = (host, port, timeout)
        assert "EQUATORIAL_EOD_COORD" in pattern
        return IndiResult(
            0,
            "PlaneWave.EQUATORIAL_EOD_COORD.RA=1.5\nPlaneWave.EQUATORIAL_EOD_COORD.DEC=30\n",
            "",
        )

    monkeypatch.setattr("telbot.indi.run_getprop", fake_getprop)
    assert read_equatorial_eod("PlaneWave", "127.0.0.1", 7624) == (1.5, 30.0)


def test_read_horizontal_coord_prefers_telescope_horizontal(monkeypatch) -> None:
    from telbot.indi import IndiResult

    calls: list[str] = []

    def fake_getprop(host, port, pattern, timeout=1.0):
        _ = (host, port, timeout)
        calls.append(pattern)
        if "TELESCOPE_HORIZONTAL" in pattern:
            return IndiResult(
                0,
                "M.TELESCOPE_HORIZONTAL_COORD.ALT=10\nM.TELESCOPE_HORIZONTAL_COORD.AZ=90\n",
                "",
            )
        return IndiResult(0, "", "")

    monkeypatch.setattr("telbot.indi.run_getprop", fake_getprop)
    assert read_horizontal_coord("M", "127.0.0.1", 7624) == (10.0, 90.0)
    assert calls[0].endswith("TELESCOPE_HORIZONTAL_COORD.*")
