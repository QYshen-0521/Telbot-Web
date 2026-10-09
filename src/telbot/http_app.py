from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile

from telbot import __version__ as telbot_version
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from telbot.http_errors import (
    http_exception_to_body,
    unhandled_exception_to_body,
    validation_error_to_body,
)

from telbot.config import load_settings
from telbot.config_env import (
    HTTP_APP_ENV_WHITELIST,
    app_env_path,
    read_app_env_values,
    write_app_env_values,
)
from telbot.ccd_paths import effective_ccd_save_dir
from telbot.horizon import BelowHorizonError, ensure_above_horizon
from telbot.indi import disconnect_telescope, indi_available, slew_equatorial_eod
from telbot.intent_exec import execute_voice_intent, slew_body_to_equatorial
from telbot.mount_resolve import resolve_telescope_device
from telbot.models import (
    CameraSnapRequest,
    GotoBodyRequest,
    GotoTargetRequest,
    PlatesolveRequest,
    VoiceIntentV1,
)
from telbot.platesolve.security import (
    capture_before_state,
    exposure_capture_search_dirs,
    fits_files_in_dir,
    max_fits_mtime_ns_in_dir,
    newest_fits_after_mtime_ns,
    resolve_new_capture_fits,
)
from telbot.platesolve.service import run_platesolve
from telbot.focuser_indi import (
    focuser_get_absolute_position,
    focuser_get_max_position,
    focuser_is_connected,
    focuser_move_absolute,
)
from telbot.platesolve_align import align_mount_after_platesolve
from telbot.nl_pipeline import resolve_intent_from_sentence
from telbot.health_devices import build_health_devices
from telbot.voice_listen import listen_pipeline_from_wav

app = FastAPI(title="Telbot local GOTO API", version="0.6.0")

# Browser clients on GitHub Pages call this API cross-origin. CORS is not authentication:
# do not expose the Pi to untrusted networks. Dry-run remains the default for control routes.
# allow_private_network lets a public https page preflight a LAN or localhost API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)


class _PrivateNetworkAccess:
    """Also mark ordinary responses, not only the CORS preflight, as private-network OK."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_pna(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(key.lower() == b"access-control-allow-private-network" for key, _ in headers):
                    headers.append((b"access-control-allow-private-network", b"true"))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_pna)


# Added last so it wraps CORS and the header survives on non-preflight responses.
app.add_middleware(_PrivateNetworkAccess)

_WEB_MEDIA = {
    "styles.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
}


def _web_file(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "web" / name


def _web_response(name: str) -> FileResponse:
    media = _WEB_MEDIA.get(name)
    if media is None:
        raise HTTPException(404, "asset not found")
    path = _web_file(name)
    if not path.is_file():
        raise HTTPException(404, f"web/{name} not found")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def web_index() -> FileResponse:
    path = _web_file("index.html")
    if not path.is_file():
        raise HTTPException(404, "web/index.html not found")
    return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-store"})


@app.get("/styles.css", include_in_schema=False)
def web_styles() -> FileResponse:
    return _web_response("styles.css")


@app.get("/app.js", include_in_schema=False)
def web_script() -> FileResponse:
    return _web_response("app.js")


@app.get("/web/{name}", include_in_schema=False)
def web_asset(name: str) -> FileResponse:
    return _web_response(name)


@app.exception_handler(HTTPException)
async def _telbot_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Always JSON — App 勿只读 HTTP 状态行。"""
    body = http_exception_to_body(exc, path=str(request.url.path))
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def _telbot_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    body = validation_error_to_body(exc, path=str(request.url.path))
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(Exception)
async def _telbot_unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    body = unhandled_exception_to_body(exc, path=str(request.url.path))
    return JSONResponse(status_code=500, content=body)


class ListenTextBody(BaseModel):
    """与 ``telbot text "…" --apply`` 同源：服务器侧解析意图并执行。"""

    text: str = Field(..., description="用户输入的自然语言指令")


class ChatBody(BaseModel):
    """General Q&A fallback for the Web console."""

    text: str = Field(..., description="用户输入的问题")


class EnvPatchBody(BaseModel):
    """iOS App「默认参数」：写回 Pi `.env` 的白名单键。"""

    updates: dict[str, str] = Field(default_factory=dict)


class CalibrationCaptureBody(BaseModel):
    """校准帧拍摄（bias / dark / flat / light），见 ``docs/CCD_CALIBRATION.md``。"""

    count: int | None = Field(None, ge=1, description="张数；省略则用 Pi 默认")
    exposure_seconds: float | None = Field(
        None, ge=0, description="每帧曝光秒数；偏置可为 0"
    )
    session_tag: str | None = Field(None, description="会话后缀（4 位 HHMM）；省略则由服务端按本地时刻生成")
    interval_seconds: float | None = Field(None, ge=0, description="帧间等待秒数")


