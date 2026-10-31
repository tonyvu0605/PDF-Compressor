# PDF Compressor

PDF Compressor shrinks PDFs so court and government e-filing portals will take them. Add a folder or a few files, click Start, and the smaller copies are ready to upload. Scanned pages shrink the most, and text stays sharp and searchable.

It was made for an attorney who used to compress filings one at a time in Adobe Acrobat, so the wording is plain and the text is large. Originals aren't touched unless you choose to replace them, and a file that is still too big for the portal is marked in red.

## Download

Get the latest version from the [Releases page](https://github.com/tonyvu0605/PDF-Compressor/releases/latest). It runs on 64-bit Windows 10 and 11.

- `PDF-Compressor-Setup-<version>.exe` installs it for your Windows account, without an admin prompt. It adds Start menu and desktop shortcuts and a Compress PDF entry to File Explorer's Send to menu.
- `PDF-Compressor-<version>-portable.zip` runs without installing. Unzip it anywhere and open `PDF Compressor.exe`. It keeps its settings in that folder and doesn't add a Send to entry.

## Using it

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
| Output or backup folder | `Documents\Compressed PDFs` and `Documents\PDF Backups`, unless you pick others |
| Compression | Low (best quality), Medium (recommended) or High (smallest files) |
| Size limit | A number of MB, or blank for no limit |
| Remove hidden info | On by default. Clears the document information and XMP metadata |

The app remembers these between runs. Replace originals, no backup asks "Are you sure? Your original files can't be recovered." before every run.

| Level | Resamples images above | Down to | JPEG quality |
|-------|------------------------|---------|--------------|
| Low | 250 dpi | 200 dpi | 85 |
| Medium | 200 dpi | 150 dpi | 75 |
| High | 150 dpi | 100 dpi | 60 |

Only color and grayscale images are resampled. Text and drawings are never turned into images, and black-and-white images are left alone. If a file is still over the size limit, it is redone once at High and the smaller result is kept.

## Results

The summary reads like "37 files: 412 MB down to 96 MB. 2 skipped." Each file gets a row with its size before and after and one of these statuses:

- Compressed.
- Already small: compressing saved less than 10%, so the original is kept.
- Not changed: this file couldn't be compressed.
- Skipped, with the reason: password-protected or secured, digitally signed, damaged, open in another program, read-only, or not found.

## Settings and logs

The installed app keeps `settings.json` and a `logs` folder in `%APPDATA%\PDF Compressor`. The portable copy, which has a `portable.txt` file next to its exe, keeps them next to `PDF Compressor.exe`. If it can't write there, it falls back to `%APPDATA%\PDF Compressor`, then the temp folder.

A launch writes a log file only if it has something to log, and the last 20 are kept.

## Limitations

- No OCR.
- It can't split a PDF that is still too big.
- Local drives only.
- No PDF/A conversion, no macOS or Linux version, and no automatic updates.
- Opening it a second time opens a second window.
- The compression levels still need tuning on more real filings.

Smaller known issues are listed in [ARCHITECTURE.md](ARCHITECTURE.md#known-gaps).

## Building from source

You need 64-bit Python 3.13, and Inno Setup to build the installer.

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pdf_compressor
.venv\Scripts\python -m pytest -q
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers the build script, the tests and releases. [ARCHITECTURE.md](ARCHITECTURE.md) explains how the app works.

## License

PDF Compressor is free software under the GNU Affero General Public License, version 3 or later. See [LICENSE](LICENSE). It uses PyMuPDF, which is AGPL, and Qt for Python, which is LGPL. [NOTICE.txt](installer/licenses/NOTICE.txt) lists every component a build includes, with its license and where to get its source.
