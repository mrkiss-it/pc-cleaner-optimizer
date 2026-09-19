"""
ui/service_context_dialog.py – Windows Services & Context Menu Manager Dialog (v3.4 Pro)
========================================================================================
Giao diện Fluent Dark 2 Tab:
1. Tab ⚙️ Windows Services Optimizer:
   - Thống kê dịch vụ chạy ngầm, telemetry, indexing, gaming.
   - Nút 1-Click Tối Ưu An Toàn.
   - Bảng tìm kiếm, lọc và điều chỉnh trạng thái khởi động từng dịch vụ.
2. Tab 🖱️ Menu Chuột Phải (Context Menu Cleaner):
   - Thống kê Shell Extensions, phát hiện menu mồ côi (Orphan).
   - Nút Dọn Menu Mồ Côi.
   - Bật/Tắt an toàn từng mục menu chuột phải.
"""
from __future__ import annotations

import os
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QFrame, QMessageBox, QAbstractItemView, QSizePolicy,
    QApplication
)

from core.service_optimizer import (
    ServiceOptimizer, WindowsService,
    RECOMMENDATION_SAFE_DISABLE, RECOMMENDATION_MANUAL, RECOMMENDATION_KEEP,
    CATEGORY_TELEMETRY, CATEGORY_INDEXING, CATEGORY_GAMING, CATEGORY_SYSTEM,
    CATEGORY_TITLES
)
from core.context_menu_manager import ContextMenuManager, ContextMenuItem
from core.network_optimizer import NetworkOptimizer


# ---------------------------------------------------------------------------
# Color Palette & Styles
# ---------------------------------------------------------------------------
_BG           = "#0d1117"
_SURFACE      = "#161b22"
_CARD_BG      = "#1c2128"
_CARD_BORDER  = "#30363d"
_TEXT_PRIMARY = "#e6edf3"
_TEXT_MUTED   = "#8b949e"
_ACCENT_BLUE  = "#58a6ff"
_SUCCESS      = "#3fb950"
_WARNING      = "#e3b341"
_DANGER       = "#f85149"
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
    min-width: 160px;
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