class LiveStackStartBody(BaseModel):
    """边拍边叠：在 duration_seconds 内按 exposure_seconds 循环曝光并叠加。"""

    duration_seconds: float = Field(..., gt=0, description="拍摄总时长（秒）")
    exposure_seconds: float | None = Field(
        None, gt=0, description="每帧曝光秒数；省略则用 TELBOT_CCD_DEFAULT_EXPOSURE_SECONDS"
    )
    cadence_seconds: float | None = Field(
        None, gt=0, description="帧间隔（秒）；默认 exposure + TELBOT_EXPOSE_LOOP_OVERHEAD_SECONDS"
    )
    session_tag: str | None = Field(
        None, description="会话子目录名；省略则自动生成 livestack_<UTC>"
    )
    cal_bias_dir: str | None = Field(None, description="偏置场会话目录（如 …/YYYYMMDD/bias_1129/）")
    cal_dark_dir: str | None = Field(None, description="暗场会话目录（如 …/dark_1129/，曝光宜与 exposure_seconds 一致）")
    cal_flat_dir: str | None = Field(None, description="平场会话目录（如 …/flat_1430/）")


def _focuser_device_or_503(s) -> str:
    foc = (getattr(s, "indi_focuser_device", None) or "").strip()
    if not foc:
        raise HTTPException(
            status_code=503,
            detail="未配置电调设备名：请在 Pi 的 .env 设置 TELBOT_INDI_FOCUSER_DEVICE（与 indi_getprop 一致）。",
        )
    return foc


@app.post("/goto")
def post_goto(
    body: GotoBodyRequest,
    execute: bool = Query(False, description="If true, send real INDI commands"),
) -> dict:
    """
    Localhost-only control plane. Pass execute=true to send real INDI commands.
    Default dry-run prints intent only at HTTP layer; INDI layer still respects execute.
    """
    s = load_settings()
    dry_run = not execute
    if not dry_run and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    try:
        ensure_above_horizon(
            body.ra_hours,
            body.dec_deg,
            latitude_deg=s.latitude,
            longitude_deg=s.longitude,
            elevation_m=s.elevation_m,
            min_altitude_deg=s.min_altitude_deg,
            detail="POST /goto",
        )
    except BelowHorizonError as e:
        raise HTTPException(400, detail=str(e)) from e
    dev = resolve_telescope_device(s)
    r1, r2 = slew_equatorial_eod(
        dev,
        s.indi_host,
        s.indi_port,
        body.ra_hours,
        body.dec_deg,
        dry_run=dry_run,
    )
    ok = r1.returncode == 0 and r2.returncode == 0
    return {
        "ok": ok,
        "dry_run": dry_run,
        "device": dev,
        "steps": [
            {"stdout": r1.stdout, "stderr": r1.stderr, "code": r1.returncode},
            {"stdout": r2.stdout, "stderr": r2.stderr, "code": r2.returncode},
        ],
    }


@app.post("/goto/body")
def post_goto_body(
    body: GotoTargetRequest,
    execute: bool = Query(False, description="If true, slew to ephemeris RA/Dec for body"),
) -> dict:
    """Solar system body name → Skyfield → EQUATORIAL_EOD_COORD + SLEW."""
    s = load_settings()
    dry_run = not execute
    if not dry_run and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    try:
        meta, (r1, r2) = slew_body_to_equatorial(s, body.target.strip(), dry_run=dry_run)
    except KeyError as e:
        raise HTTPException(400, detail=str(e)) from e
    except BelowHorizonError as e:
        raise HTTPException(400, detail=str(e)) from e
    ok = r1.returncode == 0 and r2.returncode == 0
    return {
        "ok": ok,
        "dry_run": dry_run,
        "device": resolve_telescope_device(s),
        "resolved": meta,
        "steps": [
            {"stdout": r1.stdout, "stderr": r1.stderr, "code": r1.returncode},
            {"stdout": r2.stdout, "stderr": r2.stderr, "code": r2.returncode},
        ],
    }


@app.post("/park")
def post_park(
    execute: bool = Query(False, description="If true, TELESCOPE_PARK.PARK=On"),
) -> dict:
    s = load_settings()
    dry_run = not execute
    if not dry_run and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    out = execute_voice_intent(
        s,
        VoiceIntentV1(action="park", version=1),
        execute=execute,
    )
    return out


@app.post("/unpark")
def post_unpark(
    execute: bool = Query(False, description="If true, TELESCOPE_PARK.UNPARK=On"),
) -> dict:
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    return execute_voice_intent(
        s,
        VoiceIntentV1(action="unpark", version=1),
        execute=execute,
    )


@app.post("/connect")
def post_connect(
    execute: bool = Query(False, description="If true, CONNECTION.CONNECT=On"),
) -> dict:
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    return execute_voice_intent(
        s,
        VoiceIntentV1(action="connect", version=1),
        execute=execute,
    )


@app.post("/disconnect")
def post_disconnect(
    execute: bool = Query(False, description="If true, CONNECTION.DISCONNECT=On"),
) -> dict:
    """与 ``mount connect`` 相反：断开驱动与硬件连接。"""
    s = load_settings()
    dry_run = not execute
    if not dry_run and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    dev = resolve_telescope_device(s)
    r = disconnect_telescope(
        dev,
        s.indi_host,
        s.indi_port,
        dry_run=dry_run,
    )
    ok = r.returncode == 0
    return {
        "ok": ok,
        "dry_run": dry_run,
        "action": "disconnect",
        "device": dev,
        "steps": [
            {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode},
        ],
    }


