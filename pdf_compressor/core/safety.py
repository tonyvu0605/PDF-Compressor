"""Folders the app refuses to work on."""

import os
from pathlib import Path

SYSTEM_FOLDER_VARS = (
    "WINDIR",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "APPDATA",
    "LOCALAPPDATA",
)

BLOCKED_MESSAGE = (
    "For safety, PDF Compressor can't work on {path}. Please choose a more"
    " specific folder, like one client's folder."
)


def blocked_reason(path: Path) -> str | None:
    """Return why the app refuses this file or folder, or None if it is allowed."""
    # pathlib compares Windows paths case-insensitively but literally, so
    # ".." and short 8.3 names must be resolved away before comparing.
    resolved = path.resolve()
    is_root = resolved.parent == resolved
    is_home = resolved == Path.home().resolve()
    in_system = any(
        resolved == folder or folder in resolved.parents for folder in _system_folders()
    )
    if is_root or is_home or in_system:
        return BLOCKED_MESSAGE.format(path=path)
    return None


def _system_folders() -> list[Path]:
    folders = []
    for var in SYSTEM_FOLDER_VARS:
        value = os.environ.get(var, "").strip()
        # An empty value would become Path("."), the current folder.
        if value:
            folders.append(Path(value).resolve())
    return folders
