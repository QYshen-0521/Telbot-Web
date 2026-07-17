from __future__ import annotations

from telbot.ccd_calibration import (
    _FRAME_TYPE_CANDIDATES,
    allocate_calibration_session_slug,
    calibration_session_time_tag,
    ccd_set_frame_type,
    default_calibration_session_tag,
    estimate_calibration_duration_seconds,
    run_calibration_frames,
)
from telbot.config import Settings


def test_calibration_dry_run_bias() -> None:
    s = Settings(indi_ccd_device="SBIG CCD")
    out = run_calibration_frames(s, "bias", count=5, execute=False)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["frame_kind"] == "bias"
    assert out["count"] == 5
    assert out["exposure_seconds"] == 0.0
    save = out["save_dir"].replace("\\", "/")
    assert "/bias_" in save
    assert "cal_bias_" not in save
    assert out["session_tag"].isdigit() and len(out["session_tag"]) in (4, 6)  # HHMM 或 HHMM_n


def test_calibration_dry_run_dark_needs_exposure_or_default() -> None:
    s = Settings(indi_ccd_device="CCD", cal_dark_exposure_seconds=30.0)
    out = run_calibration_frames(s, "dark", count=3, execute=False)
    assert out["exposure_seconds"] == 30.0


def test_default_session_tag() -> None:
    s = Settings(plan_timezone="UTC")
    t = default_calibration_session_tag("flat", s=s)
    assert len(t) == 4 and t.isdigit()
    assert t == calibration_session_time_tag(s)


def test_allocate_session_slug_collision(tmp_path) -> None:
    from telbot.ccd_calibration import calibration_save_dir

    root = str(tmp_path)
    calibration_save_dir(root, "bias", "1129", create=True)
    assert allocate_calibration_session_slug(root, "bias", "1129") == "1129_2"
    calibration_save_dir(root, "bias", "1129_2", create=True)
    assert allocate_calibration_session_slug(root, "bias", "1129") == "1129_3"


def test_estimate_calibration_duration_bias() -> None:
    s = Settings()
    est = estimate_calibration_duration_seconds(s, "bias", count=20, exposure_seconds=0)
    assert est["count"] == 20
    assert est["settle_seconds"] >= 12
    assert est["estimated_seconds"] >= 20 * 12


def test_estimate_calibration_duration_dark() -> None:
    s = Settings(ccd_snap_settle_seconds=3.0)
    est = estimate_calibration_duration_seconds(s, "dark", count=10, exposure_seconds=60)
    assert est["per_frame_seconds"] >= 60 + 3


def test_calibration_archived_filename() -> None:
    from telbot.ccd_calibration import calibration_archived_filename

    assert calibration_archived_filename("bias", 1) == "bias_0001.fits"
    assert calibration_archived_filename("dark", 12) == "dark_0012.fits"
    assert calibration_archived_filename("flat", 3) == "flat_0003.fits"


def test_ccd_set_frame_type_dry_run() -> None:
    steps = ccd_set_frame_type("SBIG CCD", "127.0.0.1", 7624, "dark", dry_run=True)
    assert len(steps) >= 1
    assert any("FRAME_DARK=On" in (s.stdout or "") for s in steps)


def test_resolve_frame_element_from_stdout(monkeypatch) -> None:
    from telbot.ccd_calibration import resolve_frame_element

    blob = "\n".join(
        [
            "SBIG CCD.CCD_FRAME_TYPE.FRAME_LIGHT=Off",
            "SBIG CCD.CCD_FRAME_TYPE.FRAME_BIAS=On",
            "SBIG CCD.CCD_FRAME_TYPE.FRAME_DARK=Off",
            "SBIG CCD.CCD_FRAME_TYPE.FRAME_FLAT=Off",
        ]
    )

    def fake_getprop(host, port, pattern, timeout):
        if "CCD_FRAME" in pattern:
            return type("R", (), {"returncode": 0, "stdout": blob, "stderr": ""})()
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("telbot.ccd_calibration.run_getprop", fake_getprop)
    prop, el = resolve_frame_element("SBIG CCD", "127.0.0.1", 7624, "bias", timeout=2.0)
    assert prop == "CCD_FRAME_TYPE"
    assert el == "FRAME_BIAS"


def test_frame_candidates_cover_standard() -> None:
    for kind in ("bias", "dark", "flat", "light"):
        assert _FRAME_TYPE_CANDIDATES[kind][0].startswith("FRAME_")