class ServiceContextDialog(QDialog):
    """Hộp thoại quản lý Windows Services và Menu Chuột Phải."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Windows Services & Context Menu Manager – PC Optimizer Pro")
        self.setMinimumSize(920, 640)
        self.resize(1000, 700)
        self.setStyleSheet(DIALOG_STYLE)

        self._services_cache: List[WindowsService] = []
        self._menus_cache: List[ContextMenuItem] = []

        self._build_ui()
        self._refresh_all_data()

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header Title
        header_row = QHBoxLayout()
        icon_lbl = QLabel("⚙️")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 20))
        
        title_box = QVBoxLayout()
        title_lbl = QLabel("Windows Services & Context Menu Optimizer")
        title_lbl.setFont(QFont("Segoe UI Semibold", 13, QFont.Bold))
        title_lbl.setStyleSheet(f"color: {_TEXT_PRIMARY};")
        sub_lbl = QLabel("Tối ưu hóa các dịch vụ chạy ngầm và làm sạch menu chuột phải giúp File Explorer mượt mà")
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
        if not NetworkOptimizer.is_admin():
            btn_admin = QPushButton("🛡️ Chạy Quyền Admin")
            btn_admin.setFixedHeight(32)
            btn_admin.setStyleSheet(f"""
                QPushButton {{
                    background: {_WARNING}22;
                    color: {_WARNING};
                    border: 1px solid {_WARNING};
                    border-radius: 6px;
                    padding: 0 12px;
                    font-weight: bold;
                }}
                QPushButton:hover {{ background: {_WARNING}44; }}
            """)
            btn_admin.setCursor(Qt.PointingHandCursor)
            btn_admin.setToolTip("Khởi động lại ứng dụng với đầy đủ quyền Administrator")
            btn_admin.clicked.connect(self._on_restart_admin)
            header_row.addWidget(btn_admin)

        header_row.addWidget(btn_refresh)

        root.addLayout(header_row)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tab_services = QWidget()
        self.tab_context_menus = QWidget()

        self._build_services_tab()
        self._build_context_menus_tab()

        self.tabs.addTab(self.tab_services, "⚙️ Dịch Vụ Windows")
        self.tabs.addTab(self.tab_context_menus, "🖱️ Menu Chuột Phải")

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
    # Tab 1: Windows Services
    # ------------------------------------------------------------------

    def _build_services_tab(self):
        layout = QVBoxLayout(self.tab_services)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Top Stat Cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        self.card_svc_total = self._create_stat_card("Tổng Dịch Vụ", "0", "Hệ thống Windows", _TEXT_PRIMARY)
        self.card_svc_running = self._create_stat_card("Đang Chạy", "0", "Dịch vụ nền", _SUCCESS)
        self.card_svc_candidates = self._create_stat_card("Có Thể Tối Ưu", "0", "Khuyên tắt / thủ công", _WARNING)

        cards_row.addWidget(self.card_svc_total)
        cards_row.addWidget(self.card_svc_running)
        cards_row.addWidget(self.card_svc_candidates)
        layout.addLayout(cards_row)

        # Action Bar & Filters
        action_bar = QHBoxLayout()
        action_bar.setSpacing(10)

        self.btn_optimize_services = QPushButton("🚀 1-Click Tối Ưu Dịch Vụ Khuyên Dùng")
        self.btn_optimize_services.setFixedHeight(34)
        self.btn_optimize_services.setStyleSheet(f"""
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
        self.btn_optimize_services.setCursor(Qt.PointingHandCursor)
        self.btn_optimize_services.clicked.connect(self._on_1click_optimize_services)
        action_bar.addWidget(self.btn_optimize_services)

        self.txt_svc_search = QLineEdit()
        self.txt_svc_search.setPlaceholderText("🔍 Tìm theo tên hoặc mô tả dịch vụ...")
        self.txt_svc_search.textChanged.connect(self._filter_services_table)
        action_bar.addWidget(self.txt_svc_search, stretch=1)

        self.combo_svc_category = QComboBox()
        self.combo_svc_category.addItem("📋 Tất Cả Dịch Vụ", "all")
        self.combo_svc_category.addItem("⭐ Khuyên Tối Ưu", "candidates")
        self.combo_svc_category.addItem("🛡️ Giám Sát & Telemetry", CATEGORY_TELEMETRY)
        self.combo_svc_category.addItem("🎮 Gaming & Xbox", CATEGORY_GAMING)
        self.combo_svc_category.addItem("🔍 Tìm Kiếm & Chỉ Mục", CATEGORY_INDEXING)
        self.combo_svc_category.addItem("⚙️ Dịch Vụ Hệ Thống", CATEGORY_SYSTEM)
        self.combo_svc_category.currentIndexChanged.connect(self._filter_services_table)
        action_bar.addWidget(self.combo_svc_category)

        layout.addLayout(action_bar)

        # Table
        self.table_services = QTableWidget()
        self.table_services.setColumnCount(6)
        self.table_services.setHorizontalHeaderLabels([
            "Dịch Vụ", "Hiển Thị", "Danh Mục", "Trạng Thái", "Kiểu Khởi Động", "Thao Tác"
        ])
        self.table_services.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_services.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_services.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_services.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_services.setAlternatingRowColors(True)
        self.table_services.verticalHeader().setVisible(False)
        self.table_services.setEditTriggers(QAbstractItemView.NoEditTriggers)

        layout.addWidget(self.table_services, stretch=1)

    # ------------------------------------------------------------------
    # Tab 2: Context Menu Cleaner
    # ------------------------------------------------------------------

    def _build_context_menus_tab(self):
        layout = QVBoxLayout(self.tab_context_menus)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Top Stat Cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        self.card_menu_total = self._create_stat_card("Tổng Menu Chuột Phải", "0", "Extension đã đăng ký", _TEXT_PRIMARY)
        self.card_menu_enabled = self._create_stat_card("Đang Bật", "0", "Hiển thị trong Explorer", _SUCCESS)
        self.card_menu_orphan = self._create_stat_card("Menu Mồ Côi (Rác)", "0", "File DLL không còn tồn tại", _DANGER)

        cards_row.addWidget(self.card_menu_total)
        cards_row.addWidget(self.card_menu_enabled)
        cards_row.addWidget(self.card_menu_orphan)
        layout.addLayout(cards_row)

        # Action Bar & Filters
        action_bar = QHBoxLayout()
        action_bar.setSpacing(10)

        self.btn_clean_orphans = QPushButton("🧹 Dọn Sạch Menu Mồ Côi")
        self.btn_clean_orphans.setFixedHeight(34)
        self.btn_clean_orphans.setStyleSheet(f"""
            QPushButton {{
                background: {_DANGER};
                color: #ffffff;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
                border: none;
            }}
            QPushButton:hover {{ background: #da3633; }}
        """)
        self.btn_clean_orphans.setCursor(Qt.PointingHandCursor)
        self.btn_clean_orphans.clicked.connect(self._on_clean_orphan_menus)
        action_bar.addWidget(self.btn_clean_orphans)

        self.txt_menu_search = QLineEdit()
        self.txt_menu_search.setPlaceholderText("🔍 Tìm theo tên mục menu hoặc nhà phát triển...")
        self.txt_menu_search.textChanged.connect(self._filter_menus_table)
        action_bar.addWidget(self.txt_menu_search, stretch=1)

        self.combo_menu_location = QComboBox()
        self.combo_menu_location.addItem("📋 Tất Cả Vị Trí", "all")
        self.combo_menu_location.addItem("⚠️ Chỉ Menu Mồ Côi", "orphan")
        self.combo_menu_location.addItem("📄 Tập Tin (*)", "file")
        self.combo_menu_location.addItem("📁 Thư Mục (Folder)", "directory")
        self.combo_menu_location.addItem("🖥️ Nền Desktop / Thư Mục", "background")
        self.combo_menu_location.addItem("💾 Ổ Đĩa (Drive)", "drive")
        self.combo_menu_location.currentIndexChanged.connect(self._filter_menus_table)
        action_bar.addWidget(self.combo_menu_location)

        layout.addLayout(action_bar)

        # Table
        self.table_menus = QTableWidget()
        self.table_menus.setColumnCount(6)
        self.table_menus.setHorizontalHeaderLabels([
            "Tên Menu", "Vị Trí", "Nhà Phát Triển", "Trạng Thái File", "Menu", "Thao Tác"
        ])
        self.table_menus.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_menus.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_menus.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_menus.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_menus.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_menus.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_menus.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_menus.setAlternatingRowColors(True)
        self.table_menus.verticalHeader().setVisible(False)
        self.table_menus.setEditTriggers(QAbstractItemView.NoEditTriggers)

        layout.addWidget(self.table_menus, stretch=1)

    # ------------------------------------------------------------------
    # Helper: Stat Card Widget
    # ------------------------------------------------------------------

    def _create_stat_card(self, title: str, val: str, sub: str, color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        card.setStyleSheet(f"""
            QFrame#StatCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
                padding: 8px 12px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setFont(QFont("Segoe UI", 8, QFont.Bold))
        lbl_t.setStyleSheet(f"color: {_TEXT_MUTED};")

        lbl_v = QLabel(val)
        lbl_v.setObjectName("val")
        lbl_v.setFont(QFont("Segoe UI Semibold", 16, QFont.Bold))
        lbl_v.setStyleSheet(f"color: {color};")

        lbl_s = QLabel(sub)
        lbl_s.setObjectName("sub")
        lbl_s.setFont(QFont("Segoe UI", 8))
        lbl_s.setStyleSheet(f"color: {_TEXT_MUTED};")

        layout.addWidget(lbl_t)
        layout.addWidget(lbl_v)
        layout.addWidget(lbl_s)
        return card

    # ------------------------------------------------------------------
    # Data Loading & Rendering
    # ------------------------------------------------------------------

    def _refresh_all_data(self):
        self.lbl_status.setText("Đang làm mới dữ liệu dịch vụ và menu...")
        
        # 1. Services
        self._services_cache = ServiceOptimizer.get_services()
        svc_summary = ServiceOptimizer.get_summary()
        self.card_svc_total.findChild(QLabel, "val").setText(str(svc_summary["total"]))
        self.card_svc_running.findChild(QLabel, "val").setText(str(svc_summary["running"]))
        self.card_svc_candidates.findChild(QLabel, "val").setText(f"{svc_summary['candidates']} dịch vụ")
        self._filter_services_table()

        # 2. Context Menus
        self._menus_cache = ContextMenuManager.scan_items()
        menu_summary = ContextMenuManager.get_summary()
        self.card_menu_total.findChild(QLabel, "val").setText(str(menu_summary["total"]))
        self.card_menu_enabled.findChild(QLabel, "val").setText(str(menu_summary["enabled"]))
        self.card_menu_orphan.findChild(QLabel, "val").setText(f"{menu_summary['orphan']} rác")
        self._filter_menus_table()

        self.lbl_status.setText(f"● Đã tải: {svc_summary['total']} services, {menu_summary['total']} context menu handlers.")

    def _filter_services_table(self):
        query = self.txt_svc_search.text().strip().lower()
        cat_filter = self.combo_svc_category.currentData()

        filtered: List[WindowsService] = []
        for s in self._services_cache:
            if cat_filter == "candidates" and not s.is_candidate:
                continue
            elif cat_filter not in ("all", "candidates") and s.category != cat_filter:
                continue

            if query:
                if query not in s.name.lower() and query not in s.display_name.lower() and query not in s.description.lower():
                    continue

            filtered.append(s)

        self._render_services_table(filtered)

    def _render_services_table(self, services: List[WindowsService]):
        self.table_services.setRowCount(len(services))
        for row, s in enumerate(services):
            # Name
            item_name = QTableWidgetItem(s.name)
            item_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            if s.is_candidate:
                item_name.setForeground(QColor(_WARNING))
            self.table_services.setItem(row, 0, item_name)

            # Display Name
            item_dn = QTableWidgetItem(s.display_name)
            if s.advice_note:
                item_dn.setToolTip(f"💡 Lời khuyên: {s.advice_note}\n\n{s.description}")
            else:
                item_dn.setToolTip(s.description)
            self.table_services.setItem(row, 1, item_dn)

            # Category
            cat_title = CATEGORY_TITLES.get(s.category, s.category)
            item_cat = QTableWidgetItem(cat_title)
            item_cat.setTextAlignment(Qt.AlignCenter)
            self.table_services.setItem(row, 2, item_cat)

            # Status
            item_status = QTableWidgetItem("🟢 Đang chạy" if s.is_running else "⚪ Đã dừng")
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setForeground(QColor(_SUCCESS if s.is_running else _TEXT_MUTED))
            self.table_services.setItem(row, 3, item_status)

            # Start Type
            st_text = s.start_type.capitalize()
            if s.start_type.lower() == "automatic":
                st_text = "⚡ Tự động"
            elif s.start_type.lower() == "manual":
                st_text = "🔧 Thủ công"
            elif s.start_type.lower() == "disabled":
                st_text = "⛔ Đã tắt"
            item_st = QTableWidgetItem(st_text)
            item_st.setTextAlignment(Qt.AlignCenter)
            self.table_services.setItem(row, 4, item_st)

            # Action Button
            btn_act = QPushButton("Tắt" if s.start_type != "disabled" else "Bật")
            btn_act.setFixedHeight(24)
            btn_act.setStyleSheet(f"""
                QPushButton {{
                    background: {_CARD_BG};
                    color: {_ACCENT_BLUE};
                    border: 1px solid {_CARD_BORDER};
                    border-radius: 4px;
                    padding: 0 10px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: #21262d; }}
            """)
            btn_act.setCursor(Qt.PointingHandCursor)
            target_st = "disabled" if s.start_type != "disabled" else "manual"
            btn_act.clicked.connect(lambda checked=False, svc=s.name, t=target_st: self._on_toggle_service(svc, t))
            self.table_services.setCellWidget(row, 5, btn_act)

    def _filter_menus_table(self):
        query = self.txt_menu_search.text().strip().lower()
        loc_filter = self.combo_menu_location.currentData()

        filtered: List[ContextMenuItem] = []
        for m in self._menus_cache:
            if loc_filter == "orphan" and not m.is_orphan:
                continue
            elif loc_filter not in ("all", "orphan") and m.location_key != loc_filter:
                continue

            if query:
                if query not in m.name.lower() and query not in m.company.lower() and query not in (m.dll_path or "").lower():
                    continue

            filtered.append(m)

        self._render_menus_table(filtered)

    def _render_menus_table(self, menus: List[ContextMenuItem]):
        self.table_menus.setRowCount(len(menus))
        for row, m in enumerate(menus):
            # Name
            item_name = QTableWidgetItem(m.name)
            item_name.setFont(QFont("Segoe UI", 9, QFont.Bold))
            if m.is_orphan:
                item_name.setForeground(QColor(_DANGER))
            self.table_menus.setItem(row, 0, item_name)

            # Location
            item_loc = QTableWidgetItem(m.location_title)
            self.table_menus.setItem(row, 1, item_loc)

            # Company
            item_comp = QTableWidgetItem(m.company)
            item_comp.setToolTip(m.dll_path or "Không có DLL trực tiếp")
            self.table_menus.setItem(row, 2, item_comp)

            # DLL Status
            if m.is_orphan:
                st_file = "⚠️ Mồ côi (Mất DLL)"
                color_file = _DANGER
            else:
                st_file = "✅ Bình thường"
                color_file = _SUCCESS
            item_st_f = QTableWidgetItem(st_file)
            item_st_f.setTextAlignment(Qt.AlignCenter)
            item_st_f.setForeground(QColor(color_file))
            self.table_menus.setItem(row, 3, item_st_f)

            # Menu Status
            st_menu = "🟢 Bật" if m.is_enabled else "⚪ Tắt"
            item_st_m = QTableWidgetItem(st_menu)
            item_st_m.setTextAlignment(Qt.AlignCenter)
            item_st_m.setForeground(QColor(_SUCCESS if m.is_enabled else _TEXT_MUTED))
            self.table_menus.setItem(row, 4, item_st_m)

            # Action
            btn_toggle = QPushButton("Tắt" if m.is_enabled else "Bật")
            btn_toggle.setFixedHeight(24)
            btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    background: {_CARD_BG};
                    color: {_TEXT_PRIMARY};
                    border: 1px solid {_CARD_BORDER};
                    border-radius: 4px;
                    padding: 0 10px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: #21262d; }}
            """)
            btn_toggle.setCursor(Qt.PointingHandCursor)
            target_enable = not m.is_enabled
            btn_toggle.clicked.connect(lambda checked=False, item=m, en=target_enable: self._on_toggle_menu(item, en))
            self.table_menus.setCellWidget(row, 5, btn_toggle)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_restart_admin(self):
        reply = QMessageBox.question(
            self,
            "Khởi Động Lại Quyền Administrator",
            "Ứng dụng sẽ tự động khởi động lại với đầy đủ quyền Administrator để bạn quản lý toàn diện dịch vụ và hệ thống.\n\n"
            "👉 Bạn có muốn khởi động lại ngay không?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            ServiceOptimizer.restart_as_admin()

    def _on_toggle_service(self, service_name: str, target_type: str):
        if not NetworkOptimizer.is_admin():
            reply = QMessageBox.question(
                self,
                "Xác Nhận Đổi Trạng Thái Dịch Vụ",
                f"Đổi trạng thái dịch vụ '{service_name}' sang {target_type.upper()} yêu cầu quyền Administrator.\n\n"
                f"Bạn có muốn cấp quyền UAC (bấm 'Yes' khi Windows hỏi) để thực hiện ngay không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return

        ok, msg = ServiceOptimizer.apply_service_state(service_name, target_type, stop_if_running=True, allow_elevation=True)
        if ok:
            QMessageBox.information(self, "Thành Công", msg)
            self._refresh_all_data()
        else:
            QMessageBox.warning(self, "Thông Báo", msg)

    def _on_1click_optimize_services(self):
        if not NetworkOptimizer.is_admin():
            reply = QMessageBox.question(
                self,
                "Xác Nhận Tối Ưu Dịch Vụ Hệ Thống",
                "Tối ưu hóa các dịch vụ nền Windows yêu cầu quyền Administrator.\n\n"
                "Ứng dụng sẽ gửi yêu cầu cấp quyền UAC tới Windows để tự động tối ưu 7 dịch vụ nền khuyên dùng.\n\n"
                "👉 Bạn có muốn tiếp tục và bấm 'Yes' khi Windows hiển thị hộp thoại xác nhận không?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                self.lbl_status.setText("● Đã hủy tối ưu dịch vụ.")
                return

        self.lbl_status.setText("⏳ Đang gửi yêu cầu UAC và tối ưu hóa dịch vụ...")
        self.btn_optimize_services.setEnabled(False)
        self.btn_optimize_services.setText("⏳ Đang Tối Ưu...")
        QApplication.processEvents()

        try:
            res = ServiceOptimizer.one_click_optimize(allow_elevation=True)
            if res.get("success", False):
                details_str = "\n".join(res.get("details", []))
                QMessageBox.information(
                    self,
                    "Tối Ưu Dịch Vụ Hoàn Tất",
                    f"✨ {res.get('message')}\n\n{details_str}"
                )
            else:
                details_str = "\n".join(res.get("details", []))
                msg_body = res.get('message', 'Thao tác không thành công.')
                if details_str:
                    msg_body += f"\n\nChi tiết lỗi:\n{details_str}"
                QMessageBox.warning(
                    self,
                    "Thông Báo",
                    msg_body
                )
        finally:
            self.btn_optimize_services.setEnabled(True)
            self.btn_optimize_services.setText("🚀 1-Click Tối Ưu Dịch Vụ Khuyên Dùng")
            self._refresh_all_data()

    def _on_toggle_menu(self, item: ContextMenuItem, enable: bool):
        ok, msg = ContextMenuManager.toggle_item(item, enable)
        if ok:
            self._refresh_all_data()
        else:
            QMessageBox.warning(self, "Lỗi Thao Tác", msg)

    def _on_clean_orphan_menus(self):
        cleaned_cnt, details = ContextMenuManager.clean_orphan_items()
        if cleaned_cnt > 0:
            details_str = "\n".join(details)
            QMessageBox.information(
                self,
                "Dọn Dẹp Menu Mồ Côi Hoàn Tất",
                f"✨ Đã vô hiệu hóa thành công {cleaned_cnt} mục menu mồ côi rác!\n\n{details_str}"
            )
            self._refresh_all_data()
        else:
            QMessageBox.information(
                self,
                "Menu Chuột Phải Sạch Sẽ",
                "Không phát hiện thấy menu mồ côi nào trên hệ thống."
            )