@app.post("/abort")
def post_abort(
    execute: bool = Query(False, description="If true, TELESCOPE_ABORT_MOTION.ABORT=On"),
) -> dict:
    s = load_settings()
    dry_run = not execute
    if not dry_run and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    out = execute_voice_intent(
        s,
        VoiceIntentV1(action="abort", version=1),
        execute=execute,
    )
    return out


@app.get("/focuser/position")
def get_focuser_position() -> dict:
    """读取电调绝对位置与最大行程（与 ``telbot focuser position`` / ``max`` 一致）。"""
    s = load_settings()
    dev = _focuser_device_or_503(s)
    t = max(getattr(s, "indi_getprop_timeout", None) or 10.0, 2.0)
    rc_pos, pos, _raw_p = focuser_get_absolute_position(dev, s.indi_host, s.indi_port, timeout=t)
    rc_max, mx, _raw_m = focuser_get_max_position(dev, s.indi_host, s.indi_port, timeout=t)
    connected = (
        focuser_is_connected(dev, s.indi_host, s.indi_port, timeout=t)
        if indi_available()
        else False
    )
    return {
        "device": dev,
        "name": dev,
        "connected": connected,
        "position": int(pos) if pos is not None else None,
        "max_position": int(mx) if mx is not None else None,
        "ok_position": connected and rc_pos == 0,
        "ok_max": connected and rc_max == 0,
    }


@app.post("/focuser/abs")
def post_focuser_abs(
    position: int = Query(..., description="绝对位置（ABS_FOCUS_POSITION）"),
    execute: bool = Query(False, description="true 时真实下发 indi_setprop"),
) -> dict:
    """绝对移动电调（与 ``telbot focuser abs <n> --execute`` 一致）。"""
    s = load_settings()
    dev = _focuser_device_or_503(s)
    dry_run = not execute
    if not dry_run and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")

    if position < 0:
        raise HTTPException(status_code=400, detail="position 必须 >= 0")

    t = max(getattr(s, "indi_getprop_timeout", None) or 10.0, 2.0)
    rc_max, mx, _ = focuser_get_max_position(dev, s.indi_host, s.indi_port, timeout=t)
    if rc_max == 0 and mx is not None:
        mx_i = int(mx)
        if position > mx_i:
            raise HTTPException(
                status_code=400,
                detail=f"position={position} 超过最大行程 max_position={mx_i}",
            )

    r = focuser_move_absolute(dev, s.indi_host, s.indi_port, position, dry_run=dry_run)
    ok = r.returncode == 0
    return {
        "ok": ok,
        "dry_run": dry_run,
        "device": dev,
        "position": position,
        "max_position": int(mx) if mx is not None and rc_max == 0 else None,
        "steps": [
            {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode},
        ],
    }


