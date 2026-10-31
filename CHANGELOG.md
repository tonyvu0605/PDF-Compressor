# Changelog

Notable changes to PDF Compressor are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Batch compression of PDF folders, subfolders included, and single files, with drag and drop and a Compress PDF entry in File Explorer's Send to menu.
- Save modes: compressed copies in a separate folder, replace with backups, and replace without backup.
- Low, Medium and High compression levels, modeled on Acrobat's.
- A size limit, with one retry at High and red rows for files still over it.
- Optional removal of hidden info: the document information and XMP metadata.
- Safety checks: refused system folders, a confirmation before every run, results verified before they replace anything, and skips for signed, secured, damaged and in-use files.
- A per-user installer, a portable zip, an app icon and an About box with the license notice.
