# Architecture

This document explains how PDF Compressor works and why. It is the reference for the app's behavior: when the code and this document disagree, one of them has a bug. [README.md](README.md) covers using the app, and [CONTRIBUTING.md](CONTRIBUTING.md) covers working on it.

## Goals

PDF Compressor batch-compresses PDFs for court and government e-filing portals. Its user is an older attorney who is not technical, on Windows 10 or 11, with his files on his local PC. The app succeeds when:

- he picks a folder or files, presses Start, and gets files ready to upload;
- no original is ever lost or damaged;
- text stays sharp and searchable;
- any file still over the portal's size limit is obvious.

Out of scope for now: OCR, splitting oversized PDFs, network or cloud drives, PDF/A conversion, macOS or Linux, automatic updates, code signing and single-instance window handling.

## Code map

```
pdf_compressor/
  __main__.py        entry point: data folder, logging, temp cleanup, then the window
  core/              no Qt imports; covered by the tests
    safety.py        blocked_reason(path): refuses drive roots, home and system folders
    scan.py          scan_inputs: expands inputs into jobs, with totals, name clashes,
                     existing files and everything left out, with the reason
    compress.py      compress_file: compresses one PDF into a verified temp file
    batch.py         run_batch: runs the jobs in a save mode, with backups, cancel,
                     progress, the temp file journal and the summary text
    settings.py      Settings, load and save, portable mode, folders, log rotation
  gui/
    main_window.py   the window, its two pages and its dialogs
    worker.py        QThread workers for the scan and the run
    app.ico          made by installer/make_icon.py from installer/app-icon.svg
installer/
  pdf_compressor.iss Inno Setup script
  licenses/          license texts and NOTICE.txt that every build ships
build.ps1            PyInstaller, then Inno Setup, then the portable zip
tests/               pytest for core/; conftest.py builds every test PDF
```

## How a run works

1. The window collects input paths from its buttons, drag and drop, or the command line (Send to passes them there). Blocked paths are refused at once.
2. Start saves the options and runs `scan_inputs` in a `ScanWorker` thread.
3. The window shows the confirmation. For Replace originals, no backup it also asks "Are you sure? Your original files can't be recovered."
4. A `BatchWorker` thread calls `run_batch`. For each job, `compress_file` runs in a separate process, and `run_batch` puts the result in place.
5. The workers report only through Qt signals and never touch widgets. The window then shows the summary and the results table.

## Rules

### Blocked folders

A file or folder is refused if it is a drive root, the user profile folder itself (`Path.home()`), or inside `%WINDIR%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramData%`, `%APPDATA%` or `%LOCALAPPDATA%`. Paths are resolved first, so `..` and short 8.3 names can't get around the check. The message reads: "For safety, PDF Compressor can't work on <path>. Please choose a more specific folder, like one client's folder." There is no override. The output and backup folder pickers refuse the same folders.

### Scanning

- Folders include their subfolders. The scan never follows symlinks or junctions, and it refuses volume mount points as links.
- It always skips the current output and backup folders, so results are never compressed twice. A compressed copy given as an input is left out with a reason.
- The same PDF reached twice, for example through a folder and a file inside it, becomes one job.
- Windows paths are limited to 260 characters. Anything that would pass the limit, including the destination and its temp file, is left out with a reason.
- If two inputs would produce the same output path, the later one gets " (2)", or the next free number, before `.pdf`.
- Jobs are sorted without regard to case.

### Confirmation

The dialog before every run shows the file count, the total size and the number of folders, how many files already exist at the destination and will be replaced, and a bold extra warning above 200 files.

### Each file

1. Read the original into memory.
2. Skip it, with the reason shown, if it is password-protected or secured, digitally signed, damaged, or open in another program.
   - Secured means `needs_pass` is set or the trailer has an `/Encrypt` entry. `is_encrypted` misses files locked only by an owner password, and re-saving such a file would drop its security.
   - Signed means a signature value in any `/FT /Sig` field, or a `/Perms` entry in the catalog. Re-saving would invalidate the signature.
   - Damaged means MuPDF can't open it, or opens it only by repairing it. A truncated file opens by repair with some pages blank.
3. Compress it into a temp file in the destination folder.
4. Reopen the temp file. Its page count must match the original.
5. Keep the result only if it is at least 10% smaller, or if the original is over the size limit and the result is at or under it.
6. Only then move it into place with `os.replace`.

When a check fails, the original is kept. In Save compressed copies, every file that isn't compressed, skipped files included, is copied unchanged when it can be read, so the output folder is complete.

### Statuses

