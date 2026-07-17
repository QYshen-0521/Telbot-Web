"""INDI CCD upload directory configuration."""

from pathlib import Path

from telbot.ccd_indi import ccd_configure_upload, ccd_prepare_for_capture, ccd_snap_exposure


def test_ccd_configure_upload_dry_run() -> None:
    cap = Path("/tmp/telbot_test_ccd/20260520")
    results = ccd_configure_upload("SBIG CCD", "127.0.0.1", 7624, cap, dry_run=True)
    assert len(results) == 2
    assert "UPLOAD_DIR=" in results[0].stdout
    assert "20260520" in results[0].stdout
    assert "UPLOAD_MODE.UPLOAD_LOCAL=On" in results[1].stdout


def test_ccd_prepare_for_capture_dry_run(tmp_path: Path) -> None:
    cap = tmp_path / "ccd_captures" / "20260520"
    results = ccd_prepare_for_capture("SBIG CCD", "127.0.0.1", 7624, cap, dry_run=True)
    assert not cap.exists()
    assert len(results) == 2


def test_ccd_snap_exposure_dry_run_zwo() -> None:
    device = "ZWO CCD ASI294MC Pro"
    steps, meta = ccd_snap_exposure(device, "127.0.0.1", 7624, 2.0, dry_run=True)
    assert len(steps) == 1
    assert f"{device}.CCD_EXPOSURE.CCD_EXPOSURE_VALUE=2.0" in steps[0].stdout
    assert meta["waited"] is False
