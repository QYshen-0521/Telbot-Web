"""telbot_select_mount profile selection (no live USB / systemd)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_DEPLOY = _REPO / "deploy"


def _load_select_mount():
    path = _DEPLOY / "telbot_select_mount.py"
    spec = importlib.util.spec_from_file_location("telbot_select_mount", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["telbot_select_mount"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def select_mount():
    return _load_select_mount()


@pytest.fixture(scope="module")
def manifest_data():
    return json.loads((_DEPLOY / "mount_profiles.json").read_text(encoding="utf-8"))


def test_select_profile_planewave_vid(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"1cbe:0267"}, [])
    assert prof is not None
    assert prof["id"] == "planewave_l350_usb"
    assert prof["device_name_hint"] == "PlaneWave"
    assert prof.get("requires_pwi4") is True


def test_select_profile_planewave_wins_over_gemini(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"1cbe:0267", "1fc9:1705"}, [])
    assert prof["id"] == "planewave_l350_usb"


def test_main_planewave_starts_planewave_driver_and_pwi4_flag(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"1cbe:0267"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_planewave_telescope" in text
    assert (run / "pwi4_required").read_text(encoding="utf-8").strip() == "1"
    plan = json.loads((run / "auto_connect.json").read_text(encoding="utf-8"))
    assert ["indi_planewave_telescope", "PlaneWave"] in plan["jobs"]
    assert "PlaneWave.DEVICE_ADDRESS.ADDRESS=127.0.0.1" in plan.get("pre_connect_setprop", [])


def test_main_no_usb_match_clears_pwi4_flag(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    (run / "pwi4_required").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: set())
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    assert not (run / "pwi4_required").is_file()


def test_select_profile_gemini_vid(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"1fc9:1705"}, [])
    assert prof is not None
    assert prof["id"] == "losmandy_gemini_usb"
    assert prof["device_name_hint"] == "Losmandy Gemini"


def test_select_profile_celestron_prolific_vid(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"067b:2303"}, [])
    assert prof is not None
    assert prof["id"] == "celestron_prolific_usb"
    assert prof["device_name_hint"] == "Celestron GPS"


def test_select_profile_celestron_by_id(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(
        manifest_data,
        set(),
        ["usb-Celestron_Evolution-if00-port0"],
    )
    assert prof is not None
    assert prof["id"] == "celestron_serial_by_id"


def test_select_profile_qhy_wheel_cp210x_vid(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"10c4:ea60"}, [])
    assert prof is not None
    assert prof["id"] == "qhy_cfw3_wheel_usb"


def test_select_profile_gemini_wins_over_prolific_when_both(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"1fc9:1705", "067b:2303"}, [])
    assert prof["id"] == "losmandy_gemini_usb"


def test_select_profile_sb_only_when_only_sb_usb(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"0d97:0101"}, [])
    assert prof is not None
    assert prof["id"] == "sbig_ccd_usb_only"

    assert select_mount.select_profile(manifest_data, {"1234:5678"}, []) is None


def test_apply_udev_removed_discards_qhy_from_lsusb(select_mount) -> None:
    import os

    os.environ["TELBOT_UDEV_REMOVED_VIDPID"] = "1618:c175"
    try:
        out = select_mount._apply_udev_removed_vidpids({"1618:c175", "1fc9:1705"})
        assert "1618:c175" not in out
        assert "1fc9:1705" in out
    finally:
        os.environ.pop("TELBOT_UDEV_REMOVED_VIDPID", None)


def test_select_profile_qhy174m_only(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"1618:c175"}, [])
    assert prof is not None
    assert prof["id"] == "qhy174m_usb_only"
    assert prof["telbot_env_keys"]["TELBOT_INDI_CCD_DEVICE"] == "QHY CCD QHY174M"


def test_build_dotenv_mapping_qhy_only(select_mount, manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "qhy174m_usb_only")
    m = select_mount._build_dotenv_mapping(
        prof,
        manifest_data,
        "-v indi_qhy_ccd",
        {"1618:c175"},
        [],
    )
    assert m["TELBOT_INDI_CCD_DEVICE"] == "QHY CCD QHY174M"
    assert "TELBOT_INDI_DEVICE" not in m


def test_main_qhy_only_starts_qhy_driver(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"1618:c175"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_qhy_ccd" in text
    plan = json.loads((run / "auto_connect.json").read_text(encoding="utf-8"))
    assert ["indi_qhy_ccd", "QHY CCD QHY174M"] in plan["jobs"]


def test_main_gemini_includes_qhy_when_camera_usb_present(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(
        select_mount, "_lsusb_vid_pids", lambda: {"1fc9:1705", "1618:c175"}
    )
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_lx200gemini" in text
    assert "indi_qhy_ccd" in text


def test_select_profile_zwo_asi294mc_only(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"03c3:294f"}, [])
    assert prof is not None
    assert prof["id"] == "zwo_asi294mc_usb_only"
    assert prof["telbot_env_keys"]["TELBOT_INDI_CCD_DEVICE"] == "ZWO CCD ASI294MC Pro"


def test_build_dotenv_mapping_zwo_only(select_mount, manifest_data) -> None:
    prof = next(
        p for p in manifest_data["profiles"] if p["id"] == "zwo_asi294mc_usb_only"
    )
    m = select_mount._build_dotenv_mapping(
        prof,
        manifest_data,
        "-v indi_asi_ccd",
        {"03c3:294f"},
        [],
    )
    assert m["TELBOT_INDI_CCD_DEVICE"] == "ZWO CCD ASI294MC Pro"
    assert "TELBOT_INDI_DEVICE" not in m


def test_build_dotenv_mapping_gemini_plus_asi(select_mount, manifest_data) -> None:
    prof = next(p for p in manifest_data["profiles"] if p["id"] == "losmandy_gemini_usb")
    m = select_mount._build_dotenv_mapping(
        prof,
        manifest_data,
        "-v indi_lx200gemini indi_asi_ccd",
        {"1fc9:1705", "03c3:294f"},
        [],
    )
    assert m["TELBOT_INDI_DEVICE"] == "Losmandy Gemini"
    assert m["TELBOT_INDI_CCD_DEVICE"] == "ZWO CCD ASI294MC Pro"


def test_main_zwo_only_starts_asi_driver(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"03c3:294f"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_asi_ccd" in text
    assert (run / "auto_connect.json").is_file()
    plan = json.loads((run / "auto_connect.json").read_text(encoding="utf-8"))
    assert ["indi_asi_ccd", "ZWO CCD ASI294MC Pro"] in plan["jobs"]


def test_main_gemini_includes_asi_when_camera_usb_present(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(
        select_mount, "_lsusb_vid_pids", lambda: {"1fc9:1705", "03c3:294f"}
    )
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_lx200gemini" in text
    assert "indi_asi_ccd" in text


def test_select_profile_oasis_focuser_only(select_mount, manifest_data) -> None:
    prof = select_mount.select_profile(manifest_data, {"338f:a0f0"}, [])
    assert prof is not None
    assert prof["id"] == "oasis_focuser_usb_only"


def test_main_gemini_includes_oasis_when_focuser_usb_present(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"1fc9:1705", "338f:a0f0"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_lx200gemini" in text
    assert "indi_oasis_focuser" in text


def test_main_no_usb_match_applies_fallback_restart(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: set())
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8").strip()
    assert "indi_simulator_telescope" in text
    assert "indi_sbig_ccd" not in text


def test_main_no_usb_match_missing_block_errors(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mp = tmp_path / "only_profiles.json"
    mp.write_text(json.dumps({"version": 1, "profiles": []}), encoding="utf-8")
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(mp))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: set())
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_ERROR


def test_main_on_no_usb_match_exit_error_action(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mp = tmp_path / "m.json"
    mp.write_text(
        json.dumps(
            {
                "version": 1,
                "on_no_usb_match": {"action": "exit_error"},
                "profiles": [
                    {
                        "id": "never",
                        "priority": 1,
                        "match": {"usb_vid_pid": "ffff:ffff"},
                        "indi_drivers": ["indi_simulator_telescope"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(mp))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: set())
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_ERROR


def test_main_defer_restart_when_profile_changes(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"1fc9:1705"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])

    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert text.startswith("-v indi_lx200gemini")
    assert "indi_sbig_ccd" not in text


def test_main_gemini_includes_sbig_when_sb_usb_present(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"1fc9:1705", "0d97:0101"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])
    assert select_mount.main([]) == select_mount.EXIT_RESTART_NEEDED
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_lx200gemini" in text
    assert "indi_sbig_ccd" in text


def test_main_no_restart_execstartpre_returns_ok(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ExecStartPre: NO_RESTART without DEFER_RESTART → 0 even when files change."""
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(_DEPLOY / "mount_profiles.json"))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.delenv("TELBOT_SELECT_MOUNT_DEFER_RESTART", raising=False)
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: {"067b:2303"})
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: [])

    assert select_mount.main([]) == select_mount.EXIT_OK
    text = (run / "indiserver.args").read_text(encoding="utf-8")
    assert "indi_celestron_gps" in text
    assert "indi_sbig_ccd" not in text


