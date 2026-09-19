import os
import subprocess
from typing import List, Dict, Any
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QProgressBar, QMessageBox, QFileDialog, QFrame,
    QMenu, QAction
)

from core.cleaner import LargeFileScanner, format_file_size
from core.logger import logger
from ui.styles import DARK_THEME

class LargeFileScanWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(list)

    def __init__(self, root_paths: List[str], min_size_mb: int):
        super().__init__()
        self.root_paths = root_paths
        self.min_size_mb = min_size_mb
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        results = LargeFileScanner.scan_large_files(
            root_paths=self.root_paths,
            min_size_mb=self.min_size_mb,
            progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
            cancel_check=lambda: self._is_cancelled
        )
        self.finished.emit(results)


class LargeFilesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản Lý & Quét Tệp Dung Lượng Lớn (>100MB)")
        self.resize(960, 620)
        self.setMinimumSize(850, 520)
        self.setStyleSheet(DARK_THEME)

        self.worker: LargeFileScanWorker = None
        self.all_files: List[Dict[str, Any]] = []
        self.custom_folder: str = ""

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Header Title
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        lbl_title = QLabel("🔍 BỘ QUÉT & QUẢN LÝ TỆP TIN DUNG LƯỢNG LỚN")
        lbl_title.setStyleSheet("color: #f8fafc; font-size: 17px; font-weight: 800; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Phát hiện các tệp chiếm nhiều dung lượng đĩa và hỗ trợ xóa an toàn vào Thùng Rác (có thể hoàn tác Ctrl+Z)")
        lbl_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header_layout.addWidget(lbl_title)
        header_layout.addWidget(lbl_sub)
        layout.addLayout(header_layout)

        # Control Panel / Filter Bar
        ctrl_card = QFrame()
        ctrl_card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 4px;
            }
        """)
        ctrl_layout = QHBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(14, 10, 14, 10)
        ctrl_layout.setSpacing(12)

        # 1. Size threshold
        lbl_size = QLabel("Dung lượng tối thiểu:")
        lbl_size.setStyleSheet("color: #cbd5e1; font-weight: 600; border: none;")
        self.combo_size = QComboBox()
        self.combo_size.addItem("≥ 100 MB", 100)
        self.combo_size.addItem("≥ 500 MB", 500)
        self.combo_size.addItem("≥ 1 GB (1024 MB)", 1024)
        self.combo_size.addItem("≥ 2 GB (2048 MB)", 2048)

        # 2. Location
        lbl_loc = QLabel("Vị trí quét:")
        lbl_loc.setStyleSheet("color: #cbd5e1; font-weight: 600; border: none;")
        self.combo_loc = QComboBox()
        self.combo_loc.addItem("📁 Thư mục cá nhân (Downloads, Desktop, Documents, Videos...)", "user")
        self.combo_loc.addItem("📂 Chọn thư mục khác...", "custom")
        self.combo_loc.currentIndexChanged.connect(self._on_location_changed)

        # Buttons Scan & Stop
        self.btn_scan = QPushButton("🔍 Bắt Đầu Quét")
        self.btn_scan.setProperty("class", "btn-primary")
        self.btn_scan.setCursor(Qt.PointingHandCursor)
        self.btn_scan.clicked.connect(self.start_scan)

        self.btn_stop = QPushButton("🛑 Dừng")
        self.btn_stop.setProperty("class", "btn-secondary")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_scan)

        ctrl_layout.addWidget(lbl_size)
        ctrl_layout.addWidget(self.combo_size)
        ctrl_layout.addSpacing(10)
        ctrl_layout.addWidget(lbl_loc)
        ctrl_layout.addWidget(self.combo_loc, stretch=1)
        ctrl_layout.addWidget(self.btn_scan)
        ctrl_layout.addWidget(self.btn_stop)
        layout.addWidget(ctrl_card)

        # Quick Search Box
        search_layout = QHBoxLayout()
        lbl_search = QLabel("🔎 Lọc tên tệp:")
        lbl_search.setStyleSheet("color: #94a3b8; font-weight: 600;")
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Gõ để lọc danh sách file...")
        self.txt_search.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #f8fafc;
                padding: 6px 10px;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
            }
        """)
        self.txt_search.textChanged.connect(self._filter_table)
        search_layout.addWidget(lbl_search)
        search_layout.addWidget(self.txt_search)
        layout.addLayout(search_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Tên Tệp Tin", "Dung Lượng", "Ngày Sửa Đổi", "Định Dạng", "Thư Mục Chứa"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self.open_file_location)
        self.table.setColumnWidth(0, 260)
        layout.addWidget(self.table)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #334155;
                border-radius: 6px;
                text-align: center;
                background-color: #0f172a;
                color: #f8fafc;
                height: 16px;
            }
            QProgressBar::chunk {
                background-color: #0284c7;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Bottom Bar (Summary & Action Buttons)
        bottom_layout = QHBoxLayout()
        self.lbl_summary = QLabel("Chưa thực hiện quét. Bấm 'Bắt Đầu Quét' để phân tích.")
        self.lbl_summary.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")

        self.btn_open_folder = QPushButton("📂 Mở Thư Mục Chứa")
        self.btn_open_folder.setProperty("class", "btn-secondary")
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.clicked.connect(self.open_file_location)

        self.btn_delete_trash = QPushButton("🗑️ Chuyển Vào Thùng Rác (Recycle Bin)")
        self.btn_delete_trash.setProperty("class", "btn-warning")
        self.btn_delete_trash.setCursor(Qt.PointingHandCursor)
        self.btn_delete_trash.clicked.connect(self.delete_selected_file)

        bottom_layout.addWidget(self.lbl_summary)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_open_folder)
        bottom_layout.addWidget(self.btn_delete_trash)
        layout.addLayout(bottom_layout)

    def _on_location_changed(self, idx: int):
        data = self.combo_loc.currentData()
        if data == "custom":
            folder = QFileDialog.getExistingDirectory(self, "Chọn Thư Mục Cần Quét")
            if folder:
                self.custom_folder = folder
                self.combo_loc.setItemText(idx, f"📂 {folder}")
            else:
                self.combo_loc.setCurrentIndex(0)

    def start_scan(self):
        min_size_mb = self.combo_size.currentData()
        roots = None
        if self.combo_loc.currentData() == "custom" and self.custom_folder:
            roots = [self.custom_folder]

        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.lbl_summary.setText("Đang quét tìm tệp tin dung lượng lớn...")

        self.table.setRowCount(0)
        self.all_files = []

        self.worker = LargeFileScanWorker(root_paths=roots, min_size_mb=min_size_mb)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def stop_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_summary.setText("Đang hủy bỏ quá trình quét...")
            self.btn_stop.setEnabled(False)

    def _on_progress(self, msg: str, pct: int):
        self.lbl_summary.setText(msg)
        self.progress_bar.setValue(pct)

    def _on_finished(self, results: List[Dict[str, Any]]):
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setVisible(False)

        self.all_files = results
        self._populate_table(results)

        total_bytes = sum(f["size_bytes"] for f in results)
        total_formatted = format_file_size(total_bytes)
        self.lbl_summary.setText(
            f"✅ Tìm thấy {len(results)} tệp tin lớn | Tổng dung lượng: {total_formatted}"
        )

    def _populate_table(self, file_list: List[Dict[str, Any]]):
        self.table.setRowCount(len(file_list))
        for row_idx, f in enumerate(file_list):
            item_name = QTableWidgetItem(f["filename"])
            item_name.setData(Qt.UserRole, f["path"])
            item_name.setForeground(QColor("#f8fafc"))
            item_name.setFont(QFont("Segoe UI", 10, QFont.Bold))

            item_size = QTableWidgetItem(f["size_formatted"])
            item_size.setTextAlignment(Qt.AlignCenter)
            item_size.setForeground(QColor("#38bdf8"))
            item_size.setFont(QFont("Segoe UI", 10, QFont.Bold))

            item_mod = QTableWidgetItem(f["modified"])
            item_mod.setTextAlignment(Qt.AlignCenter)
            item_mod.setForeground(QColor("#94a3b8"))

            item_ext = QTableWidgetItem(f["extension"])
            item_ext.setTextAlignment(Qt.AlignCenter)
            item_ext.setForeground(QColor("#a855f7"))

            item_dir = QTableWidgetItem(f["directory"])
            item_dir.setForeground(QColor("#64748b"))

            self.table.setItem(row_idx, 0, item_name)
            self.table.setItem(row_idx, 1, item_size)
            self.table.setItem(row_idx, 2, item_mod)
            self.table.setItem(row_idx, 3, item_ext)
            self.table.setItem(row_idx, 4, item_dir)

    def _filter_table(self, text: str):
        query = text.strip().lower()
        if not query:
            self._populate_table(self.all_files)
            return

        filtered = [f for f in self.all_files if query in f["filename"].lower() or query in f["directory"].lower()]
        self._populate_table(filtered)

    def _get_selected_filepath(self) -> str:
        cur_row = self.table.currentRow()
        if cur_row < 0:
            return ""
        item = self.table.item(cur_row, 0)
        return item.data(Qt.UserRole) if item else ""

    def open_file_location(self):
        filepath = self._get_selected_filepath()
        if not filepath or not os.path.exists(filepath):
            QMessageBox.warning(self, "Chú Ý", "Vui lòng chọn một tệp tin hợp lệ từ danh sách.")
            return

        try:
            # Highlight file in Windows Explorer
            norm_path = os.path.normpath(filepath)
            subprocess.Popen(f'explorer /select,"{norm_path}"')
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể mở Windows Explorer: {e}")

    def delete_selected_file(self):
        filepath = self._get_selected_filepath()
        if not filepath:
            QMessageBox.warning(self, "Chú Ý", "Vui lòng chọn một tệp tin cần xóa từ danh sách.")
            return

        cur_row = self.table.currentRow()
        item_name = self.table.item(cur_row, 0).text()
        item_size = self.table.item(cur_row, 1).text()

        confirm = QMessageBox.question(
            self, "Xác Nhận Chuyển Vào Thùng Rác",
            f"Bạn có chắc chắn muốn chuyển tệp sau vào Thùng Rác (Recycle Bin)?\n\n"
            f"• Tên tệp: {item_name}\n"
            f"• Dung lượng: {item_size}\n"
            f"• Đường dẫn: {filepath}\n\n"
            f"Lưu ý: Tệp sẽ nằm trong Recycle Bin và bạn có thể khôi phục lại bất cứ lúc nào.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            res = LargeFileScanner.send_to_recycle_bin(filepath)
            if res.get("success"):
                QMessageBox.information(
                    self, "Thành Công",
                    f"Đã chuyển tệp '{item_name}' vào Thùng Rác thành công!\nBạn đã giải phóng {item_size} dung lượng ổ đĩa."
                )
                # Remove from data and table
                self.all_files = [f for f in self.all_files if f["path"] != filepath]
                self.table.removeRow(cur_row)
                total_bytes = sum(f["size_bytes"] for f in self.all_files)
                self.lbl_summary.setText(
                    f"✅ Còn lại {len(self.all_files)} tệp tin lớn | Tổng dung lượng: {format_file_size(total_bytes)}"
                )
            else:
                QMessageBox.critical(
                    self, "Không Thể Xóa",
                    f"Xảy ra lỗi khi xóa tệp tin: {res.get('error')}\n(Có thể tệp đang được mở bởi một chương trình khác)"
                )

    def _show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e293b;
                border: 1px solid #334155;
                color: #f8fafc;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
            }
        """)
        action_open_loc = menu.addAction("📂 Mở vị trí tệp (Explorer)")
        action_delete = menu.addAction("🗑️ Chuyển vào Thùng Rác")

        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if action == action_open_loc:
            self.open_file_location()
        elif action == action_delete:
            self.delete_selected_file()
