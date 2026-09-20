"""
ui/winsxs_dialog.py – WinSxS & Windows Update Deep Purge Dialog (v3.6 Pro).
Giao diện Fluent Dark 3-Tab quản lý và dọn dẹp chuyên sâu các thành phần hệ thống:
- Tab 1: 🗄️ Kho Thành Phần WinSxS & DISM (StartComponentCleanup, ResetBase, RestoreHealth).
- Tab 2: 📦 Bộ Nhớ Đệm Cập Nhật & Logs (SoftwareDistribution, CBS Logs, Crash Dumps, Windows.old).
- Tab 3: 🚗 Kho Lưu Trữ Driver Cũ (DriverStore FileRepository OEM Drivers Deduplication).
"""

import os
import sys
from typing import List, Dict, Any, Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QFrame, QScrollArea, QAbstractItemView,
    QProgressBar, QPlainTextEdit, QCheckBox, QApplication
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QColor, QIcon

from core.winsxs_cleaner import WinSxSCleaner, UpdateCacheItem, OemDriverItem
from core.logger import logger

# ---------------------------------------------------------------------------
# Fluent Dark Theme Tokens
# ---------------------------------------------------------------------------
_BG_DARK       = "#0d1117"
_PANEL_BG      = "#161b22"
_CARD_BG       = "#1b212c"
_CARD_BORDER   = "#30363d"
_TEXT_WHITE    = "#f0f6fc"
_TEXT_MUTED    = "#8b949e"
_ACCENT_BLUE   = "#58a6ff"
_SUCCESS       = "#3fb950"
_WARNING       = "#d29922"
_DANGER        = "#f85149"
_PURPLE        = "#bc8cff"


# ---------------------------------------------------------------------------
# Background Worker Threads
# ---------------------------------------------------------------------------

