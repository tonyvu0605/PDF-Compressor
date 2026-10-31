"""Start PDF Compressor, loading any files and folders passed on the command line."""

import logging
import multiprocessing
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import TracebackType

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

# Absolute imports: PyInstaller runs this file as a script, not as a package.
from pdf_compressor.core.batch import remove_leftover_temps
from pdf_compressor.core.settings import (
    APP_NAME,
    app_dir,
    data_dir,
    documents_dir,
    load_settings,
    new_log_path,
    writable_dir,
)
from pdf_compressor.gui.main_window import APP_ICON, MainWindow
from pdf_compressor.gui.worker import configure_logging

BASE_FONT_POINTS = 12

logger = logging.getLogger("pdf_compressor")


def main(argv: list[str]) -> int:
    """Run the app and return its exit code."""
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    preferred = data_dir(app_dir(), appdata)
    # A portable copy unzipped where the user can't write falls back to
    # AppData, then the temp folder, instead of failing before any window.
    fallbacks = [preferred, appdata / APP_NAME, Path(tempfile.gettempdir()) / APP_NAME]
    data = writable_dir(list(dict.fromkeys(fallbacks)))
    configure_logging(new_log_path(data / "logs", datetime.now()))
    sys.excepthook = _log_uncaught
    if data != preferred:
        logger.warning(
            "Can't write to %s, so settings and logs are in %s", preferred, data
        )

    try:
        remove_leftover_temps(data)
    except OSError:
        logger.exception("Could not clean up leftover temp files")
    settings_path = data / "settings.json"
    settings = load_settings(settings_path, documents_dir())

    app = QApplication(argv)
    app.setApplicationName("PDF Compressor")
    # Set on the application, so dialogs carry the icon too.
    app.setWindowIcon(QIcon(str(APP_ICON)))
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
    # The frozen app runs this file again for every worker process;
    # freeze_support turns those runs into workers before a window opens.
    multiprocessing.freeze_support()
    sys.exit(main(sys.argv))