@app.post("/listen/audio")
async def post_listen_audio(
    execute: bool = Query(False, description="If true, send real INDI commands"),
    no_semantic: bool = Query(False, description="Disable sentence embeddings (same as telbot listen)"),
    semantic_only: bool = Query(False, description="Embeddings only (same as telbot listen)"),
    no_llm: bool = Query(False, description="Disable LLM intent path"),
    file: UploadFile = File(..., description="Audio file (WAV recommended; Whisper-compatible)"),
) -> dict:
    """
    Upload audio → cloud STT → same NLU as ``telbot listen`` → ``execute_voice_intent``.
    Mirrors the Pi processing chain used after recording.
    """
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")

    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_bytes(await file.read())
        pipe = listen_pipeline_from_wav(
            tmp_path,
            s,
            no_semantic=no_semantic,
            semantic_only=semantic_only,
            no_llm=no_llm,
            console=None,
        )
    except ValueError as e:
        raise HTTPException(503, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    if not pipe.transcript.strip():
        raise HTTPException(
            400,
            detail={
                "error": "empty_transcript",
                "message": "STT returned no usable text",
                "stt_seconds": pipe.stt_seconds,
            },
        )
    if pipe.intent is None:
        raise HTTPException(
            400,
            detail={
                "error": "no_intent",
                "transcript": pipe.transcript,
                "stt_seconds": pipe.stt_seconds,
                "nlu_seconds": pipe.nlu_seconds,
            },
        )

    try:
        out = execute_voice_intent(s, pipe.intent, execute=execute)
    except KeyError as e:
        raise HTTPException(400, detail=str(e)) from e
    except BelowHorizonError as e:
        raise HTTPException(400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e

    return {
        "ok": True,
        "transcript": pipe.transcript,
        "intent": pipe.intent.model_dump(mode="json", exclude_none=True),
        "stt_seconds": pipe.stt_seconds,
        "nlu_seconds": pipe.nlu_seconds,
        "result": out,
        "nl": out.get("nl"),
        "nl_simple": out.get("nl_simple"),
    }


@app.post("/listen/text")
@app.post("/text")
def post_listen_text(
    execute: bool = Query(False, description="If true, send real INDI commands (same as --execute)"),
    no_semantic: bool = Query(False, description="Disable sentence embeddings"),
    semantic_only: bool = Query(False, description="Embeddings only"),
    no_llm: bool = Query(False, description="Disable cloud LLM intent path"),
    body: ListenTextBody = Body(...),
) -> dict:
    """
    文本 → 与 ``telbot text`` 相同的 NLU → ``execute_voice_intent``（等同本机 ``--apply``）。

    App 发送用户输入；Pi 上解析并执行，无需 CLI。
    """
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")

    sentence = body.text.strip()
    if not sentence:
        raise HTTPException(
            400,
            detail={"error": "empty_text", "message": "文本为空"},
        )

    t0 = time.perf_counter()
    try:
        intent = resolve_intent_from_sentence(
            sentence,
            s,
            console=None,
            no_semantic=no_semantic,
            semantic_only=semantic_only,
            no_llm=no_llm,
        )
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e

    nlu_seconds = time.perf_counter() - t0

    if intent is None:
        raise HTTPException(
            400,
            detail={
                "error": "no_intent",
                "transcript": sentence,
                "nlu_seconds": nlu_seconds,
            },
        )

    try:
        out = execute_voice_intent(s, intent, execute=execute)
    except ValueError as e:
        raise HTTPException(
            400,
            detail={
                "error": "plan_or_input_error",
                "message": str(e),
                "intent_action": intent.action,
                "hint": _hint_for_plan_value_error(intent.action, e),
            },
        ) from e
    except KeyError as e:
        raise HTTPException(
            400,
            detail={"error": "unknown_target", "message": str(e)},
        ) from e
    except BelowHorizonError as e:
        raise HTTPException(
            400,
            detail={"error": "below_horizon", "message": str(e)},
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            400,
            detail={"error": "runtime_error", "message": str(e)},
        ) from e

    nl = out.get("nl")
    return {
        "ok": True,
        "transcript": sentence,
        "intent": intent.model_dump(mode="json", exclude_none=True),
        "stt_seconds": 0.0,
        "nlu_seconds": nlu_seconds,
        "result": out,
        "nl": nl,
        "nl_simple": out.get("nl_simple"),
    }


@app.post("/chat")
def post_chat(body: ChatBody) -> dict:
    """本地问答兜底：解释 Telbot/INDI/拍照/报错等，不下发硬件动作。"""
    sentence = body.text.strip()
    if not sentence:
        raise HTTPException(
            400,
            detail={"error": "empty_text", "message": "文本为空"},
        )
    from telbot.chat_qa import answer_telbot_question

    return answer_telbot_question(sentence, load_settings())


def _hint_for_plan_value_error(action: str, exc: ValueError) -> str:
    text = str(exc)
    if action == "plan_exoplanet_transit":
        if "pending" in text or "planet" in text or "凌星" in text:
            return "先请求「今晚凌星」列表，再说「规划第 N 个凌星」或带行星全名。"
        if "夜窗" in text or "交集" in text:
            return "该凌食与今夜天文夜窗无交集；换目标或调整观测地/时间窗配置。"
        return "凌星计划生成失败；确认 .env 经纬度与 TELBOT_EXOPLANET_*，无需 INDI 已连接。"
    if action == "exoplanet_transits":
        return "确认 Pi 已 pip install -e \".[exoplanets]\" 且可访问 NASA Archive。"
    return "请检查输入与 Pi 上 .env 配置。"


@app.post("/intent")
def post_intent(
    body: VoiceIntentV1,
    execute: bool = Query(False, description="If true, send real INDI commands"),
) -> dict:
    """
    Unified intent (voice/NLU output). See VoiceIntentV1 in telbot.models.
    """
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    try:
        return execute_voice_intent(s, body, execute=execute)
    except ValueError as e:
        raise HTTPException(
            400,
            detail={
                "error": "plan_or_input_error",
                "message": str(e),
                "intent_action": body.action,
                "hint": _hint_for_plan_value_error(body.action, e),
            },
        ) from e
    except KeyError as e:
        raise HTTPException(
            400,
            detail={"error": "unknown_target", "message": str(e)},
        ) from e
    except BelowHorizonError as e:
        raise HTTPException(
            400,
            detail={"error": "below_horizon", "message": str(e)},
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            400,
            detail={"error": "runtime_error", "message": str(e)},
        ) from e


@app.get("/filter/slots")
def get_filter_slots() -> dict:
    """滤镜轮槽位名称列表（与 ``telbot filter list`` / QHY CFW3 默认表一致）。"""
    from telbot.cfw_indi import list_filter_slots

    return {
        "ok": True,
        "schema_version": "telbot.filter_slots.v1",
        "slots": list_filter_slots(),
    }


@app.get("/filter/status")
def get_filter_status() -> dict:
    """滤镜轮 USB/INDI 连接状态与当前槽位（供 App 计划页）。"""
    from telbot.cfw_indi import DEFAULT_FILTER_SLOTS, cfw_get_slot, cfw_is_connected
    from telbot.config import load_settings

    s = load_settings()
    device = (s.indi_cfw_device or "").strip()
    if not device:
        return {
            "ok": True,
            "configured": False,
            "connected": False,
            "device": None,
            "current_slot": None,
            "current_name": None,
        }
    t = max(float(s.indi_getprop_timeout), 2.0)
    connected = cfw_is_connected(device, s.indi_host, s.indi_port, timeout=t)
    slot: int | None = None
    name: str | None = None
    if connected:
        rc, slot_val, _ = cfw_get_slot(device, s.indi_host, s.indi_port, timeout=t)
        if rc == 0 and slot_val is not None:
            slot = slot_val
            name = DEFAULT_FILTER_SLOTS.get(slot_val)
    return {
        "ok": True,
        "configured": True,
        "connected": connected,
        "device": device,
        "current_slot": slot,
        "current_name": name,
    }


@app.post("/camera/exposure")
def post_camera_exposure(
    body: CameraSnapRequest,
    execute: bool = Query(True, description="true 时写入 INDI CCD_EXPOSURE（不开始曝光）"),
) -> dict:
    """与 ``PUT /camera/exposure`` 相同；App 优先 POST。"""
    return put_camera_exposure(body=body, execute=execute)


@app.put("/camera/exposure")
def put_camera_exposure(
    body: CameraSnapRequest,
    execute: bool = Query(True, description="true 时写入 INDI CCD_EXPOSURE（不开始曝光）"),
) -> dict:
    """将曝光秒数同步到 INDI ``CCD_EXPOSURE.CCD_EXPOSURE_VALUE``（App 高级选项实时调参）。"""
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    sec = body.exposure_seconds
    if sec is None or sec <= 0:
        raise HTTPException(
            400,
            detail={"error": "invalid_exposure", "message": "exposure_seconds 须 > 0"},
        )
    ccd = (s.indi_ccd_device or "").strip()
    if not ccd:
        raise HTTPException(
            400,
            detail={"error": "no_ccd", "message": "TELBOT_INDI_CCD_DEVICE 未配置"},
        )
    if execute and not _ccd_is_connected(s, ccd):
        raise HTTPException(
            400,
            detail={"error": "ccd_not_connected", "message": "CCD 未连接"},
        )

    from telbot.ccd_indi import ccd_preset_exposure_seconds

    r = ccd_preset_exposure_seconds(
        ccd,
        s.indi_host,
        s.indi_port,
        float(sec),
        dry_run=not execute,
        setprop_timeout=max(float(s.indi_getprop_timeout), 4.0),
    )
    ok = r.returncode == 0
    return {
        "ok": ok,
        "action": "preset_exposure",
        "device": ccd,
        "exposure_seconds": float(sec),
        "dry_run": not execute,
        "steps": [{"returncode": r.returncode, "stderr": r.stderr}],
    }


def _ccd_is_connected(s, ccd: str) -> bool:
    from telbot.ccd_indi import ccd_is_connected

    t = max(float(s.indi_getprop_timeout), 2.0)
    return ccd_is_connected(ccd, s.indi_host, s.indi_port, timeout=t)


@app.post("/camera/snap")
def post_camera_snap(
    execute: bool = Query(False, description="If true, send real INDI CCD exposure"),
    body: CameraSnapRequest | None = Body(None),
) -> dict:
    """Single CCD exposure via INDI CCD_EXPOSURE.CCD_EXPOSURE_VALUE (same path as VoiceIntent snap)."""
    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    req = body if body is not None else CameraSnapRequest()
    sec = req.exposure_seconds
    cap = None
    before_state: dict[Path, tuple[int, frozenset[Path]]] | None = None
    if execute:
        cap = effective_ccd_save_dir(s.ccd_save_dir)
        search_dirs = exposure_capture_search_dirs(cap)
        before_state = capture_before_state(search_dirs)
    try:
        out = execute_voice_intent(
            s,
            VoiceIntentV1(version=1, action="snap", exposure_seconds=sec),
            execute=execute,
        )
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    if execute and out.get("ok") and cap is not None:
        from telbot.snap_preview import try_write_snap_preview

        cap_dir = cap
        hint = (out.get("save_dir_hint") or "").strip()
        if hint:
            cap_dir = Path(hint).expanduser().resolve()
        preview_ok, fits_path, preview_error = try_write_snap_preview(
            cap_dir,
            0,
            s,
            before_state=before_state,
        )
        out["preview_ok"] = preview_ok
        if fits_path is not None:
            out["preview_fits"] = str(fits_path)
        if preview_ok:
            out["preview_url"] = "/camera/snap/preview"
        elif preview_error:
            out["preview_error"] = preview_error
            if preview_error == "preview_encode_failed":
                out["preview_hint"] = (
                    'Pi 无法将 FITS 转为 JPEG。请执行：pip install -e ".[livestack]" 后重启 telbot serve。'
                )
            elif preview_error == "no_new_fits":
                out["preview_hint"] = (
                    "Pi 未在 CCD 保存目录发现新 FITS，请检查 INDI UPLOAD_DIR 与 TELBOT_CCD_SAVE_DIR。"
                )
    return out


@app.get("/camera/snap/preview")
def get_camera_snap_preview() -> FileResponse:
    """最近一次 ``POST /camera/snap`` 的 JPEG 预览（供 App「拍单张」下载）。"""
    from telbot.snap_preview import ensure_snap_preview_jpeg

    s = load_settings()
    path, message = ensure_snap_preview_jpeg(s)
    if path is None:
        raise HTTPException(
            404,
            detail={"error": "no_preview", "message": message},
        )
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename="snap_preview.jpg",
    )


_CALIBRATION_KINDS = frozenset({"bias", "dark", "flat", "light"})


@app.post("/camera/cal/stop")
def post_camera_cal_stop() -> dict:
    """请求停止正在进行的校准拍摄（当前帧结束后生效）。"""
    from telbot.calibration.service import request_calibration_abort

    request_calibration_abort("app_stop")
    return {
        "ok": True,
        "message": "已请求停止校准拍摄（当前张完成后停止，已完成的帧会保留）",
    }


@app.post("/camera/cal/{kind}")
def post_camera_cal(
    kind: str,
    body: CalibrationCaptureBody | None = Body(None),
    execute: bool = Query(False, description="true 时真机曝光并保存 FITS"),
) -> dict:
    """
    校准帧：偏置 / 暗场 / 平场 / 亮场（``telbot camera cal <kind>``）。

    真机请求可能持续较久（多张长曝光），App 请使用足够长的 HTTP 超时。
    """
    k = kind.strip().lower()
    if k not in _CALIBRATION_KINDS:
        raise HTTPException(
            400,
            detail={
                "error": "invalid_calibration_kind",
                "message": f"kind 须为 bias|dark|flat|light，收到 {kind!r}",
            },
        )
    from telbot.ccd_calibration import run_calibration_frames

    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    req = body if body is not None else CalibrationCaptureBody()
    try:
        return run_calibration_frames(
            s,
            k,  # type: ignore[arg-type]
            count=req.count,
            exposure_seconds=req.exposure_seconds,
            session_tag=req.session_tag,
            execute=execute,
            interval_seconds=req.interval_seconds or 0.0,
        )
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e


@app.post("/camera/live-stack/start")
def post_camera_live_stack_start(
    body: LiveStackStartBody,
    execute: bool = Query(False, description="true 时真机曝光并后台叠加"),
) -> dict:
    """
    边拍边叠（Live Stack）。原始 FITS 保存在会话 ``raw/``；App 轮询 preview/status。

    见 ``docs/LIVE_STACK.md``。
    """
    from telbot.live_stack.service import live_stack_is_running, start_live_stack_background

    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    if execute and live_stack_is_running():
        raise HTTPException(
            409,
            detail={"error": "live_stack_already_active", "message": "已有边拍边叠在运行"},
        )
    try:
        return start_live_stack_background(
            s,
            duration_seconds=body.duration_seconds,
            exposure_seconds=body.exposure_seconds,
            cadence_seconds=body.cadence_seconds,
            session_tag=body.session_tag,
            cal_bias_dir=body.cal_bias_dir,
            cal_dark_dir=body.cal_dark_dir,
            cal_flat_dir=body.cal_flat_dir,
            execute=execute,
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, detail=str(e)) from e


@app.post("/camera/live-stack/stop")
def post_camera_live_stack_stop() -> dict:
    """请求中止正在运行的边拍边叠。"""
    from telbot.live_stack.service import stop_live_stack

    return stop_live_stack()


@app.get("/camera/live-stack/status")
def get_camera_live_stack_status() -> dict:
    """边拍边叠进度（JSON）；App 可轮询 ``frames_stacked``、``running``。"""
    from telbot.live_stack.service import read_live_stack_status

    return read_live_stack_status()


@app.get("/camera/live-stack/preview")
def get_camera_live_stack_preview() -> FileResponse:
    """当前叠加预览 JPEG（供 App ``UIImage`` / SwiftUI 显示）。"""
    from telbot.repo_paths import live_stack_preview_jpeg_path

    path = live_stack_preview_jpeg_path()
    if not path.is_file():
        raise HTTPException(
            404,
            detail={
                "error": "no_preview",
                "message": "尚无预览图；请先启动边拍边叠或等待第一帧完成",
            },
        )
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename="live_stack_preview.jpg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/platesolve")
def post_platesolve(body: PlatesolveRequest) -> dict:
    """ASTAP plate solve；可选 snap_first 先真机曝光再解算（见 PlatesolveRequest）。"""
    s = load_settings()
    snap_block: dict | None = None
    try:
        if body.snap_first:
            if not indi_available():
                raise HTTPException(503, "indi_setprop not available on this host")
            cap = effective_ccd_save_dir(s.ccd_save_dir)
            before_paths = fits_files_in_dir(cap)
            before_ns = max_fits_mtime_ns_in_dir(cap)
            try:
                snap_block = execute_voice_intent(
                    s,
                    VoiceIntentV1(
                        version=1,
                        action="snap",
                        exposure_seconds=body.exposure_seconds,
                    ),
                    execute=True,
                )
            except RuntimeError as e:
                raise HTTPException(400, detail=str(e)) from e
            if not snap_block.get("ok"):
                return {**snap_block, "ok": False, "message": "CCD 曝光步骤失败"}
            cap_dir = cap
            hint = (snap_block.get("save_dir_hint") or "").strip()
            if hint:
                cap_dir = Path(hint).expanduser().resolve()
            new_fits = resolve_new_capture_fits(cap_dir, before_ns, before_paths)
            if new_fits is None:
                return {
                    "snap": snap_block,
                    "ok": False,
                    "message": (
                        f"曝光后在 {cap} 未检测到新的 FITS；"
                        "请确认 INDI UPLOAD_SETTINGS.UPLOAD_DIR 与该目录一致且 UPLOAD_LOCAL=On"
                    ),
                }
            out = run_platesolve(s, fits_path=new_fits, use_latest=False)
        else:
            fp = Path(body.fits_path) if (body.fits_path or "").strip() else None
            out = run_platesolve(s, fits_path=fp, use_latest=body.use_latest)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(503, detail=str(e)) from e

    if snap_block is not None:
        out["snap"] = snap_block

    if body.align is not None:
        if not out.get("ok"):
            out["align"] = {
                "mode": body.align,
                "ok": False,
                "skipped": "solve_not_ok",
                "error": "解算未成功，跳过对准",
            }
        else:
            if body.execute and not indi_available():
                raise HTTPException(503, "indi_setprop not available on this host")
            out["align"] = align_mount_after_platesolve(
                s,
                out,
                align=body.align,
                execute=body.execute,
            )
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


