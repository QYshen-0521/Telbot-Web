"""Skyfield data directory (de421.bsp etc.); default ~/Telbot, not process CWD."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from skyfield.api import Loader

from telbot.config import apply_telbot_dotenv_to_environ


def resolve_skyfield_data_dir() -> Path:
    """
    Directory where Skyfield looks for ephemeris files before downloading.

    Priority: TELBOT_SKYFIELD_DATA_DIR → ~/Telbot (Pi default install layout).
    """
    apply_telbot_dotenv_to_environ()
    explicit = os.environ.get("TELBOT_SKYFIELD_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / "Telbot").resolve()


@lru_cache
def get_skyfield_loader() -> Loader:
    d = resolve_skyfield_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return Loader(str(d))