class DismWorker(QThread):
    """Worker thread để thực thi các lệnh DISM chạy nền không gây treo giao diện."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, mode: str = "cleanup", reset_base: bool = False):
        super().__init__()
        self.mode = mode               # cleanup | restore_health
        self.reset_base = reset_base

    def run(self):
        if self.mode == "cleanup":
            tag = "ResetBase (Chuyên Sâu)" if self.reset_base else "Chuẩn"
            self.log_signal.emit(f"⏳ Đang khởi chạy lệnh DISM StartComponentCleanup [{tag}]...")
            self.log_signal.emit("Quá trình này có thể mất từ 1 đến 5 phút tùy thuộc cấu hình máy. Vui lòng chờ...")
            ok, msg = WinSxSCleaner.run_dism_cleanup(reset_base=self.reset_base)
            self.finished_signal.emit(ok, msg)
        elif self.mode == "restore_health":
            self.log_signal.emit("⏳ Đang khởi chạy DISM RestoreHealth & SFC Scannow...")
            self.log_signal.emit("Hệ thống đang quét và sửa chữa các tệp tin hệ điều hành bị lỗi...")
            ok, msg = WinSxSCleaner.run_dism_health_repair()
            self.finished_signal.emit(ok, msg)


# ---------------------------------------------------------------------------
# Main Dialog: WinSxSDialog
# ---------------------------------------------------------------------------

class WinSxSDialog(QDialog):
    """
    Hộp thoại Quản Lý & Dọn Dẹp Kho WinSxS, Windows Update & DriverStore (v3.6 Pro).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dọn Dẹp Kho WinSxS & Windows Update Chuyên Sâu (v3.6 Pro)")
        self.resize(1000, 700)
        self.setMinimumSize(880, 580)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_BG_DARK};
                color: {_TEXT_WHITE};
            }}
            QTabWidget::pane {{
                border: 1px solid {_CARD_BORDER};
                background: {_PANEL_BG};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: {_PANEL_BG};
                color: {_TEXT_MUTED};
                padding: 10px 20px;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {_CARD_BORDER};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background: #21262d;
                color: {_ACCENT_BLUE};
                border-bottom: 2px solid {_ACCENT_BLUE};
            }}
            QTabBar::tab:hover:!selected {{
                color: {_TEXT_WHITE};
                background: #1c2128;
            }}
        """)

        # Dữ liệu cache
        self._caches_cache: List[UpdateCacheItem] = []
        self._drivers_all_cache: List[OemDriverItem] = []
        self._drivers_dup_cache: List[OemDriverItem] = []
        self._worker: Optional[DismWorker] = None

        self._build_ui()
        self._refresh_all_data()

    # ------------------------------------------------------------------
    # UI Layout Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 18)
        root_layout.setSpacing(14)

        # Header
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("🗄️")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 26))

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        lbl_title = QLabel("WinSxS & Windows Update Deep Purge")
        lbl_title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        lbl_title.setStyleSheet(f"color: {_TEXT_WHITE};")

        lbl_desc = QLabel("Dọn dẹp kho thành phần WinSxS, bộ đệm cập nhật đã tải về và thanh lọc DriverStore cũ")
        lbl_desc.setFont(QFont("Segoe UI", 9))
        lbl_desc.setStyleSheet(f"color: {_TEXT_MUTED};")
        title_vbox.addWidget(lbl_title)
        title_vbox.addWidget(lbl_desc)

        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()

        self.btn_refresh = QPushButton("🔄 Quét Lại")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setFixedHeight(32)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_ACCENT_BLUE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: #21262d; }}
        """)
        self.btn_refresh.clicked.connect(self._refresh_all_data)
        header_layout.addWidget(self.btn_refresh)

        root_layout.addLayout(header_layout)

        # 3 Tabs
        self.tabs = QTabWidget()
        self.tab_winsxs = QWidget()
        self.tab_caches = QWidget()
        self.tab_drivers = QWidget()

        self._build_winsxs_tab()
        self._build_caches_tab()
        self._build_drivers_tab()

        self.tabs.addTab(self.tab_winsxs, "🗄️ Kho Thành Phần WinSxS & DISM")
        self.tabs.addTab(self.tab_caches, "📦 Bộ Nhớ Đệm Cập Nhật & Logs")
        self.tabs.addTab(self.tab_drivers, "🚗 Kho Lưu Trữ Driver Cũ (DriverStore)")

        root_layout.addWidget(self.tabs, stretch=1)

        # Footer Bottom Bar
        footer_layout = QHBoxLayout()
        self.lbl_status = QLabel("● Đang khởi tạo thông tin hệ thống...")
        self.lbl_status.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        footer_layout.addWidget(self.lbl_status)
        footer_layout.addStretch()

        btn_close = QPushButton("Đóng")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setFixedHeight(30)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: #21262d;
                color: {_TEXT_WHITE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 20px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #30363d; }}
        """)
        btn_close.clicked.connect(self.accept)
        footer_layout.addWidget(btn_close)

        root_layout.addLayout(footer_layout)

    # ------------------------------------------------------------------
    # Tab 1: WinSxS & DISM Engine
    # ------------------------------------------------------------------

    def _build_winsxs_tab(self):
        layout = QVBoxLayout(self.tab_winsxs)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Stat cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.card_winsxs_status = self._create_stat_card("Trạng Thái WinSxS", "Sẵn Sàng", "Thư mục thành phần hệ thống")
        self.card_winsxs_rec = self._create_stat_card("Khuyến Nghị Dọn", "Nên dọn dẹp", "Chuẩn Microsoft DISM")
        self.card_winsxs_saving = self._create_stat_card("Dung Lượng Tiết Kiệm", "1 GB – 5 GB", "Ước tính thu hồi ổ C:")

        cards_layout.addWidget(self.card_winsxs_status)
        cards_layout.addWidget(self.card_winsxs_rec)
        cards_layout.addWidget(self.card_winsxs_saving)
        layout.addLayout(cards_layout)

        # Description Banner
        banner = QFrame()
        banner.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-left: 4px solid {_ACCENT_BLUE};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        b_layout = QVBoxLayout(banner)
        b_layout.setContentsMargins(10, 8, 10, 8)
        b_layout.setSpacing(4)

        b_title = QLabel("💡 Giới Thiệu Về Kho Lưu Trữ Thành Phần Windows (WinSxS):")
        b_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        b_title.setStyleSheet(f"color: {_ACCENT_BLUE};")

        b_desc = QLabel(
            "Thư mục C:\\Windows\\WinSxS lưu trữ các phiên bản tệp tin hệ thống và các bản sao lưu sau mỗi lần Windows Update. "
            "Sau nhiều bản cập nhật, các phiên bản cũ bị thay thế (superseded) sẽ tích tụ chiếm nhiều GB dung lượng. "
            "Dọn dẹp bằng công cụ DISM chính thức của Microsoft sẽ loại bỏ hoàn toàn các tệp dư thừa này một cách an toàn 100%."
        )
        b_desc.setWordWrap(True)
        b_desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")

        b_layout.addWidget(b_title)
        b_layout.addWidget(b_desc)
        layout.addWidget(banner)

        # Action Buttons Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)

        self.btn_dism_std = QPushButton("⚡ 1-Click Dọn Dẹp Chuẩn (StartComponentCleanup)")
        self.btn_dism_std.setFixedHeight(36)
        self.btn_dism_std.setCursor(Qt.PointingHandCursor)
        self.btn_dism_std.setToolTip("Dọn dẹp các thành phần bị thay thế nhưng vẫn giữ khả năng gỡ bỏ bản cập nhật gần nhất.")
        self.btn_dism_std.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #388bfd);
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: #388bfd; }}
            QPushButton:disabled {{ background: #21262d; color: {_TEXT_MUTED}; }}
        """)
        self.btn_dism_std.clicked.connect(lambda: self._on_run_dism(reset_base=False))
        actions_row.addWidget(self.btn_dism_std, stretch=2)

        self.btn_dism_deep = QPushButton("🚀 Dọn Dẹp Chuyên Sâu (/ResetBase)")
        self.btn_dism_deep.setFixedHeight(36)
        self.btn_dism_deep.setCursor(Qt.PointingHandCursor)
        self.btn_dism_deep.setToolTip("Deep Purge: Xóa vĩnh viễn tất cả bản sao lưu cũ, giải phóng tối đa ổ C:.")
        self.btn_dism_deep.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_WARNING};
                border: 1px solid {_WARNING};
                font-weight: bold;
                font-size: 11px;
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: {_WARNING}22; }}
            QPushButton:disabled {{ background: #21262d; color: {_TEXT_MUTED}; border-color: {_CARD_BORDER}; }}
        """)
        self.btn_dism_deep.clicked.connect(lambda: self._on_run_dism(reset_base=True))
        actions_row.addWidget(self.btn_dism_deep, stretch=2)

        self.btn_dism_repair = QPushButton("🩺 Sửa Lỗi Tệp Hệ Thống (RestoreHealth & SFC)")
        self.btn_dism_repair.setFixedHeight(36)
        self.btn_dism_repair.setCursor(Qt.PointingHandCursor)
        self.btn_dism_repair.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_SUCCESS};
                border: 1px solid {_SUCCESS};
                font-weight: bold;
                font-size: 11px;
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: {_SUCCESS}22; }}
            QPushButton:disabled {{ background: #21262d; color: {_TEXT_MUTED}; border-color: {_CARD_BORDER}; }}
        """)
        self.btn_dism_repair.clicked.connect(self._on_run_restore_health)
        actions_row.addWidget(self.btn_dism_repair, stretch=2)

        layout.addLayout(actions_row)

        # Terminal Console Output Live View
        lbl_console = QLabel("📋 Nhật Ký Thực Thi DISM & Hệ Thống:")
        lbl_console.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_console.setStyleSheet(f"color: {_TEXT_WHITE};")
        layout.addWidget(lbl_console)

        self.txt_console = QPlainTextEdit()
        self.txt_console.setReadOnly(True)
        self.txt_console.setFont(QFont("Consolas", 9))
        self.txt_console.setStyleSheet(f"""
            QPlainTextEdit {{
                background: #090d13;
                color: #58a6ff;
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        self.txt_console.setPlaceholderText("Nhật ký thực thi lệnh DISM sẽ hiển thị trực tiếp tại đây...")
        layout.addWidget(self.txt_console, stretch=1)

    # ------------------------------------------------------------------
    # Tab 2: Update Caches & System Logs
    # ------------------------------------------------------------------

    def _build_caches_tab(self):
        layout = QVBoxLayout(self.tab_caches)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.card_cache_total = self._create_stat_card("Tổng Rác Cập Nhật", "0.0 MB", "Dung lượng phát hiện")
        self.card_cache_files = self._create_stat_card("Tổng Số Tệp", "0 tệp", "Tệp tạm & nhật ký")
        self.card_cache_dirs  = self._create_stat_card("Số Danh Mục", "0 mục", "Thư mục hệ thống")

        cards_layout.addWidget(self.card_cache_total)
        cards_layout.addWidget(self.card_cache_files)
        cards_layout.addWidget(self.card_cache_dirs)
        layout.addLayout(cards_layout)

        # Toolbar & Actions
        act_row = QHBoxLayout()
        self.chk_select_all_caches = QCheckBox("Chọn Tất Cả")
        self.chk_select_all_caches.setChecked(True)
        self.chk_select_all_caches.setStyleSheet(f"color: {_TEXT_WHITE}; font-size: 11px;")
        self.chk_select_all_caches.stateChanged.connect(self._on_toggle_all_caches)
        act_row.addWidget(self.chk_select_all_caches)

        act_row.addStretch()

        self.btn_clean_selected_caches = QPushButton("🧹 Dọn Sạch Bộ Đệm Đã Chọn")
        self.btn_clean_selected_caches.setFixedHeight(32)
        self.btn_clean_selected_caches.setCursor(Qt.PointingHandCursor)
        self.btn_clean_selected_caches.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2ea043);
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: #2ea043; }}
        """)
        self.btn_clean_selected_caches.clicked.connect(self._on_clean_selected_caches)
        act_row.addWidget(self.btn_clean_selected_caches)
        layout.addLayout(act_row)

        # Table
        self.table_caches = QTableWidget()
        self.table_caches.setColumnCount(5)
        self.table_caches.setHorizontalHeaderLabels([
            "Chọn", "Danh Mục", "Đường Dẫn", "Dung Lượng", "Số Tệp"
        ])
        self.table_caches.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_caches.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_caches.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_caches.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_caches.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_caches.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_caches.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_caches.verticalHeader().setVisible(False)
        self.table_caches.setShowGrid(False)
        self._apply_table_style(self.table_caches)
        layout.addWidget(self.table_caches, stretch=1)

    # ------------------------------------------------------------------
    # Tab 3: DriverStore & OEM Drivers Purge
    # ------------------------------------------------------------------

    def _build_drivers_tab(self):
        layout = QVBoxLayout(self.tab_drivers)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.card_drv_total = self._create_stat_card("Tổng Gói Driver OEM", "0 gói", "Trong DriverStore")
        self.card_drv_dups  = self._create_stat_card("Bản Cũ Trùng Lặp", "0 gói", "Có thể dọn dẹp")
        self.card_drv_safe  = self._create_stat_card("Bảo Vệ Phần Cứng", "100% An Toàn", "Windows tự động giữ lại")

        cards_layout.addWidget(self.card_drv_total)
        cards_layout.addWidget(self.card_drv_dups)
        cards_layout.addWidget(self.card_drv_safe)
        layout.addLayout(cards_layout)

        # Action bar
        act_row = QHBoxLayout()
        lbl_info = QLabel("💡 Danh sách các gói Driver OEM có nhiều phiên bản lưu trong DriverStore (FileRepository):")
        lbl_info.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        act_row.addWidget(lbl_info)

        act_row.addStretch()

        self.btn_clean_duplicate_drivers = QPushButton("🗑️ Dọn Dẹp Các Phiên Bản Driver Cũ")
        self.btn_clean_duplicate_drivers.setFixedHeight(32)
        self.btn_clean_duplicate_drivers.setCursor(Qt.PointingHandCursor)
        self.btn_clean_duplicate_drivers.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_DANGER};
                border: 1px solid {_DANGER};
                font-weight: bold;
                font-size: 11px;
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: {_DANGER}22; }}
            QPushButton:disabled {{ background: #21262d; color: {_TEXT_MUTED}; border-color: {_CARD_BORDER}; }}
        """)
        self.btn_clean_duplicate_drivers.clicked.connect(self._on_clean_duplicate_drivers)
        act_row.addWidget(self.btn_clean_duplicate_drivers)
        layout.addLayout(act_row)

        # Table
        self.table_drivers = QTableWidget()
        self.table_drivers.setColumnCount(7)
        self.table_drivers.setHorizontalHeaderLabels([
            "Gói OEM", "Tên Gốc (INF)", "Nhà Cung Cấp", "Loại Thiết Bị", "Phiên Bản", "Ngày Phát Hành", "Trạng Thái"
        ])
        self.table_drivers.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_drivers.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_drivers.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_drivers.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_drivers.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_drivers.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_drivers.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table_drivers.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_drivers.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_drivers.verticalHeader().setVisible(False)
        self.table_drivers.setShowGrid(False)
        self._apply_table_style(self.table_drivers)
        layout.addWidget(self.table_drivers, stretch=1)

    # ------------------------------------------------------------------
    # Data Refresh & Rendering
    # ------------------------------------------------------------------

    def _refresh_all_data(self):
        self.lbl_status.setText("⏳ Đang rà soát bộ nhớ đệm Windows Update và DriverStore...")
        QApplication.processEvents()

        # On-demand: bypass idle CACHE_TTL so opening the dialog / Làm mới is fresh.
        summary = WinSxSCleaner.get_summary(force_refresh=True)

        self._caches_cache = summary.get("caches", [])
        self._drivers_all_cache, self._drivers_dup_cache = WinSxSCleaner.scan_oem_drivers()

        # 1. Update Tab 1 Cards
        self.card_winsxs_status.findChild(QLabel, "val").setText("Đang Hoạt Động")
        self.card_winsxs_status.findChild(QLabel, "val").setStyleSheet(f"color: {_SUCCESS}; font-size: 18px; font-weight: bold;")

        # 2. Update Tab 2
        total_cache_mb = summary.get("total_cache_mb", 0.0)
        self.card_cache_total.findChild(QLabel, "val").setText(f"{total_cache_mb:.1f} MB")
        self.card_cache_files.findChild(QLabel, "val").setText(f"{summary.get('total_cache_files', 0)} tệp")
        self.card_cache_dirs.findChild(QLabel, "val").setText(f"{len(self._caches_cache)} mục")

        self._render_caches_table()

        # 3. Update Tab 3
        cleanable_count = sum(1 for d in self._drivers_dup_cache if not d.is_in_use)
        in_use_count = sum(1 for d in self._drivers_dup_cache if d.is_in_use)

        self.card_drv_total.findChild(QLabel, "val").setText(f"{len(self._drivers_all_cache)} gói")
        self.card_drv_dups.findChild(QLabel, "val").setText(f"{cleanable_count} gói")
        if cleanable_count > 0:
            self.card_drv_dups.findChild(QLabel, "val").setStyleSheet(f"color: {_WARNING}; font-size: 18px; font-weight: bold;")
        else:
            self.card_drv_dups.findChild(QLabel, "val").setStyleSheet(f"color: {_SUCCESS}; font-size: 18px; font-weight: bold;")

        self.card_drv_safe.findChild(QLabel, "val").setText(f"{in_use_count} gói")
        self.card_drv_safe.findChild(QLabel, "sub").setText("Windows tự động bảo vệ an toàn")

        self._render_drivers_table()

        self.lbl_status.setText(
            f"● Đã tải: {len(self._caches_cache)} mục đệm ({total_cache_mb:.1f} MB), "
            f"{cleanable_count} driver cũ có thể dọn, {in_use_count} gói được Windows bảo vệ an toàn."
        )

    def _render_caches_table(self):
        self.table_caches.setRowCount(len(self._caches_cache))
        for row, c in enumerate(self._caches_cache):
            # Checkbox
            chk = QCheckBox()
            chk.setChecked(True)
            chk.setStyleSheet("margin-left: 10px;")
            self.table_caches.setCellWidget(row, 0, chk)

            # Name
            it_name = QTableWidgetItem(c.name)
            it_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_caches.setItem(row, 1, it_name)

            # Path
            it_path = QTableWidgetItem(c.path)
            it_path.setToolTip(c.description)
            it_path.setForeground(QColor(_TEXT_MUTED))
            self.table_caches.setItem(row, 2, it_path)

            # Size
            it_sz = QTableWidgetItem(c.size_display)
            it_sz.setTextAlignment(Qt.AlignCenter)
            it_sz.setFont(QFont("Segoe UI", 9, QFont.Bold))
            if c.size_mb >= 300:
                it_sz.setForeground(QColor(_WARNING))
            else:
                it_sz.setForeground(QColor(_TEXT_WHITE))
            self.table_caches.setItem(row, 3, it_sz)

            # Files
            it_fc = QTableWidgetItem(f"{c.file_count:,} tệp")
            it_fc.setTextAlignment(Qt.AlignCenter)
            it_fc.setForeground(QColor(_TEXT_MUTED))
            self.table_caches.setItem(row, 4, it_fc)

    def _render_drivers_table(self):
        # Hiển thị các driver trùng lặp
        self.table_drivers.setRowCount(len(self._drivers_dup_cache))
        cleanable_count = 0
        for row, drv in enumerate(self._drivers_dup_cache):
            it_oem = QTableWidgetItem(drv.published_name)
            it_oem.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_drivers.setItem(row, 0, it_oem)

            it_orig = QTableWidgetItem(drv.original_name)
            it_orig.setForeground(QColor(_ACCENT_BLUE))
            self.table_drivers.setItem(row, 1, it_orig)

            it_prov = QTableWidgetItem(drv.provider)
            self.table_drivers.setItem(row, 2, it_prov)

            it_cls = QTableWidgetItem(drv.class_name)
            self.table_drivers.setItem(row, 3, it_cls)

            it_ver = QTableWidgetItem(drv.version)
            it_ver.setTextAlignment(Qt.AlignCenter)
            self.table_drivers.setItem(row, 4, it_ver)

            it_date = QTableWidgetItem(drv.date)
            it_date.setTextAlignment(Qt.AlignCenter)
            it_date.setForeground(QColor(_TEXT_MUTED))
            self.table_drivers.setItem(row, 5, it_date)

            if drv.is_in_use:
                it_st = QTableWidgetItem("🔒 Đang dùng cho thiết bị (Windows bảo vệ)")
                it_st.setForeground(QColor("#58a6ff"))
                it_st.setToolTip("Gói driver này đang được liên kết trực tiếp với thiết bị phần cứng (Bluetooth, Wi-Fi, Máy in...). Windows tự động bảo vệ an toàn 100% để tránh mất kết nối.")
            else:
                cleanable_count += 1
                it_st = QTableWidgetItem("⚠️ Phiên bản cũ (Có thể dọn)")
                it_st.setForeground(QColor(_WARNING))
                it_st.setToolTip("Gói driver cũ này không còn thiết bị nào sử dụng, an toàn để dọn dẹp.")
            self.table_drivers.setItem(row, 6, it_st)

        if cleanable_count > 0:
            self.btn_clean_duplicate_drivers.setEnabled(True)
            self.btn_clean_duplicate_drivers.setText(f"🗑️ Dọn Dẹp {cleanable_count} Gói Driver Cũ")
            self.btn_clean_duplicate_drivers.setStyleSheet(f"""
                QPushButton {{
                    background: {_CARD_BG};
                    color: {_DANGER};
                    border: 1px solid {_DANGER};
                    font-weight: bold;
                    font-size: 11px;
                    border-radius: 6px;
                    padding: 0 16px;
                }}
                QPushButton:hover {{ background: {_DANGER}22; }}
            """)
        else:
            self.btn_clean_duplicate_drivers.setEnabled(False)
            self.btn_clean_duplicate_drivers.setText("🛡️ Tất Cả Driver Đang Được Bảo Vệ An Toàn")
            self.btn_clean_duplicate_drivers.setToolTip("Tất cả các gói Driver hiện tại đều đang được phần cứng máy tính sử dụng trực tiếp. Windows tự động bảo vệ an toàn 100% để tránh gây lỗi phần cứng.")
            self.btn_clean_duplicate_drivers.setStyleSheet(f"""
                QPushButton {{
                    background: #21262d;
                    color: {_TEXT_MUTED};
                    border: 1px solid {_CARD_BORDER};
                    font-size: 11px;
                    border-radius: 6px;
                    padding: 0 16px;
                }}
            """)

    # ------------------------------------------------------------------
    # Actions: DISM
    # ------------------------------------------------------------------

    def _on_run_dism(self, reset_base: bool = False):
        tag = "ResetBase" if reset_base else "StartComponentCleanup"
        if reset_base:
            reply = QMessageBox.warning(
                self,
                "Xác Nhận Dọn Dẹp Chuyên Sâu (/ResetBase)",
                "⚠️ CẢNH BÁO QUAN TRỌNG TỪ MICROSOFT:\n\n"
                "Tùy chọn /ResetBase sẽ xóa vĩnh viễn tất cả các bản sao lưu cập nhật cũ bị thay thế trong WinSxS.\n\n"
                "• Lợi ích: Giải phóng dung lượng ổ C: tối đa (từ 2 GB đến 8 GB).\n"
                "• Lưu ý: Sau khi thực hiện, bạn sẽ KHÔNG thể gỡ bỏ (uninstall) các bản cập nhật Windows đã cài trước đó.\n\n"
                "Bạn có chắc chắn muốn tiếp tục không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self._set_dism_buttons_enabled(False)
        self.txt_console.clear()
        self._worker = DismWorker(mode="cleanup", reset_base=reset_base)
        self._worker.log_signal.connect(self._append_console)
        self._worker.finished_signal.connect(self._on_dism_finished)
        self._worker.start()

    def _on_run_restore_health(self):
        self._set_dism_buttons_enabled(False)
        self.txt_console.clear()
        self._worker = DismWorker(mode="restore_health")
        self._worker.log_signal.connect(self._append_console)
        self._worker.finished_signal.connect(self._on_dism_finished)
        self._worker.start()

    def _append_console(self, text: str):
        self.txt_console.appendPlainText(text)

    def _on_dism_finished(self, success: bool, message: str):
        self._set_dism_buttons_enabled(True)
        self._append_console("\n" + "=" * 50)
        self._append_console(f"Kết quả: {message}")
        if success:
            QMessageBox.information(self, "Hoàn Tất", message)
        else:
            QMessageBox.warning(self, "Thông Báo", message)
        self._refresh_all_data()

    def _set_dism_buttons_enabled(self, enabled: bool):
        self.btn_dism_std.setEnabled(enabled)
        self.btn_dism_deep.setEnabled(enabled)
        self.btn_dism_repair.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Actions: Caches & DriverStore
    # ------------------------------------------------------------------

    def _on_toggle_all_caches(self, state: int):
        checked = (state == Qt.Checked)
        for row in range(self.table_caches.rowCount()):
            chk = self.table_caches.cellWidget(row, 0)
            if isinstance(chk, QCheckBox):
                chk.setChecked(checked)

    def _on_clean_selected_caches(self):
        selected_items: List[UpdateCacheItem] = []
        for row in range(self.table_caches.rowCount()):
            chk = self.table_caches.cellWidget(row, 0)
            if isinstance(chk, QCheckBox) and chk.isChecked():
                selected_items.append(self._caches_cache[row])

        if not selected_items:
            QMessageBox.warning(self, "Thông Báo", "Vui lòng chọn ít nhất một danh mục bộ đệm để dọn dẹp.")
            return

        total_mb = sum(i.size_mb for i in selected_items)
        reply = QMessageBox.question(
            self,
            "Xác Nhận Dọn Bộ Nhớ Đệm Cập Nhật",
            f"Bạn có chắc chắn muốn dọn dẹp {len(selected_items)} danh mục bộ đệm cập nhật và nhật ký servicing ({total_mb:.1f} MB)?\n\n"
            "Thao tác này hoàn toàn an toàn cho Windows.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        total_freed = 0.0
        total_files = 0
        for item in selected_items:
            _, _, f_cnt, mb = WinSxSCleaner.clean_cache_item(item)
            total_files += f_cnt
            total_freed += mb

        QMessageBox.information(
            self,
            "Dọn Dẹp Hoàn Tất",
            f"Đã dọn dẹp thành công {total_files:,} tệp, giải phóng {total_freed:.1f} MB dung lượng ổ đĩa!"
        )
        self._refresh_all_data()

    def _on_clean_duplicate_drivers(self):
        cleanable = [d for d in self._drivers_dup_cache if not d.is_in_use]
        in_use = [d for d in self._drivers_dup_cache if d.is_in_use]

        if not cleanable:
            QMessageBox.information(
                self,
                "Bảo Vệ Phần Cứng An Toàn",
                f"Tất cả {len(in_use)} gói driver OEM này hiện đang được các thiết bị phần cứng máy tính "
                "(chip Bluetooth, card Wi-Fi, dịch vụ Máy in...) trực tiếp sử dụng.\n\n"
                "Windows đã kích hoạt cơ chế bảo vệ phần cứng tự động để đảm bảo kết nối của máy tính luôn ổn định 100%.\n\n"
                "Bạn không cần thao tác thêm vì hệ thống đã ở trạng thái tối ưu và an toàn nhất!"
            )
            return

        reply = QMessageBox.question(
            self,
            "Xác Nhận Dọn Driver OEM Cũ",
            f"Phát hiện {len(cleanable)} gói Driver OEM phiên bản cũ không còn thiết bị nào sử dụng.\n\n"
            f"(Ngoài ra có {len(in_use)} gói được Windows bảo vệ an toàn do phần cứng đang nạp).\n\n"
            "Bạn có muốn gỡ bỏ các phiên bản cũ không còn sử dụng này?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.lbl_status.setText("⏳ Đang dọn dẹp các driver OEM cũ...")
        QApplication.processEvents()

        success, failed, msg = WinSxSCleaner.clean_duplicate_drivers(self._drivers_dup_cache)
        QMessageBox.information(self, "Kết Quả Dọn Driver", msg)
        self._refresh_all_data()

    # ------------------------------------------------------------------
    # Helper Widgets
    # ------------------------------------------------------------------

    def _create_stat_card(self, title: str, val: str, sub: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(8, 6, 8, 6)
        c_lay.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")

        lbl_v = QLabel(val)
        lbl_v.setObjectName("val")
        lbl_v.setStyleSheet(f"color: {_TEXT_WHITE}; font-size: 18px; font-weight: bold;")

        lbl_s = QLabel(sub)
        lbl_s.setObjectName("sub")
        lbl_s.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")

        c_lay.addWidget(lbl_t)
        c_lay.addWidget(lbl_v)
        c_lay.addWidget(lbl_s)
        return card

    def _apply_table_style(self, table: QTableWidget):
        table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                gridline-color: transparent;
                color: {_TEXT_WHITE};
            }}
            QHeaderView::section {{
                background-color: #21262d;
                color: {_TEXT_MUTED};
                border: none;
                border-bottom: 1px solid {_CARD_BORDER};
                padding: 6px 8px;
                font-size: 11px;
                font-weight: bold;
            }}
            QTableWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid #21262d;
            }}
            QTableWidget::item:selected {{
                background-color: #283347;
            }}
        """)
