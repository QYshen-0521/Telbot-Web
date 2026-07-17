from fastapi.testclient import TestClient

from telbot.indi import IndiResult
from telbot.http_app import app
from telbot.models import VoiceIntentV1
from telbot.voice_listen import ListenFromWavResult

client = TestClient(app)


def test_listen_text_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.http_app.resolve_intent_from_sentence",
        lambda *_a, **_k: VoiceIntentV1(version=1, action="park"),
    )

    def fake_exec(_s, _intent, *, execute: bool, **_k):
        return {
            "ok": True,
            "dry_run": True,
            "action": "park",
            "nl": {"version": 1, "text": "nl-summary", "lines": ["nl-summary"]},
        }

    monkeypatch.setattr("telbot.http_app.execute_voice_intent", fake_exec)

    r = client.post("/listen/text?execute=false", json={"text": "停车"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["transcript"] == "停车"
    assert body["intent"]["action"] == "park"
    assert body["nl"]["text"] == "nl-summary"
    assert body["result"]["action"] == "park"

    r2 = client.post("/text?execute=false", json={"text": "停车"})
    assert r2.status_code == 200
    assert r2.json()["transcript"] == "停车"


def test_listen_audio_ok(monkeypatch) -> None:
    def fake_pipeline(path, _s, **kwargs):
        return ListenFromWavResult(
            transcript="park now",
            intent=VoiceIntentV1(version=1, action="park"),
            stt_seconds=0.1,
            nlu_seconds=0.05,
        )

    monkeypatch.setattr("telbot.http_app.listen_pipeline_from_wav", fake_pipeline)

    r = client.post(
        "/listen/audio?execute=false",
        files={"file": ("t.wav", b"dummy-bytes", "audio/wav")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["transcript"] == "park now"
    assert body["intent"]["action"] == "park"
    assert body["result"]["action"] == "park"
    assert body.get("nl") is not None
    assert "text" in body["nl"]


def test_listen_audio_no_intent(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.http_app.listen_pipeline_from_wav",
        lambda *a, **k: ListenFromWavResult(
            transcript="hello world no intent",
            intent=None,
            stt_seconds=0.1,
            nlu_seconds=0.2,
        ),
    )

    r = client.post(
        "/listen/audio",
        files={"file": ("t.wav", b"x", "audio/wav")},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["error"] == "no_intent"
    assert detail["transcript"] == "hello world no intent"


def test_intent_describe(monkeypatch) -> None:
    def fake_intro(_s, q: str) -> dict:
        return {
            "ok": True,
            "dry_run": True,
            "action": "describe",
            "intro": {"query": q, "summary_lines": [f"stub:{q}"]},
        }

    monkeypatch.setattr("telbot.object_intro.build_object_introduction", fake_intro)
    r = client.post(
        "/intent?execute=false",
        json={"version": 1, "action": "describe", "target": "jupiter"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "describe"
    assert body["intro"]["query"] == "jupiter"


def test_listen_audio_empty_transcript(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.http_app.listen_pipeline_from_wav",
        lambda *a, **k: ListenFromWavResult(
            transcript="",
            intent=None,
            stt_seconds=0.01,
            nlu_seconds=0.0,
        ),
    )

    r = client.post(
        "/listen/audio",
        files={"file": ("t.wav", b"x", "audio/wav")},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "empty_transcript"


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "indi_tools" in data
    assert "mount" in data
    assert "devices" in data
    assert "name" in data["mount"]
    assert "connected" in data["mount"]


def test_camera_cal_bias_dry() -> None:
    r = client.post("/camera/cal/bias?execute=false", json={"count": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["frame_kind"] == "bias"
    assert data["count"] == 5
    assert "save_dir" in data
    assert data["duration_estimate"]["estimated_seconds"] > 0


def test_camera_cal_stop() -> None:
    r = client.post("/camera/cal/stop")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_camera_cal_invalid_kind() -> None:
    r = client.post("/camera/cal/unknown?execute=false", json={})
    assert r.status_code == 400


def test_usb_devices() -> None:
    r = client.get("/usb/devices")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["schema_version"] == "telbot.usb_devices.v1"
    assert "vid_pids_present" in data
    assert "devices" in data
    assert "slots" in data
    for key in ("mount", "main_camera", "filter_wheel", "focuser"):
        slot = data["slots"][key]
        assert "connected" in slot
        assert "vid_pid" in slot


def test_config_env_get_all_and_patch(monkeypatch, tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("TELBOT_LATITUDE=31.0\nTELBOT_TRANSIT_ETC_APERTURE_MM=200\n", encoding="utf-8")
    monkeypatch.setenv("TELBOT_ENV_FILE", str(env))
    monkeypatch.delenv("TELBOT_LATITUDE", raising=False)

    r = client.get("/config/env")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "TELBOT_TRANSIT_ETC_APERTURE_MM" in body["values"]
    assert body["values"]["TELBOT_LATITUDE"] in {"31", "31.0"}

    r2 = client.patch(
        "/config/env",
        json={"updates": {"TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM": "5.5"}},
    )
    assert r2.status_code == 200
    assert r2.json()["values"]["TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM"] == "5.5"


def test_config_env_keys_list() -> None:
    r = client.get("/config/env/keys")
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert "TELBOT_TRANSIT_ETC_APERTURE_MM" in keys


def test_config_env_rejects_secret_key() -> None:
    r = client.patch("/config/env", json={"updates": {"TELBOT_OPENAI_API_KEY": "sk-test"}})
    assert r.status_code == 400


def test_intent_park_dry_run() -> None:
    r = client.post("/intent?execute=false", json={"version": 1, "action": "park"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["action"] == "park"


def test_intent_invalid_goto() -> None:
    r = client.post("/intent?execute=false", json={"version": 1, "action": "goto"})
    assert r.status_code == 422
    data = r.json()
    assert data["ok"] is False
    assert data["error"] == "validation_error"
    assert "goto" in data["message"].lower() or "target" in data["message"].lower()


def test_intent_connect_dry_run() -> None:
    r = client.post("/intent?execute=false", json={"version": 1, "action": "connect"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["action"] == "connect"


def test_intent_unpark_dry_run() -> None:
    r = client.post("/intent?execute=false", json={"version": 1, "action": "unpark"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["action"] == "unpark"


def test_intent_snap_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.ccd_indi.run_setprop",
        lambda *a, **k: IndiResult(0, "dry", ""),
    )
    r = client.post(
        "/intent?execute=false",
        json={"version": 1, "action": "snap", "exposure_seconds": 2.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["action"] == "snap"
    assert body["exposure_seconds"] == 2.0


def test_intent_platesolve_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.ccd_indi.run_setprop",
        lambda *a, **k: IndiResult(0, "dry", ""),
    )
    monkeypatch.setattr("telbot.ccd_indi.ccd_is_connected", lambda *a, **k: True)
    r = client.post(
        "/intent?execute=false",
        json={"version": 1, "action": "platesolve", "exposure_seconds": 1.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "platesolve"
    assert body["dry_run"] is True
    assert body["solve"]["skipped"] == "dry_run"


def test_intent_platesolve_dry_run_with_sync_skips_align(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.ccd_indi.run_setprop",
        lambda *a, **k: IndiResult(0, "dry", ""),
    )
    monkeypatch.setattr("telbot.ccd_indi.ccd_is_connected", lambda *a, **k: True)
    r = client.post(
        "/intent?execute=false",
        json={"version": 1, "action": "platesolve", "platesolve_align": "sync"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["align"]["skipped"] == "dry_run"


def test_camera_snap_preview_no_file_returns_no_preview_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.snap_preview.ensure_snap_preview_jpeg",
        lambda _s: (None, "尚无单张预览，请先完成一次 snap 曝光。"),
    )
    r = client.get("/camera/snap/preview")
    assert r.status_code == 404
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "no_preview"
    assert body["path"] == "/camera/snap/preview"


def test_camera_snap_dry_run_empty_body(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.ccd_indi.run_setprop",
        lambda *a, **k: IndiResult(0, "dry", ""),
    )
    r = client.post("/camera/snap?execute=false", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["action"] == "snap"


def test_intent_snap_ccd_not_connected_returns_400(monkeypatch) -> None:
    monkeypatch.setattr("telbot.http_app.indi_available", lambda: True)
    monkeypatch.setattr(
        "telbot.ccd_indi.run_setprop",
        lambda *a, **k: IndiResult(0, "", ""),
    )
    monkeypatch.setattr(
        "telbot.ccd_indi.ccd_is_connected",
        lambda *a, **k: False,
    )
    r = client.post(
        "/intent?execute=true",
        json={"version": 1, "action": "snap", "exposure_seconds": 1.0},
    )
    assert r.status_code == 400
    data = r.json()
    assert data["ok"] is False
    assert "CCD" in (data.get("message") or str(data.get("detail")))


def test_intent_nudge_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(
        "telbot.intent_exec.read_equatorial_eod",
        lambda *a, **k: (12.0, 45.0),
    )
    monkeypatch.setattr(
        "telbot.intent_exec.ensure_above_horizon",
        lambda *a, **k: 45.0,
    )
    r = client.post(
        "/intent?execute=false",
        json={"version": 1, "action": "nudge", "nudge_direction": "up"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["action"] == "nudge"
