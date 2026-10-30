# Manual checklist

Run this once before handing the app over, using the build from `.\build.ps1`. Work only on copies of real filings.

## The window

- [ ] Send To on a folder and a file whose names have spaces, an n-tilde and a curly apostrophe: every item loads, and no run starts.
- [ ] Dragging files and a folder onto the window adds them. Remove and Clear work.
- [ ] Adding `C:\` shows "For safety, PDF Compressor can't work on C:\. Please choose a more specific folder, like one client's folder."
- [ ] The confirmation shows the file count, total size, folder count and how many files will be replaced.
- [ ] A folder with more than 200 PDFs shows the bold warning in the confirmation.
- [ ] Save compressed copies leaves the originals alone and fills the output folder.
- [ ] Replace originals, keep backups puts each original in the backup folder before replacing it.
- [ ] Replace originals, no backup asks "Are you sure? Your original files can't be recovered." first.
- [ ] During a run the bar counts files and the label under it shows the current file name.
- [ ] Cancel stops after the current file.
- [ ] Closing the window during a run asks first, stops after the current file, and leaves no `~*.pdfc-tmp` file next to the PDFs.
- [ ] A 0.1 MB size limit turns the rows of larger files light red, with "Still ... MB. That's over your 0.1 MB limit, so it may need splitting."
- [ ] Open Folder opens the output folder for copies, or the folder of the first file in the replace modes.
- [ ] Options are the same after closing and opening the app.

## Installer

- [ ] The installer runs without an admin prompt.
- [ ] SmartScreen shows "Windows protected your PC", and More info, then Run anyway, starts it. Smart App Control must be off (Windows Security, App & browser control). A copy from a USB stick may show no warning at all.
- [ ] The Start Menu and desktop shortcuts open the app.
- [ ] Send To shows "Compress PDF". On Windows 11 it is under "Show more options", or Shift+right-click.
- [ ] Sending several files and a folder at once opens one window with all of them.
- [ ] Uninstalling removes the shortcuts, the Send To entry and the program folder, and keeps `%APPDATA%\PDF Compressor`.

## Portable zip

- [ ] Unzipped anywhere, the app keeps `settings.json` and `logs\` next to the exe and writes nothing to `%APPDATA%\PDF Compressor`.
- [ ] The portable copy adds no Send To entry.

## Both

- [ ] The installed and the portable copy both contain `licenses\`.

## Before handover

- [ ] Tune `LEVELS` in `pdf_compressor/core/compress.py` on real scanned filings: check that text stays sharp at each level and note the sizes.
