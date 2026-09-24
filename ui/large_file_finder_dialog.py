"""Tìm file lớn trong hồ sơ người dùng. Không xóa cho đến khi xác nhận."""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.c_drive_clean import (
    DEFAULT_LARGE_FILE_MIN_BYTES,
    delete_large_files,
    scan_large_user_files,
)
from ui.styles import DARK_THEME


class LargeFileScanWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(dict)

    def __init__(self, min_bytes: int, min_age_days: int, include_local_appdata: bool, exclude_paths=None):
        super().__init__()
        self.min_bytes = int(min_bytes)
        self.min_age_days = int(min_age_days)
        self.include_local_appdata = bool(include_local_appdata)
        self.exclude_paths = list(exclude_paths or [])
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        result = scan_large_user_files(
            min_bytes=self.min_bytes,
            min_age_days=self.min_age_days,
            include_local_appdata=self.include_local_appdata,
            progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
            cancel_check=lambda: self._cancel,
            exclude_paths=self.exclude_paths,
        )
        self.finished.emit(result)


class LargeFileDeleteWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, paths, exclude_paths=None):
        super().__init__()
        self.paths = list(paths)
        self.exclude_paths = list(exclude_paths or [])

    def run(self):
        self.finished.emit(delete_large_files(self.paths, exclude_paths=self.exclude_paths))


