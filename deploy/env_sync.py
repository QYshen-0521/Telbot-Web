"""Atomic updates to Telbot `.env` keys (standalone copy for /usr/local/lib/telbot-deploy)."""

from __future__ import annotations

import os
import pwd
import tempfile
import warnings
from pathlib import Path

DOTENV_WHITELIST = frozenset(
    {
        "TELBOT_INDI_DEVICE",
        "TELBOT_INDI_DEVICE_AUTO",
        "TELBOT_ACTIVE_MOUNT_PROFILE",
        "TELBOT_INDI_CCD_DEVICE",
        "TELBOT_INDI_CFW_DEVICE",
        "TELBOT_INDI_FOCUSER_DEVICE",
    }
)


def resolve_dotenv_path() -> Path:
    explicit = os.environ.get("TELBOT_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home_env = Path.home() / "Telbot" / ".env"
    if home_env.is_file():
        return home_env.resolve()
    cwd_env = Path(".env")
    if cwd_env.is_file():
        return cwd_env.resolve()
    return home_env.resolve()


def _resolve_env_owner_uid_gid(path: Path) -> tuple[int, int] | None:
    explicit = os.environ.get("TELBOT_ENV_OWNER", "").strip()
    if explicit:
        try:
            pw = pwd.getpwnam(explicit)
            return pw.pw_uid, pw.pw_gid
        except KeyError:
            warnings.warn(
                f"TELBOT_ENV_OWNER={explicit!r} 不存在，跳过 .env chown",
                stacklevel=3,
            )
            return None

    try:
        parts = path.expanduser().resolve().parts
    except OSError:
        return None
    if len(parts) < 3 or parts[0] != os.sep or parts[1] != "home":
        return None
    username = parts[2]
    try:
        pw = pwd.getpwnam(username)
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        warnings.warn(
            f".env 路径在 /home/{username}/ 下但系统无此用户，跳过 chown",
            stacklevel=3,
        )
        return None


def _restore_home_env_ownership_if_root(path: Path, *, mode: int | None) -> None:
    if os.geteuid() != 0:
        return
    owner = _resolve_env_owner_uid_gid(path)
    if owner is None:
        return
    uid, gid = owner
    try:
        resolved = path.expanduser().resolve()
    except OSError as e:
        warnings.warn(f".env chown 失败（无法 resolve 路径）: {e}", stacklevel=3)
        return
    target_mode = mode if mode is not None else 0o600
    try:
        os.chown(resolved, uid, gid)
        os.chmod(resolved, target_mode)
    except OSError as e:
        warnings.warn(f".env chown 失败: {e}", stacklevel=3)


def update_dotenv_keys(path: Path, mapping: dict[str, str]) -> None:
    for key in mapping:
        if key not in DOTENV_WHITELIST:
            raise ValueError(f"dotenv key not allowed: {key}")

    path = path.expanduser()
    prev_mode: int | None = None
    if path.is_file():
        try:
            prev_mode = path.stat().st_mode & 0o777
        except OSError:
            prev_mode = None
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    remaining = dict(mapping)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key, _, _val = stripped.partition("=")
        key = key.strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)

    for key, val in remaining.items():
        out.append(f"{key}={val}")

    text = "\n".join(out)
    if out:
        text += "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".env.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
        _restore_home_env_ownership_if_root(path, mode=prev_mode)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
