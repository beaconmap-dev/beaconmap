"""Where BeaconMap keeps its data and settings, per operating system."""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

APP = "beaconmap"


def data_dir() -> Path:
    """Folder for the offline databases (large files)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def access_token() -> str:
    """Secret that proves a browser was opened by this user, not another account on the PC.

    Kept in a file only the owner can read, and reused between runs so an
    already-open BeaconMap tab reconnects after a restart.
    """
    path = data_dir() / "token"
    try:
        token = path.read_text(encoding="ascii").strip()
        if len(token) >= 20:
            return token
    except (OSError, ValueError):
        pass
    token = secrets.token_urlsafe(24)
    write_private(path, token)
    return token


def write_private(path: Path, text: str) -> None:
    """Write a file readable only by the current user (0600 on Linux/macOS)."""
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
