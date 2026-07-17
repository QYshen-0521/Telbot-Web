"""env_sync: atomic .env key updates."""

from __future__ import annotations

import os
import pwd
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from telbot.env_sync import (
    DOTENV_WHITELIST,
    _resolve_env_owner_uid_gid,
    _restore_home_env_ownership_if_root,
    resolve_dotenv_path,
    update_dotenv_keys,
)


def test_update_dotenv_keys_preserves_comments_and_other_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# observer\n"
        "TELBOT_LATITUDE=31.2\n"
        "TELBOT_INDI_DEVICE=Old Mount\n"
        "TELBOT_LONGITUDE=121.5\n",
        encoding="utf-8",
    )
    update_dotenv_keys(
        env,
        {
            "TELBOT_INDI_DEVICE": "Celestron GPS",
            "TELBOT_INDI_DEVICE_AUTO": "true",
        },
    )
    text = env.read_text(encoding="utf-8")
    assert "# observer" in text
    assert "TELBOT_LATITUDE=31.2" in text
    assert "TELBOT_LONGITUDE=121.5" in text
    assert "TELBOT_INDI_DEVICE=Celestron GPS" in text
    assert "TELBOT_INDI_DEVICE_AUTO=true" in text
    assert "Old Mount" not in text


def test_update_dotenv_keys_appends_missing_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TELBOT_INDI_HOST=127.0.0.1\n", encoding="utf-8")
    update_dotenv_keys(env, {"TELBOT_INDI_DEVICE": "Losmandy Gemini"})
    text = env.read_text(encoding="utf-8")
    assert "TELBOT_INDI_HOST=127.0.0.1" in text
    assert "TELBOT_INDI_DEVICE=Losmandy Gemini" in text


def test_update_dotenv_keys_rejects_non_whitelist(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    with pytest.raises(ValueError, match="not allowed"):
        update_dotenv_keys(env, {"TELBOT_OPENAI_API_KEY": "secret"})


def test_dotenv_whitelist_includes_active_profile() -> None:
    assert "TELBOT_ACTIVE_MOUNT_PROFILE" in DOTENV_WHITELIST
    assert "TELBOT_INDI_CCD_DEVICE" in DOTENV_WHITELIST


def test_update_dotenv_keys_ccd_device(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TELBOT_INDI_CCD_DEVICE=SBIG CCD\n", encoding="utf-8")
    update_dotenv_keys(env, {"TELBOT_INDI_CCD_DEVICE": "ZWO CCD ASI294MC Pro"})
    assert "ZWO CCD ASI294MC Pro" in env.read_text(encoding="utf-8")


def test_resolve_dotenv_path_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "custom.env"
    target.write_text("x=1\n", encoding="utf-8")
    monkeypatch.setenv("TELBOT_ENV_FILE", str(target))
    assert resolve_dotenv_path() == target


def test_resolve_env_owner_from_home_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELBOT_ENV_OWNER", raising=False)

    class FakePw:
        pw_uid = 1001
        pw_gid = 1002

    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda name: FakePw() if name == "alice" else (_ for _ in ()).throw(KeyError()),
    )
    path = Path("/home/alice/Telbot/.env")
    monkeypatch.setattr(type(path), "resolve", lambda self: Path("/home/alice/Telbot/.env"))
    assert _resolve_env_owner_uid_gid(path) == (1001, 1002)


def test_resolve_env_owner_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELBOT_ENV_OWNER", os.environ["USER"])
    pw = pwd.getpwnam(os.environ["USER"])
    uid_gid = _resolve_env_owner_uid_gid(Path("/tmp/not-home/.env"))
    assert uid_gid == (pw.pw_uid, pw.pw_gid)


def test_restore_home_env_ownership_if_root(monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path("/home/alice/Telbot/.env")
    monkeypatch.setattr(type(path), "resolve", lambda self: Path("/home/alice/Telbot/.env"))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    chown_calls: list[tuple[Path, int, int]] = []
    chmod_calls: list[tuple[Path, int]] = []

    class FakePw:
        pw_uid = 1001
        pw_gid = 1002

    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda name: FakePw() if name == "alice" else (_ for _ in ()).throw(KeyError()),
    )

    def _chown(p: os.PathLike[str] | str | int, u: int, g: int) -> None:
        chown_calls.append((Path(p), u, g))

    def _chmod(p: os.PathLike[str] | str | int, mode: int) -> None:
        chmod_calls.append((Path(p), mode))

    monkeypatch.setattr(os, "chown", _chown)
    monkeypatch.setattr(os, "chmod", _chmod)
    _restore_home_env_ownership_if_root(path, mode=0o640)
    assert chown_calls == [(Path("/home/alice/Telbot/.env"), 1001, 1002)]
    assert chmod_calls == [(Path("/home/alice/Telbot/.env"), 0o640)]


def test_update_dotenv_keys_chowns_when_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home_root = tmp_path / "home" / os.environ["USER"] / "Telbot"
    home_root.mkdir(parents=True)
    env = home_root / ".env"
    env.write_text("TELBOT_INDI_DEVICE=Old\n", encoding="utf-8")
    pw = pwd.getpwnam(os.environ["USER"])
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    chown_calls: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(os, "chown", lambda p, u, g: chown_calls.append((Path(p), u, g)))
    monkeypatch.setattr(os, "chmod", lambda _p, _m: None)
    monkeypatch.setattr(
        "telbot.env_sync._resolve_env_owner_uid_gid",
        lambda _p: (pw.pw_uid, pw.pw_gid),
    )
    resolved = MagicMock(return_value=env.resolve())
    monkeypatch.setattr(Path, "resolve", resolved)

    update_dotenv_keys(env, {"TELBOT_INDI_DEVICE": "PlaneWave"})
    assert env.read_text(encoding="utf-8") == "TELBOT_INDI_DEVICE=PlaneWave\n"
    assert chown_calls == [(env.resolve(), pw.pw_uid, pw.pw_gid)]