class LargeFileFinderDialog(QDialog):
    """Danh sách file lớn. Mặc định không chọn dòng nào."""

    def __init__(self, parent=None, exclude_paths=None):
        super().__init__(parent)
        self.exclude_paths = list(exclude_paths or [])
        self.setWindowTitle("Tìm file lớn")
        self.setModal(True)
        self.resize(920, 640)
        self.setMinimumSize(760, 480)
        self.setStyleSheet(DARK_THEME)
        self.scan_worker = None
        self.delete_worker = None
        self._rows = []
        self._checks = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Tìm file lớn")
        title.setStyleSheet("color: #f8fafc; font-size: 16px; font-weight: bold; background: transparent;")
        layout.addWidget(title)

        sub = QLabel(
            "Quét hồ sơ của bạn (và LocalAppData nếu bạn bật). "
            "Không xóa cho đến khi bạn tick dòng và xác nhận. "
            "Mục này không chạy cùng «Dọn ổ C». "
            "Bỏ qua OneDrive, thư mục hệ thống, cơ sở dữ liệu trình duyệt, node_modules, kho pnpm "
            "và đường dẫn trong danh sách loại trừ."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        layout.addWidget(sub)

        controls = QFrame()
        controls.setObjectName("LargeFileControls")
        controls.setStyleSheet("""
            QFrame#LargeFileControls {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
            }
        """)
        row = QHBoxLayout(controls)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(8)

        lbl_size = QLabel("Ngưỡng:")
        lbl_size.setStyleSheet("color: #cbd5e1; background: transparent; border: none;")
        self.combo_size = QComboBox()
        self.combo_size.addItem("≥ 50 MB", 50 * 1024 * 1024)
        self.combo_size.addItem("≥ 100 MB", DEFAULT_LARGE_FILE_MIN_BYTES)
        self.combo_size.addItem("≥ 500 MB", 500 * 1024 * 1024)
        self.combo_size.addItem("≥ 1 GB", 1024 * 1024 * 1024)
        self.combo_size.setCurrentIndex(1)

        lbl_age = QLabel("Tuổi:")
        lbl_age.setStyleSheet("color: #cbd5e1; background: transparent; border: none;")
        self.combo_age = QComboBox()
        self.combo_age.addItem("Mọi độ tuổi", 0)
        self.combo_age.addItem("Cũ hơn 30 ngày", 30)
        self.combo_age.addItem("Cũ hơn 90 ngày", 90)
        self.combo_age.addItem("Cũ hơn 180 ngày", 180)

        self.chk_local = QCheckBox("Quét thêm LocalAppData")
        self.chk_local.setChecked(False)
        self.chk_local.setStyleSheet("color: #e2e8f0; background: transparent; border: none;")

        self.btn_scan = QPushButton("Quét")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_stop = QPushButton("Dừng")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_scan)

        row.addWidget(lbl_size)
        row.addWidget(self.combo_size)
        row.addWidget(lbl_age)
        row.addWidget(self.combo_age)
        row.addWidget(self.chk_local)
        row.addStretch()
        row.addWidget(self.btn_scan)
        row.addWidget(self.btn_stop)
        layout.addWidget(controls)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Chọn", "Đường dẫn", "Dung lượng", "Tuổi"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setColumnWidth(0, 72)
        layout.addWidget(self.table, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        self.lbl_summary = QLabel("Chưa quét. Không có tệp nào bị xóa.")
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setStyleSheet("color: #cbd5e1; font-size: 12px; background: transparent;")
        layout.addWidget(self.lbl_summary)

        actions = QHBoxLayout()
        self.btn_close = QPushButton("Đóng")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.reject)
        self.btn_delete = QPushButton("Xóa các mục đã chọn")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self.confirm_delete)
        actions.addStretch()
        actions.addWidget(self.btn_close)
        actions.addWidget(self.btn_delete)
        layout.addLayout(actions)

    def start_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.table.setRowCount(0)
        self._rows = []
        self._checks = []
        self.btn_delete.setEnabled(False)
        self.lbl_summary.setText("Đang quét… chưa xóa tệp nào.")
        self.scan_worker = LargeFileScanWorker(
            int(self.combo_size.currentData()),
            int(self.combo_age.currentData()),
            self.chk_local.isChecked(),
            exclude_paths=self.exclude_paths,
        )
        self.scan_worker.progress.connect(self._on_progress)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self._set_busy(True, scanning=True)
        self.scan_worker.start()

    def stop_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.lbl_summary.setText("Đang dừng quét…")

    def _on_progress(self, message: str, percent: int):
        self.lbl_summary.setText(message)
        self.progress.setValue(int(percent))

    def _on_scan_finished(self, result: dict):
        self._set_busy(False, scanning=False)
        self.progress.setVisible(False)
        self.show_files(result or {})

    def show_files(self, result: dict):
        data = result if isinstance(result, dict) else {}
        files = [row for row in (data.get("files") or []) if isinstance(row, dict)]
        self._rows = files
        self._checks = []
        self.table.setRowCount(len(files))
        for index, row in enumerate(files):
            path = str(row.get("path") or "")
            box = QCheckBox()
            box.setChecked(False)
            box.setProperty("filePath", path)
            box.setStyleSheet("""
                QCheckBox { background: transparent; spacing: 0px; }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #94a3b8;
                    border-radius: 4px;
                    background: #0f172a;
                }
                QCheckBox::indicator:checked {
                    background: #0f766e;
                    border: 2px solid #5eead4;
                }
            """)
            box.stateChanged.connect(self._on_check_changed)
            holder = QWidget()
            holder.setStyleSheet("background: transparent;")
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.addWidget(box)
            holder_layout.setAlignment(Qt.AlignCenter)
            self.table.setCellWidget(index, 0, holder)
            self._checks.append(box)
            path_item = QTableWidgetItem(path)
            path_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            path_item.setToolTip(path)
            size_item = QTableWidgetItem(str(row.get("size_label_vi") or ""))
            size_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            age_item = QTableWidgetItem(str(row.get("age_label_vi") or ""))
            age_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(index, 1, path_item)
            self.table.setItem(index, 2, size_item)
            self.table.setItem(index, 3, age_item)
        count = len(files)
        extra = ""
        if data.get("truncated") and data.get("truncate_reason_vi"):
            extra = " " + str(data.get("truncate_reason_vi"))
        if count == 0:
            text = "Không thấy tệp lớn nào với ngưỡng này. Chưa xóa tệp nào." + extra
        else:
            text = (
                f"Tìm thấy {count} tệp. Chưa chọn mục nào — tick dòng rồi bấm xóa nếu muốn."
                + extra
            )
        self.lbl_summary.setText(text.strip())
        self.btn_delete.setEnabled(False)

    def _checked_paths(self):
        paths = []
        for box in getattr(self, "_checks", []):
            if box.isChecked():
                path = str(box.property("filePath") or "")
                if path:
                    paths.append(path)
        return paths

    def _on_check_changed(self, _state):
        self.btn_delete.setEnabled(bool(self._checked_paths()))

    def confirm_delete(self):
        paths = self._checked_paths()
        if not paths:
            QMessageBox.information(
                self,
                "Chưa chọn tệp",
                "Hãy tick ít nhất một tệp. Mặc định không chọn sẵn.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Xác nhận xóa file lớn",
            (
                f"Xóa {len(paths)} tệp đã chọn?\n\n"
                "Chỉ xóa đúng các dòng bạn đã tick. "
                "Tệp đang khóa sẽ được bỏ qua và không tính dung lượng."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.lbl_summary.setText("Đã hủy. Chưa xóa tệp nào.")
            return
        self.lbl_summary.setText("Đang xóa các tệp đã chọn…")
        self.delete_worker = LargeFileDeleteWorker(paths, exclude_paths=self.exclude_paths)
        self.delete_worker.finished.connect(self._on_delete_finished)
        self._set_busy(True, scanning=False)
        self.delete_worker.start()

    def _on_delete_finished(self, result: dict):
        self._set_busy(False, scanning=False)
        data = result if isinstance(result, dict) else {}
        removed = set(data.get("deleted") or [])
        kept = [row for row in self._rows if str(row.get("path") or "") not in removed]
        self.show_files({
            "files": kept,
            "truncated": False,
            "truncate_reason_vi": "",
        })
        self.lbl_summary.setText(str(data.get("report_vi") or "Đã xong."))

    def _set_busy(self, busy: bool, *, scanning: bool = False):
        self.btn_scan.setEnabled(not busy)
        self.btn_stop.setEnabled(busy and scanning)
        self.btn_delete.setEnabled((not busy) and bool(self._checked_paths()))
        self.combo_size.setEnabled(not busy)
        self.combo_age.setEnabled(not busy)
        self.chk_local.setEnabled(not busy)

    def closeEvent(self, event):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.scan_worker.wait(2000)
        if self.delete_worker and self.delete_worker.isRunning():
            self.delete_worker.wait(2000)
        super().closeEvent(event)