| Status | When |
|--------|------|
| Compressed | The smaller file is in place. |
| Already small | The result failed the 10% rule. |
| Not changed: this file couldn't be compressed | MuPDF failed, or the page count changed. |
| Skipped: password-protected or secured | See "Each file". |
| Skipped: digitally signed | See "Each file". |
| Skipped: can't be opened (it may be damaged) | See "Each file". |
| Skipped: open in another program | The file is locked, or Windows refused the replace. |
| Skipped: the file is read-only | The replace modes only. |
| Skipped: file not found | It disappeared after the scan. |
| Not changed: the backup copy failed | Replace originals, keep backups only. |
| Not changed: something went wrong with this file | Anything else; the log has the details. |

A row turns red when its file is still over the size limit. Compressed and Already small rows then read "Still 14.2 MB. That's over your 10 MB limit, so it may need splitting." Other rows keep their reason. The summary reads like "37 files: 412 MB down to 96 MB. 2 skipped.", where skipped counts every row that isn't Compressed or Already small. Sizes are decimal megabytes, with one decimal from 1 MB up, two below, and "under 0.01 MB" for tiny files.

### Save modes

1. Save compressed copies (the default). Files go to the output folder, `Documents\Compressed PDFs` by default. A folder input keeps its structure as `<output>\<input folder name>\<relative path>`. A single file goes directly into the output folder. File names are unchanged.
2. Replace originals, keep backups. Before a file is replaced, its original is copied to `<backup folder>\<YYYY-MM-DD HHMM>\`, in the same layout as mode 1. The backup folder defaults to `Documents\PDF Backups`. If the backup copy fails, that original is not replaced. If the dated folder already exists, " (2)" or the next free number is added, so earlier backups are never overwritten. A run folder that stays empty is removed.
3. Replace originals, no backup. Every run asks a second question first.

### Compression

The steps for each file:

1. `Document.rewrite_images(options=...)` resamples color and gray images above the level's threshold to its target dpi with bicubic resampling, and saves them as JPEG at its quality. Black-and-white images are left alone.
2. `repair_jpeg_colorspaces` relabels JPEG images whose channel count disagrees with their color space.
3. `subset_fonts()`.
4. If Remove hidden info is on, the document information and the XMP metadata are cleared. Attachments, form fields and annotations are never removed.
5. Save with `garbage=3`, `deflate=True` and `use_objstms=True`.

Text and vector content are never rasterized. The levels in `LEVELS` (`core/compress.py`) are starting points; tune them on real scanned filings.

When a result is still over the size limit and the level wasn't High, the file is redone once from the original at High, and the smaller of the two results is kept.

### Errors and cancel

- An error on one file never stops the batch.
- Cancel finishes the current file and then stops. Closing the window during a run asks first, then does the same.
- Temp files are named `~<8 hex digits>.pdfc-tmp`. Each is recorded in `temp-files.txt` in the data folder before it is created. Leftovers are removed when a run ends and when the app starts, and the journal is deleted once it is empty. Only names ending in `.pdfc-tmp` are ever deleted, whatever the journal says.

### Settings, logs and startup

- Settings are JSON: `%APPDATA%\PDF Compressor\settings.json` when installed, or next to the exe when `portable.txt` sits there. If that folder can't be written to, the app falls back to `%APPDATA%\PDF Compressor`, then the temp folder, instead of failing before the window opens.
- A missing, corrupt or hand-edited settings file loads with defaults, field by field. Relative folders are ignored. Saving writes a temp file and renames it into place.
- Options are saved at Start and when the window closes.
- Logs go in a `logs` folder beside the settings: one file per launch, created only when something is logged, keeping the last 20. MuPDF's warnings go to the same log, in the worker process too.
- Paths on the command line are added to the input list, which is how Send to works. The app never starts a run by itself.

### Packaging

- PyInstaller builds one folder (`--onedir --windowed`). QtNetwork is excluded: nothing uses it, and it would pull OpenSSL DLLs from Git's folder on `PATH` into the build.
- The Inno Setup installer is per user, so there is no admin prompt, and installs into `%LOCALAPPDATA%\Programs\PDF Compressor`. It adds Start menu and desktop shortcuts and a Compress PDF entry in Send to. Send to opens one window for all the selected items as long as their paths fit in Windows' 32,766-character command line. An upgrade deletes the old `_internal` folder before copying the new one. The uninstaller removes everything it installed and keeps the settings and logs. Never change the script's `AppId`; upgrades and the uninstaller find the install by it.
- The portable version is the same folder zipped, plus `portable.txt`. It adds no Send to entry and makes no registry changes of its own; Windows and Qt still remember recent folders in file dialogs, Qt under `HKCU\Software\QtProject`.
- The builds are unsigned, so SmartScreen warns on the first run.
- Every build ships a `licenses` folder: `LICENSE.txt`, `GPL-3.0.txt`, `LGPL-3.0.txt`, `NOTICE.txt`, the wheels' license metadata and Python's license.

## Key decisions

- Compression runs in a child process. PyMuPDF holds Python's interpreter lock for the whole of each call, so a QThread alone froze the window for seconds on long scans. `BatchWorker` runs `compress_file` in a one-process `ProcessPoolExecutor`, and `__main__.py` calls `multiprocessing.freeze_support()` so the frozen exe can start that process. This costs about a second per run.
- MuPDF 1.28 needs several workarounds, each reproduced on PyMuPDF 1.28.2:
  - The plain `rewrite_images(dpi_threshold, dpi_target, quality)` call only halves resolution, so a 300 dpi scan stayed at 300 dpi on Low and Medium. Explicit options with bicubic resampling hit the target.
  - MuPDF writes ICC gray, ICC CMYK and CalGray images as 3-channel JPEGs under the old color space, which renders as noise. `repair_jpeg_colorspaces` fixes the label.
  - MuPDF repairs lazily, when a broken object first loads. `is_repaired` is checked again after the signature scan and once more before saving, so damage is never saved as blank pages. This also skips complete files that MuPDF repairs silently, such as one with a wrong `startxref` offset; they keep their original.
  - `set_metadata({})` does nothing on files with object streams, so hidden info is cleared by setting `/Info` to `<<>>` and calling `del_xml_metadata()`.
  - `garbage=4` would also merge duplicate streams but takes seconds on long scans, so saving uses `garbage=3`.
- PyMuPDF is pinned to `~=1.28`. Version 2.0 is coming, and the workarounds above need checking again on any upgrade.
- Every PyMuPDF error class is caught at the file level: `RuntimeError`, `ValueError` and `mupdf.FzErrorBase`. None of them is an `OSError`, and a failed save raises only `FzErrorBase`.
- The original is read whole into memory, so no open handle can block `os.replace` in the replace modes. Very large files use that much memory.
- Temp files sit next to their destination, so `os.replace` is a rename within one folder. A replace that Windows refuses is reported as read-only when the file has the read-only attribute, and as open in another program otherwise.
- Backup run folders are claimed with `mkdir`, which either creates the folder or fails. Two windows starting a run in the same minute never share one, and an existing backup is never overwritten.
- Copies made in mode 1 use `shutil.copyfile`, which leaves out the read-only attribute. Backups use `shutil.copy2`, which keeps the file's attributes.
- Defaults follow Windows' Documents known folder, so with OneDrive folder backup they land in OneDrive, where the user expects his documents.
- The app is licensed AGPL-3.0-or-later because PyMuPDF is AGPL. Qt is used under the LGPL; its DLLs ship as separate files, so they can be replaced. The About box shows the notice that the AGPL asks interactive programs to show.

## Known gaps

None of these loses data. They are candidates for issues.

Scanning:

- Overlapping inputs that reach the same over-long path or unreadable folder list it twice in the left-out list.
- A folder whose own path is over 260 characters is reported with the file wording, "This file's path is too long for Windows."
- An access-denied folder, or any other failed `stat()`, is told its path may be too long. Checking `winerror` would name the real cause.
- `blocked_reason` resolves the home and system folders on every call: about 8 seconds for an 8,000-file tree, off the GUI thread. Adding paths calls it on the GUI thread, once per path.
- When the same PDF is reached as a file and through its folder, the first input decides its output layout.

Compression:

- Damage that MuPDF only warns about, such as a zeroed stream with an intact header, can't be detected. MuPDF's warnings are logged at INFO.
- Reader-enabled forms (`/Perms /UR3`) are reported as digitally signed.
- Palette images are left alone by the image rewriter, so some scans come back Already small.
- JPEG 2000 images are tested and compress, but other formats Acrobat may write, such as JBIG2, are untested.
- If antivirus holds a temp file when an Already small result is discarded, the row says "something went wrong" instead.
- Under a size limit, the High retry roughly doubles the work for files that need it.

Batch:

- In the replace modes, a source deleted between the scan and the run is reported as read-only.
- In mode 1, when an earlier output copy is open or read-only, the message reads as if the original were.
- When `os.replace` is refused after a successful backup copy, the backup of the unchanged file stays in the run folder.
- Two windows share one journal. One window's cleanup can delete the other's temp file between its save and its replace, which gives that file a wrong status row while the original stays safe. A journal per process, or a run lock, would close this.

Window:

- If a run finishes while the "still working" question is open, answering Yes leaves the window open until it is closed again.
- Closing during a scan waits for the scan without saying so.
- A failed scan reuses the message "The run stopped because of an error."
- Opening the app while it runs, for example through Send to, starts a second window.

Tests:

- No test builds a folder over 260 characters inside an input.
- No test covers a `PermissionError` while reading, a `/Perms` signature, a JPEG under the threshold staying byte for byte the same, or `_move_into_place`'s `PermissionError` branch in mode 1.
