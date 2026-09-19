"""
Hardware Monitor Dialog - Trung tâm Giám Sát Cảm Biến Phần Cứng & Độ Chai Pin Laptop.
Cung cấp:
1. Đo lường sức khỏe Pin Laptop: Design Capacity, Full Charge Capacity, Cycle Count, Wear Level %.
2. Xuất báo cáo lịch sử Pin HTML chuẩn của Windows (powercfg /batteryreport).
3. Giám sát CPU đa nhân (Per-core load visualizer), xung nhịp, tên vi xử lý.
4. Nhận diện GPU: Tên card đồ họa, Driver Version, VRAM.
"""

import sys
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QFrame, QMessageBox, QTabWidget, QProgressBar,
    QGridLayout, QScrollArea
)

from core.hardware_monitor import HardwareMonitor
from core.logger import logger


class HardwareMonitorDialog(QDialog):
    """
    Hộp thoại Giám sát Phần cứng & Sức khỏe Pin hiện đại chuẩn Fluent Dark.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔋 Quản Lý Sức Khỏe Pin & Giám Sát Phần Cứng - PC Optimizer Pro")
        self.resize(920, 640)
        self.setMinimumSize(820, 560)
        self.setStyleSheet("""
            QDialog, QLabel, QPushButton {
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel {
                border: none;
                background-color: transparent;
            }
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                background-color: #0f172a;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 10px 24px;
                margin-right: 6px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 13px;
                font-weight: 600;
                min-width: 150px;
            }
            QTabBar::tab:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #334155;
                color: #f8fafc;
            }
            QScrollArea {
                border: none;
                background-color: #0f172a;
            }
            QScrollArea > QWidget > QWidget {
                background-color: #0f172a;
            }
            QScrollBar:vertical {
                border: none;
                background: #0f172a;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #475569;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        self.core_bars = []
        self.core_labels = []

        self.init_ui()

        # Timer cập nhật CPU load & xung nhịp mỗi 1.5s
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_cpu_live)
        self.update_timer.start(1500)

    def init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 20)
        root_layout.setSpacing(14)

        # Header
        header_layout = QHBoxLayout()
        header_left = QVBoxLayout()
        header_left.setSpacing(2)

        lbl_title = QLabel("🔋 CẢM BIẾN PHẦN CỨNG & SỨC KHỎE PIN LAPTOP")
        lbl_title.setStyleSheet("font-size: 17px; font-weight: bold; color: #38bdf8;")
        header_left.addWidget(lbl_title)

        cpu_name = HardwareMonitor.get_cpu_name()
        self.lbl_subtitle = QLabel(f"Thiết bị: {cpu_name}")
        self.lbl_subtitle.setStyleSheet("font-size: 12px; color: #94a3b8;")
        header_left.addWidget(self.lbl_subtitle)

        header_layout.addLayout(header_left)
        header_layout.addStretch()

        btn_refresh = QPushButton("🔄 Làm Mới Dữ Liệu")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #38bdf8;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #38bdf8;
                color: #0f172a;
            }
        """)
        btn_refresh.clicked.connect(self.manual_refresh_all)
        header_layout.addWidget(btn_refresh)

        root_layout.addLayout(header_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_battery = self.create_battery_tab()
        self.tab_cpu_gpu = self.create_cpu_gpu_tab()

        self.tabs.addTab(self.tab_battery, "🔋 Sức Khỏe Pin Laptop")
        self.tabs.addTab(self.tab_cpu_gpu, "💻 Vi Xử Lý & Đồ Họa")

        root_layout.addWidget(self.tabs)

        # Footer
        footer_layout = QHBoxLayout()
        lbl_hint = QLabel("💡 Lưu ý: Báo cáo pin dựa trên telemetry chính thức của hệ điều hành Windows qua công cụ Powercfg.")
        lbl_hint.setStyleSheet("font-size: 11px; color: #64748b; font-style: italic;")
        footer_layout.addWidget(lbl_hint)
        footer_layout.addStretch()

        btn_close = QPushButton("Đóng")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: 600;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_close.clicked.connect(self.accept)
        footer_layout.addWidget(btn_close)

        root_layout.addLayout(footer_layout)

    # =========================================================================
    # TAB 1: BATTERY HEALTH
    # =========================================================================
    def create_battery_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        bat_data = HardwareMonitor.get_battery_info()

        if not bat_data.get("has_battery", False):
            # Desktop PC Card
            desktop_card = QFrame()
            desktop_card.setStyleSheet("""
                QFrame {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    padding: 30px;
                }
            """)
            d_layout = QVBoxLayout(desktop_card)
            d_layout.setAlignment(Qt.AlignCenter)
            d_layout.setSpacing(12)

            lbl_icon = QLabel("🖥️")
            lbl_icon.setStyleSheet("font-size: 56px;")
            lbl_icon.setAlignment(Qt.AlignCenter)
            d_layout.addWidget(lbl_icon)

            lbl_d_title = QLabel("MÁY TÍNH ĐỂ BÀN (DESKTOP PC)")
            lbl_d_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #38bdf8;")
            lbl_d_title.setAlignment(Qt.AlignCenter)
            d_layout.addWidget(lbl_d_title)

            lbl_d_desc = QLabel(
                "Hệ thống phát hiện thiết bị đang sử dụng nguồn điện AC trực tiếp từ ổ cắm.\n"
                "Máy tính để bàn không có pin lưu trữ lithium-ion, do đó không có độ chai pin hoặc chu kỳ sạc."
            )
            lbl_d_desc.setStyleSheet("font-size: 13px; color: #94a3b8; line-height: 1.5;")
            lbl_d_desc.setAlignment(Qt.AlignCenter)
            d_layout.addWidget(lbl_d_desc)

            btn_goto_hw = QPushButton("👉 Chuyển Sang Tab Cảm Biến CPU & GPU")
            btn_goto_hw.setCursor(Qt.PointingHandCursor)
            btn_goto_hw.setStyleSheet("""
                QPushButton {
                    background-color: #0284c7;
                    color: #ffffff;
                    border-radius: 8px;
                    padding: 10px 24px;
                    font-weight: 600;
                    margin-top: 10px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #0369a1;
                }
            """)
            btn_goto_hw.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
            d_layout.addWidget(btn_goto_hw, alignment=Qt.AlignCenter)

            layout.addWidget(desktop_card)
            layout.addStretch()
            return widget

        # --- LAPTOP BATTERY UI ---
        # Update device subtitle
        prod = bat_data.get("system_product_name", "")
        mfg = bat_data.get("system_manufacturer", "")
        if prod and prod != "Laptop Windows":
            self.lbl_subtitle.setText(f"Thiết bị: {mfg} {prod} | {HardwareMonitor.get_cpu_name()}")

        # 1. Top Health Banner Card
        health_banner = QFrame()
        health_banner.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e293b, stop:1 #0f172a);
                border: 1px solid #334155;
                border-radius: 12px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)

        h_layout = QHBoxLayout(health_banner)
        h_layout.setContentsMargins(10, 8, 10, 8)

        # Health Gauge
        health_pct = bat_data.get("health_percent", 100.0)
        health_color = bat_data.get("health_color", "#10b981")
        health_status = bat_data.get("health_status", "Tốt")

        left_box = QVBoxLayout()
        lbl_h_tag = QLabel("SỨC KHỎE PIN TỔNG THỂ")
        lbl_h_tag.setStyleSheet("font-family: 'Segoe UI'; font-size: 11px; font-weight: bold; color: #94a3b8; letter-spacing: 1px;")
        left_box.addWidget(lbl_h_tag)

        self.lbl_health_val = QLabel(f"{health_pct}%")
        self.lbl_health_val.setStyleSheet(f"font-family: 'Segoe UI'; font-size: 34px; font-weight: bold; color: {health_color};")
        left_box.addWidget(self.lbl_health_val)

        self.lbl_health_status = QLabel(f"Đánh giá: {health_status}")
        self.lbl_health_status.setStyleSheet("font-family: 'Segoe UI'; font-size: 13px; font-weight: 600; color: #e2e8f0;")
        left_box.addWidget(self.lbl_health_status)
        h_layout.addLayout(left_box)

        h_layout.addStretch()

        # Current Charge Status
        cur_pct = bat_data.get("percent", 100)
        plugged = bat_data.get("power_plugged", False)
        secs_str = bat_data.get("secs_left_str", "")

        right_box = QVBoxLayout()
        right_box.setAlignment(Qt.AlignRight)

        lbl_c_tag = QLabel("MỨC PIN HIỆN TẠI")
        lbl_c_tag.setStyleSheet("font-family: 'Segoe UI'; font-size: 11px; font-weight: bold; color: #94a3b8; letter-spacing: 1px;")
        lbl_c_tag.setAlignment(Qt.AlignRight)
        right_box.addWidget(lbl_c_tag)

        charge_symbol = "⚡ " if plugged else "🔋 "
        self.lbl_cur_val = QLabel(f"{charge_symbol}{cur_pct}%")
        self.lbl_cur_val.setStyleSheet("font-family: 'Segoe UI'; font-size: 34px; font-weight: bold; color: #38bdf8;")
        self.lbl_cur_val.setAlignment(Qt.AlignRight)
        right_box.addWidget(self.lbl_cur_val)

        self.lbl_cur_status = QLabel(secs_str)
        self.lbl_cur_status.setStyleSheet("font-family: 'Segoe UI'; font-size: 13px; color: #cbd5e1;")
        self.lbl_cur_status.setAlignment(Qt.AlignRight)
        right_box.addWidget(self.lbl_cur_status)

        h_layout.addLayout(right_box)

        layout.addWidget(health_banner)

        # 2. Six Stat Cards Grid
        grid_frame = QWidget()
        grid = QGridLayout(grid_frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        des_mwh = bat_data.get("design_capacity_mwh", 0)
        full_mwh = bat_data.get("full_charge_capacity_mwh", 0)
        cycles = bat_data.get("cycle_count", 0)
        wear = bat_data.get("wear_level_percent", 0.0)

        self.card_des = self.create_stat_card("⚡ Dung Lượng Thiết Kế", f"{des_mwh:,} mWh", "Tiêu chuẩn xuất xưởng")
        self.card_full = self.create_stat_card("📦 Sạc Đầy Hiện Tại", f"{full_mwh:,} mWh", "Khả năng tích điện tối đa")
        self.card_cycles = self.create_stat_card("🔄 Chu Kỳ Sạc (Cycles)", f"{cycles} lần", "Số lần sạc/xả tích lũy")
        self.card_wear = self.create_stat_card("⚠️ Tỉ Lệ Chai Pin", f"{wear}% chai", "Hao mòn theo thời gian", "#f43f5e" if wear > 20 else "#34d399")
        self.card_name = self.create_stat_card("🏷️ Tên Pin & Cell", bat_data.get("battery_name", "Standard"), f"{bat_data.get('manufacturer', '')} ({bat_data.get('chemistry', 'LIon')})")
        self.card_health = self.create_stat_card("🛡️ Tình Trạng Cell", health_status, f"Độ bền đạt {health_pct}%", health_color)

        grid.addWidget(self.card_des, 0, 0)
        grid.addWidget(self.card_full, 0, 1)
        grid.addWidget(self.card_cycles, 0, 2)
        grid.addWidget(self.card_wear, 1, 0)
        grid.addWidget(self.card_name, 1, 1)
        grid.addWidget(self.card_health, 1, 2)

        layout.addWidget(grid_frame)

        # 3. Smart Advice Card
        advice_card = QFrame()
        advice_card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-left: 4px solid #38bdf8;
                border-radius: 8px;
                padding: 12px 16px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        ad_layout = QVBoxLayout(advice_card)
        ad_layout.setContentsMargins(6, 6, 6, 6)
        ad_layout.setSpacing(4)

        lbl_ad_title = QLabel("💡 Lời Khuyên Bảo Dưỡng Pin:")
        lbl_ad_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #38bdf8;")
        ad_layout.addWidget(lbl_ad_title)

        self.lbl_advice = QLabel(bat_data.get("advice", ""))
        self.lbl_advice.setWordWrap(True)
        self.lbl_advice.setStyleSheet("font-size: 12px; color: #cbd5e1; line-height: 1.4;")
        ad_layout.addWidget(self.lbl_advice)

        layout.addWidget(advice_card)

        # 4. Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)

        btn_html_report = QPushButton("📄 Xem Báo Cáo Pin Chi Tiết (Windows Report HTML)")
        btn_html_report.setCursor(Qt.PointingHandCursor)
        btn_html_report.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        btn_html_report.clicked.connect(self.export_html_report)
        btn_bar.addWidget(btn_html_report)

        btn_bar.addStretch()

        layout.addLayout(btn_bar)
        layout.addStretch()
        return widget

    def create_stat_card(self, title: str, value: str, sub: str, val_color: str = "#f8fafc") -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 10px 14px;
            }
            QFrame:hover {
                border-color: #475569;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-family: 'Segoe UI'; font-size: 11px; font-weight: 600; color: #94a3b8;")
        lay.addWidget(lbl_t)

        lbl_v = QLabel(value)
        lbl_v.setStyleSheet(f"font-family: 'Segoe UI'; font-size: 16px; font-weight: bold; color: {val_color};")
        lay.addWidget(lbl_v)

        lbl_s = QLabel(sub)
        lbl_s.setStyleSheet("font-family: 'Segoe UI'; font-size: 11px; color: #64748b;")
        lay.addWidget(lbl_s)

        frame.lbl_val = lbl_v
        frame.lbl_sub = lbl_s
        return frame

    # =========================================================================
    # TAB 2: CPU & GPU SENSORS
    # =========================================================================
    def create_cpu_gpu_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: #0f172a; border: none; }")

        content = QWidget()
        content.setStyleSheet("QWidget { background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI'; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        cpu_data = HardwareMonitor.get_cpu_details()

        # 1. CPU Card
        cpu_frame = QFrame()
        cpu_frame.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 16px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        c_layout = QVBoxLayout(cpu_frame)
        c_layout.setSpacing(10)

        c_header = QHBoxLayout()
        lbl_c_title = QLabel("💻 BỘ VI XỬ LÝ (CPU)")
        lbl_c_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        c_header.addWidget(lbl_c_title)
        c_header.addStretch()

        self.lbl_cpu_load_badge = QLabel(f"Tải: {cpu_data['overall_percent']}%")
        self.lbl_cpu_load_badge.setStyleSheet("""
            background-color: #0284c7;
            color: #ffffff;
            font-size: 12px;
            font-weight: bold;
            border-radius: 4px;
            padding: 3px 10px;
        """)
        c_header.addWidget(self.lbl_cpu_load_badge)
        c_layout.addLayout(c_header)

        # CPU Name & Cores
        lbl_cpu_name = QLabel(cpu_data["name"])
        lbl_cpu_name.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        c_layout.addWidget(lbl_cpu_name)

        self.lbl_cpu_sub = QLabel(
            f"Kiến trúc: {cpu_data['core_summary']} | "
            f"Xung nhịp: {cpu_data['current_freq_ghz']} GHz (Tối đa {cpu_data['max_freq_ghz']} GHz)"
        )
        self.lbl_cpu_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        c_layout.addWidget(self.lbl_cpu_sub)

        # Multi-core Grid
        lbl_grid_tag = QLabel("Mức tải thời gian thực trên từng luồng xử lý:")
        lbl_grid_tag.setStyleSheet("font-size: 12px; font-weight: 600; color: #cbd5e1; margin-top: 6px;")
        c_layout.addWidget(lbl_grid_tag)

        cores_grid = QGridLayout()
        cores_grid.setSpacing(8)

        per_core = cpu_data.get("per_core_percent", [])
        self.core_bars = []
        self.core_labels = []

        cols = 4  # 4 columns for clean layout
        for i, val in enumerate(per_core):
            row = i // cols
            col = i % cols

            c_box = QFrame()
            c_box.setStyleSheet("""
                QFrame {
                    background-color: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 6px 10px;
                }
                QLabel {
                    border: none;
                    background: transparent;
                }
            """)
            b_lay = QHBoxLayout(c_box)
            b_lay.setContentsMargins(4, 2, 4, 2)
            b_lay.setSpacing(8)

            c_lbl = QLabel(f"C{i:02d}")
            c_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #94a3b8;")
            b_lay.addWidget(c_lbl)

            bar = QProgressBar()
            bar.setFixedHeight(12)
            bar.setTextVisible(False)
            bar.setRange(0, 100)
            bar.setValue(int(val))
            self.apply_bar_color(bar, val)
            b_lay.addWidget(bar)

            val_lbl = QLabel(f"{int(val)}%")
            val_lbl.setFixedWidth(34)
            val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #cbd5e1;")
            b_lay.addWidget(val_lbl)

            self.core_bars.append(bar)
            self.core_labels.append(val_lbl)
            cores_grid.addWidget(c_box, row, col)

        c_layout.addLayout(cores_grid)
        layout.addWidget(cpu_frame)

        # 2. GPU Card
        gpus = HardwareMonitor.get_gpu_details()
        gpu_frame = QFrame()
        gpu_frame.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
                padding: 16px;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        g_layout = QVBoxLayout(gpu_frame)
        g_layout.setSpacing(10)

        lbl_g_title = QLabel("🎮 BỘ XỬ LÝ ĐỒ HỌA (GPU)")
        lbl_g_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        g_layout.addWidget(lbl_g_title)

        for gpu in gpus:
            g_item = QFrame()
            g_item.setStyleSheet("""
                QFrame {
                    background-color: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 8px;
                    padding: 12px;
                }
                QLabel {
                    border: none;
                    background: transparent;
                }
            """)
            i_lay = QVBoxLayout(g_item)
            i_lay.setSpacing(6)

            top_row = QHBoxLayout()
            lbl_gpu_name = QLabel(f"🎮 {gpu['name']}")
            lbl_gpu_name.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
            top_row.addWidget(lbl_gpu_name)
            top_row.addStretch()

            lbl_brand = QLabel(gpu.get("brand", "GPU"))
            lbl_brand.setStyleSheet(f"""
                background-color: {gpu.get('brand_color', '#0284c7')};
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
                padding: 3px 8px;
            """)
            top_row.addWidget(lbl_brand)
            i_lay.addLayout(top_row)

            # Details
            lbl_g_info = QLabel(
                f"Bộ nhớ Video: {gpu.get('vram', 'Shared')} | "
                f"Phiên bản Driver: {gpu.get('driver_version', 'N/A')} | "
                f"Trạng thái: {gpu.get('status', 'Hoạt động')}"
            )
            lbl_g_info.setStyleSheet("font-size: 12px; color: #94a3b8;")
            i_lay.addWidget(lbl_g_info)

            g_layout.addWidget(g_item)

        layout.addWidget(gpu_frame)
        layout.addStretch()

        scroll.setWidget(content)
        return scroll

    def apply_bar_color(self, bar: QProgressBar, val: float):
        if val > 80:
            c = "#ef4444"
        elif val > 50:
            c = "#f59e0b"
        else:
            c = "#10b981"
        bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {c};
                border-radius: 2px;
            }}
        """)

    # =========================================================================
    # ACTIONS & REFRESH
    # =========================================================================
    def refresh_cpu_live(self):
        """Cập nhật liên tục CPU usage và per-core bars khi dialog đang mở."""
        if not self.isVisible():
            return
        cpu = HardwareMonitor.get_cpu_details()
        pct = cpu["overall_percent"]
        self.lbl_cpu_load_badge.setText(f"Tải: {pct}%")
        self.lbl_cpu_sub.setText(
            f"Kiến trúc: {cpu['core_summary']} | "
            f"Xung nhịp: {cpu['current_freq_ghz']} GHz (Tối đa {cpu['max_freq_ghz']} GHz)"
        )

        per_core = cpu.get("per_core_percent", [])
        for i, val in enumerate(per_core):
            if i < len(self.core_bars):
                bar = self.core_bars[i]
                lbl = self.core_labels[i]
                bar.setValue(int(val))
                self.apply_bar_color(bar, val)
                lbl.setText(f"{int(val)}%")

    def manual_refresh_all(self):
        """Làm mới toàn diện dữ liệu Pin, CPU và GPU."""
        bat = HardwareMonitor.get_battery_info(force_refresh=True)
        if bat.get("has_battery", False):
            health_pct = bat.get("health_percent", 100.0)
            health_color = bat.get("health_color", "#10b981")
            health_status = bat.get("health_status", "Tốt")
            cur_pct = bat.get("percent", 100)
            plugged = bat.get("power_plugged", False)
            charge_symbol = "⚡ " if plugged else "🔋 "

            self.lbl_health_val.setText(f"{health_pct}%")
            self.lbl_health_val.setStyleSheet(f"font-size: 38px; font-weight: bold; color: {health_color};")
            self.lbl_health_status.setText(f"Đánh giá: {health_status}")

            self.lbl_cur_val.setText(f"{charge_symbol}{cur_pct}%")
            self.lbl_cur_status.setText(bat.get("secs_left_str", ""))

            self.card_des.lbl_val.setText(f"{bat.get('design_capacity_mwh', 0):,} mWh")
            self.card_full.lbl_val.setText(f"{bat.get('full_charge_capacity_mwh', 0):,} mWh")
            self.card_cycles.lbl_val.setText(f"{bat.get('cycle_count', 0)} lần")
            self.card_wear.lbl_val.setText(f"{bat.get('wear_level_percent', 0.0)}% chai")
            self.card_health.lbl_val.setText(health_status)
            self.card_health.lbl_val.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {health_color};")
            self.card_health.lbl_sub.setText(f"Độ bền đạt {health_pct}%")
            self.lbl_advice.setText(bat.get("advice", ""))

        self.refresh_cpu_live()
        QMessageBox.information(
            self,
            "Đã Làm Mới",
            "Dữ liệu cảm biến phần cứng và sức khỏe pin đã được cập nhật thành công!"
        )

    def export_html_report(self):
        """Xuất và mở báo cáo pin HTML Windows chính thức."""
        res_path = HardwareMonitor.export_battery_report_html()
        if res_path:
            logger.info(f"Battery report opened: {res_path}")
        else:
            QMessageBox.warning(
                self,
                "Không Thể Tạo Báo Cáo",
                "Không thể trích xuất báo cáo pin Windows từ công cụ Powercfg. Vui lòng thử lại sau."
            )

    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)
