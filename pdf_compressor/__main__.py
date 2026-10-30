"""Start PDF Compressor, loading any files and folders passed on the command line."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from types import TracebackType

import pymupdf
from PySide6.QtWidgets import QApplication

# Absolute imports: PyInstaller runs this file as a script, not as a package.
from pdf_compressor.core.batch import remove_leftover_temps
from pdf_compressor.core.settings import (
    app_dir,
    data_dir,
    documents_dir,
    load_settings,
    new_log_path,
)
from pdf_compressor.gui.main_window import MainWindow

BASE_FONT_POINTS = 12

logger = logging.getLogger("pdf_compressor")


def main(argv: list[str]) -> int:
    """Run the app and return its exit code."""
    data = data_dir(app_dir(), Path(os.environ["APPDATA"]))
    data.mkdir(parents=True, exist_ok=True)
    # delay=True: a launch that logs nothing leaves no log file behind.
    handler = logging.FileHandler(
        new_log_path(data / "logs", datetime.now()), delay=True, encoding="utf-8"
    )
    logging.basicConfig(
        handlers=[handler],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    pymupdf.set_messages(pylogging=True, pylogging_level=logging.WARNING)
    sys.excepthook = _log_uncaught

    try:
        remove_leftover_temps(data)
    except OSError:
        logger.exception("Could not clean up leftover temp files")
    settings_path = data / "settings.json"
    settings = load_settings(settings_path, documents_dir())

    app = QApplication(argv)
    app.setApplicationName("PDF Compressor")
    font = app.font()
    font.setPointSize(BASE_FONT_POINTS)
    app.setFont(font)
    window = MainWindow(settings, settings_path, data, [Path(arg) for arg in argv[1:]])
    window.show()
    return app.exec()


def _log_uncaught(
    kind: type[BaseException], value: BaseException, trace: TracebackType | None
) -> None:
    logger.critical("Uncaught error", exc_info=(kind, value, trace))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
