import os
import shutil
import stat
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path

import pytest
from conftest import BASE, hold_open, lock_bytes

from pdf_compressor.core import batch
from pdf_compressor.core.batch import (
    BatchResult,
    backup_run_dir,
    remove_leftover_temps,
    run_batch,
    summary_text,
    temp_path_for,
)
from pdf_compressor.core.compress import FileResult, Status, compress_file
from pdf_compressor.core.scan import TEMP_NAME_ROOM, scan_inputs
from pdf_compressor.core.settings import Level, SaveMode, Settings

NOW = datetime(2026, 10, 29, 14, 5)
IN_USE = "Skipped: open in another program"


@pytest.fixture
def case(tmp_path: Path, scan_pdf: Path, text_pdf: Path) -> Path:
    folder = tmp_path / BASE / "Smith Case"
    folder.mkdir(parents=True)
    shutil.copyfile(scan_pdf, folder / "a scan.pdf")
    shutil.copyfile(text_pdf, folder / "b text.pdf")
    shutil.copyfile(scan_pdf, folder / "c scan.pdf")
    return folder


def settings_for(
    tmp_path: Path, mode: SaveMode, limit_mb: float | None = None
) -> Settings:
    return Settings(
        mode, tmp_path / "Output", tmp_path / "Backups", Level.MEDIUM, limit_mb, True
    )


def run(
    case: Path,
    settings: Settings,
    data: Path,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, int, Path], None] | None = None,
) -> BatchResult:
    return run_batch(
        scan_inputs([case], settings),
        settings,
        cancel or threading.Event(),
        on_progress or (lambda number, total, source: None),
        data,
        NOW,
    )


def contents(folder: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in folder.iterdir()}


def temp_files(tmp_path: Path) -> list[Path]:
    return list(tmp_path.rglob("*.pdfc-tmp"))


def test_copy_mode(case: Path, tmp_path: Path) -> None:
    originals = contents(case)

    result = run(case, settings_for(tmp_path, SaveMode.COPY), tmp_path / "Data")

    assert [row.status for row in result.results] == [
        Status.COMPRESSED,
        Status.ALREADY_SMALL,
        Status.COMPRESSED,
    ]
    output = tmp_path / "Output" / "Smith Case"
    assert len((output / "a scan.pdf").read_bytes()) < len(originals["a scan.pdf"])
    assert len((output / "c scan.pdf").read_bytes()) < len(originals["c scan.pdf"])
    assert (output / "b text.pdf").read_bytes() == originals["b text.pdf"]
    assert contents(case) == originals
    assert temp_files(tmp_path) == []


def test_backup_mode(case: Path, tmp_path: Path) -> None:
    originals = contents(case)

    run(case, settings_for(tmp_path, SaveMode.BACKUP), tmp_path / "Data")

    backup = tmp_path / "Backups" / "2026-10-29 1405" / "Smith Case"
    assert contents(backup) == {
        "a scan.pdf": originals["a scan.pdf"],
        "c scan.pdf": originals["c scan.pdf"],
    }
    assert not (tmp_path / "Backups" / "2026-10-29 1405 (2)").exists()
    assert len((case / "a scan.pdf").read_bytes()) < len(originals["a scan.pdf"])
    assert (case / "b text.pdf").read_bytes() == originals["b text.pdf"]
    assert temp_files(tmp_path) == []


def test_replace_mode(case: Path, tmp_path: Path) -> None:
    originals = contents(case)

    run(case, settings_for(tmp_path, SaveMode.REPLACE), tmp_path / "Data")

    assert len((case / "a scan.pdf").read_bytes()) < len(originals["a scan.pdf"])
    assert len((case / "c scan.pdf").read_bytes()) < len(originals["c scan.pdf"])
    assert not (tmp_path / "Backups").exists()
    assert temp_files(tmp_path) == []


