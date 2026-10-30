import _winapi
from pathlib import Path

import pytest

# An n-tilde, a curly apostrophe and a letter outside cp1252, so every path
# operation is exercised with names a client folder can really have.
BASE = "Client Files \u00f1 O\u2019Brien \u1ec5"

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


def make_junction(link: Path, target: Path) -> None:
    """Create a directory junction, which needs no admin rights."""
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def can_symlink(folder: Path) -> bool:
    """Return True if this account may create symlinks."""
    target = folder / "symlink-probe-target.txt"
    link = folder / "symlink-probe.txt"
    target.write_text("probe", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError:
        return False
    else:
        link.unlink()
        return True
    finally:
        target.unlink()
