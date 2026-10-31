# Contributing

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing how the app behaves.

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

## Code

- `core/` never imports Qt, and the window is a thin layer over `core.batch`. Long work runs in the `QThread` workers in `gui/worker.py`, which talk to the window only through signals.
- `core/` never shows dialogs. A problem with one file becomes a result with a plain-English message.
- Python 3.13, with type hints on every function using built-in generics such as `list[str]` and `Path | None`. Ruff formats and lints with its defaults.
- `pyproject.toml` is the only config file. Ask before adding a dependency. PyMuPDF stays pinned to `~=1.28` until the workarounds in [ARCHITECTURE.md](ARCHITECTURE.md#key-decisions) are checked on a newer version.
- Results and settings are dataclasses, and the save mode and compression level are enums. Values such as the dpi, the JPEG quality, the 10% rule and the 200-file warning are constants at the top of the module that uses them.
- Log with `logging.getLogger(__name__)`, never `print`. Catch specific exceptions.
- Use `pathlib`. Paths with spaces and non-ASCII names have to work, and text files are read and written as UTF-8.
- A frozen build is detected with `getattr(sys, "frozen", False)`, and its app folder is `Path(sys.executable).parent`.
- UI text is short, plain English for people who aren't technical. The base font is 12 pt.

## Tests

- Changes to `core/` need tests, ideally written first. The window, the installer and the build script are checked by hand with the [release checklist](#release-checklist).
- Test files mirror the module they cover: `tests/test_scan.py` covers `core/scan.py`.
- `tests/conftest.py` builds every test PDF in code from a seeded `random.Random`. Unless a fixture says otherwise, it saves with `garbage=3, deflate=True, use_objstms=True, no_new_id=True`, so rebuilds are byte for byte the same.
- Tests only touch `tmp_path`. An autouse fixture points the home folder and the system-folder variables into it, because `tmp_path` normally sits in `%LOCALAPPDATA%`, which the app refuses. Never point the app or the tests at real user folders.
- Scan and batch tests build their folders under `BASE`, a name with an n-tilde, a curly apostrophe and a letter outside cp1252, written with escapes in `conftest.py`.

## Commits and pull requests

- One change per commit. Never commit `.venv/`, `build/`, `dist/` or test output.
- Subjects are imperative, 50 characters or fewer, with no trailing period and no prefix such as `feat:`. For example: `Add blocked-folder check`. Add a body, wrapped at 72 characters, when the reason for the change isn't obvious.
- Before opening a pull request, `ruff check .`, `ruff format --check .` and `python -m pytest -q` must pass. Say what changed and how you checked it. A change in behavior updates ARCHITECTURE.md in the same pull request.

## Building

`.\build.ps1` reads the version from `pyproject.toml` and writes three things to `dist\`:

- `PDF Compressor\`, the PyInstaller one-folder app;
- `PDF-Compressor-Setup-<version>.exe`, the per-user installer from `installer\pdf_compressor.iss`;
- `PDF-Compressor-<version>-portable.zip`, the app folder plus `portable.txt`.

The script also fills the app's `licenses` folder from `installer\licenses\`, the project's `LICENSE` and Python's own license. To change the icon, edit `installer\app-icon.svg`, run `installer\make_icon.py`, and commit the new `pdf_compressor\gui\app.ico`. Never change the installer's `AppId`, because upgrades and the uninstaller find the install by it.

Local builds are for testing. The files on the Releases page are built by GitHub Actions.

## Releasing

1. Set the version in `pyproject.toml`, and rename `## Unreleased` in `CHANGELOG.md` to `## <version> - <yyyy-mm-dd>`.
2. Commit that on `main`, then tag and push it: `git tag v<version>`, then `git push origin main v<version>`.
3. The Release workflow (`.github/workflows/release.yml`) checks that the tag matches `pyproject.toml` and that the changelog has a section for that version. It then runs the tests, runs `build.ps1` and creates a draft release with the installer, the portable zip and that changelog section as the notes.
4. Download both files from the draft and go through the release checklist below.
5. Publish the draft.

The workflow installs the newest versions that `pyproject.toml` allows, and it compiles the installer with the Inno Setup 6 that GitHub's Windows image includes, so its files can differ from a local build. That is why the checklist runs on the draft's files. To get a build without making a release, run the Release workflow by hand from the Actions tab. The files are attached to the run.

## Release checklist

Run this on the draft release's files before publishing it. Work only on copies of real filings.

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

### Before the first release

- [ ] Tune `LEVELS` in `pdf_compressor/core/compress.py` on real scanned filings: check that text stays sharp at each level and note the sizes.