_transit_run_thread: threading.Thread | None = None
_transit_run_last_out: dict[str, Any] | None = None


def _background_transit_run(
    *,
    plan_path: Path,
    execute: bool,
    force: bool,
    on_fail: str,
) -> None:
    global _transit_run_last_out
    from telbot.planning.execute import load_plan_json
    from telbot.planning.transit_abort import clear_run_session, write_run_session
    from telbot.planning.transit_execute import execute_transit_plan

    s = load_settings()
    try:
        payload = load_plan_json(plan_path)
        if execute:
            write_run_session(plan_path.resolve())
        try:
            out = execute_transit_plan(
                s,
                payload,
                execute=execute,
                force=force,
                on_fail=on_fail,  # type: ignore[arg-type]
            )
            _transit_run_last_out = out
        finally:
            if execute:
                clear_run_session()
    except Exception as e:
        _transit_run_last_out = {"ok": False, "error": str(e), "stopped_reason": "error"}


@app.get("/plan/transit/status")
def get_plan_transit_status() -> dict:
    """凌星 ``transit-run`` 会话状态（供 iOS「计划」页轮询）。"""
    from telbot.planning.transit_abort import abort_flag_present, read_run_session

    session = read_run_session()
    pid = session.get("pid") if session else None
    running = isinstance(pid, int) and _pid_alive(pid)
    from telbot.planning.transit_ingress_precheck import get_last_ingress_precheck

    return {
        "ok": True,
        "running": running,
        "session": session,
        "abort_flag": abort_flag_present(),
        "last_result": _transit_run_last_out,
        "ingress_precheck": get_last_ingress_precheck(),
    }


