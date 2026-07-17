"""Structured HTTP API errors for Telbot (FastAPI / iOS App).

See ``docs/HTTP_API_ERRORS.md`` for the full catalog and App parsing guide.
"""

from __future__ import annotations

import os
import traceback
from typing import Any

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError


def _error_code_for_status(status_code: int, detail: Any) -> str:
    if isinstance(detail, dict) and detail.get("error"):
        return str(detail["error"])
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        503: "service_unavailable",
        500: "internal_error",
    }
    return mapping.get(status_code, f"http_{status_code}")


def _message_from_detail(detail: Any) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key in ("message", "detail", "error"):
            v = detail.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return str(detail)
    return str(detail)


def build_error_body(
    *,
    status_code: int,
    detail: Any = None,
    path: str | None = None,
    error: str | None = None,
    message: str | None = None,
    exception_type: str | None = None,
    hint: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Standard JSON envelope for App clients.

    Always parse response **body** as JSON; do not rely on HTTP reason phrase alone.
    """
    code = error or _error_code_for_status(status_code, detail)
    msg = message or _message_from_detail(detail)
    body: dict[str, Any] = {
        "ok": False,
        "status_code": status_code,
        "error": code,
        "message": msg,
        "detail": detail,
    }
    if path:
        body["path"] = path
    if exception_type:
        body["exception_type"] = exception_type
    if hint:
        body["hint"] = hint
    if extra:
        body.update(extra)
    if os.environ.get("TELBOT_HTTP_DEBUG", "").strip() in ("1", "true", "yes"):
        import sys

        exc = sys.exc_info()[1]
        if exc is not None:
            body["traceback"] = traceback.format_exception_only(type(exc), exc)
    return body


def http_exception_to_body(exc: HTTPException, *, path: str | None = None) -> dict[str, Any]:
    return build_error_body(
        status_code=exc.status_code,
        detail=exc.detail,
        path=path,
    )


def unhandled_exception_to_body(exc: BaseException, *, path: str | None = None) -> dict[str, Any]:
    hint = _hint_for_exception(exc)
    return build_error_body(
        status_code=500,
        error="internal_error",
        message=str(exc) or type(exc).__name__,
        detail={
            "error": "internal_error",
            "message": str(exc),
            "exception_type": type(exc).__name__,
        },
        path=path,
        exception_type=type(exc).__name__,
        hint=hint,
    )


def _json_safe_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pydantic ctx may embed ValueError objects — stringify for JSONResponse."""
    out: list[dict[str, Any]] = []
    for err in errors:
        row = dict(err)
        ctx = row.get("ctx")
        if isinstance(ctx, dict):
            row["ctx"] = {
                k: (str(v) if isinstance(v, BaseException) else v) for k, v in ctx.items()
            }
        out.append(row)
    return out


def validation_error_to_body(exc: RequestValidationError, *, path: str | None = None) -> dict[str, Any]:
    errors = _json_safe_validation_errors(exc.errors())
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", ()))
    msg = first.get("msg", "请求参数无效")
    ctx = first.get("ctx") or {}
    user_msg = ctx.get("error") if isinstance(ctx.get("error"), str) else None
    if not user_msg and "Value error" in str(msg):
        user_msg = str(msg).split("Value error, ", 1)[-1].strip()
    return build_error_body(
        status_code=422,
        error="validation_error",
        message=user_msg or (f"{loc}: {msg}" if loc else str(msg)),
        detail={"errors": errors},
        path=path,
        hint="检查 JSON 字段是否与 OpenAPI / docs/HTTP_API_ERRORS.md 一致（如 VoiceIntentV1、ListenTextBody）。",
    )


def _hint_for_exception(exc: BaseException) -> str | None:
    name = type(exc).__name__
    text = str(exc)
    if name == "NameError" and "plans_dir" in text:
        return "服务端代码缺陷（plans_dir 未导入）；请更新 Telbot 到最新版本。"
    if name == "ModuleNotFoundError" and ("astroplan" in text or "astroquery" in text):
        return "Pi 上请执行：pip install -e \".[exoplanets]\" 后重启 telbot serve。"
    if name == "ImportError" and "platesolve" in text.lower():
        return "Pi 上请执行：pip install -e \".[platesolve]\" 并安装 ASTAP。"
    if name == "ConnectionError" or "timed out" in text.lower() or "Name or service not known" in text:
        return "Pi 无法访问外网（凌星列表/语音 STT 等）；检查网络或稍后重试。"
    if "exoplanet" in text.lower() or "NASA" in text:
        return "系外行星凌星数据拉取失败；确认网络与 pip install -e \".[exoplanets]\"."
    if "pending" in text.lower() or "planet" in text.lower():
        return "凌星规划：先调用「今晚凌星列表」或指定有效行星名 / event_index。"
    return (
        "服务端未捕获异常；请将 response JSON 中的 message、exception_type、path 发给维护者，"
        "并在 Pi 上查看 telbot serve 终端日志。"
    )


def raise_http_error(
    status_code: int,
    *,
    error: str,
    message: str,
    detail: Any | None = None,
    hint: str | None = None,
) -> None:
    """Raise HTTPException with structured detail dict."""
    payload: dict[str, Any] = {
        "error": error,
        "message": message,
    }
    if hint:
        payload["hint"] = hint
    if detail is not None:
        payload["detail"] = detail
    raise HTTPException(status_code=status_code, detail=payload)
