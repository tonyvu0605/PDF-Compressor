import os
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import BASE, can_symlink, make_junction

from pdf_compressor.core.scan import MAX_PATH, scan_inputs
from pdf_compressor.core.settings import Level, SaveMode, Settings

LINK = "This is a link to another place. Please add the real folder or file."


def write(path: Path, size: int = 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def settings_for(tmp_path: Path, mode: SaveMode = SaveMode.COPY) -> Settings:
    return Settings(
        mode, tmp_path / "Output", tmp_path / "Backups", Level.MEDIUM, None, True
    )


def layouts(result_jobs: list) -> list[Path]:
    return [job.layout for job in result_jobs]


def test_folder_keeps_structure(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")
    write(case / "B.pdf")
    write(case / "Sub" / "b.pdf")
    single = write(tmp_path / BASE / "single.pdf")
    settings = settings_for(tmp_path)

    result = scan_inputs([case, single], settings)

    assert layouts(result.jobs) == [
        Path("Smith Case/a.pdf"),
        Path("Smith Case/B.pdf"),
        Path("Smith Case/Sub/b.pdf"),
        Path("single.pdf"),
    ]
    assert result.jobs[0].source == case / "a.pdf"
    assert result.jobs[0].dest == tmp_path / "Output" / "Smith Case" / "a.pdf"
    assert result.left_out == []


def test_dest_is_source_in_replace_modes(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")

    result = scan_inputs([case], settings_for(tmp_path, SaveMode.REPLACE))

    assert result.jobs[0].dest == case / "a.pdf"


def test_suffix_any_case(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "B.PDF")
    write(case / "notes.txt")
    write(case / "~1a2b3c4d.pdfc-tmp")

    result = scan_inputs([case], settings_for(tmp_path))

    assert layouts(result.jobs) == [Path("Smith Case/B.PDF")]


def test_skips_output_and_backup_folders(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")
    settings = Settings(
        SaveMode.COPY, case / "Output", case / "Backups", Level.MEDIUM, None, True
    )
    write(settings.output_dir / "a.pdf")
    write(settings.backup_dir / "2026-10-29 1405" / "a.pdf")

    result = scan_inputs([case], settings)

    assert layouts(result.jobs) == [Path("Smith Case/a.pdf")]


def test_skips_blocked_folders_below_input(tmp_path: Path) -> None:
    write(tmp_path / "Home" / "Documents" / "in home.pdf")
    write(tmp_path / "System" / "APPDATA" / "Roaming" / "in appdata.pdf")
    write(tmp_path / "Cases" / "c.pdf")

    result = scan_inputs([tmp_path], settings_for(tmp_path))

    assert [job.source for job in result.jobs] == [tmp_path / "Cases" / "c.pdf"]


def test_does_not_follow_links(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")
    elsewhere = tmp_path / "Elsewhere"
    write(elsewhere / "outside.pdf")
    make_junction(case / "Linked", elsewhere)
    link_input = tmp_path / BASE / "Link Input"
    make_junction(link_input, elsewhere)

    result = scan_inputs([case, link_input], settings_for(tmp_path))

    assert layouts(result.jobs) == [Path("Smith Case/a.pdf")]
    assert result.left_out == [(link_input, LINK)]


def test_does_not_follow_symlinks(tmp_path: Path) -> None:
    if not can_symlink(tmp_path):
        pytest.skip("this account can't create symlinks")
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")
    elsewhere = tmp_path / "Elsewhere"
    outside = write(elsewhere / "outside.pdf")
    (case / "Linked").symlink_to(elsewhere, target_is_directory=True)
    (case / "linked.pdf").symlink_to(outside)
    file_link = tmp_path / BASE / "file link.pdf"
    file_link.symlink_to(outside)

    result = scan_inputs([case, file_link], settings_for(tmp_path))

    assert layouts(result.jobs) == [Path("Smith Case/a.pdf")]
    assert result.left_out == [(file_link, LINK)]


def test_name_clash_next_free_number(tmp_path: Path) -> None:
    first = write(tmp_path / BASE / "A" / "report.pdf")
    second = write(tmp_path / BASE / "C" / "report (2).pdf")
    third = write(tmp_path / BASE / "B" / "Report.PDF")

    result = scan_inputs([first, second, third], settings_for(tmp_path))

    assert layouts(result.jobs) == [
        Path("report.pdf"),
        Path("report (2).pdf"),
        Path("Report (3).PDF"),
    ]


def test_same_file_twice_is_one_job(tmp_path: Path) -> None:
    folder = tmp_path / BASE / "Smith Case"
    pdf = write(folder / "a.pdf")

    result = scan_inputs([folder, pdf], settings_for(tmp_path))

    assert layouts(result.jobs) == [Path("Smith Case/a.pdf")]


def test_output_copy_left_out(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    output_file = write(settings.output_dir / "Smith Case" / "a.pdf")
    output_folder = settings.output_dir / "Smith Case"
    backup_file = write(settings.backup_dir / "2026-10-29 1405" / "a.pdf")

    result = scan_inputs([output_file, output_folder, backup_file], settings)

    in_output = f"This is inside your output folder ({settings.output_dir})."
    in_backup = f"This is inside your backup folder ({settings.backup_dir})."
    assert result.jobs == []
    assert result.left_out == [
        (output_file, in_output),
        (output_folder, in_output),
        (backup_file, in_backup),
    ]


def test_unreadable_folder_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")
    write(case / "Sealed" / "s.pdf")
    write(case / "Zed" / "z.pdf")
    sealed = case / "Sealed"
    real_scandir = os.scandir

    def scandir_denying_sealed(path: str = ".") -> object:
        if Path(path) == sealed:
            raise PermissionError(13, "Access is denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir_denying_sealed)

    result = scan_inputs([case], settings_for(tmp_path))

    assert layouts(result.jobs) == [
        Path("Smith Case/a.pdf"),
        Path("Smith Case/Zed/z.pdf"),
    ]
    assert result.left_out == [
        (sealed, "Couldn't open this folder. Its path may be too long.")
    ]


def test_long_paths_left_out(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf")
    # A folder Windows can still list, holding a file whose own path is 271
    # characters, which only the \\?\ prefix can create.
    deep = case / ("d" * (240 - len(str(case)) - 1))
    deep.mkdir(parents=True)
    long_file = deep / ("f" * 26 + ".pdf")
    assert len(str(long_file)) >= MAX_PATH
    Path("\\\\?\\" + str(long_file)).write_bytes(b"x" * 100)

    result = scan_inputs([case], settings_for(tmp_path))

    assert layouts(result.jobs) == [Path("Smith Case/a.pdf")]
    assert result.left_out == [(long_file, "This file's path is too long for Windows.")]

    long_output = replace(settings_for(tmp_path), output_dir=tmp_path / ("o" * 200))
    long_backup = replace(
        settings_for(tmp_path, SaveMode.BACKUP), backup_dir=tmp_path / ("b" * 180)
    )
    too_long = "The output path would be too long for Windows."
    for settings in (long_output, long_backup):
        result = scan_inputs([case / "a.pdf"], settings)
        assert result.jobs == []
        assert result.left_out == [(case / "a.pdf", too_long)]


def test_bad_inputs_left_out(tmp_path: Path) -> None:
    blocked = Path(os.environ["WINDIR"]) / "System32"
    missing = tmp_path / BASE / "missing.pdf"
    not_pdf = write(tmp_path / BASE / "notes.docx")

    result = scan_inputs([blocked, missing, not_pdf], settings_for(tmp_path))

    refused = (
        f"For safety, PDF Compressor can't work on {blocked}. Please choose a"
        " more specific folder, like one client's folder."
    )
    assert result.jobs == []
    assert result.left_out == [
        (blocked, refused),
        (missing, "Not found."),
        (not_pdf, "Not a PDF."),
    ]


def test_counts(tmp_path: Path) -> None:
    case = tmp_path / BASE / "Smith Case"
    write(case / "a.pdf", 100)
    write(case / "Sub" / "b.pdf", 200)
    single = write(tmp_path / BASE / "c.pdf", 300)
    settings = settings_for(tmp_path)
    write(settings.output_dir / "Smith Case" / "a.pdf")

    copy = scan_inputs([case, single], settings)
    backup = scan_inputs([case, single], replace(settings, save_mode=SaveMode.BACKUP))

    assert len(copy.jobs) == 3
    assert copy.folder_count == 3
    assert copy.existing_count == 1
    assert copy.total_bytes == 600
    assert backup.existing_count == 3
