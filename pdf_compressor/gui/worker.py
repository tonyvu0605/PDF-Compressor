"""Background threads, so the window stays responsive during long work."""

import logging
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from pdf_compressor.core.batch import run_batch
from pdf_compressor.core.scan import ScanResult, scan_inputs
from pdf_compressor.core.settings import Settings

logger = logging.getLogger(__name__)

CRASHED = "The run stopped because of an error. Details are in the log."


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
            result = run_batch(
                self._scan,
                self._settings,
                self._cancel,
                self._report,
                self._data_dir,
                datetime.now(),
            )
        except Exception:
            # The window waits for one of these signals, so always send one.
            logger.exception("The run failed")
            self.crashed.emit(CRASHED)
            return
        self.done.emit(result)

    def _report(self, number: int, total: int, source: Path) -> None:
        self.progress.emit(number, total, source.name)
