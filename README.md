# PDF Compressor

PDF Compressor is a Windows desktop app that makes PDF files smaller, so court and government e-filing portals accept them. Pick a folder or files, press Start, and get files ready to upload. Originals are never lost or damaged, text stays sharp and searchable, and any file still over the portal's size limit is easy to spot.

It was written for one user, an attorney who used to compress files one at a time in Adobe Acrobat, so the window uses short, plain English and large text.

- Compresses whole folders, subfolders included, or single files. Files can also be dragged onto the window or sent from File Explorer.
- Saves compressed copies to a separate folder by default. It can also replace the originals, with or without backups.
- Has three compression levels that mirror Acrobat's Low, Medium and High.
- Retries a file at High once when it is over your size limit, and marks it in red if it is still over.
- Can remove hidden info, such as the author and title, from each file.
- Skips files that compressing would harm, such as signed or password-protected PDFs, and says why.

It runs on Windows 10 and 11, 64-bit.

## Install

There are no published releases yet. Build the installer and the portable zip from source with `.\build.ps1`, as described in [CONTRIBUTING.md](CONTRIBUTING.md#building).

- The installer, `PDF-Compressor-Setup-<version>.exe`, installs for the current user without an admin prompt. It adds Start menu and desktop shortcuts and a Compress PDF entry to File Explorer's Send to menu.
- The portable zip, `PDF-Compressor-<version>-portable.zip`, runs from any folder. It keeps its settings next to `PDF Compressor.exe` and adds no Send to entry.

The app is not code-signed, so Windows SmartScreen warns the first time it runs.

## Getting started

### The first time you open it

Windows may show a blue box that says "Windows protected your PC". This happens because the app is new to Windows. Click More info, then click Run anyway. You only need to do this once.

### Compressing files

1. Open PDF Compressor from the Start menu or the desktop.
2. Click Add Folder or Add Files, or drag files onto the window.
3. Choose how to save. Save compressed copies is the safe choice: your files stay as they are, and the smaller copies go to the Compressed PDFs folder in Documents. Files that can't be made smaller are copied there as they are, so that folder holds every file.
4. Click Start, read the summary, and click Start again.
5. When it is done, click Open Folder to see the smaller files.

A red row means that file is still bigger than the size limit you typed. It may need to be split before you upload it.

### From File Explorer

Right-click a PDF or a folder, then choose Send to, then Compress PDF. On Windows 11, click Show more options first, or hold Shift while you right-click.

To compress hundreds of files, send the folder that holds them instead of selecting every file. Windows can't send a very long list of files.

## Options

| Option | Choices |
|--------|---------|
| How to save | Save compressed copies (the default), Replace originals, keep backups, or Replace originals, no backup |
| Output or backup folder | `Documents\Compressed PDFs` and `Documents\PDF Backups` unless you choose others |
| Compression | Low (best quality), Medium (recommended) or High (smallest files) |
| Size limit | A number of MB, or blank for no limit |
| Remove hidden info | On by default; clears the document information and XMP metadata |

The app remembers these for next time. Replace originals, no backup asks "Are you sure? Your original files can't be recovered." before every run.

| Level | Resamples images above | Down to | JPEG quality |
|-------|------------------------|---------|--------------|
| Low | 250 dpi | 200 dpi | 85 |
| Medium | 200 dpi | 150 dpi | 75 |
| High | 150 dpi | 100 dpi | 60 |

Text and drawings are never turned into images, and black-and-white images are never re-encoded.

## Results

The summary reads like "37 files: 412 MB down to 96 MB. 2 skipped." Each file gets a row with its size before and after and one of these statuses:

- Compressed.
- Already small: compressing saved less than 10%, so the original is kept.
- Not changed: this file couldn't be compressed.
- Skipped, with the reason: password-protected or secured, digitally signed, damaged, open in another program, read-only, or not found.

## Settings and logs

- Installed: `%APPDATA%\PDF Compressor\settings.json`, with a `logs` folder beside it.
- Portable (when `portable.txt` sits next to the exe): `settings.json` and `logs` next to the exe. If that folder can't be written to, the app uses `%APPDATA%\PDF Compressor`, then the temp folder.

The app writes one log file per launch, only when it has something to log, and keeps the last 20.

## Limitations

This version has no OCR, can't split oversized PDFs, and works only on local drives. It has no PDF/A conversion, no macOS or Linux version, no automatic updates and no code signing, and opening it twice gives two windows. The compression levels are starting points to tune on real filings. [ARCHITECTURE.md](ARCHITECTURE.md#known-gaps) lists smaller known gaps.

## Development

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pdf_compressor
.venv\Scripts\python -m pytest -q
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers the project rules, testing, building and the release checklist. [ARCHITECTURE.md](ARCHITECTURE.md) explains how the app works and why.

## License

PDF Compressor is free software under the GNU Affero General Public License, version 3 or later. See [LICENSE](LICENSE). It uses PyMuPDF, which is AGPL, and Qt for Python, which is LGPL. [installer/licenses/NOTICE.txt](installer/licenses/NOTICE.txt) lists every component a build includes, its license and where to get its source.
