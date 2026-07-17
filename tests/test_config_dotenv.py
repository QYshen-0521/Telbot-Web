"""Multi-layer .env merge for Settings (Pi: run telbot from ~ vs ~/Telbot)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from telbot.config import apply_telbot_dotenv_to_environ, merged_telbot_dotenv, telbot_dotenv_layer_paths


def test_merged_telbot_dotenv_telbot_overrides_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TELBOT_ENV_FILE", raising=False)
    (tmp_path / ".env").write_text("TELBOT_INDI_DEVICE=FromCwd\nTELBOT_INDI_DEVICE_AUTO=false\n", encoding="utf-8")
    telbot_dir = tmp_path / "Telbot"
    telbot_dir.mkdir()
    (telbot_dir / ".env").write_text(
        "TELBOT_INDI_DEVICE=Celestron GPS\nTELBOT_INDI_DEVICE_AUTO=true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    m = merged_telbot_dotenv()
    assert m["TELBOT_INDI_DEVICE"] == "Celestron GPS"
    assert m["TELBOT_INDI_DEVICE_AUTO"] == "true"


def test_apply_respects_shell_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TELBOT_ENV_FILE", raising=False)
    monkeypatch.setenv("TELBOT_INDI_DEVICE", "ShellMount")
    (tmp_path / ".env").write_text("TELBOT_INDI_DEVICE=FromCwd\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    apply_telbot_dotenv_to_environ()
    assert os.environ["TELBOT_INDI_DEVICE"] == "ShellMount"


def test_telbot_dotenv_layer_paths_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "x.env"
    p.write_text("TELBOT_INDI_HOST=1\n", encoding="utf-8")
    monkeypatch.setenv("TELBOT_ENV_FILE", str(p))
    assert telbot_dotenv_layer_paths() == [p]


def test_resolve_dotenv_prefers_home_telbot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from telbot.env_sync import resolve_dotenv_path

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TELBOT_ENV_FILE", raising=False)
    telbot_dir = tmp_path / "Telbot"
    telbot_dir.mkdir()
    (telbot_dir / ".env").write_text("TELBOT_INDI_DEVICE=Celestron GPS\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TELBOT_INDI_DEVICE=Wrong\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert resolve_dotenv_path() == (telbot_dir / ".env").resolve()
