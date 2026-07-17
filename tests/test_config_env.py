"""config_env: App 白名单 .env 读写。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from telbot.config_env import HTTP_APP_ENV_WHITELIST, read_app_env_values, write_app_env_values


def test_read_app_env_values_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELBOT_INDI_HOST", "192.168.1.10")
    monkeypatch.setenv("TELBOT_INDI_PORT", "7624")
    monkeypatch.setenv("TELBOT_LATITUDE", "31.2")
    out = read_app_env_values(["TELBOT_INDI_HOST", "TELBOT_INDI_PORT", "TELBOT_LATITUDE"])
    assert out["TELBOT_INDI_HOST"] == "192.168.1.10"
    assert out["TELBOT_INDI_PORT"] == "7624"
    assert out["TELBOT_LATITUDE"] == "31.2"


def test_read_app_env_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="unknown env keys"):
        read_app_env_values(["TELBOT_OPENAI_API_KEY"])


def test_write_app_env_values_updates_file_and_environ(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("TELBOT_LATITUDE=30.0\n", encoding="utf-8")
    monkeypatch.setenv("TELBOT_ENV_FILE", str(env))
    monkeypatch.delenv("TELBOT_LATITUDE", raising=False)

    written = write_app_env_values({"TELBOT_LATITUDE": "31.5", "TELBOT_LONGITUDE": "121.4"})
    assert written["TELBOT_LATITUDE"] == "31.5"
    assert written["TELBOT_LONGITUDE"] == "121.4"
    assert os.environ["TELBOT_LATITUDE"] == "31.5"
    text = env.read_text(encoding="utf-8")
    assert "TELBOT_LATITUDE=31.5" in text
    assert "TELBOT_LONGITUDE=121.4" in text


def test_http_whitelist_excludes_secrets() -> None:
    assert "TELBOT_OPENAI_API_KEY" not in HTTP_APP_ENV_WHITELIST
    assert "TELBOT_LLM_API_KEY" not in HTTP_APP_ENV_WHITELIST


def test_read_app_env_includes_etc_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELBOT_TRANSIT_ETC_APERTURE_MM", "250")
    monkeypatch.setenv("TELBOT_TRANSIT_EXPOSURE_SECONDS", "0")
    out = read_app_env_values(["TELBOT_TRANSIT_ETC_APERTURE_MM", "TELBOT_TRANSIT_EXPOSURE_SECONDS"])
    assert out["TELBOT_TRANSIT_ETC_APERTURE_MM"] == "250"
    assert out["TELBOT_TRANSIT_EXPOSURE_SECONDS"] in {"0", "0.0"}


def test_write_etc_env_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setenv("TELBOT_ENV_FILE", str(env))
    write_app_env_values({"TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM": "3.75"})
    assert "TELBOT_TRANSIT_ETC_PIXEL_SIZE_UM=3.75" in env.read_text(encoding="utf-8")
