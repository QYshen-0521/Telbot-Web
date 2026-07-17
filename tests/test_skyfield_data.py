"""Skyfield data directory resolution (de421.bsp)."""

from __future__ import annotations

from pathlib import Path

import pytest

from telbot import skyfield_data


def test_resolve_skyfield_data_dir_defaults_to_home_telbot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TELBOT_SKYFIELD_DATA_DIR", raising=False)
    skyfield_data.get_skyfield_loader.cache_clear()
    assert skyfield_data.resolve_skyfield_data_dir() == (tmp_path / "Telbot").resolve()


def test_resolve_skyfield_data_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "ephem"
    custom.mkdir()
    monkeypatch.setenv("TELBOT_SKYFIELD_DATA_DIR", str(custom))
    skyfield_data.get_skyfield_loader.cache_clear()
    assert skyfield_data.resolve_skyfield_data_dir() == custom.resolve()


def test_loader_uses_existing_de421_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TELBOT_SKYFIELD_DATA_DIR", raising=False)
    skyfield_data.get_skyfield_loader.cache_clear()
    data_dir = tmp_path / "Telbot"
    data_dir.mkdir()
    (data_dir / "de421.bsp").write_bytes(b"not-a-real-bsp")
    loader = skyfield_data.get_skyfield_loader()

    def fail_download(*args: object, **kwargs: object) -> None:
        raise AssertionError("should not download when de421.bsp exists locally")

    monkeypatch.setattr(loader, "download", fail_download)
    with pytest.raises(Exception):
        loader("de421.bsp")