@app.get("/plan/transit/ingress-precheck")
def get_plan_transit_ingress_precheck() -> dict:
    """
    凌食 ingress 前预检结果（``telbot.transit_ingress_precheck.v1``）。

    App 轮询：若 ``capture_ok`` 为 false，读取 ``user_alert`` 向用户提示调整望远镜摆放。
    无结果时 ``precheck`` 为 null（尚未执行或 transit-run 未跑到该步骤）。
    """
    from telbot.planning.transit_ingress_precheck import get_last_ingress_precheck

    precheck = get_last_ingress_precheck()
    return {
        "ok": True,
        "precheck": precheck,
        "has_alert": bool(precheck and precheck.get("user_alert")),
    }


@app.post("/plan/transit/run")
def post_plan_transit_run(
    execute: bool = Query(False, description="真机按 UTC 时间线执行（等同 transit-run --execute）"),
    plan_path: str | None = Query(None, description="计划 JSON 路径；省略则用最新 transit_*.json"),
    force: bool = Query(
        True,
        description="跳过 confirmation 校验（App 侧用户已确认规划）",
    ),
    on_fail: str = Query("abort", description="失败策略：abort | continue | park"),
) -> dict:
    """后台启动 ``telbot plan transit-run``（阻塞至凌星夜结束；勿重复提交）。"""
    global _transit_run_thread
    from telbot.planning.phase0_config import validate_planning_settings
    from telbot.planning.transit_plan import resolve_latest_transit_plan

    if on_fail not in ("abort", "continue", "park"):
        raise HTTPException(400, detail="on_fail 须为 abort | continue | park")

    s = load_settings()
    if execute and not indi_available():
        raise HTTPException(503, "indi_setprop not available on this host")
    try:
        validate_planning_settings(s)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e

    from telbot.planning.transit_abort import read_run_session

    sess = read_run_session()
    if sess and isinstance(sess.get("pid"), int) and _pid_alive(sess["pid"]):
        raise HTTPException(
            409,
            detail={
                "error": "transit_run_already_active",
                "session": sess,
            },
        )

    if _transit_run_thread is not None and _transit_run_thread.is_alive():
        raise HTTPException(409, detail={"error": "transit_run_thread_active"})

    try:
        path = Path(plan_path).expanduser() if plan_path else resolve_latest_transit_plan()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, detail=str(e)) from e

    if not path.is_file():
        raise HTTPException(404, detail=f"计划文件不存在：{path}")

    _transit_run_thread = threading.Thread(
        target=_background_transit_run,
        kwargs={
            "plan_path": path.resolve(),
            "execute": execute,
            "force": force,
            "on_fail": on_fail,
        },
        daemon=True,
        name="telbot-transit-run-http",
    )
    _transit_run_thread.start()
    return {
        "ok": True,
        "started": True,
        "execute": execute,
        "plan_path": str(path.resolve()),
        "dry_run": not execute,
    }


