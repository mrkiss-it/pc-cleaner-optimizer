from typing import Optional, Callable
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction

class SystemTrayManager(QSystemTrayIcon):
    # Signals to connect with MainWindow
    quick_clean_requested = pyqtSignal()
    optimize_ram_requested = pyqtSignal()
    network_optimize_requested = pyqtSignal()
    game_boost_requested = pyqtSignal()
    toggle_window_requested = pyqtSignal()
    toggle_floating_widget_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, parent=None, config_manager=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.setIcon(self.create_default_icon())
        self.setToolTip("PC Auto Cleaner & RAM Optimizer\nĐang chạy ngầm bảo vệ hệ thống")

        self.create_context_menu()
        self.activated.connect(self._on_tray_activated)

    def create_default_icon(self) -> QIcon:
        """
        Tạo icon vector sắc nét cho khay hệ thống (màu xanh neon phong cách booster)
        """
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Vòng tròn nền
        painter.setPen(QPen(QColor("#0284c7"), 3))
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.drawEllipse(4, 4, size - 8, size - 8)

        # Biểu tượng tia chớp / tên lửa ở giữa
        painter.setPen(QPen(QColor("#38bdf8"), 2))
        painter.setBrush(QBrush(QColor("#38bdf8")))

        from PyQt5.QtGui import QPolygon
        from PyQt5.QtCore import QPoint
        points = [
            QPoint(34, 12),
            QPoint(20, 34),
            QPoint(32, 34),
            QPoint(28, 52),
            QPoint(44, 28),
            QPoint(33, 28),
        ]
        painter.drawPolygon(QPolygon(points))
        painter.end()

        return QIcon(pixmap)

    def create_context_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
                color: #f8fafc;
                font-family: 'Segoe UI';
                font-size: 12px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #334155;
                margin: 4px 8px;
            }
        """)

        action_open = QAction("🖥️ Mở Bảng Điều Khiển", self)
        action_open.triggered.connect(self.toggle_window_requested.emit)
        menu.addAction(action_open)

        action_widget = QAction("👁️ Ẩn / Hiện Widget Màn Hình", self)
        action_widget.triggered.connect(self.toggle_floating_widget_requested.emit)
        menu.addAction(action_widget)

        menu.addSeparator()

        action_clean = QAction("⚡ Dọn Rác Nhanh", self)
        action_clean.triggered.connect(self.quick_clean_requested.emit)
        menu.addAction(action_clean)

        action_ram = QAction("🚀 Tối Ưu RAM Ngay", self)
        action_ram.triggered.connect(self.optimize_ram_requested.emit)
        menu.addAction(action_ram)

        action_game_boost = QAction("🎮 Tăng Tốc Game (Game Boost)", self)
        action_game_boost.triggered.connect(self.game_boost_requested.emit)
        menu.addAction(action_game_boost)

        action_net = QAction("🌐 Tối Ưu Mạng (Flush DNS)", self)
        action_net.triggered.connect(self.network_optimize_requested.emit)
        menu.addAction(action_net)

        menu.addSeparator()

        action_exit = QAction("❌ Thoát Ứng Dụng", self)
        action_exit.triggered.connect(self.exit_requested.emit)
        menu.addAction(action_exit)

        self.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        # Khi người dùng nhấp đúp hoặc nhấp chuột trái vào icon khay
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window_requested.emit()

    def notify(
        self,
        title: str,
        message: str,
        is_warning: bool = False,
        level: str = "info",
        icon: Optional[str] = None,
        action_text: Optional[str] = None,
        action_callback: Optional[Callable] = None,
        duration_ms: int = 4500
    ):
        """
        Phát thông báo đa phương thức:
        1. On-Screen HUD Toast banner nổi trực tiếp trên màn hình desktop.
        2. Windows Tray Balloon tiêu chuẩn nếu được cấu hình.
        """
        cfg = self.config_manager
        screen_enabled = True
        sound_enabled = False
        tray_enabled = True
        if cfg:
            screen_enabled = cfg.get("instant_screen_notifications_enabled", True)
            sound_enabled = cfg.get("notification_sound_enabled", False)
            tray_enabled = cfg.get("show_notifications", True)

        actual_level = "warning" if is_warning and level == "info" else level

        # 1. On-Screen Instant HUD Toast
        if screen_enabled:
            try:
                from ui.toast_notification import ToastManager
                ToastManager.show_toast(
                    title=title,
                    message=message,
                    level=actual_level,
                    icon=icon,
                    action_text=action_text,
                    action_callback=action_callback,
                    duration_ms=duration_ms,
                    play_sound=sound_enabled
                )
            except Exception as e:
                print(f"[SystemTrayManager] Không thể hiển thị Toast: {e}")

        # 2. Windows Tray Balloon
        if tray_enabled:
            tray_icon = QSystemTrayIcon.Warning if (is_warning or actual_level in ("warning", "danger")) else QSystemTrayIcon.Information
            self.showMessage(title, message, tray_icon, duration_ms)

    def update_tooltip(self, ram_pct: float, cpu_pct: float, net_str: str = ""):
        tip = f"PC Auto Cleaner & RAM Optimizer\nRAM: {ram_pct:.1f}% | CPU: {cpu_pct:.1f}%"
        if net_str:
            tip += f" | Mạng: {net_str}"
        tip += "\nChạy ngầm tự động"
        self.setToolTip(tip)
