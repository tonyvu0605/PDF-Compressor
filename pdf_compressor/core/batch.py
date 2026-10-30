"""Run the jobs of one scan in the chosen save mode."""

import logging
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pdf_compressor.core.compress import (
    MB,
    SKIP_IN_USE,
    FileResult,
    Status,
    compress_file,
    format_mb,
)
from pdf_compressor.core.scan import Job, ScanResult
from pdf_compressor.core.settings import Level, SaveMode, Settings

logger = logging.getLogger(__name__)

Compress = Callable[[Path, Path, Level, bool, float | None], FileResult]

TEMP_SUFFIX = ".pdfc-tmp"
JOURNAL_NAME = "temp-files.txt"

READ_ONLY = "Skipped: the file is read-only"
BACKUP_FAILED = "Not changed: the backup copy failed"
SOMETHING_WENT_WRONG = "Not changed: something went wrong with this file"


@dataclass
class BatchResult:
    """Every file's result, how many files the run had, and whether it stopped early."""

    results: list[FileResult]
    total: int
    cancelled: bool


def temp_path_for(dest: Path) -> Path:
    """Return a fresh temp file path in the destination's folder."""
    return dest.parent / f"~{uuid.uuid4().hex[:8]}{TEMP_SUFFIX}"


def backup_run_dir(backup_dir: Path, now: datetime) -> Path:
    """Create and return a backup folder for this run that no other run uses."""
    stamp = f"{now:%Y-%m-%d %H%M}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        folder = backup_dir / (stamp if number == 1 else f"{stamp} ({number})")
        try:
            # mkdir either claims the folder or fails, so a second window
            # starting a run in the same minute moves on to the next name.
            folder.mkdir()
        except FileExistsError:
            number += 1
        else:
            return folder


def run_batch(
    scan: ScanResult,
    settings: Settings,
    cancel: threading.Event,
    on_progress: Callable[[int, int, Path], None],
    data_dir: Path,
    now: datetime,
    compress: Compress | None = None,
) -> BatchResult:
    """Compress every job, stopping after the current file once cancel is set.

    Args:
        compress: Stands in for compress_file, so the window's worker can run
            it in a separate process.
    """
    compress = compress or compress_file
    data_dir.mkdir(parents=True, exist_ok=True)
    journal = data_dir / JOURNAL_NAME
    total = len(scan.jobs)
    logger.info(
        "Run started: %s mode, %s level, limit %s MB, %d files",
        settings.save_mode.value,
        settings.level.value,
        settings.size_limit_mb,
        total,
    )
    backups = None
    if settings.save_mode is SaveMode.BACKUP:
        backups = backup_run_dir(settings.backup_dir, now)

    results: list[FileResult] = []
    cancelled = False
    try:
        for number, job in enumerate(scan.jobs, start=1):
            if cancel.is_set():
                cancelled = True
                break
            on_progress(number, total, job.source)
            result = _run_job(job, settings, journal, backups, compress)
            logger.info(
                "%s: %s (%s bytes to %s)",
                job.source,
                result.message,
                result.before,
                result.after,
            )
            results.append(result)
    finally:
        remove_leftover_temps(data_dir)
        if backups is not None:
            _remove_if_empty(backups)

    batch = BatchResult(results=results, total=total, cancelled=cancelled)
    logger.info("Run finished: %s", summary_text(batch))
    return batch


def remove_leftover_temps(data_dir: Path) -> int:
    """Delete temp files that a crashed or finished run left behind."""
    journal = data_dir / JOURNAL_NAME
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return 0
    except (OSError, ValueError):
        # Cleanup is best effort: it must never stop the app or end a run.
        logger.warning(
            "Could not read the temp file journal %s", journal, exc_info=True
        )
        return 0
    removed = 0
    kept: list[str] = []
    for line in lines:
        # Only our own temp files are ever deleted, whatever the journal says.
        if not line.endswith(TEMP_SUFFIX):
            continue
        path = Path(line)
        try:
            if path.exists():
                path.unlink()
                removed += 1
        except OSError:
            # Another window may still be writing it.
            logger.warning(
                "Could not delete leftover temp file %s", path, exc_info=True
            )
            kept.append(line)
    _write_journal(journal, kept)
    return removed


