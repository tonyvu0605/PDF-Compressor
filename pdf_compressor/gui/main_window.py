"""The main window: add PDFs, choose how to save them, run, and read the results."""

import html
import logging
import math
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pdf_compressor.core.batch import BatchResult, short_names, summary_text
from pdf_compressor.core.compress import FileResult, format_mb
from pdf_compressor.core.safety import blocked_reason
from pdf_compressor.core.scan import ScanResult
from pdf_compressor.core.settings import Level, SaveMode, Settings, save_settings
from pdf_compressor.gui.worker import BatchWorker, ScanWorker

logger = logging.getLogger(__name__)

MANY_FILES = 200
LEFT_OUT_SHOWN = 10
TITLE = "PDF Compressor"
WINDOW_WIDTH = 900
WINDOW_HEIGHT = 800
SCREEN_SHARE = 0.9
BUTTON_HEIGHT = 36

INK = "#1F2933"
MUTED = "#5F6B7A"
ACCENT = "#1F4E8C"
ACCENT_HOVER = "#2A5FA3"
ACCENT_DISABLED = "#A9B7C9"
OVER_LIMIT_BACKGROUND = "#FDE2E1"
OVER_LIMIT_TEXT = "#8A1C1C"

MODE_CHOICES = (
    (SaveMode.COPY, "Save compressed copies"),
    (SaveMode.BACKUP, "Replace originals, keep backups"),
    (SaveMode.REPLACE, "Replace originals, no backup"),
)
LEVEL_CHOICES = (
    (Level.LOW, "Low (best quality)"),
    (Level.MEDIUM, "Medium (recommended)"),
    (Level.HIGH, "High (smallest files)"),
)

ADD_FIRST = "Add a folder or PDF files first."
NO_FILES = "No PDF files to compress."
BAD_LIMIT = "Please type the size limit as a number, like 10, or leave it blank."
NO_RECOVERY = "Are you sure? Your original files can't be recovered."
MANY_WARNING = "That is a lot of files. Please check that you picked the right folder."
STILL_WORKING = (
    "PDF Compressor is still working. Stop after the current file and close?"
)

STYLE = f"""
QLabel[role="heading"] {{ font-size: 15pt; font-weight: 600; color: {INK}; }}
QLabel[role="hint"] {{ color: {MUTED}; }}
QLabel[role="summary"] {{ font-size: 16pt; font-weight: 600; color: {INK}; }}
QPushButton[role="primary"] {{
    background: {ACCENT};
    color: white;
    border: 2px solid {ACCENT};
    border-radius: 6px;
    padding: 10px 28px;
    font-size: 13pt;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:focus {{ border-color: {INK}; }}
QPushButton[role="primary"]:disabled {{
    background: {ACCENT_DISABLED};
    border-color: {ACCENT_DISABLED};
}}
"""