@app.post("/plan/transit/abort")
def post_plan_transit_abort(
    execute: bool = Query(
        True,
        description="同时直接对赤道仪 ABORT（等同 telbot plan transit-abort --execute）",
    ),
    reason: str = Query("user requested abort", description="中止原因（写入标志文件）"),
) -> dict:
    """立即终止正在运行的凌星观测（``telbot plan transit-abort``）。"""
    from telbot.indi import abort_motion
    from telbot.planning.transit_abort import (
        read_run_session,
        signal_run_session,
        write_abort_flag,
    )

    flag = write_abort_flag(reason)
    session = read_run_session()
    signaled_pid = signal_run_session()
    direct: dict[str, Any] | None = None
    if execute:
        if not indi_available():
            pass
        else:
            s = load_settings()
            dev = resolve_telescope_device(s)
            r = abort_motion(
                dev,
                s.indi_host,
                s.indi_port,
                dry_run=False,
            )
            direct = {
                "device": dev,
                "code": r.returncode,
                "stdout": r.stdout,
                "stderr": r.stderr,
            }
    return {
        "ok": True,
        "abort_flag": str(flag),
        "reason": reason,
        "session": session,
        "signaled_pid": signaled_pid,
        "direct_abort": direct,
    }


@app.get("/usb/devices")
def get_usb_devices() -> dict:
    """
    树莓派 ``lsusb`` 与 ``docs/USB_DEVICE_REGISTRY.md`` 登记设备（供 iOS「连接设备」）。

    以 **USB 是否出现对应 VID:PID** 判断物理连接，不依赖 INDI CONNECTION 属性。
    """
    import datetime as dt

    from telbot.usb_devices import (
        build_usb_connection_slots,
        list_connected_usb_devices,
        list_registered_usb_catalog,
        lsusb_vid_pids,
    )

    present = sorted(lsusb_vid_pids())
    connected = list_connected_usb_devices(vid_pids=set(present))
    return {
        "ok": True,
        "schema_version": "telbot.usb_devices.v1",
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "vid_pids_present": present,
        "devices": connected,
        "slots": build_usb_connection_slots(connected),
        "registry_entries": len(list_registered_usb_catalog()),
    }