def summary_text(batch: BatchResult) -> str:
    """Return the one-line summary shown above the results table."""
    done = len(batch.results)
    skipped = sum(
        result.status in (Status.SKIPPED, Status.FAILED) for result in batch.results
    )
    sized = [result for result in batch.results if result.after is not None]
    if batch.cancelled:
        head = f"Stopped early. {done} of {_files(batch.total)}"
    else:
        head = _files(done)
    if sized:
        before = format_mb(sum(result.before for result in sized))
        after = format_mb(sum(result.after or 0 for result in sized))
        text = f"{head}: {before} down to {after}."
    else:
        text = f"{head}: none could be compressed."
    if skipped:
        text += f" {skipped} skipped."
    return text


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def _run_job(
    job: Job,
    settings: Settings,
    journal: Path,
    backups: Path | None,
    compress: Compress,
) -> FileResult:
    replacing = settings.save_mode is not SaveMode.COPY
    if replacing and not os.access(job.source, os.W_OK):
        return _not_done(job, settings, Status.SKIPPED, READ_ONLY)
    tmp = temp_path_for(job.dest)
    try:
        with journal.open("a", encoding="utf-8") as file:
            file.write(f"{tmp}\n")
        result = compress(
            job.source,
            tmp,
            settings.level,
            settings.remove_hidden_info,
            settings.size_limit_mb,
        )
        return _place(result, job, tmp, settings, backups)
    except Exception:
        # One file must never stop the batch, whatever went wrong with it.
        logger.exception("Unexpected error with %s", job.source)
        return _not_done(job, settings, Status.FAILED, SOMETHING_WENT_WRONG)
    finally:
        _discard_temp(tmp, journal)


def _place(
    result: FileResult,
    job: Job,
    tmp: Path,
    settings: Settings,
    backups: Path | None,
) -> FileResult:
    if result.status is Status.COMPRESSED:
        if backups is not None:
            backup = backups / job.layout
            if backup.exists():
                # A backup may be the only copy of an original: never replace it.
                logger.error(
                    "Backup %s already exists; %s not changed", backup, job.source
                )
                return _not_done(job, settings, Status.FAILED, BACKUP_FAILED)
            try:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(job.source, backup)
            except OSError:
                logger.exception("Backup copy of %s failed", job.source)
                return _not_done(job, settings, Status.FAILED, BACKUP_FAILED)
        return _move_into_place(result, job, tmp, settings)
    if result.status is Status.ALREADY_SMALL and settings.save_mode is SaveMode.COPY:
        # copyfile, not copy2: copy2 would carry a read-only attribute over.
        job.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(job.source, tmp)
        return _move_into_place(result, job, tmp, settings)
    return result


def _move_into_place(
    result: FileResult, job: Job, tmp: Path, settings: Settings
) -> FileResult:
    try:
        os.replace(tmp, job.dest)
    except PermissionError:
        # Windows refuses the same way for read-only and in-use files.
        read_only = job.dest.exists() and not os.access(job.dest, os.W_OK)
        message = READ_ONLY if read_only else SKIP_IN_USE
        return _not_done(job, settings, Status.SKIPPED, message)
    return result


def _not_done(job: Job, settings: Settings, status: Status, message: str) -> FileResult:
    limit = settings.size_limit_mb
    over = limit is not None and job.size > limit * MB
    return FileResult(job.source, job.size, None, status, message, over)


def _discard_temp(tmp: Path, journal: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not delete temp file %s; it stays in the journal", tmp)
        return
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        # A stale line only costs a lookup at the next cleanup.
        logger.warning(
            "Could not read the temp file journal %s", journal, exc_info=True
        )
        return
    _write_journal(journal, [line for line in lines if line != str(tmp)])


def _write_journal(journal: Path, lines: list[str]) -> None:
    try:
        journal.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    except OSError:
        logger.warning(
            "Could not update the temp file journal %s", journal, exc_info=True
        )


def _remove_if_empty(folder: Path) -> None:
    try:
        if not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        logger.warning("Could not tidy the backup folder %s", folder, exc_info=True)
