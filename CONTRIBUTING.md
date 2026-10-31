# Contributing

This guide covers setting up, the project's rules, testing and building a release. Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing how the app behaves; it is the reference for the rules the code follows.

## Setup

You need Windows 10 or 11, 64-bit Python 3.13 and, to build the installer, Inno Setup 6.3 or newer.

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
winget install -e --id JRSoftware.InnoSetup.7 --scope user
```

## Everyday commands

| Task | Command |
|------|---------|
| Run the app | `.venv\Scripts\python -m pdf_compressor` (paths after it are preloaded) |
| Run the tests | `.venv\Scripts\python -m pytest -q` |
| Format, then lint | `.venv\Scripts\ruff format .` then `.venv\Scripts\ruff check --fix .` |
| Build everything | `.\build.ps1` |
| Remake the icon | `.venv\Scripts\python installer\make_icon.py` |

## Project rules

### Structure

- `core/` never imports Qt. The window is a thin layer over `core.batch`.
- Long work runs in the `QThread` workers in `gui/worker.py`. They talk to the window only through signals and never touch widgets.
- `core/` turns a failure with one file into a result with a plain-English message, and never shows dialogs.

### Python

- Python 3.13, with type hints on every function signature, using built-in generics such as `list[str]` and `Path | None`.
- `pyproject.toml` is the only config file.
- The runtime dependencies are PySide6-Essentials and PyMuPDF, and the dev dependencies are pytest, Ruff and PyInstaller. Discuss any new dependency first. PyMuPDF stays pinned to `~=1.28` until the workarounds in [ARCHITECTURE.md](ARCHITECTURE.md#key-decisions) are checked on a newer version.
- Ruff formats and lints, with its default line length of 88.
- Use dataclasses for results and settings, and `enum.Enum` for the save mode and the compression level. Values from the design, such as the dpi, the JPEG quality, the 10% rule and the 200-file warning, are named constants at the top of the module that uses them.
- Log with `logger = logging.getLogger(__name__)`. The app never uses `print`.
- Catch specific exceptions. No bare `except:`, and no silent `except Exception: pass`.
- No module-level mutable state.
- Use `pathlib`. Paths with spaces and non-ASCII names must work, and every text file is read and written as UTF-8.
- Detect a frozen build with `getattr(sys, "frozen", False)`, and use `Path(sys.executable).parent` as the app folder.

### Writing

These apply to UI text, code comments, docstrings, docs and commit messages.

- UI text is short, plain English for an older reader who is not technical, with no jargon. The base font is 12 pt.
- Use plain ASCII punctuation: no em or en dashes, curly quotes, arrows or emoji.
- Comments explain why, never what. Don't narrate the code, number steps or leave change notes.
- Public functions and classes get a one-sentence docstring. Add Args or Returns only when the type hints don't make them obvious.
- A TODO says what is missing and why.
- Headings are in sentence case.

## Tests

- Write the test first for any change to `core/`, watch it fail, then make it pass. The window, the installer and the build scripts are checked by hand with the [release checklist](#release-checklist).
- A test that passes the first time it runs proves nothing yet. Break the code on purpose and watch the test fail before trusting it.
- Test files mirror the module they cover: `tests/test_scan.py` covers `core/scan.py`.
- `tests/conftest.py` builds every test PDF in code, each with a seeded `random.Random`, in under a second. Unless a fixture says otherwise, it saves with `garbage=3, deflate=True, use_objstms=True, no_new_id=True`, so rebuilds are byte for byte the same.
- Tests use only `tmp_path`. An autouse fixture points the home folder and the six system-folder variables into it, because `tmp_path` normally sits in `%LOCALAPPDATA%`, which the app refuses. Never point the app or the tests at real user folders.
- Scan and batch tests build their folders under `BASE`, a name with an n-tilde, a curly apostrophe and a letter outside cp1252. It is written with escapes in `conftest.py`.

## Commits and pull requests

- Make one change per commit, and stage files by name. Never commit `.venv/`, `build/`, `dist/` or test output.
- Write the subject in the imperative, in 50 characters or fewer, with no trailing period and no prefix such as `feat:`. For example: `Add blocked-folder check`.
- Add a body, wrapped at 72 characters, only when the reason for the change isn't obvious. Don't recap the diff.
- Before opening a pull request, `ruff check .`, `ruff format --check .` and `python -m pytest -q` must all pass. Say in the pull request what changed and how you checked it. A change in behavior updates ARCHITECTURE.md in the same pull request.

## Building

`.\build.ps1` reads the version from `pyproject.toml` and writes three things to `dist\`:

- `PDF Compressor\`, the PyInstaller one-folder app;
- `PDF-Compressor-Setup-<version>.exe`, the per-user installer from `installer\pdf_compressor.iss`;
- `PDF-Compressor-<version>-portable.zip`, the app folder plus `portable.txt`.

The script also fills the app's `licenses` folder from `installer\licenses\`, the project's `LICENSE` and Python's own license. To change the icon, edit `installer\app-icon.svg`, run `installer\make_icon.py`, and commit the new `pdf_compressor\gui\app.ico`. Never change the installer's `AppId`, because upgrades and the uninstaller find the install by it.

## Release checklist

Run this before handing out a build, using the output of `.\build.ps1`. Work only on copies of real filings.

### The window

- [ ] Send to on a folder and a file whose names have spaces, an n-tilde and a curly apostrophe: every item loads, and no run starts.
- [ ] Dragging files and a folder onto the window adds them. Remove and Clear work.
- [ ] Adding `C:\` shows "For safety, PDF Compressor can't work on C:\. Please choose a more specific folder, like one client's folder."
- [ ] The confirmation shows the file count, total size, folder count and how many files will be replaced.
- [ ] A folder with more than 200 PDFs shows the bold warning in the confirmation.
- [ ] Save compressed copies leaves the originals alone and fills the output folder.
- [ ] Replace originals, keep backups puts each original in the backup folder before replacing it.
- [ ] Replace originals, no backup asks "Are you sure? Your original files can't be recovered." first.
- [ ] During a run the bar counts files, and the label under it shows the current file name.
- [ ] Cancel stops after the current file.
- [ ] While a long scanned filing is being compressed, the window still moves and Cancel responds within a second.
- [ ] Closing the window during a run asks first, stops after the current file, and leaves no `~*.pdfc-tmp` file next to the PDFs.
- [ ] A 0.1 MB size limit turns the rows of larger files light red, with "Still ... MB. That's over your 0.1 MB limit, so it may need splitting."
- [ ] Open Folder opens the output folder for copies, or the folder of the first file in the replace modes.
- [ ] Options are the same after closing and opening the app, even when no run was started.
- [ ] In Save compressed copies, a signed PDF is copied unchanged into the output folder, and its row says "Skipped: digitally signed".
- [ ] Files from different subfolders show their subfolder in the File column.
- [ ] The window and the taskbar show the PDF Compressor icon.
- [ ] About shows the copyright, the no-warranty notice and the license, and its link opens the licenses folder.

### Installer

- [ ] The installer runs without an admin prompt.
- [ ] SmartScreen shows "Windows protected your PC", and More info, then Run anyway, starts it. Smart App Control must be off (Windows Security, App & browser control). A copy from a USB stick may show no warning at all.
- [ ] The Start menu and desktop shortcuts open the app.
- [ ] Send to shows Compress PDF. On Windows 11 it is under Show more options, or Shift+right-click.
- [ ] Sending several files and a folder at once opens one window with all of them.
- [ ] The installer and the shortcuts show the app icon.
- [ ] Running the installer again over an installed copy works, and the app still opens.
- [ ] Uninstalling removes the shortcuts, the Send to entry and the program folder, and keeps `%APPDATA%\PDF Compressor`.

### Portable zip

- [ ] Unzipped anywhere, the app keeps `settings.json` and `logs` next to the exe and writes nothing to `%APPDATA%\PDF Compressor`.
- [ ] The portable copy adds no Send to entry.
- [ ] Unzipped into a folder you can't write to, the portable copy still opens, keeps its settings in `%APPDATA%\PDF Compressor`, and compresses normally.

### Both

- [ ] The licenses folder holds `NOTICE.txt`, `LICENSE.txt`, `GPL-3.0.txt`, `LGPL-3.0.txt` and the python folder's `LICENSE.txt`.

### Before the first handover

- [ ] Tune `LEVELS` in `pdf_compressor/core/compress.py` on real scanned filings: check that text stays sharp at each level and note the sizes.
