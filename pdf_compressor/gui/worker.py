"""Background work, so the window stays responsive during long jobs."""

import logging
import threading
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pymupdf
from PySide6.QtCore import QThread, Signal

from pdf_compressor.core.batch import run_batch
from pdf_compressor.core.compress import FileResult, compress_file
from pdf_compressor.core.scan import ScanResult, scan_inputs
from pdf_compressor.core.settings import Level, Settings

logger = logging.getLogger(__name__)

CRASHED = "The run stopped because of an error. Details are in the log."
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(log_file: Path | None) -> None:
    """Send this process's log records and MuPDF's messages to the log file."""
    if log_file is not None:
        # delay=True: a launch that logs nothing leaves no log file behind.
        handler = logging.FileHandler(log_file, delay=True, encoding="utf-8")
        logging.basicConfig(handlers=[handler], level=logging.INFO, format=LOG_FORMAT)
    pymupdf.set_messages(pylogging=True, pylogging_level=logging.WARNING)


class ScanWorker(QThread):
    """Expand the chosen files and folders into jobs off the GUI thread."""

    scanned = Signal(object)
    crashed = Signal(str)

    def __init__(self, inputs: list[Path], settings: Settings) -> None:
        super().__init__()
        self._inputs = list(inputs)
        self._settings = replace(settings)

    def run(self) -> None:
        """Scan, then emit the ScanResult or a plain message."""
        try:
            result = scan_inputs(self._inputs, self._settings)
        except Exception:
            # The window waits for one of these signals, so always send one.
            logger.exception("The scan failed")
            self.crashed.emit(CRASHED)
            return
        self.scanned.emit(result)


class BatchWorker(QThread):
    """Run one batch off the GUI thread, reporting progress through signals."""

    progress = Signal(int, int, str)
    done = Signal(object)
    crashed = Signal(str)

    def __init__(self, scan: ScanResult, settings: Settings, data_dir: Path) -> None:
        super().__init__()
        self._scan = scan
        self._settings = replace(settings)
        self._data_dir = data_dir
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Ask the run to stop after the current file."""
        self._cancel.set()

    def run(self) -> None:
        """Run the batch, then emit the BatchResult or a plain message."""
        try:
            # PyMuPDF keeps Python's interpreter lock for a whole call, which
            # would freeze the window for seconds on a long scan, so each file
            # is compressed in a separate process.
            with ProcessPoolExecutor(
                max_workers=1,
                initializer=configure_logging,
                initargs=(_current_log_file(),),
            ) as pool:

                def compress_in_child(
                    source: Path,
                    tmp: Path,
                    level: Level,
                    remove_hidden_info: bool,
                    size_limit_mb: float | None,
                ) -> FileResult:
                    arguments = (source, tmp, level, remove_hidden_info, size_limit_mb)
                    return pool.submit(compress_file, *arguments).result()

                result = run_batch(
                    self._scan,
                    self._settings,
                    self._cancel,
                    self._report,
                    self._data_dir,
                    datetime.now(),
                    compress_in_child,
                )
        except Exception:
            # The window waits for one of these signals, so always send one.
            logger.exception("The run failed")
            self.crashed.emit(CRASHED)
            return
        self.done.emit(result)

    def _report(self, number: int, total: int, source: Path) -> None:
        self.progress.emit(number, total, source.name)


def _current_log_file() -> Path | None:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return None
