"""User options, where they are stored, and the app's folders."""

import ctypes
import json
import logging
import math
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

KEEP_LOGS = 20
APP_NAME = "PDF Compressor"
PORTABLE_MARKER = "portable.txt"
OUTPUT_FOLDER_NAME = "Compressed PDFs"
BACKUP_FOLDER_NAME = "PDF Backups"
FOLDERID_DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"


class SaveMode(Enum):
    """Where compressed files go."""

    COPY = "copy"
    BACKUP = "backup"
    REPLACE = "replace"


class Level(Enum):
    """How hard images are compressed, named like Acrobat's levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Settings:
    """The options the user picks, remembered between runs."""

    save_mode: SaveMode
    output_dir: Path
    backup_dir: Path
    level: Level
    size_limit_mb: float | None
    remove_hidden_info: bool


def default_settings(documents: Path) -> Settings:
    """Return the settings a first run starts with."""
    return Settings(
        save_mode=SaveMode.COPY,
        output_dir=documents / OUTPUT_FOLDER_NAME,
        backup_dir=documents / BACKUP_FOLDER_NAME,
        level=Level.MEDIUM,
        size_limit_mb=None,
        remove_hidden_info=True,
    )


def load_settings(path: Path, documents: Path) -> Settings:
    """Read saved settings, using the default for anything missing or invalid."""
    defaults = default_settings(documents)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defaults
    except (OSError, ValueError):
        logger.warning("Settings file %s is unreadable; using defaults", path)
        return defaults
    if not isinstance(raw, dict):
        logger.warning("Settings file %s holds no settings; using defaults", path)
        return defaults

    hidden = raw.get("remove_hidden_info")
    return Settings(
        save_mode=_enum_or(raw.get("save_mode"), SaveMode, defaults.save_mode),
        output_dir=_path_or(raw.get("output_dir"), defaults.output_dir),
        backup_dir=_path_or(raw.get("backup_dir"), defaults.backup_dir),
        level=_enum_or(raw.get("level"), Level, defaults.level),
        size_limit_mb=_limit_or_none(raw.get("size_limit_mb")),
        remove_hidden_info=(
            hidden if isinstance(hidden, bool) else defaults.remove_hidden_info
        ),
    )


def save_settings(settings: Settings, path: Path) -> None:
    """Write settings as JSON without ever leaving a half-written file."""
    data = {
        "save_mode": settings.save_mode.value,
        "output_dir": str(settings.output_dir),
        "backup_dir": str(settings.backup_dir),
        "level": settings.level.value,
        "size_limit_mb": settings.size_limit_mb,
        "remove_hidden_info": settings.remove_hidden_info,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def app_dir() -> Path:
    """Return the folder that holds the exe, or the repo root when not frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def data_dir(app: Path, appdata: Path) -> Path:
    """Return where settings and logs live: beside the exe when portable."""
    if (app / PORTABLE_MARKER).is_file():
        return app
    return appdata / APP_NAME


def documents_dir() -> Path:
    """Return the user's Documents folder, following OneDrive redirection."""
    try:
        return _known_folder(FOLDERID_DOCUMENTS)
    except OSError:
        logger.warning("Windows did not report a Documents folder", exc_info=True)
        return Path.home() / "Documents"


def new_log_path(logs: Path, now: datetime) -> Path:
    """Make room for one more log file and return its path."""
    logs.mkdir(parents=True, exist_ok=True)
    # The timestamped names sort in time order.
    old = sorted(logs.glob("*.log"), key=lambda log: log.name)
    for stale in old[: max(0, len(old) - (KEEP_LOGS - 1))]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("Could not delete old log %s", stale)
    return logs / f"{now:%Y-%m-%d %H%M%S}.log"


def _enum_or[E: Enum](value: object, kind: type[E], default: E) -> E:
    try:
        return kind(value)
    except (ValueError, TypeError):
        return default


def _path_or(value: object, default: Path) -> Path:
    if isinstance(value, str) and value.strip():
        return Path(value)
    return default


def _limit_or_none(value: object) -> float | None:
    # bool is an int, so a stray true must not become a 1 MB limit.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_ulong),
        ("data2", ctypes.c_ushort),
        ("data3", ctypes.c_ushort),
        ("data4", ctypes.c_ubyte * 8),
    ]


def _known_folder(folder_id: str) -> Path:
    guid = _Guid.from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    buffer = ctypes.c_wchar_p()
    try:
        # oledll raises OSError when the call returns a failed HRESULT.
        ctypes.oledll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(buffer)
        )
        return Path(buffer.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(buffer)