@app.get("/health")
def health(
    quick: bool = Query(
        False,
        description="true 时仅返回存活字段，不调用 indi_getprop（telbot serve restart 用）",
    ),
) -> dict:
    """存活探测 + INDI 设备连接快照（供 iOS「连接设备」页解析）。"""
    body: dict[str, Any] = {
        "status": "ok",
        "indi_tools": indi_available(),
        "version": telbot_version,
    }
    if not quick:
        s = load_settings()
        body.update(build_health_devices(s))
    return body


@app.get("/config/env")
def get_config_env(
    keys: list[str] = Query(default=[], description="要读取的 TELBOT_* 键；省略则返回全部 App 白名单"),
) -> dict:
    """读取 App 白名单内的 `.env` 参数当前生效值（合并 .env 与进程环境）。"""
    try:
        values = read_app_env_values(keys if keys else None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "path": app_env_path(),
        "keys": sorted(values.keys()),
        "values": values,
    }


@app.get("/config/env/keys")
def get_config_env_keys() -> dict:
    """返回 App 可编辑的 env 键列表（供客户端构建表单）。"""
    return {"ok": True, "keys": sorted(HTTP_APP_ENV_WHITELIST)}


@app.patch("/config/env")
def patch_config_env(body: EnvPatchBody) -> dict:
    """写回 App 白名单内的 `.env` 参数；当前 serve 进程立即生效。"""
    try:
        values = write_app_env_values(body.updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "path": app_env_path(), "values": values}