def test_select_profile_match_mode_all(select_mount) -> None:
    data = {
        "profiles": [
            {
                "id": "combo",
                "priority": 50,
                "match_mode": "all",
                "match": {"usb_vid_pid": "aaaa:bbbb", "by_id_substring": "ZZZ"},
                "indi_drivers": ["foo"],
            }
        ]
    }
    assert select_mount.select_profile(data, {"aaaa:bbbb"}, ["xZZZy"])["id"] == "combo"
    assert select_mount.select_profile(data, {"aaaa:bbbb"}, ["no"]) is None
    assert select_mount.select_profile(data, set(), ["xZZZy"]) is None


def test_main_indiserver_args_line_written(
    select_mount, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mp = tmp_path / "m.json"
    mp.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "qhy_cfw3_wheel_usb",
                        "priority": 88,
                        "match": {"by_id_substring": "MYCFW"},
                        "indiserver_args_line": "-p 7624 -v indi_qhycfw3_wheel",
                        "indi_drivers": ["indi_qhycfw3_wheel"],
                        "optional_indi_drivers": [],
                        "device_name_hint": "QHY CFW3",
                        "telbot_env_sync": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    run = tmp_path / "run" / "telbot"
    run.mkdir(parents=True)
    monkeypatch.setattr(select_mount, "RUN", run)
    monkeypatch.setenv("TELBOT_MOUNT_PROFILES", str(mp))
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_NO_RESTART", "1")
    monkeypatch.setenv("TELBOT_SELECT_MOUNT_WRITE_ENV", "0")
    monkeypatch.setattr(select_mount, "_lsusb_vid_pids", lambda: set())
    monkeypatch.setattr(select_mount, "_by_id_strings", lambda: ["usb-MYCFW-1"])
    assert select_mount.main([]) == select_mount.EXIT_OK
    assert (
        (run / "indiserver.args").read_text(encoding="utf-8").strip()
        == "-p 7624 -v indi_qhycfw3_wheel"
    )
