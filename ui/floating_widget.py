import sys
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QTimer
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QBrush, QLinearGradient
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, 
    QMenu, QAction, QGraphicsDropShadowEffect
)

from config_manager import ConfigManager
from core.system_monitor import SystemMonitor
from core.memory_optimizer import MemoryOptimizer

class FloatingWidget(QWidget):
    open_dashboard_requested = pyqtSignal()
    open_network_requested = pyqtSignal()
    boost_completed = pyqtSignal(float)

    def __init__(self, config_manager: ConfigManager, monitor_hub=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.monitor_hub = monitor_hub
        self.drag_position = QPoint()

        # Frameless, Always on Top, Tool window (no taskbar item)
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(400, 52)  # Rộng hơn để chứa thêm chỉ số PING

        self.ram_pct = 0.0
        self.cpu_pct = 0.0
        self.ping_ms = -1.0
        self.pulse_state = False
        self.boost_text = ""
        self.boost_timer = QTimer(self)
        self.boost_timer.setSingleShot(True)
        self.boost_timer.timeout.connect(self._clear_boost_text)

        self.init_ui()
        self.restore_position()
        self.update_opacity()

        # Kết nối với Monitor Hub duy nhất để đồng bộ 100% với Bảng điều khiển
        if self.monitor_hub:
            self.monitor_hub.stats_updated.connect(self.update_stats)

        # Timer nhịp tim độc lập 800ms đảm bảo số liệu luôn nhảy liên tục từng giây
        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._on_heartbeat)
        self.heartbeat_timer.start(800)
        self._on_heartbeat()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # Pulse Live Dot (Chấm xanh nhấp nháy báo hiệu đang giám sát trực tiếp)
        self.lbl_pulse = QLabel("●")
        self.lbl_pulse.setStyleSheet("color: #10b981; font-size: 11px; background: transparent;")
        self.lbl_pulse.setToolTip("Đang giám sát thời gian thực (Nhảy số mỗi 800ms)")
        layout.addWidget(self.lbl_pulse, alignment=Qt.AlignCenter)

        # 1. RAM Indicator
        ram_box = QVBoxLayout()
        ram_box.setSpacing(1)
        self.lbl_ram_title = QLabel("RAM")
        self.lbl_ram_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold; background: transparent;")
        self.lbl_ram_val = QLabel("0.0%")
        self.lbl_ram_val.setStyleSheet("color: #38bdf8; font-size: 13px; font-weight: bold; background: transparent; min-width: 48px;")
        ram_box.addWidget(self.lbl_ram_title, alignment=Qt.AlignCenter)
        ram_box.addWidget(self.lbl_ram_val, alignment=Qt.AlignCenter)

        # 2. CPU Indicator
        cpu_box = QVBoxLayout()
        cpu_box.setSpacing(1)
        self.lbl_cpu_title = QLabel("CPU")
        self.lbl_cpu_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold; background: transparent;")
        self.lbl_cpu_val = QLabel("0.0%")
        self.lbl_cpu_val.setStyleSheet("color: #34d399; font-size: 13px; font-weight: bold; background: transparent; min-width: 48px;")
        cpu_box.addWidget(self.lbl_cpu_title, alignment=Qt.AlignCenter)
        cpu_box.addWidget(self.lbl_cpu_val, alignment=Qt.AlignCenter)

        # 3. NET Indicator (download speed)
        net_box = QVBoxLayout()
        net_box.setSpacing(1)
        self.lbl_net_title = QLabel("NET")
        self.lbl_net_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold; background: transparent;")
        self.lbl_net_val = QLabel("↓ 0B")
        self.lbl_net_val.setStyleSheet("color: #a78bfa; font-size: 12px; font-weight: bold; background: transparent; min-width: 60px;")
        net_box.addWidget(self.lbl_net_title, alignment=Qt.AlignCenter)
        net_box.addWidget(self.lbl_net_val, alignment=Qt.AlignCenter)

        # 4. PING Indicator
        ping_box = QVBoxLayout()
        ping_box.setSpacing(1)
        self.lbl_ping_title = QLabel("PING")
        self.lbl_ping_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: bold; background: transparent;")
        self.lbl_ping_val = QLabel("-- ms")
        self.lbl_ping_val.setStyleSheet("color: #34d399; font-size: 12px; font-weight: bold; background: transparent; min-width: 50px;")
        ping_box.addWidget(self.lbl_ping_title, alignment=Qt.AlignCenter)
        ping_box.addWidget(self.lbl_ping_val, alignment=Qt.AlignCenter)

        # 5. 1-Click Boost Rocket Button
        self.btn_boost = QPushButton("🚀")
        self.btn_boost.setToolTip("Click để giải phóng RAM ngay lập tức!")
        self.btn_boost.setCursor(Qt.PointingHandCursor)
        self.btn_boost.setFixedSize(36, 36)
        self.btn_boost.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0284c7, stop:1 #06b6d4);
                color: #ffffff;
                border-radius: 18px;
                font-size: 16px;
                border: 1px solid #38bdf8;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0369a1, stop:1 #0891b2);
            }
            QPushButton:pressed {
                background: #075985;
            }
        """)
        self.btn_boost.clicked.connect(self.quick_boost_ram)

        layout.addLayout(ram_box)
        layout.addLayout(cpu_box)
        layout.addLayout(net_box)
        layout.addLayout(ping_box)
        layout.addWidget(self.btn_boost)

        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect()
        # Draw background pill with glow border
        border_color = QColor("#38bdf8") if self.ram_pct < 80 else QColor("#f43f5e")
        painter.setPen(QPen(border_color, 1.5))
        painter.setBrush(QBrush(QColor(15, 23, 42, 230)))
        painter.drawRoundedRect(1, 1, rect.width() - 2, rect.height() - 2, 24, 24)

        if self.boost_text:
            painter.setPen(QColor("#34d399"))
            font = QFont("Segoe UI", 9, QFont.Bold)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self.boost_text)

    def _on_heartbeat(self):
        self.pulse_state = not self.pulse_state
        dot_color = "#10b981" if self.pulse_state else "#059669"
        self.lbl_pulse.setStyleSheet(f"color: {dot_color}; font-size: 11px; background: transparent;")

        stats = self.monitor_hub.get_latest() if self.monitor_hub else SystemMonitor.get_all_stats()
        self.update_stats(stats)

    def update_stats(self, stats: dict = None):
        if stats is None:
            stats = self.monitor_hub.get_latest() if self.monitor_hub else SystemMonitor.get_all_stats()
        self.ram_pct = stats["ram"]["percent"]
        self.cpu_pct = stats["cpu"]["percent"]

        # Hiển thị 1 chữ số thập phân để thấy rõ giá trị nhảy liên tục theo thời gian thực
        ram_color = "#38bdf8" if self.ram_pct < 75 else ("#fbbf24" if self.ram_pct < 85 else "#f43f5e")
        self.lbl_ram_val.setText(f"{self.ram_pct:.1f}%")
        self.lbl_ram_val.setStyleSheet(f"color: {ram_color}; font-size: 13px; font-weight: bold; background: transparent; min-width: 48px;")

        cpu_color = "#34d399" if self.cpu_pct < 70 else ("#fbbf24" if self.cpu_pct < 85 else "#f43f5e")
        self.lbl_cpu_val.setText(f"{self.cpu_pct:.1f}%")
        self.lbl_cpu_val.setStyleSheet(f"color: {cpu_color}; font-size: 13px; font-weight: bold; background: transparent; min-width: 48px;")

        # Hiển thị tốc độ mạng
        net_info = stats.get("net", {})
        down_str = net_info.get("down_speed_str", "0 B/s")
        self.lbl_net_val.setText(f"↓ {down_str}")

        # Hiển thị Ping trực tiếp trên widget với màu theo mức chất lượng
        from core.system_monitor import format_ping_overlay_text
        ping_val = net_info.get("ping_ms", -1)
        ping_measured = bool(net_info.get("ping_measured"))
        ping_status = str(net_info.get("ping_status") or net_info.get("ping_error") or "")
        self.ping_ms = ping_val
        ping_text = format_ping_overlay_text(ping_val, ping_measured, ping_status)
        if ping_val <= 0:
            ping_color = "#64748b"   # Xám - không đo được
            if ping_measured:
                err = net_info.get("ping_error") or ping_status or "timeout"
                cause_tip = ""
                try:
                    from core.network_optimizer import NetworkOptimizer
                    report = getattr(NetworkOptimizer, "last_missing_ping_report", None) or {}
                    if report.get("cause_label"):
                        cause_tip = f"\nNguyên nhân: {report.get('cause_label')}"
                    if report.get("applied_summary"):
                        cause_tip += f"\nĐã sửa: {report.get('applied_summary')}"
                except Exception:
                    cause_tip = ""
                self.lbl_ping_title.setToolTip(
                    f"Ping không đo được ({err}).{cause_tip}"
                )
                self.lbl_ping_val.setToolTip(
                    f"Lỗi đo Ping: {err}.{cause_tip}"
                )
            else:
                self.lbl_ping_title.setToolTip("Đang đo Ping...")
                self.lbl_ping_val.setToolTip("Đang đo Ping...")
        elif ping_val < 40:
            ping_color = "#34d399"   # Xanh lá - cực nhanh
        elif ping_val < 80:
            ping_color = "#86efac"   # Xanh nhạt - tốt
        elif ping_val < 150:
            ping_color = "#fbbf24"   # Vàng - trung bình
        elif ping_val < 250:
            ping_color = "#fb923c"   # Cam - cao
        else:
            ping_color = "#f43f5e"   # Đỏ - rất cao

        if ping_val > 0:
            self.lbl_ping_title.setToolTip(f"Ping {ping_val:.0f} ms")
            self.lbl_ping_val.setToolTip(f"Ping {ping_val:.0f} ms")

        self.lbl_ping_val.setText(ping_text)
        self.lbl_ping_val.setStyleSheet(
            f"color: {ping_color}; font-size: 12px; font-weight: bold; background: transparent; min-width: 50px;"
        )

        # Tooltip chi tiết khi rê chuột
        ram_info = stats.get("ram", {})
        ping_str = format_ping_overlay_text(ping_val, ping_measured, ping_status)
        if ping_val > 0:
            ping_str = f"{ping_val:.0f}ms"
        repair_line = ""
        try:
            from core.network_optimizer import NetworkOptimizer
            report = getattr(NetworkOptimizer, "last_missing_ping_report", None) or {}
            if report.get("cause_label") or report.get("applied_summary"):
                repair_line = (
                    f"\nChẩn đoán: {report.get('cause_label') or '—'}"
                    f"\nĐã sửa: {report.get('applied_summary') or '—'}"
                )
        except Exception:
            repair_line = ""
        ram_detail = (
            f"RAM: {self.ram_pct:.1f}% ({ram_info.get('used_gb', 0):.1f}/{ram_info.get('total_gb', 0):.1f} GB)\n"
            f"CPU: {self.cpu_pct:.1f}%\n"
            f"Mạng: ↓ {net_info.get('down_speed_str', '0 B/s')} | ↑ {net_info.get('up_speed_str', '0 B/s')}\n"
            f"Ping: {ping_str} | Card: {net_info.get('adapter', 'Wi-Fi')}"
            f"{repair_line}\n"
            f"● Đang nhảy số trực tiếp (800ms)\n"
            f"Click đúp để mở Dashboard"
        )
        self.setToolTip(ram_detail)

        # Ép vẽ lại trên Windows Layered Window
        self.lbl_ram_val.repaint()
        self.lbl_cpu_val.repaint()
        self.lbl_net_val.repaint()
        self.lbl_ping_val.repaint()
        self.lbl_pulse.repaint()
        self.repaint()

    def quick_boost_ram(self):
        if self.boost_text:
            return  # Đang hiển thị kết quả, bỏ qua click dồn dập

        res = MemoryOptimizer.optimize_ram()
        freed = res.get("freed_mb", 0.0)
        self.config_manager.add_history(0.0, freed, trigger_type="floating_widget")
        self.btn_boost.setText("✨")
        self.btn_boost.setToolTip(f"Đã giải phóng +{int(freed)}MB RAM!")
        self.boost_text = f"+{int(freed)}M"
        self.boost_timer.start(1800)

        # Phát signal thông báo để Bảng điều khiển cập nhật Lịch sử & Thống kê ngay lập tức
        self.boost_completed.emit(freed)

        # Ép trạm điều phối cập nhật ngay lập tức cho cả Bảng điều khiển
        if self.monitor_hub:
            self.monitor_hub.force_refresh()
        self._on_heartbeat()

    def _clear_boost_text(self):
        self.boost_text = ""
        self.btn_boost.setText("🚀")
        self.btn_boost.setToolTip("Click để giải phóng RAM ngay lập tức!")
        if self.monitor_hub:
            self.monitor_hub.force_refresh()
        self._on_heartbeat()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.save_position()

    def mouseDoubleClickEvent(self, event):
        self.open_dashboard_requested.emit()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
                color: #f8fafc;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
            }
        """)

        action_boost = QAction("🚀 Tối Ưu RAM Ngay", self)
        action_boost.triggered.connect(self.quick_boost_ram)
        menu.addAction(action_boost)

        action_dash = QAction("🖥️ Mở Bảng Điều Khiển", self)
        action_dash.triggered.connect(self.open_dashboard_requested.emit)
        menu.addAction(action_dash)

        action_gb = QAction("🎮 Bật / Tắt Game Boost", self)
        action_gb.triggered.connect(self.toggle_game_boost)
        menu.addAction(action_gb)

        action_net = QAction("🌐 Tối Ưu Hóa Mạng", self)
        action_net.triggered.connect(self.open_network_requested.emit)
        menu.addAction(action_net)

        menu.addSeparator()

        action_hide = QAction("👁️ Ẩn Widget Này", self)
        action_hide.triggered.connect(self.hide_widget)
        menu.addAction(action_hide)

        menu.exec_(event.globalPos())

    def update_opacity(self):
        op = self.config_manager.get("floating_widget_opacity", 92) / 100.0
        self.setWindowOpacity(max(0.3, min(1.0, op)))

    def toggle_game_boost(self):
        from core.game_booster import GameBooster
        if GameBooster.is_active():
            GameBooster.disable_game_boost()
            self.btn_boost.setText("🚀")
            self.setToolTip("Chế độ bình thường\nClick để tối ưu RAM")
        else:
            GameBooster.enable_game_boost()
            self.btn_boost.setText("🎮")
            self.setToolTip("🎮 ĐANG BẬT GAME BOOST\nĐã tối ưu RAM & CPU cho Gaming!")
        if self.monitor_hub:
            self.monitor_hub.force_refresh()

    def hide_widget(self):
        self.hide()
        self.config_manager.set("floating_widget_enabled", False)

    def show_widget(self):
        self.show()
        self.config_manager.set("floating_widget_enabled", True)

    def toggle_widget(self):
        if self.isVisible():
            self.hide_widget()
        else:
            self.show_widget()

    def save_position(self):
        pos = self.pos()
        self.config_manager.set("floating_widget_x", pos.x())
        self.config_manager.set("floating_widget_y", pos.y())

    def restore_position(self):
        from PyQt5.QtWidgets import QApplication
        primary = QApplication.primaryScreen().geometry()
        default_x = primary.width() - 260
        default_y = 100

        x = self.config_manager.get("floating_widget_x", default_x)
        y = self.config_manager.get("floating_widget_y", default_y)

        # Kiểm tra xem tọa độ (x, y) có nằm trên bất kỳ màn hình nào đang kết nối không
        screens = QApplication.screens()
        is_visible_on_any_screen = False
        for s in screens:
            geom = s.geometry()
            if geom.contains(x + 20, y + 20):
                is_visible_on_any_screen = True
                break

        if not is_visible_on_any_screen:
            x = default_x
            y = default_y

        self.move(x, y)
