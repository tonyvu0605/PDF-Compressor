import os
from pathlib import Path

import pytest

from pdf_compressor.core.safety import blocked_reason

SIX_VARS = [
    "WINDIR",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "APPDATA",
    "LOCALAPPDATA",
]


def test_message() -> None:
    assert blocked_reason(Path("C:/")) == (
        "For safety, PDF Compressor can't work on C:\\. Please choose a more"
        " specific folder, like one client's folder."
    )


@pytest.mark.parametrize("root", ["c:\\", "Z:/"])
def test_drive_roots(root: str) -> None:
    assert blocked_reason(Path(root)) is not None


def test_home(tmp_path: Path) -> None:
    home = tmp_path / "Home"
    home.mkdir()

    assert blocked_reason(home) is not None
    assert blocked_reason(home / "Clients") is None


@pytest.mark.parametrize("var", SIX_VARS)
def test_system_folders(var: str) -> None:
    folder = Path(os.environ[var])

    assert blocked_reason(folder) is not None
    assert blocked_reason(folder / "Sub Folder" / "Deeper") is not None
    assert blocked_reason(folder / "Sub Folder" / "file.pdf") is not None
    assert blocked_reason(folder.parent / "Cases") is None


def test_case_and_dots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))

    assert blocked_reason(tmp_path / "WINDOWS" / "Temp") is not None
    assert blocked_reason(tmp_path / "Windows" / ".." / "Cases") is None


def test_unset_or_empty_variable_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    monkeypatch.delenv("ProgramData")
    assert blocked_reason(tmp_path / "Cases") is None

    monkeypatch.setenv("ProgramData", "")
    assert blocked_reason(tmp_path / "Cases") is None
