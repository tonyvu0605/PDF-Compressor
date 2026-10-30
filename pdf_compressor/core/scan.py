"""Expand the user's files and folders into a list of jobs."""

import os
from dataclasses import dataclass
from pathlib import Path

from pdf_compressor.core.safety import blocked_reason
from pdf_compressor.core.settings import SaveMode, Settings

# Windows path limits while long paths are off, which is the default.
MAX_PATH = 260
MAX_DIR = 248
# Room for a separator plus the batch runner's temp file name.
TEMP_NAME_ROOM = 20
# The longest backup run folder name the batch runner can pick.
LONGEST_BACKUP_RUN = "2026-10-29 1405 (99)"

LINK = "This is a link to another place. Please add the real folder or file."
NOT_FOUND = "Not found."
NOT_PDF = "Not a PDF."
UNREADABLE_FOLDER = "Couldn't open this folder. Its path may be too long."
LONG_SOURCE = "This file's path is too long for Windows."
LONG_OUTPUT = "The output path would be too long for Windows."
IN_OUTPUT = "This is inside your output folder ({folder})."
IN_BACKUP = "This is inside your backup folder ({folder})."


@dataclass(frozen=True)
class Job:
    """One PDF to compress and where its result goes."""

    source: Path
    layout: Path
    dest: Path
    size: int


@dataclass
class ScanResult:
    """The jobs found, the inputs left out, and the totals shown before a run."""

    jobs: list[Job]
    left_out: list[tuple[Path, str]]
    total_bytes: int
    folder_count: int
    existing_count: int


def scan_inputs(inputs: list[Path], settings: Settings) -> ScanResult:
    """Turn files and folders into jobs, leaving out anything unsafe or unusable."""
    output = settings.output_dir.resolve()
    backup = settings.backup_dir.resolve()
    found: list[tuple[Path, Path]] = []
    left_out: list[tuple[Path, str]] = []

    for item in inputs:
        path = Path(os.path.abspath(item))
        problem = _input_problem(path, settings, output, backup)
        if problem:
            left_out.append((path, problem))
        elif path.is_dir():
            _walk(path, output, backup, found, left_out)
        else:
            found.append((path, Path(path.name)))

    jobs = _make_jobs(found, settings, left_out)
    if settings.save_mode is SaveMode.COPY:
        existing = sum(1 for job in jobs if job.dest.exists())
    else:
        existing = len(jobs)
    return ScanResult(
        jobs=jobs,
        left_out=left_out,
        total_bytes=sum(job.size for job in jobs),
        folder_count=len({os.path.normcase(str(job.source.parent)) for job in jobs}),
        existing_count=existing,
    )


def _input_problem(
    path: Path, settings: Settings, output: Path, backup: Path
) -> str | None:
    if path.is_symlink() or path.is_junction():
        return LINK
    blocked = blocked_reason(path)
    if blocked:
        return blocked
    if len(str(path)) >= MAX_PATH:
        return LONG_SOURCE
    if not path.exists():
        return NOT_FOUND
    resolved = path.resolve()
    if _inside(resolved, output):
        return IN_OUTPUT.format(folder=settings.output_dir)
    if _inside(resolved, backup):
        return IN_BACKUP.format(folder=settings.backup_dir)
    if path.is_file() and path.suffix.lower() != ".pdf":
        return NOT_PDF
    return None


def _walk(
    top: Path,
    output: Path,
    backup: Path,
    found: list[tuple[Path, Path]],
    left_out: list[tuple[Path, str]],
) -> None:
    def on_error(error: OSError) -> None:
        left_out.append((Path(error.filename), UNREADABLE_FOLDER))

    # Path.walk is avoided because its junction handling differs between
    # Python versions; plain os.walk follows junctions, so prune them here.
    for dirpath, dirnames, filenames in os.walk(top, onerror=on_error):
        here = Path(dirpath)
        dirnames[:] = sorted(
            (name for name in dirnames if _may_enter(here / name, output, backup)),
            key=str.casefold,
        )
        for name in sorted(filenames, key=str.casefold):
            file = here / name
            if file.suffix.lower() == ".pdf" and not file.is_symlink():
                found.append((file, Path(top.name) / file.relative_to(top)))


def _may_enter(folder: Path, output: Path, backup: Path) -> bool:
    if folder.is_symlink() or folder.is_junction():
        return False
    resolved = folder.resolve()
    if _inside(resolved, output) or _inside(resolved, backup):
        return False
    return blocked_reason(folder) is None


def _make_jobs(
    found: list[tuple[Path, Path]],
    settings: Settings,
    left_out: list[tuple[Path, str]],
) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    taken: set[str] = set()
    for source, wanted in found:
        # Windows refuses to stat a path this long, so check before stat().
        if len(str(source)) >= MAX_PATH:
            left_out.append((source, LONG_SOURCE))
            continue
        key = os.path.normcase(str(source.resolve()))
        if key in seen:
            continue
        seen.add(key)
        try:
            size = source.stat().st_size
        except OSError:
            left_out.append((source, LONG_SOURCE))
            continue
        layout = _free_layout(wanted, taken)
        dest = settings.output_dir / layout
        if settings.save_mode is not SaveMode.COPY:
            dest = source
        if _too_long(dest, layout, settings):
            left_out.append((source, LONG_OUTPUT))
            continue
        taken.add(str(layout).casefold())
        jobs.append(Job(source=source, layout=layout, dest=dest, size=size))
    return jobs


def _free_layout(layout: Path, taken: set[str]) -> Path:
    if str(layout).casefold() not in taken:
        return layout
    number = 2
    while True:
        candidate = layout.with_name(f"{layout.stem} ({number}){layout.suffix}")
        if str(candidate).casefold() not in taken:
            return candidate
        number += 1


def _too_long(dest: Path, layout: Path, settings: Settings) -> bool:
    if len(str(dest)) >= MAX_PATH:
        return True
    if len(str(dest.parent)) + TEMP_NAME_ROOM >= MAX_PATH:
        return True
    if settings.save_mode is SaveMode.BACKUP:
        backup_path = settings.backup_dir / LONGEST_BACKUP_RUN / layout
        if len(str(backup_path)) >= MAX_PATH:
            return True
        if len(str(backup_path.parent)) >= MAX_DIR:
            return True
    return False


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents
