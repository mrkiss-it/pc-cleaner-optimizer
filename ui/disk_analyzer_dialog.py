"""
Disk Analyzer Dialog - Hộp thoại trực quan hóa không gian lưu trữ ổ đĩa.

Hiển thị:
  - Thanh phân bổ màu sắc theo 8 nhóm tệp
  - Bảng Top thư mục và tệp lớn nhất
  - Tùy chọn xóa an toàn vào Thùng rác hoặc mở Explorer
"""
import os
import ctypes
import subprocess
from ctypes import wintypes

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush, QPen
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QComboBox, QWidget, QFrame, QFileDialog, QMessageBox,
    QTabWidget, QLineEdit, QSizePolicy, QAbstractItemView
)

from core.disk_analyzer import DiskAnalyzer, CATEGORY_COLORS
from core.logger import logger


# Win32 Shell File Operation (an toàn - vào Thùng rác)
FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


def _trash_file_win32(path: str) -> bool:
    """Chuyển tệp vào Thùng rác Windows an toàn qua SHFileOperationW."""
    try:
        class SHFILEOPSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", ctypes.c_uint),
                ("pFrom", ctypes.c_wchar_p),
                ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", ctypes.c_bool),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p),
            ]
        op = SHFILEOPSTRUCT()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = path + "\0\0"
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return ret == 0
    except Exception as e:
        logger.error(f"[DiskAnalyzerDialog] Lỗi khi chuyển vào Thùng rác: {e}")
        return False


class ColorBar(QWidget):
    """Widget thanh phân bổ màu sắc hiển thị tỷ lệ dung lượng từng danh mục."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []  # [(color_hex, percent), ...]
        self.setMinimumHeight(28)
        self.setMaximumHeight(28)

    def set_data(self, categories: dict):
        """Nhận dict categories từ DiskAnalyzer và cập nhật thanh màu."""
        self.data = []
        for cat, info in sorted(categories.items(), key=lambda x: x[1]["size_mb"], reverse=True):
            pct = info.get("percent", 0)
            if pct > 0.5:
                self.data.append((info.get("color", "#64748b"), pct, cat, info.get("size_mb", 0)))
        self.update()

    def paintEvent(self, event):
        if not self.data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        x = 0
        total_pct = sum(d[1] for d in self.data)
        scale = 100.0 / max(total_pct, 1)

        for i, (color, pct, cat, _) in enumerate(self.data):
            bar_w = int(w * pct * scale / 100)
            if i == len(self.data) - 1:
                bar_w = w - x  # Fill remainder

            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.NoPen)
            if i == 0:
                painter.drawRoundedRect(x, 0, bar_w, h, 6, 6)
                # Re-fill right part without rounding
                painter.drawRect(x + 6, 0, bar_w - 6, h)
            elif i == len(self.data) - 1:
                painter.drawRoundedRect(x, 0, bar_w, h, 6, 6)
                painter.drawRect(x, 0, bar_w - 6, h)
            else:
                painter.drawRect(x, 0, bar_w, h)
            x += bar_w

        painter.end()


class DiskAnalyzerDialog(QDialog):
    """Hộp thoại phân tích và trực quan hóa không gian ổ đĩa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Phân Tích Không Gian Lưu Trữ (Disk Space Analyzer)")
        self.resize(900, 620)
        self.setMinimumSize(780, 520)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QLabel { color: #f8fafc; }
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #334155; color: #f8fafc; }
            QPushButton[class="btn-primary"] {
                background-color: #0284c7;
                color: white;
                border-color: #0369a1;
            }
            QPushButton[class="btn-primary"]:hover { background-color: #0369a1; }
            QPushButton[class="btn-danger"] {
                background-color: #881337;
                color: #fda4af;
                border-color: #9f1239;
            }
            QPushButton[class="btn-danger"]:hover { background-color: #9f1239; }
            QComboBox {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 10px;
            }
            QComboBox::drop-down { border: none; }
            QLineEdit {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 10px;
            }
            QTableWidget {
                background-color: #0f172a;
                alternate-background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                gridline-color: #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                border: none;
                padding: 6px;
                font-weight: bold;
                font-size: 11px;
            }
            QProgressBar {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                height: 10px;
            }
            QProgressBar::chunk { background-color: #0284c7; border-radius: 6px; }
            QTabWidget::pane { border: 1px solid #334155; border-radius: 6px; }
            QTabBar::tab {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 8px 16px;
                border-radius: 6px 6px 0 0;
                margin-right: 2px;
            }
            QTabBar::tab:selected { background-color: #0284c7; color: white; }
        """)

        self._scan_worker = None
        self._last_result = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        # --- Header ---
        hdr = QHBoxLayout()
        lbl_title = QLabel("📊 PHÂN TÍCH KHÔNG GIAN LƯU TRỮ Ổ ĐĨA")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        lbl_sub = QLabel("Trực quan hóa phân bổ dung lượng và tìm kiếm tệp chiếm nhiều không gian nhất")
        lbl_sub.setStyleSheet("color: #64748b; font-size: 11px;")
        title_box = QVBoxLayout()
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        hdr.addLayout(title_box)
        hdr.addStretch()
        layout.addLayout(hdr)

        # --- Scan Control Bar ---
        ctrl = QHBoxLayout()
        lbl_scan = QLabel("Quét thư mục:")
        lbl_scan.setStyleSheet("color: #94a3b8;")
        self.combo_scan = QComboBox()
        self.combo_scan.addItem("📂 Thư mục người dùng (Downloads, Desktop, Documents...)", "user")
        self.combo_scan.addItem("💾 Ổ C:\\ (Toàn bộ)", "C:\\")
        self.combo_scan.addItem("💾 Ổ D:\\ (Toàn bộ)", "D:\\")
        self.combo_scan.addItem("📁 Tùy chọn thư mục...", "custom")
        self.combo_scan.setMinimumWidth(340)

        self.btn_scan = QPushButton("🔍 BẮT ĐẦU PHÂN TÍCH")
        self.btn_scan.setProperty("class", "btn-primary")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self._start_scan)

        self.btn_stop = QPushButton("⏹ Dừng")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)

        ctrl.addWidget(lbl_scan)
        ctrl.addWidget(self.combo_scan)
        ctrl.addWidget(self.btn_scan)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # --- Progress Bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #64748b; font-size: 11px;")
        prog_row = QHBoxLayout()
        prog_row.addWidget(self.progress_bar)
        prog_row.addWidget(self.lbl_progress)
        layout.addLayout(prog_row)

        # --- Summary Stats Row ---
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet("QFrame { background-color: #1e293b; border-radius: 8px; border: 1px solid #334155; }")
        stats_layout = QHBoxLayout(self.stats_frame)
        stats_layout.setContentsMargins(14, 10, 14, 10)

        self.lbl_total_size = QLabel("--")
        self.lbl_total_size.setStyleSheet("font-size: 22px; font-weight: 800; color: #38bdf8;")
        self.lbl_file_count = QLabel("--")
        self.lbl_file_count.setStyleSheet("font-size: 16px; font-weight: 600; color: #94a3b8;")
        self.lbl_scan_path = QLabel("Chưa quét")
        self.lbl_scan_path.setStyleSheet("font-size: 11px; color: #64748b;")
        self.lbl_scan_path.setWordWrap(True)

        left_stats = QVBoxLayout()
        left_stats.addWidget(QLabel("Tổng dung lượng:"))
        left_stats.addWidget(self.lbl_total_size)

        mid_stats = QVBoxLayout()
        mid_stats.addWidget(QLabel("Số tệp phát hiện:"))
        mid_stats.addWidget(self.lbl_file_count)

        right_stats = QVBoxLayout()
        right_stats.addWidget(QLabel("Đường dẫn đã quét:"))
        right_stats.addWidget(self.lbl_scan_path)

        stats_layout.addLayout(left_stats)
        stats_layout.addSpacing(30)
        stats_layout.addLayout(mid_stats)
        stats_layout.addSpacing(30)
        stats_layout.addLayout(right_stats, stretch=2)
        layout.addWidget(self.stats_frame)

        # --- Color Bar ---
        bar_label = QLabel("Phân bổ dung lượng theo loại tệp:")
        bar_label.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        layout.addWidget(bar_label)

        self.color_bar = ColorBar()
        layout.addWidget(self.color_bar)

        # --- Legend ---
        self.legend_layout = QHBoxLayout()
        self.legend_layout.setSpacing(10)
        layout.addLayout(self.legend_layout)

        # --- Tabs: Top Files / Top Dirs ---
        self.tabs = QTabWidget()
        self.tab_files = QWidget()
        self.tab_dirs = QWidget()
        self.tabs.addTab(self.tab_files, "📄 Tệp Tin Lớn Nhất")
        self.tabs.addTab(self.tab_dirs, "📁 Thư Mục Lớn Nhất")
        layout.addWidget(self.tabs)

        self._init_files_tab()
        self._init_dirs_tab()

        # --- Bottom Buttons ---
        btn_close = QPushButton("✕ Đóng")
        btn_close.clicked.connect(self.close)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def _init_files_tab(self):
        layout = QVBoxLayout(self.tab_files)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        # Search bar
        search_row = QHBoxLayout()
        lbl_search = QLabel("🔍 Lọc tên tệp:")
        lbl_search.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Nhập tên tệp để lọc...")
        self.search_box.textChanged.connect(self._filter_files_table)
        search_row.addWidget(lbl_search)
        search_row.addWidget(self.search_box)
        search_row.addStretch()
        layout.addLayout(search_row)

        self.table_files = QTableWidget()
        self.table_files.setColumnCount(5)
        self.table_files.setHorizontalHeaderLabels(["Tên tệp", "Loại", "Kích thước", "Thư mục chứa", "Thao tác"])
        self.table_files.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_files.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_files.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_files.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_files.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_files.verticalHeader().setVisible(False)
        self.table_files.setAlternatingRowColors(True)
        self.table_files.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table_files)

    def _init_dirs_tab(self):
        layout = QVBoxLayout(self.tab_dirs)
        layout.setContentsMargins(0, 8, 0, 0)

        self.table_dirs = QTableWidget()
        self.table_dirs.setColumnCount(4)
        self.table_dirs.setHorizontalHeaderLabels(["Thư mục", "Dung lượng", "Tỷ lệ (%)", "Thao tác"])
        self.table_dirs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_dirs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_dirs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_dirs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_dirs.verticalHeader().setVisible(False)
        self.table_dirs.setAlternatingRowColors(True)
        layout.addWidget(self.table_dirs)

    def _start_scan(self):
        scan_choice = self.combo_scan.currentData()

        if scan_choice == "custom":
            folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục để phân tích", os.path.expanduser("~"))
            if not folder:
                return
            paths = [folder]
        elif scan_choice == "user":
            paths = DiskAnalyzer.get_default_scan_paths()
        else:
            paths = [scan_choice]

        # Dừng worker cũ nếu có
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.request_stop()
            self._scan_worker.wait(3000)

        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.lbl_progress.setText("Đang khởi tạo quét...")
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.table_files.setRowCount(0)
        self.table_dirs.setRowCount(0)

        self._scan_worker = DiskAnalyzer.create_worker(paths, min_file_size_mb=5.0)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.scan_finished.connect(self._on_scan_finished)
        self._scan_worker.error_occurred.connect(self._on_scan_error)
        self._scan_worker.start()

    def _stop_scan(self):
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.request_stop()
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.lbl_progress.setText("Đã dừng quét.")

    def _on_scan_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.lbl_progress.setText(msg[:80] + "..." if len(msg) > 80 else msg)

    def _on_scan_error(self, error_msg: str):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.lbl_progress.setText(f"Lỗi: {error_msg}")

    def _on_scan_finished(self, result: dict):
        self._last_result = result
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.lbl_progress.setText("")

        total_mb = result.get("total_mb", 0)
        total_gb = result.get("total_gb", 0)
        file_count = result.get("file_count", 0)
        paths = result.get("scanned_paths", [])

        if total_gb >= 1.0:
            self.lbl_total_size.setText(f"{total_gb:.2f} GB")
        else:
            self.lbl_total_size.setText(f"{total_mb:.1f} MB")

        self.lbl_file_count.setText(f"{file_count:,} tệp")
        self.lbl_scan_path.setText(" | ".join(paths[:3]))

        # Cập nhật color bar
        categories = result.get("categories", {})
        self.color_bar.set_data(categories)

        # Cập nhật legend
        for i in reversed(range(self.legend_layout.count())):
            w = self.legend_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

        for cat, info in sorted(categories.items(), key=lambda x: x[1]["size_mb"], reverse=True):
            if info["size_mb"] < 1:
                continue
            size_txt = f"{info['size_mb'] / 1024:.2f} GB" if info['size_mb'] >= 1024 else f"{info['size_mb']:.0f} MB"
            legend_lbl = QLabel(f"■ {cat}: {size_txt} ({info['percent']:.1f}%)")
            legend_lbl.setStyleSheet(f"color: {info['color']}; font-size: 10px;")
            self.legend_layout.addWidget(legend_lbl)
        self.legend_layout.addStretch()

        # Populate tables
        self._populate_files_table(result.get("top_files", []))
        self._populate_dirs_table(result.get("top_dirs", []))

    def _populate_files_table(self, files: list):
        self.table_files.setRowCount(len(files))
        for row, f in enumerate(files):
            name_item = QTableWidgetItem(f.get("name", ""))
            name_item.setForeground(QColor("#f8fafc"))
            name_item.setFont(QFont("Segoe UI", 9, QFont.Bold))

            cat = f.get("category", "Khác")
            cat_item = QTableWidgetItem(cat)
            cat_item.setTextAlignment(Qt.AlignCenter)
            cat_item.setForeground(QColor(CATEGORY_COLORS.get(cat, "#64748b")))

            size_mb = f.get("size_mb", 0)
            if size_mb >= 1024:
                size_txt = f"{size_mb/1024:.2f} GB"
            else:
                size_txt = f"{size_mb:.1f} MB"
            size_item = QTableWidgetItem(size_txt)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            size_item.setForeground(QColor("#38bdf8"))
            size_item.setFont(QFont("Segoe UI", 9, QFont.Bold))

            dir_item = QTableWidgetItem(os.path.dirname(f.get("path", "")))
            dir_item.setForeground(QColor("#64748b"))

            # Action widget
            action_w = QWidget()
            action_l = QHBoxLayout(action_w)
            action_l.setContentsMargins(4, 2, 4, 2)
            action_l.setSpacing(4)

            btn_open = QPushButton("📂")
            btn_open.setFixedWidth(36)
            btn_open.setToolTip("Mở thư mục chứa trong Explorer")
            btn_open.clicked.connect(lambda _, p=f.get("path", ""): self._open_in_explorer(p))

            btn_trash = QPushButton("🗑️")
            btn_trash.setFixedWidth(36)
            btn_trash.setProperty("class", "btn-danger")
            btn_trash.setToolTip("Chuyển vào Thùng rác (có thể khôi phục)")
            btn_trash.clicked.connect(lambda _, p=f.get("path", ""), r=row: self._trash_file(p, r))

            action_l.addWidget(btn_open)
            action_l.addWidget(btn_trash)

            self.table_files.setItem(row, 0, name_item)
            self.table_files.setItem(row, 1, cat_item)
            self.table_files.setItem(row, 2, size_item)
            self.table_files.setItem(row, 3, dir_item)
            self.table_files.setCellWidget(row, 4, action_w)

    def _populate_dirs_table(self, dirs: list):
        self.table_dirs.setRowCount(len(dirs))
        for row, d in enumerate(dirs):
            name_item = QTableWidgetItem(d.get("name", ""))
            name_item.setForeground(QColor("#f8fafc"))
            name_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
            name_item.setToolTip(d.get("path", ""))

            size_mb = d.get("size_mb", 0)
            if size_mb >= 1024:
                size_txt = f"{size_mb/1024:.2f} GB"
            else:
                size_txt = f"{size_mb:.1f} MB"
            size_item = QTableWidgetItem(size_txt)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            size_item.setForeground(QColor("#38bdf8"))
            size_item.setFont(QFont("Segoe UI", 9, QFont.Bold))

            pct_item = QTableWidgetItem(f"{d.get('percent', 0):.1f}%")
            pct_item.setTextAlignment(Qt.AlignCenter)
            pct_item.setForeground(QColor("#a855f7"))

            btn_open = QPushButton("📂 Mở")
            btn_open.setToolTip("Mở thư mục trong Explorer")
            btn_open.clicked.connect(lambda _, p=d.get("path", ""): subprocess.Popen(["explorer", p]))

            self.table_dirs.setItem(row, 0, name_item)
            self.table_dirs.setItem(row, 1, size_item)
            self.table_dirs.setItem(row, 2, pct_item)
            self.table_dirs.setCellWidget(row, 3, btn_open)

    def _filter_files_table(self, text: str):
        if not self._last_result:
            return
        all_files = self._last_result.get("top_files", [])
        filtered = [f for f in all_files if text.lower() in f.get("name", "").lower()] if text else all_files
        self._populate_files_table(filtered)

    def _open_in_explorer(self, path: str):
        """Mở thư mục chứa tệp trong Explorer và tự động chọn (highlight) tệp."""
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", path])
        elif os.path.exists(os.path.dirname(path)):
            subprocess.Popen(["explorer", os.path.dirname(path)])

    def _trash_file(self, path: str, row: int):
        """Chuyển tệp vào Thùng rác với xác nhận."""
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Không tìm thấy tệp", f"Tệp không còn tồn tại:\n{path}")
            return

        name = os.path.basename(path)
        size_mb = os.path.getsize(path) / (1024 ** 2)
        confirm = QMessageBox.question(
            self, "Xác Nhận Chuyển Vào Thùng Rác",
            f"Bạn có muốn chuyển tệp này vào Thùng rác không?\n\n"
            f"📄 {name}\n💾 {size_mb:.1f} MB\n\n"
            f"Bạn vẫn có thể khôi phục lại tệp này từ Thùng rác nếu cần.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            success = _trash_file_win32(path)
            if success:
                self.table_files.removeRow(row)
                logger.info(f"[DiskAnalyzerDialog] Đã chuyển vào Thùng rác: {path}")
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể chuyển tệp vào Thùng rác:\n{path}")

    def closeEvent(self, event):
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.request_stop()
            self._scan_worker.wait(2000)
        super().closeEvent(event)
