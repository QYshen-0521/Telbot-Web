"""HYG catalog IDs and OpenNGC parsing (no full CSV required)."""

from __future__ import annotations

import telbot.catalog as catalog
import telbot.dso_catalog as dso


def test_build_hyg_index_includes_hd_hip_hr() -> None:
    row = {
        "ra": "6.0",
        "dec": "45.0",
        "mag": "3.5",
        "proper": "",
        "bf": "",
        "hip": "12345",
        "hd": "224",
        "hr": "464",
        "gl": "",
    }
    slim, _label_mag = catalog._build_index([row])
    idx = slim
    assert "hip 12345" in idx
    assert "hd 224" in idx
    assert "hr 464" in idx


def test_sexagesimal_openngc() -> None:
    ra_deg = dso._sex_ra_to_ra_deg("00:42:44.35")
    dec_deg = dso._sex_dec_to_dec_deg("+41:16:08.6")
    assert abs(ra_deg - 10.6847917) < 0.02
    assert abs(dec_deg - 41.2690556) < 0.02


def test_find_dso_monkeypatched_index(monkeypatch) -> None:
    monkeypatch.setattr(
        dso,
        "_openngc_index",
        {"ngc 224": (10.684, 41.269, "NGC0224")},
    )
    ra, dec, lab = dso.find_dso("NGC 224")
    assert abs(ra - 10.684) < 1e-6
    assert "NGC" in lab
