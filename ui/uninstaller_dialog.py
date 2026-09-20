"""
ui/uninstaller_dialog.py – Software Uninstaller & Residual Junk Hunter Dialog (v3.5 Pro)
=======================================================================================
Giao diện Fluent Dark 3 Tab:
1. Tab 📦 Phần Mềm Đã Cài Đặt:
   - Danh sách phần mềm Desktop kèm dung lượng thực, ngày cài đặt, nhà phát triển.
   - Sắp xếp thông minh: theo dung lượng lớn nhất để dọn dẹp bộ nhớ nhanh.
   - Thao tác: Gỡ cài đặt gốc & Quét tàn dư rác.
2. Tab 🗑️ Gỡ Ứng Dụng Rác Windows (Bloatware):
   - Nhận diện các ứng dụng UWP tích hợp sẵn không cần thiết (Xbox, Tips, Solitaire, News...).
   - Nút 1-Click Gỡ Bloatware an toàn.
3. Tab 🧹 Thợ Săn Rác Còn Sót (Residual Hunter):
   - Truy tìm các thư mục ẩn trong AppData, ProgramData, Program Files và khóa Registry bị bỏ lại.
   - 1-Click xóa sạch tàn dư.
"""
from __future__ import annotations

import os
from typing import List, Dict, Any, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QFrame, QMessageBox, QAbstractItemView, QSizePolicy,
    QApplication, QSplitter
)

from app_meta import APP_NAME
from core.uninstaller_manager import UninstallerManager, InstalledApp, KNOWN_BLOATWARE
from core.network_optimizer import NetworkOptimizer
from core.service_optimizer import ServiceOptimizer


# ---------------------------------------------------------------------------
# Styling Palette
# ---------------------------------------------------------------------------
_BG           = "#0d1117"
_SURFACE      = "#161b22"
_CARD_BG      = "#1c2128"
_CARD_BORDER  = "#30363d"
_TEXT_PRIMARY = "#f0f6fc"
_TEXT_MUTED   = "#8b949e"
_ACCENT_BLUE  = "#58a6ff"
_SUCCESS      = "#238636"
_WARNING      = "#d29922"
_DANGER       = "#da3633"
_PURPLE       = "#bc8cff"

