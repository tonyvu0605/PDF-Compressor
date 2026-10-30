from pathlib import Path

import pytest

# An n-tilde, a curly apostrophe and a letter outside cp1252, so every path
# operation is exercised with names a client folder can really have.
BASE = "Client Files ñ O’Brien ễ"

SYSTEM_VARS = (
    "WINDIR",
    "ProgramFiles",
    "ProgramFiles(x86)",
    "ProgramData",
    "APPDATA",
    "LOCALAPPDATA",
)


@pytest.fixture(autouse=True)
def isolated_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the home folder and the system folders into tmp_path."""
    # tmp_path normally sits inside the real %LOCALAPPDATA%, which is blocked.
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Home"))
    for var in SYSTEM_VARS:
        monkeypatch.setenv(var, str(tmp_path / "System" / var))
