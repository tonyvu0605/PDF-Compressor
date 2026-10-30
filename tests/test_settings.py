import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from pdf_compressor.core.settings import (
    Level,
    SaveMode,
    Settings,
    app_dir,
    data_dir,
    default_settings,
    load_settings,
    new_log_path,
    save_settings,
)


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    return tmp_path / "Documents"


def test_missing_file_gives_defaults(tmp_path: Path, docs: Path) -> None:
    assert load_settings(tmp_path / "settings.json", docs) == Settings(
        SaveMode.COPY,
        docs / "Compressed PDFs",
        docs / "PDF Backups",
        Level.MEDIUM,
        None,
        True,
    )


def test_round_trip(tmp_path: Path, docs: Path) -> None:
    path = tmp_path / "settings.json"
    output = tmp_path / "Out \u00f1"
    settings = Settings(
        SaveMode.BACKUP, output, tmp_path / "Backups", Level.HIGH, 9.5, False
    )

    save_settings(settings, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["save_mode"] == "backup"
    assert raw["level"] == "high"
    assert raw["output_dir"] == str(output)
    assert load_settings(path, docs) == settings


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe{", b"[]"])
def test_corrupt_file_gives_defaults(
    tmp_path: Path, docs: Path, content: bytes
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(content)

    assert load_settings(path, docs) == default_settings(docs)


def test_bad_field_falls_back(tmp_path: Path, docs: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "save_mode": "backup",
                "level": "extreme",
                "size_limit_mb": 0,
                "output_dir": "",
                "remove_hidden_info": "yes",
            }
        ),
        encoding="utf-8",
    )

    assert load_settings(path, docs) == Settings(
        SaveMode.BACKUP,
        docs / "Compressed PDFs",
        docs / "PDF Backups",
        Level.MEDIUM,
        None,
        True,
    )


def test_data_dir(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    appdata = tmp_path / "AppData"

    assert data_dir(app, appdata) == appdata / "PDF Compressor"

    (app / "portable.txt").touch()
    assert data_dir(app, appdata) == app


def test_app_dir_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "PDF Compressor.exe"))

    assert app_dir() == tmp_path


def test_new_log_path(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    now = datetime(2026, 10, 29, 14, 5)

    assert new_log_path(logs, now) == logs / "2026-10-29 140500.log"
    assert logs.is_dir()

    for day in range(1, 26):
        (logs / f"2026-10-{day:02d} 000000.log").touch()
    new_log_path(logs, now)

    remaining = sorted(path.name for path in logs.glob("*.log"))
    assert remaining == [f"2026-10-{day:02d} 000000.log" for day in range(7, 26)]