def test_backup_failure_keeps_original(
    case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = (case / "a scan.pdf").read_bytes()

    def failing_copy(*args: object, **kwargs: object) -> None:
        raise OSError("simulated full disk")

    monkeypatch.setattr(batch.shutil, "copy2", failing_copy)

    result = run(case, settings_for(tmp_path, SaveMode.BACKUP), tmp_path / "Data")

    first = result.results[0]
    assert first.status is Status.FAILED
    assert first.message == "Not changed: the backup copy failed"
    assert first.after is None
    assert (case / "a scan.pdf").read_bytes() == original
    assert temp_files(tmp_path) == []


def test_backup_run_dir_is_fresh(tmp_path: Path) -> None:
    backups = tmp_path / "Backups"

    # Each call claims its folder, so two runs in one minute never share one.
    first = backup_run_dir(backups, NOW)
    second = backup_run_dir(backups, NOW)

    assert first == backups / "2026-10-29 1405"
    assert second == backups / "2026-10-29 1405 (2)"
    assert first.is_dir()
    assert second.is_dir()


def test_existing_backup_is_never_overwritten(
    case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = (case / "a scan.pdf").read_bytes()
    taken = tmp_path / "Backups" / "taken"
    earlier = taken / "Smith Case" / "a scan.pdf"
    earlier.parent.mkdir(parents=True)
    earlier.write_bytes(b"an earlier run's backup")
    monkeypatch.setattr(batch, "backup_run_dir", lambda folder, now: taken)

    result = run(case, settings_for(tmp_path, SaveMode.BACKUP), tmp_path / "Data")

    first = result.results[0]
    assert first.status is Status.FAILED
    assert first.message == "Not changed: the backup copy failed"
    assert earlier.read_bytes() == b"an earlier run's backup"
    assert (case / "a scan.pdf").read_bytes() == original


def test_unused_backup_folder_is_removed(tmp_path: Path, text_pdf: Path) -> None:
    folder = tmp_path / BASE / "Smith Case"
    folder.mkdir(parents=True)
    shutil.copyfile(text_pdf, folder / "b text.pdf")

    run(folder, settings_for(tmp_path, SaveMode.BACKUP), tmp_path / "Data")

    assert not (tmp_path / "Backups" / "2026-10-29 1405").exists()


def test_journal_trouble_does_not_stop_the_run(case: Path, tmp_path: Path) -> None:
    data = tmp_path / "Data"
    data.mkdir()
    journal = data / "temp-files.txt"
    journal.write_text("held by antivirus\n", encoding="utf-8")

    with lock_bytes(journal):
        result = run(case, settings_for(tmp_path, SaveMode.COPY), data)

    assert [row.status for row in result.results] == [
        Status.COMPRESSED,
        Status.ALREADY_SMALL,
        Status.COMPRESSED,
    ]


def test_corrupt_journal_is_ignored(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    data.mkdir()
    (data / "temp-files.txt").write_bytes(bytes([0xFF, 0xFE, 0x00, 0x7B]))

    assert remove_leftover_temps(data) == 0


def test_cancel_after_current_file(case: Path, tmp_path: Path) -> None:
    cancel = threading.Event()
    reported: list[tuple[int, int]] = []
    journal = tmp_path / "Data" / "temp-files.txt"
    journal_before_file_2: list[str] = []

    def on_progress(number: int, total: int, source: Path) -> None:
        reported.append((number, total))
        if number == 2:
            # File 1 is finished, so its temp file has left the journal.
            journal_before_file_2.append(journal.read_text(encoding="utf-8"))
            cancel.set()

    result = run(
        case,
        settings_for(tmp_path, SaveMode.COPY),
        tmp_path / "Data",
        cancel,
        on_progress,
    )

    assert reported == [(1, 3), (2, 3)]
    assert journal_before_file_2 == [""]
    assert len(result.results) == 2
    assert result.total == 3
    assert result.cancelled is True
    assert temp_files(tmp_path) == []
    assert journal.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("mode", "lock"),
    [(SaveMode.REPLACE, hold_open), (SaveMode.COPY, lock_bytes)],
    ids=["replace-held-open", "copy-locked"],
)
def test_locked_file_reported(
    case: Path,
    tmp_path: Path,
    mode: SaveMode,
    lock: Callable[[Path], AbstractContextManager[object]],
) -> None:
    target = case / "a scan.pdf"
    original = target.read_bytes()

    with lock(target):
        result = run(case, settings_for(tmp_path, mode), tmp_path / "Data")

    first = result.results[0]
    assert first.status is Status.SKIPPED
    assert first.message == IN_USE
    assert target.read_bytes() == original
    assert result.results[2].status is Status.COMPRESSED
    assert temp_files(tmp_path) == []


def test_read_only_original_skipped(case: Path, tmp_path: Path) -> None:
    target = case / "a scan.pdf"
    original = target.read_bytes()
    os.chmod(target, stat.S_IREAD)
    try:
        settings = settings_for(tmp_path, SaveMode.REPLACE, limit_mb=0.000001)
        result = run(case, settings, tmp_path / "Data")
    finally:
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)

    first = result.results[0]
    assert first.status is Status.SKIPPED
    assert first.message == "Skipped: the file is read-only"
    assert first.over_limit is True
    assert target.read_bytes() == original


def test_unexpected_error_continues(
    case: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_compress = batch.compress_file

    def failing_on_first(source: Path, *args: object) -> FileResult:
        if source.name == "a scan.pdf":
            raise RuntimeError("simulated bug")
        return real_compress(source, *args)

    monkeypatch.setattr(batch, "compress_file", failing_on_first)

    result = run(case, settings_for(tmp_path, SaveMode.COPY), tmp_path / "Data")

    first = result.results[0]
    assert first.status is Status.FAILED
    assert first.message == "Not changed: something went wrong with this file"
    assert result.results[2].status is Status.COMPRESSED
    assert temp_files(tmp_path) == []


def test_leftover_temps_removed(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    data.mkdir()
    work = tmp_path / BASE / "Work"
    work.mkdir(parents=True)
    stale = work / "~11111111.pdfc-tmp"
    held = work / "~22222222.pdfc-tmp"
    other = work / "keep me.pdf"
    for path in (stale, held, other):
        path.write_bytes(b"x")
    journal = data / "temp-files.txt"
    journal.write_text(f"{stale}\n{held}\n{other}\n", encoding="utf-8")

    with hold_open(held):
        removed = remove_leftover_temps(data)

    assert removed == 1
    assert not stale.exists()
    assert held.exists()
    assert other.exists()
    assert journal.read_text(encoding="utf-8").splitlines() == [str(held)]


def test_compress_can_run_in_another_process(case: Path, tmp_path: Path) -> None:
    # The window's worker does this, because PyMuPDF holds the interpreter
    # lock and would otherwise freeze the window.
    settings = settings_for(tmp_path, SaveMode.COPY)
    with ProcessPoolExecutor(max_workers=1) as pool:

        def in_child(
            source: Path,
            tmp: Path,
            level: Level,
            remove_hidden_info: bool,
            size_limit_mb: float | None,
        ) -> FileResult:
            arguments = (source, tmp, level, remove_hidden_info, size_limit_mb)
            return pool.submit(compress_file, *arguments).result()

        result = run_batch(
            scan_inputs([case], settings),
            settings,
            threading.Event(),
            lambda number, total, source: None,
            tmp_path / "Data",
            NOW,
            in_child,
        )

    assert [row.status for row in result.results] == [
        Status.COMPRESSED,
        Status.ALREADY_SMALL,
        Status.COMPRESSED,
    ]
    assert temp_files(tmp_path) == []


def test_temp_name_fits(tmp_path: Path) -> None:
    dest = tmp_path / "report.pdf"

    tmp = temp_path_for(dest)

    assert tmp.parent == dest.parent
    assert tmp.name.endswith(".pdfc-tmp")
    assert len(tmp.name) + 1 <= TEMP_NAME_ROOM


def row(status: Status, before: int, after: int | None) -> FileResult:
    return FileResult(Path("x.pdf"), before, after, status, "message")


def test_summary_text() -> None:
    compressed = row(Status.COMPRESSED, 1_600_000, 100_000)
    small = row(Status.ALREADY_SMALL, 400_000, 400_000)
    skipped = row(Status.SKIPPED, 999, None)
    failed = row(Status.FAILED, 20, None)

    assert summary_text(BatchResult([compressed, small, skipped], 3, False)) == (
        "3 files: 2 MB down to 0.5 MB. 1 skipped."
    )
    assert summary_text(
        BatchResult([row(Status.COMPRESSED, 1_000_000, 200_000)], 1, False)
    ) == ("1 file: 1 MB down to 0.2 MB.")
    assert summary_text(BatchResult([compressed, small], 3, True)) == (
        "Stopped early. 2 of 3 files: 2 MB down to 0.5 MB."
    )
    assert summary_text(BatchResult([skipped, failed], 2, False)) == (
        "2 files: none could be compressed. 2 skipped."
    )