DIALOG_STYLE = f"""
QDialog {{
    background: {_BG};
    color: {_TEXT_PRIMARY};
    font-family: 'Segoe UI', sans-serif;
}}
QTabWidget::pane {{
    border: 1px solid {_CARD_BORDER};
    background: {_BG};
    border-radius: 8px;
}}
QTabBar::tab {{
    background: {_SURFACE};
    color: {_TEXT_MUTED};
    font-weight: bold;
    font-size: 13px;
    padding: 8px 20px;
    min-width: 170px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid {_CARD_BORDER};
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    background: {_CARD_BG};
    color: {_ACCENT_BLUE};
    border-bottom: 2px solid {_ACCENT_BLUE};
}}
QTableWidget {{
    background: {_SURFACE};
    alternate-background-color: {_CARD_BG};
    color: {_TEXT_PRIMARY};
    border: 1px solid {_CARD_BORDER};
    border-radius: 6px;
    gridline-color: #21262d;
    selection-background-color: #2b313a;
    selection-color: {_TEXT_PRIMARY};
}}
QHeaderView::section {{
    background: {_CARD_BG};
    color: {_TEXT_MUTED};
    font-weight: bold;
    font-size: 11px;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {_CARD_BORDER};
}}
QLineEdit {{
    background: {_SURFACE};
    color: {_TEXT_PRIMARY};
    border: 1px solid {_CARD_BORDER};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
}}
QLineEdit:focus {{
    border: 1px solid {_ACCENT_BLUE};
}}
QComboBox {{
    background: {_SURFACE};
    color: {_TEXT_PRIMARY};
    border: 1px solid {_CARD_BORDER};
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
}}
QScrollBar:vertical {{
    background: {_SURFACE};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #30363d;
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""


class UninstallerDialog(QDialog):
    """Hộp thoại quản lý gỡ cài đặt phần mềm và dọn dẹp rác tàn dư."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"📦 Software Uninstaller & Residual Junk Hunter – {APP_NAME}")
        self.setMinimumSize(1000, 700)
        self.resize(1050, 720)
        self.setStyleSheet(DIALOG_STYLE)

        self._desktop_apps_cache: List[InstalledApp] = []
        self._bloatware_apps_cache: List[InstalledApp] = []
        self._current_residuals: Dict[str, Any] = {}

        self._build_ui()
        self._refresh_all_data()

    # ------------------------------------------------------------------
    # UI Layout Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header Title
        header_row = QHBoxLayout()
        icon_lbl = QLabel("📦")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 20))

        title_box = QVBoxLayout()
        title_lbl = QLabel("Software Uninstaller & Residual Junk Hunter")
        title_lbl.setFont(QFont("Segoe UI Semibold", 13, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {_TEXT_PRIMARY};")
        sub_lbl = QLabel("Gỡ cài đặt phần mềm tận gốc, loại bỏ Bloatware Windows và truy quét 100% tàn dư rác còn sót")
        sub_lbl.setFont(QFont("Segoe UI", 9))
        sub_lbl.setStyleSheet(f"color: {_TEXT_MUTED};")
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)

        header_row.addWidget(icon_lbl)
        header_row.addSpacing(6)
        header_row.addLayout(title_box, stretch=1)

        btn_refresh = QPushButton("🔄 Làm Mới")
        btn_refresh.setFixedHeight(32)
        btn_refresh.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_ACCENT_BLUE};
                border: 1px solid {_ACCENT_BLUE};
                border-radius: 6px;
                padding: 0 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {_ACCENT_BLUE}22; }}
        """)
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(lambda: self._refresh_all_data(force=True))
        header_row.addWidget(btn_refresh)

        root.addLayout(header_row)

        # 3 Tabs
        self.tabs = QTabWidget()
        self.tabs.tabBar().setElideMode(Qt.ElideNone)

        self.tab_desktop = QWidget()
        self.tab_bloatware = QWidget()
        self.tab_residuals = QWidget()

        self._build_desktop_tab()
        self._build_bloatware_tab()
        self._build_residuals_tab()

        self.tabs.addTab(self.tab_desktop, "📦 Phần Mềm Đã Cài Đặt")
        self.tabs.addTab(self.tab_bloatware, "🗑️ Gỡ Bloatware Windows")
        self.tabs.addTab(self.tab_residuals, "🧹 Thợ Săn Rác Còn Sót")

        root.addWidget(self.tabs, stretch=1)

        # Footer
        footer = QHBoxLayout()
        self.lbl_status = QLabel("● Sẵn sàng")
        self.lbl_status.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")

        btn_close = QPushButton("Đóng")
        btn_close.setFixedSize(90, 32)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_TEXT_PRIMARY};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: #21262d; }}
        """)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)

        footer.addWidget(self.lbl_status, stretch=1)
        footer.addWidget(btn_close)
        root.addLayout(footer)

    # ------------------------------------------------------------------
    # Tab 1: Desktop Apps
    # ------------------------------------------------------------------

    def _build_desktop_tab(self):
        layout = QVBoxLayout(self.tab_desktop)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Stat Cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.card_desk_total = self._create_stat_card("Tổng Phần Mềm", "0", "Đang quét...", _TEXT_PRIMARY)
        self.card_desk_size = self._create_stat_card("Tổng Dung Lượng", "0.0 GB", "Ước tính ổ đĩa", _ACCENT_BLUE)
        self.card_desk_largest = self._create_stat_card("Chiếm Nhiều Nhất", "Không có", "0 MB", _WARNING)
        cards_row.addWidget(self.card_desk_total)
        cards_row.addWidget(self.card_desk_size)
        cards_row.addWidget(self.card_desk_largest)
        layout.addLayout(cards_row)

        # Filters Bar
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.txt_desk_search = QLineEdit()
        self.txt_desk_search.setPlaceholderText("🔍 Tìm theo tên phần mềm hoặc nhà phát triển...")
        self.txt_desk_search.setFixedHeight(34)
        self.txt_desk_search.textChanged.connect(self._filter_desktop_table)
        bar.addWidget(self.txt_desk_search, stretch=1)

        self.combo_desk_sort = QComboBox()
        self.combo_desk_sort.setFixedHeight(34)
        self.combo_desk_sort.addItem("📊 Dung lượng lớn nhất", "size_desc")
        self.combo_desk_sort.addItem("🔤 Tên phần mềm (A-Z)", "name_asc")
        self.combo_desk_sort.addItem("📅 Ngày cài gần nhất", "date_desc")
        self.combo_desk_sort.currentIndexChanged.connect(self._filter_desktop_table)
        bar.addWidget(self.combo_desk_sort)

        layout.addLayout(bar)

        # Table
        self.table_desktop = QTableWidget()
        self.table_desktop.setColumnCount(6)
        self.table_desktop.setHorizontalHeaderLabels([
            "Tên Phần Mềm", "Nhà Phát Triển", "Phiên Bản", "Dung Lượng", "Ngày Cài Đặt", "Thao Tác"
        ])
        self.table_desktop.setAlternatingRowColors(True)
        self.table_desktop.verticalHeader().setVisible(False)
        self.table_desktop.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_desktop.setSelectionBehavior(QAbstractItemView.SelectRows)

        header = self.table_desktop.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table_desktop.setColumnWidth(5, 180)

        layout.addWidget(self.table_desktop, stretch=1)

    # ------------------------------------------------------------------
    # Tab 2: Bloatware Remover
    # ------------------------------------------------------------------

    def _build_bloatware_tab(self):
        layout = QVBoxLayout(self.tab_bloatware)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Stat Cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self.card_bloat_total = self._create_stat_card("Bloatware Phát Hiện", "0", "Ứng dụng UWP", _WARNING)
        self.card_bloat_safe = self._create_stat_card("Có Thể Gỡ An Toàn", "0", "Khuyên dọn dẹp", _SUCCESS)
        self.card_bloat_note = self._create_stat_card("Lợi Ích", "Nhẹ RAM & CPU", "Tắt tiến trình ngầm", _PURPLE)
        cards_row.addWidget(self.card_bloat_total)
        cards_row.addWidget(self.card_bloat_safe)
        cards_row.addWidget(self.card_bloat_note)
        layout.addLayout(cards_row)

        # Action Bar
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.btn_1click_bloat = QPushButton("🚀 1-Click Gỡ Toàn Bộ Bloatware Khuyên Dùng")
        self.btn_1click_bloat.setFixedHeight(34)
        self.btn_1click_bloat.setStyleSheet(f"""
            QPushButton {{
                background: {_SUCCESS};
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
                border: none;
            }}
            QPushButton:hover {{ background: #2ea043; }}
        """)
        self.btn_1click_bloat.setCursor(Qt.PointingHandCursor)
        self.btn_1click_bloat.clicked.connect(self._on_1click_remove_bloatware)
        bar.addWidget(self.btn_1click_bloat)

        self.txt_bloat_search = QLineEdit()
        self.txt_bloat_search.setPlaceholderText("🔍 Tìm theo tên ứng dụng Windows...")
        self.txt_bloat_search.setFixedHeight(34)
        self.txt_bloat_search.textChanged.connect(self._filter_bloatware_table)
        bar.addWidget(self.txt_bloat_search, stretch=1)

        layout.addLayout(bar)

        # Table
        self.table_bloatware = QTableWidget()
        self.table_bloatware.setColumnCount(5)
        self.table_bloatware.setHorizontalHeaderLabels([
            "Ứng Dụng Bloatware", "Mô Tả & Mục Đích", "Phiên Bản", "Độ An Toàn", "Thao Tác"
        ])
        self.table_bloatware.setAlternatingRowColors(True)
        self.table_bloatware.verticalHeader().setVisible(False)
        self.table_bloatware.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_bloatware.setSelectionBehavior(QAbstractItemView.SelectRows)

        header = self.table_bloatware.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table_bloatware.setColumnWidth(4, 110)

        layout.addWidget(self.table_bloatware, stretch=1)

    # ------------------------------------------------------------------
    # Tab 3: Residual Hunter
    # ------------------------------------------------------------------

    def _build_residuals_tab(self):
        layout = QVBoxLayout(self.tab_residuals)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Info Box
        info_banner = QFrame()
        info_banner.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        ib_layout = QHBoxLayout(info_banner)
        ib_icon = QLabel("🧹")
        ib_icon.setFont(QFont("Segoe UI Emoji", 16))
        ib_text = QLabel(
            "<b>Thợ Săn Rác Tàn Dư (Residual Hunter):</b> Tự động quét sâu các thư mục AppData, ProgramData, "
            "Program Files và các khóa Registry bị bỏ lại của phần mềm đã gỡ cài đặt trước đó."
        )
        ib_text.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 12px;")
        ib_text.setWordWrap(True)
        ib_layout.addWidget(ib_icon)
        ib_layout.addWidget(ib_text, stretch=1)
        layout.addWidget(info_banner)

        # Search / Scan Bar
        search_box = QHBoxLayout()
        search_box.setSpacing(10)

        self.txt_residual_query = QLineEdit()
        self.txt_residual_query.setPlaceholderText("Nhập tên phần mềm đã gỡ (Ví dụ: Kaspersky, Steam, Chrome, Riot...)")
        self.txt_residual_query.setFixedHeight(36)
        self.txt_residual_query.returnPressed.connect(self._on_scan_residuals)
        search_box.addWidget(self.txt_residual_query, stretch=1)

        btn_scan = QPushButton("🔍 Quét Tàn Dư")
        btn_scan.setFixedHeight(36)
        btn_scan.setStyleSheet(f"""
            QPushButton {{
                background: {_ACCENT_BLUE};
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
                border: none;
            }}
            QPushButton:hover {{ background: #4795e6; }}
        """)
        btn_scan.setCursor(Qt.PointingHandCursor)
        btn_scan.clicked.connect(self._on_scan_residuals)
        search_box.addWidget(btn_scan)

        self.btn_clean_residuals = QPushButton("🧹 Dọn Sạch Rác Đã Tìm Thấy")
        self.btn_clean_residuals.setFixedHeight(36)
        self.btn_clean_residuals.setEnabled(False)
        self.btn_clean_residuals.setStyleSheet(f"""
            QPushButton {{
                background: {_DANGER};
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
                border: none;
            }}
            QPushButton:hover {{ background: #b82725; }}
            QPushButton:disabled {{ background: #2b313a; color: #6e7681; }}
        """)
        self.btn_clean_residuals.setCursor(Qt.PointingHandCursor)
        self.btn_clean_residuals.clicked.connect(self._on_clean_residuals)
        search_box.addWidget(self.btn_clean_residuals)

        layout.addLayout(search_box)

        # Results Summary Header
        self.lbl_residuals_summary = QLabel("Nhập từ khóa và bấm 'Quét Tàn Dư' để bắt đầu.")
        self.lbl_residuals_summary.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-weight: bold; font-size: 12px;")
        layout.addWidget(self.lbl_residuals_summary)

        # Splitter: Folders on Top, Registry on Bottom
        splitter = QSplitter(Qt.Vertical)

        # 1. Folders Table
        box_folders = QWidget()
        bf_layout = QVBoxLayout(box_folders)
        bf_layout.setContentsMargins(0, 0, 0, 0)
        lbl_f = QLabel("📂 Thư Mục Rác Trên Ổ Đĩa:")
        lbl_f.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        bf_layout.addWidget(lbl_f)

        self.table_res_folders = QTableWidget()
        self.table_res_folders.setColumnCount(3)
        self.table_res_folders.setHorizontalHeaderLabels(["Tên Thư Mục", "Đường Dẫn Chi Tiết", "Dung Lượng"])
        self.table_res_folders.setAlternatingRowColors(True)
        self.table_res_folders.verticalHeader().setVisible(False)
        self.table_res_folders.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_res_folders.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_res_folders.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_res_folders.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        bf_layout.addWidget(self.table_res_folders)
        splitter.addWidget(box_folders)

        # 2. Registry Table
        box_reg = QWidget()
        br_layout = QVBoxLayout(box_reg)
        br_layout.setContentsMargins(0, 0, 0, 0)
        lbl_r = QLabel("🔑 Khóa Rác Trong Registry:")
        lbl_r.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        br_layout.addWidget(lbl_r)

        self.table_res_registry = QTableWidget()
        self.table_res_registry.setColumnCount(2)
        self.table_res_registry.setHorizontalHeaderLabels(["Gốc Registry", "Đường Dẫn Khóa Tàn Dư"])
        self.table_res_registry.setAlternatingRowColors(True)
        self.table_res_registry.verticalHeader().setVisible(False)
        self.table_res_registry.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_res_registry.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_res_registry.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        br_layout.addWidget(self.table_res_registry)
        splitter.addWidget(box_reg)

        layout.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------
    # Helper: Stat Card Factory
    # ------------------------------------------------------------------

    def _create_stat_card(self, title: str, val: str, sub: str, val_color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
                padding: 10px 14px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(3)

        t_lbl = QLabel(title)
        t_lbl.setFont(QFont("Segoe UI", 9))
        t_lbl.setStyleSheet(f"color: {_TEXT_MUTED};")

        v_lbl = QLabel(val)
        v_lbl.setObjectName("val")
        v_lbl.setFont(QFont("Segoe UI", 16, QFont.Bold))
        v_lbl.setStyleSheet(f"color: {val_color};")

        s_lbl = QLabel(sub)
        s_lbl.setObjectName("sub")
        s_lbl.setFont(QFont("Segoe UI", 8))
        s_lbl.setStyleSheet(f"color: {_TEXT_MUTED};")

        cl.addWidget(t_lbl)
        cl.addWidget(v_lbl)
        cl.addWidget(s_lbl)
        return card

    # ------------------------------------------------------------------
    # Data Loading & Rendering
    # ------------------------------------------------------------------

    def _refresh_all_data(self, force: bool = False):
        self.lbl_status.setText("Đang làm mới danh sách phần mềm và bloatware...")
        QApplication.processEvents()

        # 1. Desktop Apps
        self._desktop_apps_cache = UninstallerManager.get_installed_desktop_apps(force_refresh=force)
        sum_desk = UninstallerManager.get_summary()

        self.card_desk_total.findChild(QLabel, "val").setText(str(sum_desk["desktop_count"]))
        self.card_desk_total.findChild(QLabel, "sub").setText("Ứng dụng Windows")

        self.card_desk_size.findChild(QLabel, "val").setText(f"{sum_desk['total_size_gb']} GB")

        largest_txt = sum_desk["largest_name"]
        if len(largest_txt) > 20:
            largest_txt = largest_txt[:18] + "..."
        self.card_desk_largest.findChild(QLabel, "val").setText(largest_txt)
        self.card_desk_largest.findChild(QLabel, "sub").setText(f"{sum_desk['largest_size_mb']:.1f} MB")

        self._filter_desktop_table()

        # 2. Bloatware Apps
        self._bloatware_apps_cache = UninstallerManager.get_bloatware_apps(force_refresh=force)
        self.card_bloat_total.findChild(QLabel, "val").setText(str(len(self._bloatware_apps_cache)))
        safe_count = sum(1 for b in self._bloatware_apps_cache if b.safety_rating == "safe")
        self.card_bloat_safe.findChild(QLabel, "val").setText(f"{safe_count} ứng dụng")

        self._filter_bloatware_table()

        self.lbl_status.setText(f"● Đã tải: {len(self._desktop_apps_cache)} phần mềm desktop, {len(self._bloatware_apps_cache)} bloatware.")

    def _filter_desktop_table(self):
        query = self.txt_desk_search.text().strip().lower()
        sort_mode = self.combo_desk_sort.currentData()

        filtered = list(self._desktop_apps_cache)
        if query:
            filtered = [a for a in filtered if query in a.name.lower() or query in a.publisher.lower()]

        if sort_mode == "size_desc":
            filtered.sort(key=lambda x: x.size_mb, reverse=True)
        elif sort_mode == "name_asc":
            filtered.sort(key=lambda x: x.name.lower())
        elif sort_mode == "date_desc":
            filtered.sort(key=lambda x: x.install_date, reverse=True)

        self._render_desktop_table(filtered)

    def _render_desktop_table(self, apps: List[InstalledApp]):
        self.table_desktop.setRowCount(len(apps))
        for row, a in enumerate(apps):
            # Name
            item_name = QTableWidgetItem(a.name)
            item_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_desktop.setItem(row, 0, item_name)

            # Publisher
            item_pub = QTableWidgetItem(a.publisher)
            self.table_desktop.setItem(row, 1, item_pub)

            # Version
            item_ver = QTableWidgetItem(a.version)
            item_ver.setTextAlignment(Qt.AlignCenter)
            self.table_desktop.setItem(row, 2, item_ver)

            # Size
            item_size = QTableWidgetItem(a.size_display)
            item_size.setTextAlignment(Qt.AlignCenter)
            if a.size_mb >= 1024:
                item_size.setForeground(QColor(_WARNING))
                item_size.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_desktop.setItem(row, 3, item_size)

            # Date
            item_date = QTableWidgetItem(a.date_display)
            item_date.setTextAlignment(Qt.AlignCenter)
            self.table_desktop.setItem(row, 4, item_date)

            # Actions Widget (Gỡ Bỏ + Quét Rác)
            act_widget = QWidget()
            aw_layout = QHBoxLayout(act_widget)
            aw_layout.setContentsMargins(4, 2, 4, 2)
            aw_layout.setSpacing(6)

            btn_uninst = QPushButton("Gỡ Cài Đặt")
            btn_uninst.setFixedHeight(24)
            btn_uninst.setStyleSheet(f"""
                QPushButton {{
                    background: {_CARD_BG};
                    color: {_DANGER};
                    border: 1px solid {_DANGER};
                    border-radius: 4px;
                    padding: 0 8px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: {_DANGER}22; }}
            """)
            btn_uninst.setCursor(Qt.PointingHandCursor)
            btn_uninst.clicked.connect(lambda checked=False, app=a: self._on_uninstall_desktop(app))
            aw_layout.addWidget(btn_uninst)

            btn_hunt = QPushButton("🧹 Quét Rác")
            btn_hunt.setFixedHeight(24)
            btn_hunt.setStyleSheet(f"""
                QPushButton {{
                    background: {_CARD_BG};
                    color: {_ACCENT_BLUE};
                    border: 1px solid {_CARD_BORDER};
                    border-radius: 4px;
                    padding: 0 8px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: #21262d; }}
            """)
            btn_hunt.setCursor(Qt.PointingHandCursor)
            btn_hunt.setToolTip("Chuyển sang Thợ Săn Rác để quét tàn dư của phần mềm này")
            btn_hunt.clicked.connect(lambda checked=False, app=a: self._jump_to_residuals_hunter(app.name))
            aw_layout.addWidget(btn_hunt)

            self.table_desktop.setCellWidget(row, 5, act_widget)

    def _filter_bloatware_table(self):
        query = self.txt_bloat_search.text().strip().lower()
        filtered = self._bloatware_apps_cache
        if query:
            filtered = [b for b in filtered if query in b.name.lower() or query in b.description.lower()]
        self._render_bloatware_table(filtered)

    def _render_bloatware_table(self, bloat: List[InstalledApp]):
        self.table_bloatware.setRowCount(len(bloat))
        for row, b in enumerate(bloat):
            # Title
            item_name = QTableWidgetItem(b.name)
            item_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_bloatware.setItem(row, 0, item_name)

            # Description
            item_desc = QTableWidgetItem(b.description)
            item_desc.setForeground(QColor(_TEXT_MUTED))
            self.table_bloatware.setItem(row, 1, item_desc)

            # Version
            item_ver = QTableWidgetItem(b.version or "Windows Build")
            item_ver.setTextAlignment(Qt.AlignCenter)
            self.table_bloatware.setItem(row, 2, item_ver)

            # Safety
            st_text = "✅ Khuyên gỡ" if b.safety_rating == "safe" else "⚠️ Thận trọng"
            st_color = _SUCCESS if b.safety_rating == "safe" else _WARNING
            item_safe = QTableWidgetItem(st_text)
            item_safe.setTextAlignment(Qt.AlignCenter)
            item_safe.setForeground(QColor(st_color))
            self.table_bloatware.setItem(row, 3, item_safe)

            # Action Button
            btn_uninst = QPushButton("Gỡ Bỏ")
            btn_uninst.setFixedHeight(24)
            btn_uninst.setStyleSheet(f"""
                QPushButton {{
                    background: {_CARD_BG};
                    color: {_DANGER};
                    border: 1px solid {_DANGER};
                    border-radius: 4px;
                    padding: 0 10px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: {_DANGER}22; }}
            """)
            btn_uninst.setCursor(Qt.PointingHandCursor)
            btn_uninst.clicked.connect(lambda checked=False, app=b: self._on_uninstall_bloatware(app))
            self.table_bloatware.setCellWidget(row, 4, btn_uninst)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_uninstall_desktop(self, app: InstalledApp):
        reply = QMessageBox.question(
            self,
            "Xác Nhận Gỡ Cài Đặt",
            f"Bạn có chắc chắn muốn khởi chạy gỡ cài đặt phần mềm:\n\n"
            f"👉 <b>{app.name}</b> (Phiên bản: {app.version})\n\n"
            f"Sau khi gỡ xong, bạn có thể chuyển sang tab 'Thợ Săn Rác' để quét sạch tàn dư AppData/Registry.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        ok, msg = UninstallerManager.uninstall_desktop_app(app)
        if ok:
            QMessageBox.information(
                self,
                "Đang Khởi Chạy",
                f"{msg}\n\n"
                f"💡 Mẹo: Khi quá trình gỡ cài đặt hoàn tất, hãy bấm 'Quét Rác' để dọn sạch 100% tàn dư còn sót lại."
            )
        else:
            QMessageBox.warning(self, "Lỗi Gỡ Cài Đặt", msg)

    def _on_uninstall_bloatware(self, app: InstalledApp):
        reply = QMessageBox.question(
            self,
            "Xác Nhận Gỡ Ứng Dụng Windows",
            f"Bạn có chắc muốn gỡ bỏ ứng dụng Bloatware:\n\n"
            f"👉 <b>{app.name}</b>\n\n"
            f"(Bạn có thể cài đặt lại bất kỳ lúc nào từ Microsoft Store nếu cần).",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.lbl_status.setText(f"⏳ Đang gỡ bỏ {app.name}...")
        QApplication.processEvents()

        ok, msg = UninstallerManager.uninstall_uwp_app(app)
        if ok:
            QMessageBox.information(self, "Thành Công", msg)
            self._refresh_all_data(force=True)
        else:
            QMessageBox.warning(self, "Lỗi", msg)

    def _on_1click_remove_bloatware(self):
        safe_bloat = [b for b in self._bloatware_apps_cache if b.safety_rating == "safe"]
        if not safe_bloat:
            QMessageBox.information(self, "Thông Báo", "Không phát hiện thấy bloatware nào cần gỡ bỏ.")
            return

        reply = QMessageBox.question(
            self,
            "Xác Nhận 1-Click Gỡ Bloatware",
            f"Hệ thống sẽ tự động gỡ bỏ {len(safe_bloat)} ứng dụng Bloatware an toàn được khuyên dùng.\n\n"
            f"👉 Bạn có muốn tiếp tục không?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.lbl_status.setText("⏳ Đang gỡ bỏ hàng loạt ứng dụng bloatware...")
        self.btn_1click_bloat.setEnabled(False)
        QApplication.processEvents()

        success_cnt = 0
        failed_cnt = 0
        for b in safe_bloat:
            ok, _ = UninstallerManager.uninstall_uwp_app(b)
            if ok:
                success_cnt += 1
            else:
                failed_cnt += 1

        self.btn_1click_bloat.setEnabled(True)
        QMessageBox.information(
            self,
            "Hoàn Tất",
            f"✨ Đã gỡ bỏ thành công {success_cnt} ứng dụng Bloatware Windows!" +
            (f"\n({failed_cnt} ứng dụng thất bại)" if failed_cnt > 0 else "")
        )
        self._refresh_all_data(force=True)

    # ------------------------------------------------------------------
    # Residual Hunter Actions
    # ------------------------------------------------------------------

    def _jump_to_residuals_hunter(self, app_name: str):
        """Chuyển sang Tab 3 và tự động quét tàn dư cho phần mềm này."""
        self.tabs.setCurrentWidget(self.tab_residuals)
        self.txt_residual_query.setText(app_name)
        self._on_scan_residuals()

    def _on_scan_residuals(self):
        query = self.txt_residual_query.text().strip()
        if not query or len(query) < 3:
            QMessageBox.warning(self, "Thông Báo", "Vui lòng nhập tên phần mềm từ 3 ký tự trở lên để quét tàn dư.")
            return

        self.lbl_status.setText(f"⏳ Đang quét tàn dư cho '{query}'...")
        QApplication.processEvents()

        residuals = UninstallerManager.scan_residuals(query)
        self._current_residuals = residuals

        folders = residuals.get("folders", [])
        reg_keys = residuals.get("reg_keys", [])
        total_size = residuals.get("total_size_mb", 0.0)

        # Update summary label
        self.lbl_residuals_summary.setText(
            f"🔍 Kết quả quét cho '{query}': Tìm thấy {len(folders)} thư mục rác ({total_size} MB) "
            f"và {len(reg_keys)} khóa Registry tàn dư."
        )

        # Render folders table
        self.table_res_folders.setRowCount(len(folders))
        for r, f in enumerate(folders):
            it_name = QTableWidgetItem(f.get("name", ""))
            it_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_res_folders.setItem(r, 0, it_name)

            it_path = QTableWidgetItem(f.get("path", ""))
            it_path.setToolTip(f.get("path", ""))
            self.table_res_folders.setItem(r, 1, it_path)

            it_sz = QTableWidgetItem(f"{f.get('size_mb', 0.0):.2f} MB")
            it_sz.setTextAlignment(Qt.AlignCenter)
            it_sz.setForeground(QColor(_WARNING))
            self.table_res_folders.setItem(r, 2, it_sz)

        # Render registry table
        self.table_res_registry.setRowCount(len(reg_keys))
        for r, k in enumerate(reg_keys):
            it_root = QTableWidgetItem(k.get("root", ""))
            it_root.setTextAlignment(Qt.AlignCenter)
            it_root.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table_res_registry.setItem(r, 0, it_root)

            it_p = QTableWidgetItem(k.get("full", ""))
            it_p.setToolTip(k.get("full", ""))
            self.table_res_registry.setItem(r, 1, it_p)

        self.btn_clean_residuals.setEnabled(len(folders) > 0 or len(reg_keys) > 0)
        self.lbl_status.setText(f"● Đã tìm thấy {len(folders)} thư mục, {len(reg_keys)} khóa Registry.")

    def _on_clean_residuals(self):
        folders = self._current_residuals.get("folders", [])
        reg_keys = self._current_residuals.get("reg_keys", [])
        if not folders and not reg_keys:
            return

        reply = QMessageBox.question(
            self,
            "Xác Nhận Dọn Sạch Tàn Dư",
            f"Bạn có chắc chắn muốn xóa vĩnh viễn:\n\n"
            f"- {len(folders)} thư mục rác trên ổ đĩa\n"
            f"- {len(reg_keys)} khóa tàn dư trong Windows Registry\n\n"
            f"👉 Thao tác này sẽ dọn sạch 100% dấu tích của phần mềm khỏi hệ thống.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        self.lbl_status.setText("⏳ Đang dọn sạch tàn dư...")
        QApplication.processEvents()

        cleaned_f, cleaned_k, msg = UninstallerManager.clean_residuals(self._current_residuals, allow_elevation=True)
        QMessageBox.information(
            self,
            "Dọn Dẹp Tàn Dư Hoàn Tất",
            f"✨ {msg}"
        )

        # Re-scan to verify
        self._on_scan_residuals()
        self._refresh_all_data(force=True)