class MainWindow(QMainWindow):
    """Add PDFs, choose how to save them, run, and show the results."""

    def __init__(
        self,
        settings: Settings,
        settings_path: Path,
        data_dir: Path,
        initial_paths: list[Path],
    ) -> None:
        super().__init__()
        self._settings = settings
        self._settings_path = settings_path
        self._data_dir = data_dir
        self._output_dir = settings.output_dir
        self._backup_dir = settings.backup_dir
        self._scan_worker: ScanWorker | None = None
        self._batch_worker: BatchWorker | None = None
        self._last_scan: ScanResult | None = None
        self._close_when_idle = False

        self.setWindowTitle(TITLE)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        # A fixed size could be taller than a small laptop screen.
        available = self.screen().availableGeometry()
        self.resize(
            min(WINDOW_WIDTH, int(available.width() * SCREEN_SHARE)),
            min(WINDOW_HEIGHT, int(available.height() * SCREEN_SHARE)),
        )

        self._pages = QStackedWidget()
        self._choose_page = self._build_choose_page()
        self._pages.addWidget(self._choose_page)
        self._pages.addWidget(self._build_results_page())
        self.setCentralWidget(self._pages)
        self._load_options(settings)
        if initial_paths:
            # After the window shows, so a refusal message appears over it.
            QTimer.singleShot(0, lambda: self._add_paths(initial_paths))

    # Building the two pages

    def _build_choose_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        layout.addWidget(_label("1. Add PDFs", "heading"))
        layout.addWidget(
            _label("Add a folder or PDF files, or drag them onto this window.", "hint")
        )
        self._inputs = QListWidget()
        self._inputs.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._inputs.setMinimumHeight(150)
        buttons = QVBoxLayout()
        for text, slot in (
            ("Add Folder", self._add_folder),
            ("Add Files", self._add_files),
            ("Remove", self._remove_selected),
            ("Clear", self._inputs.clear),
        ):
            button = QPushButton(text)
            button.setMinimumHeight(BUTTON_HEIGHT)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        inputs_row = QHBoxLayout()
        inputs_row.addWidget(self._inputs, 1)
        inputs_row.addLayout(buttons)
        layout.addLayout(inputs_row, 1)

        layout.addSpacing(8)
        layout.addWidget(_label("2. Choose how to save", "heading"))
        self._mode_group = QButtonGroup(page)
        self._mode_buttons: dict[SaveMode, QRadioButton] = {}
        for mode, text in MODE_CHOICES:
            button = QRadioButton(text)
            self._mode_group.addButton(button)
            self._mode_buttons[mode] = button
            button.toggled.connect(self._show_folder_for_mode)
            layout.addWidget(button)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self._folder_label = QLabel("Output folder:")
        self._folder_path = QLineEdit()
        self._folder_path.setReadOnly(True)
        self._folder_button = QPushButton("Change...")
        self._folder_button.setMinimumHeight(BUTTON_HEIGHT)
        self._folder_button.clicked.connect(self._choose_folder)
        grid.addWidget(self._folder_label, 0, 0)
        grid.addWidget(self._folder_path, 0, 1)
        grid.addWidget(self._folder_button, 0, 2)

        self._level = QComboBox()
        for _level, text in LEVEL_CHOICES:
            self._level.addItem(text)
        grid.addWidget(QLabel("Compression:"), 1, 0)
        grid.addWidget(self._level, 1, 1)

        self._limit = QLineEdit()
        self._limit.setPlaceholderText("No limit")
        self._limit.setMaximumWidth(140)
        limit_row = QHBoxLayout()
        limit_row.addWidget(self._limit)
        limit_row.addWidget(QLabel("MB"))
        limit_row.addStretch()
        grid.addWidget(QLabel("Size limit:"), 2, 0)
        grid.addLayout(limit_row, 2, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        self._hidden_info = QCheckBox("Remove hidden info")
        self._hidden_info.setToolTip(
            "Removes the author, title and other details saved inside each file."
        )
        layout.addWidget(self._hidden_info)

        layout.addSpacing(8)
        self._status = _label("", "hint")
        self._start = QPushButton("Start")
        self._start.setProperty("role", "primary")
        self._start.clicked.connect(self._start_clicked)
        start_row = QHBoxLayout()
        start_row.addWidget(self._status, 1)
        start_row.addWidget(self._start)
        layout.addLayout(start_row)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        self._summary = _label("Compressing...", "summary")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._progress = QProgressBar()
        self._cancel = QPushButton("Cancel")
        self._cancel.setMinimumHeight(BUTTON_HEIGHT)
        self._cancel.clicked.connect(self._cancel_clicked)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self._progress, 1)
        progress_row.addWidget(self._cancel)
        layout.addLayout(progress_row)
        self._current_file = _label("", "hint")
        layout.addWidget(self._current_file)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["File", "Before", "After", "Status"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setWordWrap(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)

        self._back = QPushButton("Compress more files")
        self._back.setMinimumHeight(BUTTON_HEIGHT)
        self._back.clicked.connect(self._back_clicked)
        self._open_folder = QPushButton("Open Folder")
        self._open_folder.setProperty("role", "primary")
        self._open_folder.clicked.connect(self._open_folder_clicked)
        buttons = QHBoxLayout()
        buttons.addWidget(self._back)
        buttons.addStretch()
        buttons.addWidget(self._open_folder)
        layout.addLayout(buttons)
        return page

    # Inputs

    def _add_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Add Folder")
        if chosen:
            self._add_paths([Path(chosen)])

    def _add_files(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileNames(
            self, "Add Files", "", "PDF files (*.pdf)"
        )
        self._add_paths([Path(name) for name in chosen])

    def _add_paths(self, paths: list[Path]) -> None:
        present = {os.path.normcase(path) for path in self._input_paths_text()}
        refused = []
        for item in paths:
            path = Path(os.path.abspath(item))
            reason = blocked_reason(path)
            if reason:
                refused.append(reason)
                continue
            key = os.path.normcase(str(path))
            if key in present:
                continue
            present.add(key)
            entry = QListWidgetItem(str(path))
            entry.setData(Qt.ItemDataRole.UserRole, str(path))
            self._inputs.addItem(entry)
        if refused:
            self._warn("\n\n".join(refused))

    def _remove_selected(self) -> None:
        for entry in self._inputs.selectedItems():
            self._inputs.takeItem(self._inputs.row(entry))

    def _input_paths_text(self) -> list[str]:
        return [
            self._inputs.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._inputs.count())
        ]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept files and folders dragged from Explorer while choosing."""
        if (
            self._pages.currentWidget() is self._choose_page
            and not self._busy()
            and event.mimeData().hasUrls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        """Add the dropped files and folders to the list."""
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self._add_paths(paths)
        event.acceptProposedAction()

    # Options

    def _load_options(self, settings: Settings) -> None:
        self._mode_buttons[settings.save_mode].setChecked(True)
        levels = [level for level, _text in LEVEL_CHOICES]
        self._level.setCurrentIndex(levels.index(settings.level))
        if settings.size_limit_mb is not None:
            self._limit.setText(f"{settings.size_limit_mb:g}")
        self._hidden_info.setChecked(settings.remove_hidden_info)
        self._show_folder_for_mode()

    def _checked_mode(self) -> SaveMode | None:
        for mode, button in self._mode_buttons.items():
            if button.isChecked():
                return mode
        return None

    def _show_folder_for_mode(self) -> None:
        mode = self._checked_mode()
        if mode is None:
            return
        visible = mode is not SaveMode.REPLACE
        for widget in (self._folder_label, self._folder_path, self._folder_button):
            widget.setVisible(visible)
        if mode is SaveMode.COPY:
            self._folder_label.setText("Output folder:")
            self._folder_path.setText(str(self._output_dir))
        elif mode is SaveMode.BACKUP:
            self._folder_label.setText("Backup folder:")
            self._folder_path.setText(str(self._backup_dir))

    def _choose_folder(self) -> None:
        mode = self._checked_mode()
        current = self._output_dir if mode is SaveMode.COPY else self._backup_dir
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", str(current))
        if not chosen:
            return
        folder = Path(chosen)
        reason = blocked_reason(folder)
        if reason:
            self._warn(reason)
            return
        if mode is SaveMode.COPY:
            self._output_dir = folder
        else:
            self._backup_dir = folder
        self._show_folder_for_mode()

    # Running

    def _start_clicked(self) -> None:
        paths = self._input_paths_text()
        if not paths:
            self._inform(ADD_FIRST)
            return
        valid, limit = parse_limit(self._limit.text())
        if not valid:
            self._warn(BAD_LIMIT)
            return
        self._remember_options(limit)

        self._choose_page.setEnabled(False)
        self._status.setText("Looking for PDF files...")
        worker = ScanWorker([Path(path) for path in paths], self._settings)
        worker.scanned.connect(self._scanned)
        worker.crashed.connect(self._scan_crashed)
        worker.finished.connect(self._worker_finished)
        self._scan_worker = worker
        worker.start()

    def _remember_options(self, limit: float | None) -> None:
        self._settings = Settings(
            save_mode=self._checked_mode() or self._settings.save_mode,
            output_dir=self._output_dir,
            backup_dir=self._backup_dir,
            level=LEVEL_CHOICES[self._level.currentIndex()][0],
            size_limit_mb=limit,
            remove_hidden_info=self._hidden_info.isChecked(),
        )
        try:
            save_settings(self._settings, self._settings_path)
        except OSError:
            logger.exception("Could not save the settings")

    def _scanned(self, scan: ScanResult) -> None:
        self._status.setText("")
        for path, reason in scan.left_out:
            logger.info("Left out %s: %s", path, reason)
        if self._close_when_idle:
            return
        if not scan.jobs:
            self._choose_page.setEnabled(True)
            lines = left_out_lines(scan)
            if lines:
                self._inform(f"{NO_FILES}\n\nThese were left out:\n" + "\n".join(lines))
            else:
                self._inform(NO_FILES)
            return
        if not self._confirm(scan) or (
            self._settings.save_mode is SaveMode.REPLACE and not self._ask(NO_RECOVERY)
        ):
            self._choose_page.setEnabled(True)
            return
        self._start_batch(scan)

    def _scan_crashed(self, message: str) -> None:
        self._status.setText("")
        self._choose_page.setEnabled(True)
        self._warn(message)

    def _confirm(self, scan: ScanResult) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(TITLE)
        box.setIcon(QMessageBox.Icon.Question)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(confirmation_html(scan, self._settings))
        start = box.addButton("Start", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(start)
        box.exec()
        return box.clickedButton() is start

    def _start_batch(self, scan: ScanResult) -> None:
        self._last_scan = scan
        total = len(scan.jobs)
        self._pages.setCurrentIndex(1)
        self._summary.setText("Compressing...")
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        self._progress.setFormat(f"0 of {total}")
        self._progress.show()
        self._cancel.setText("Cancel")
        self._cancel.setEnabled(True)
        self._cancel.show()
        self._current_file.setText("")
        self._current_file.show()
        self._table.setRowCount(0)
        self._table.hide()
        self._back.hide()
        self._open_folder.hide()

        worker = BatchWorker(scan, self._settings, self._data_dir)
        worker.progress.connect(self._progressed)
        worker.done.connect(self._run_done)
        worker.crashed.connect(self._run_crashed)
        worker.finished.connect(self._worker_finished)
        self._batch_worker = worker
        worker.start()

    def _progressed(self, number: int, total: int, name: str) -> None:
        self._progress.setValue(number - 1)
        # The file name goes in a label: the bar's format would treat % signs
        # in a file name as placeholders.
        self._progress.setFormat(f"{number} of {total}")
        self._current_file.setText(name)

    def _cancel_clicked(self) -> None:
        if self._batch_worker is not None:
            self._batch_worker.cancel()
        self._cancel.setText("Stopping after this file")
        self._cancel.setEnabled(False)

    def _run_done(self, result: BatchResult) -> None:
        self._progress.hide()
        self._cancel.hide()
        self._current_file.hide()
        self._summary.setText(summary_text(result))
        self._fill_table(result.results)
        self._table.show()
        folder = self._result_folder()
        self._open_folder.setVisible(folder is not None and folder.is_dir())
        self._back.show()

    def _run_crashed(self, message: str) -> None:
        self._pages.setCurrentIndex(0)
        self._choose_page.setEnabled(True)
        self._warn(message)

    def _fill_table(self, results: list[FileResult]) -> None:
        self._table.setRowCount(len(results))
        names = short_names([result.source for result in results])
        for row, (result, name) in enumerate(zip(results, names, strict=True)):
            after = "" if result.after is None else format_mb(result.after)
            cells = [
                name,
                format_mb(result.before),
                after,
                result.message,
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(str(result.source) if column == 0 else text)
                if result.over_limit:
                    item.setBackground(QBrush(QColor(OVER_LIMIT_BACKGROUND)))
                    item.setForeground(QBrush(QColor(OVER_LIMIT_TEXT)))
                self._table.setItem(row, column, item)
        self._table.resizeRowsToContents()

    def _result_folder(self) -> Path | None:
        if self._settings.save_mode is SaveMode.COPY:
            return self._settings.output_dir
        if self._last_scan is not None and self._last_scan.jobs:
            return self._last_scan.jobs[0].source.parent
        return None

    def _open_folder_clicked(self) -> None:
        folder = self._result_folder()
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _back_clicked(self) -> None:
        self._pages.setCurrentIndex(0)
        self._choose_page.setEnabled(True)

    # Workers and closing

    def _busy(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self._scan_worker, self._batch_worker)
        )

    def _worker_finished(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isFinished():
            self._scan_worker = None
        if self._batch_worker is not None and self._batch_worker.isFinished():
            self._batch_worker = None
        if self._close_when_idle and not self._busy():
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Save the options and close when idle; during a run, ask first."""
        if not self._busy():
            # Options count even without a run. A size limit that can't be
            # read keeps the last saved one, so the other options still save.
            valid, limit = parse_limit(self._limit.text())
            self._remember_options(limit if valid else self._settings.size_limit_mb)
            event.accept()
            return
        if self._batch_worker is not None and not self._close_when_idle:
            if not self._ask(STILL_WORKING):
                event.ignore()
                return
            self._cancel_clicked()
        # Closing while a worker runs would destroy its thread mid-file.
        self._close_when_idle = True
        event.ignore()

    # Messages

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, TITLE, text)

    def _inform(self, text: str) -> None:
        QMessageBox.information(self, TITLE, text)

    def _ask(self, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            TITLE,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


def parse_limit(text: str) -> tuple[bool, float | None]:
    """Read the size limit box: blank means no limit, otherwise a number above 0."""
    cleaned = text.strip()
    if cleaned.lower().endswith("mb"):
        cleaned = cleaned[:-2].strip()
    if not cleaned:
        return True, None
    try:
        value = float(cleaned)
    except ValueError:
        return False, None
    if not math.isfinite(value) or value <= 0:
        return False, None
    return True, value


def left_out_lines(scan: ScanResult) -> list[str]:
    """Return one line per left-out item, the first few only."""
    lines = [
        f"{path.name or path}: {reason}"
        for path, reason in scan.left_out[:LEFT_OUT_SHOWN]
    ]
    extra = len(scan.left_out) - LEFT_OUT_SHOWN
    if extra > 0:
        lines.append(f"And {extra} more.")
    return lines


def confirmation_html(scan: ScanResult, settings: Settings) -> str:
    """Return the text of the dialog shown before every run."""
    count = len(scan.jobs)
    files = "1 PDF file" if count == 1 else f"{count} PDF files"
    folders = "1 folder" if scan.folder_count == 1 else f"{scan.folder_count} folders"
    paragraphs = []
    if count > MANY_FILES:
        paragraphs.append(f"<b>{html.escape(MANY_WARNING)}</b>")
    paragraphs.append(f"Compress {files} ({format_mb(scan.total_bytes)}) in {folders}?")
    if settings.save_mode is SaveMode.COPY:
        if scan.existing_count == 1:
            paragraphs.append(
                "1 file is already in the output folder and will be replaced."
            )
        elif scan.existing_count:
            paragraphs.append(
                f"{scan.existing_count} files are already in the output folder"
                " and will be replaced."
            )
        paragraphs.append(
            f"The compressed copies go to {html.escape(str(settings.output_dir))}."
        )
    elif settings.save_mode is SaveMode.BACKUP:
        paragraphs.append(
            f"Up to {scan.existing_count} original files will be replaced. Their"
            f" backups go to {html.escape(str(settings.backup_dir))}."
        )
    else:
        paragraphs.append(
            f"Up to {scan.existing_count} original files will be replaced,"
            " with no backup."
        )
    lines = left_out_lines(scan)
    if lines:
        items = "<br>".join(html.escape(line) for line in lines)
        paragraphs.append(f"These will be left out:<br>{items}")
    return "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)


def _label(text: str, role: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", role)
    return label
