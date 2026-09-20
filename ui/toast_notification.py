"""
ui/toast_notification.py – Hệ Thống Thông Báo Tức Thì Trên Màn Hình (On-Screen HUD Toast Notifications v4.0 Pro)
- Tự động hiển thị nổi trên mọi cửa sổ ứng dụng và game (Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus).
- Thiết kế Fluent Dark Acrylic, viền sáng theo cấp độ (Info, Success, Warning, Danger).
- Nút tương tác nhanh 1-Click (Action Buttons) cho phép xử lý sự kiện tức thì.
- Thanh đếm ngược thời gian tự đóng (Countdown Progress Bar), tự dừng khi rê chuột vào.
- Hiệu ứng trượt lên (Slide-up) và mờ dần (Fade-in/Fade-out) mượt mà.
- Hỗ trợ phát âm thanh thông báo nhẹ của Windows.
"""

import sys
import os
from typing import Optional, Callable, List

from PyQt5.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
    QProgressBar, QGraphicsDropShadowEffect, QApplication
)
from PyQt5.QtCore import (
    Qt, QTimer, QPoint, QRect, QPropertyAnimation, QEasingCurve,
    QParallelAnimationGroup, pyqtSignal, QObject
)
from PyQt5.QtGui import QFont, QColor, QCursor

def _qt_object_alive(obj) -> bool:
    """True if the Qt C++ object behind a sip wrapper still exists."""
    if obj is None:
        return False
    try:
        from PyQt5 import sip
        if sip.isdeleted(obj):
            return False
    except Exception:
        pass
    try:
        obj.objectName()
        return True
    except RuntimeError:
        return False
LEVEL_INFO    = "info"
LEVEL_SUCCESS = "success"
LEVEL_WARNING = "warning"
LEVEL_DANGER  = "danger"

_LEVEL_CONFIG = {
    LEVEL_INFO: {
        "border": "#38bdf8",
        "bg_top": "#161b22",
        "bg_bot": "#0d1117",
        "btn_bg": "#1f6feb",
        "btn_hover": "#388bfd",
        "default_icon": "🔔",
        "beep": 0x00000040,  # MB_ICONASTERISK
    },
    LEVEL_SUCCESS: {
        "border": "#3fb950",
        "bg_top": "#13231b",
        "bg_bot": "#0d1117",
        "btn_bg": "#238636",
        "btn_hover": "#2ea043",
        "default_icon": "✅",
        "beep": 0x00000040,
    },
    LEVEL_WARNING: {
        "border": "#d29922",
        "bg_top": "#261d11",
        "bg_bot": "#0d1117",
        "btn_bg": "#9e6a03",
        "btn_hover": "#bb8009",
        "default_icon": "⚡",
        "beep": 0x00000030,  # MB_ICONEXCLAMATION
    },
    LEVEL_DANGER: {
        "border": "#f85149",
        "bg_top": "#2d1517",
        "bg_bot": "#0d1117",
        "btn_bg": "#da3633",
        "btn_hover": "#f85149",
        "default_icon": "🚨",
        "beep": 0x00000010,  # MB_ICONHAND
    }
}


class ToastNotification(QFrame):
    """
    Banner thông báo HUD nổi trên màn hình desktop.
    """
    closed_signal = pyqtSignal(object)

    def __init__(
        self,
        title: str,
        message: str,
        level: str = LEVEL_INFO,
        icon_str: Optional[str] = None,
        action_text: Optional[str] = None,
        action_callback: Optional[Callable] = None,
        duration_ms: int = 4500,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.title_text = title
        self.message_text = message
        self.level = level if level in _LEVEL_CONFIG else LEVEL_INFO
        self.cfg = _LEVEL_CONFIG[self.level]
        self.icon_str = icon_str or self.cfg["default_icon"]
        self.action_text = action_text
        self.action_callback = action_callback
        self.duration_ms = max(1500, duration_ms)
        self.remaining_ms = self.duration_ms
        self.is_paused = False
        self._dismissing = False
        self._finished = False

        # Thiết lập cửa sổ không viền, luôn nổi và không chiếm tiêu điểm bàn phím
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.setFixedWidth(360)
        self._build_ui()

        # Hiệu ứng đổ bóng Acrylic
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 190))
        shadow.setOffset(0, 5)
        self.setGraphicsEffect(shadow)

        # Timer đếm ngược tự đóng và cập nhật thanh tiến trình
        self.step_interval_ms = 40
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)

        self._anim_group = None

    def _build_ui(self):
        root_vbox = QVBoxLayout(self)
        root_vbox.setContentsMargins(0, 0, 0, 0)
        root_vbox.setSpacing(0)

        # Container Frame chính
        self.container = QFrame()
        self.container.setObjectName("toastContainer")
        border_col = self.cfg["border"]
        bg_top = self.cfg["bg_top"]
        bg_bot = self.cfg["bg_bot"]
        self.container.setStyleSheet(f"""
            QFrame#toastContainer {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {bg_top}, stop:1 {bg_bot});
                border: 1.5px solid {border_col};
                border-radius: 10px;
            }}
        """)

        c_layout = QVBoxLayout(self.container)
        c_layout.setContentsMargins(14, 10, 14, 10)
        c_layout.setSpacing(6)

        # Hàng 1: Icon + Tiêu đề + Nút Đóng
        h_top = QHBoxLayout()
        h_top.setSpacing(8)

        clean_title = self.title_text
        if self.icon_str and clean_title.startswith(self.icon_str):
            clean_title = clean_title[len(self.icon_str):].strip()

        lbl_icon = QLabel(self.icon_str)
        lbl_icon.setFont(QFont("Segoe UI Emoji", 14))
        h_top.addWidget(lbl_icon)

        lbl_title = QLabel(clean_title)
        lbl_title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        lbl_title.setStyleSheet("color: #f0f6fc;")
        lbl_title.setWordWrap(False)
        h_top.addWidget(lbl_title, stretch=1)

        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(20, 20)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #8b949e;
                border: none;
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #30363d;
                color: #f0f6fc;
            }
        """)
        self.btn_close.clicked.connect(self.dismiss)
        h_top.addWidget(self.btn_close)
        c_layout.addLayout(h_top)

        # Hàng 2: Nội dung tin nhắn
        lbl_msg = QLabel(self.message_text)
        lbl_msg.setFont(QFont("Segoe UI", 9))
        lbl_msg.setStyleSheet("color: #c9d1d9; line-height: 1.3;")
        lbl_msg.setWordWrap(True)
        c_layout.addWidget(lbl_msg)

        # Hàng 3: Nút hành động nhanh (nếu có)
        if self.action_text:
            h_action = QHBoxLayout()
            h_action.addStretch()
            self.btn_action = QPushButton(self.action_text)
            self.btn_action.setCursor(Qt.PointingHandCursor)
            self.btn_action.setFixedHeight(26)
            btn_bg = self.cfg["btn_bg"]
            btn_hover = self.cfg["btn_hover"]
            self.btn_action.setStyleSheet(f"""
                QPushButton {{
                    background: {btn_bg};
                    color: #ffffff;
                    border: none;
                    border-radius: 5px;
                    padding: 0 14px;
                    font-size: 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {btn_hover};
                }}
            """)
            self.btn_action.clicked.connect(self._on_action_clicked)
            h_action.addWidget(self.btn_action)
            c_layout.addLayout(h_action)

        # Thanh tiến trình tự đóng ở đáy
        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, self.duration_ms)
        self.progress.setValue(self.duration_ms)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                background: #21262d;
                border: none;
                border-bottom-left-radius: 9px;
                border-bottom-right-radius: 9px;
            }}
            QProgressBar::chunk {{
                background: {border_col};
                border-bottom-left-radius: 9px;
                border-bottom-right-radius: 9px;
            }}
        """)

        root_vbox.addWidget(self.container)
        root_vbox.addWidget(self.progress)

        self.adjustSize()

    def _on_tick(self):
        if getattr(self, "_dismissing", False):
            return
        if not _qt_object_alive(self):
            return
        try:
            if self.is_paused:
                return
            self.remaining_ms -= self.step_interval_ms
            if self.remaining_ms <= 0:
                try:
                    if _qt_object_alive(self.timer):
                        self.timer.stop()
                except RuntimeError:
                    pass
                self.dismiss()
            elif _qt_object_alive(getattr(self, "progress", None)):
                self.progress.setValue(self.remaining_ms)
        except RuntimeError:
            return

    def _on_action_clicked(self):
        if getattr(self, "_dismissing", False):
            return
        cb = self.action_callback
        self.action_callback = None
        # Stop the countdown timer BEFORE the callback (which may pump Qt
        # events / open a dialog). Clicking the missing-ping action used to
        # delete the QTimer while _on_tick still ran.
        self.dismiss()
        if cb and callable(cb):
            try:
                cb()
            except Exception as e:
                print(f"[ToastNotification] Lỗi khi thực thi action callback: {e}")

    def enterEvent(self, event):
        """Tạm dừng đếm ngược khi người dùng di chuột vào."""
        if getattr(self, "_dismissing", False) or not _qt_object_alive(self):
            return
        try:
            self.is_paused = True
            self.setWindowOpacity(1.0)
        except RuntimeError:
            return
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Tiếp tục đếm ngược khi người dùng rời chuột."""
        if getattr(self, "_dismissing", False) or not _qt_object_alive(self):
            return
        try:
            self.is_paused = False
        except RuntimeError:
            return
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Nếu có action và click vào nội dung toast, ưu tiên gọi action
            if self.action_callback and callable(self.action_callback):
                self._on_action_clicked()
            else:
                self.dismiss()
        super().mousePressEvent(event)

    def start(self, target_pos: QPoint):
        """Khởi động hiệu ứng trượt lên và hiện mờ dần."""
        self.show()
        start_pos = QPoint(target_pos.x(), target_pos.y() + 30)
        self.move(start_pos)
        self.setWindowOpacity(0.0)

        anim_pos = QPropertyAnimation(self, b"pos")
        anim_pos.setDuration(280)
        anim_pos.setStartValue(start_pos)
        anim_pos.setEndValue(target_pos)
        anim_pos.setEasingCurve(QEasingCurve.OutCubic)

        anim_op = QPropertyAnimation(self, b"windowOpacity")
        anim_op.setDuration(280)
        anim_op.setStartValue(0.0)
        anim_op.setEndValue(0.98)

        self._anim_group = QParallelAnimationGroup(self)
        self._anim_group.addAnimation(anim_pos)
        self._anim_group.addAnimation(anim_op)
        self._anim_group.start()

        self.timer.start(self.step_interval_ms)

    def dismiss(self):
        """Đóng thông báo với hiệu ứng mờ dần. Idempotent — an toàn khi click action."""
        if getattr(self, "_dismissing", False):
            return
        self._dismissing = True
        try:
            if _qt_object_alive(getattr(self, "timer", None)):
                self.timer.stop()
                try:
                    self.timer.timeout.disconnect(self._on_tick)
                except (TypeError, RuntimeError):
                    pass
        except RuntimeError:
            self._finish_dismiss()
            return
        if not _qt_object_alive(self):
            return
        try:
            anim_op = QPropertyAnimation(self, b"windowOpacity", self)
            anim_op.setDuration(220)
            anim_op.setStartValue(self.windowOpacity())
            anim_op.setEndValue(0.0)
            anim_op.finished.connect(self._finish_dismiss)
            anim_op.start()
            self._fade_out_anim = anim_op
        except RuntimeError:
            self._finish_dismiss()

    def _finish_dismiss(self):
        if getattr(self, "_finished", False):
            return
        self._finished = True
        try:
            self.closed_signal.emit(self)
        except RuntimeError:
            pass
        try:
            if _qt_object_alive(self):
                self.close()
                self.deleteLater()
        except RuntimeError:
            pass


class ToastManager(QObject):
    """
    Bộ điều phối hiển thị Toast Notification đa tầng (Stacking Manager).
    """
    _instance = None
    _signal_emitter = None

    # Tín hiệu nội bộ để hiển thị an toàn từ thread nền
    request_toast_signal = pyqtSignal(str, str, str, str, str, object, int, bool)

    def __init__(self):
        super().__init__()
        self.active_toasts: List[ToastNotification] = []
        self.max_stacked = 4
        self.margin_x = 24
        self.margin_y = 28
        self.toast_gap = 12

    @classmethod
    def get_instance(cls) -> 'ToastManager':
        if cls._instance is None:
            cls._instance = ToastManager()
            cls._instance.request_toast_signal.connect(cls._instance._do_show_toast)
        return cls._instance

    @classmethod
    def show_toast(
        cls,
        title: str,
        message: str,
        level: str = LEVEL_INFO,
        icon: Optional[str] = None,
        action_text: Optional[str] = None,
        action_callback: Optional[Callable] = None,
        duration_ms: int = 4500,
        play_sound: bool = False
    ):
        """
        API tĩnh gọi nhanh thông báo tức thì từ bất kỳ đâu trong ứng dụng.
        An toàn khi gọi từ cả main thread và background worker threads.
        """
        mgr = cls.get_instance()
        # Chuyển tiếp an toàn qua PyQt signal
        mgr.request_toast_signal.emit(
            title,
            message,
            level,
            icon or "",
            action_text or "",
            action_callback,
            duration_ms,
            play_sound
        )

    def _do_show_toast(
        self,
        title: str,
        message: str,
        level: str,
        icon: str,
        action_text: str,
        action_callback: Optional[Callable],
        duration_ms: int,
        play_sound: bool
    ):
        # Phát âm thanh Windows nhẹ nếu được yêu cầu
        if play_sound:
            self._play_chime(level)

        toast = ToastNotification(
            title=title,
            message=message,
            level=level,
            icon_str=icon if icon else None,
            action_text=action_text if action_text else None,
            action_callback=action_callback,
            duration_ms=duration_ms
        )
        toast.closed_signal.connect(self._on_toast_closed)

        # Nếu đã đạt giới hạn thông báo đồng thời, đóng thông báo cũ nhất
        if len(self.active_toasts) >= self.max_stacked:
            oldest = self.active_toasts.pop(0)
            oldest.dismiss()

        self.active_toasts.append(toast)
        self._reposition_toasts()

    def _play_chime(self, level: str):
        try:
            import winsound
            cfg = _LEVEL_CONFIG.get(level, _LEVEL_CONFIG[LEVEL_INFO])
            winsound.MessageBeep(cfg.get("beep", winsound.MB_ICONASTERISK))
        except Exception:
            pass

    def _get_available_geometry(self) -> QRect:
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen:
                return screen.availableGeometry()
        return QRect(0, 0, 1920, 1080)

    def _reposition_toasts(self):
        """Căn chỉnh vị trí các toast xếp chồng từ góc dưới bên phải lên trên."""
        geom = self._get_available_geometry()
        screen_right = geom.x() + geom.width()
        screen_bottom = geom.y() + geom.height()

        accumulated_y = screen_bottom - self.margin_y

        # Duyệt từ toast mới nhất (ở dưới cùng) lên toast cũ hơn (ở trên)
        for toast in reversed(self.active_toasts):
            t_w = toast.width()
            t_h = toast.height()
            accumulated_y -= t_h

            target_x = screen_right - self.margin_x - t_w
            target_y = accumulated_y

            if not toast.isVisible():
                toast.start(QPoint(target_x, target_y))
            else:
                # Animate mượt mà đến vị trí mới nếu có toast khác bị đóng
                anim = QPropertyAnimation(toast, b"pos", self)
                anim.setDuration(200)
                anim.setStartValue(toast.pos())
                anim.setEndValue(QPoint(target_x, target_y))
                anim.setEasingCurve(QEasingCurve.OutQuad)
                anim.start()
                toast._reposition_anim = anim

            accumulated_y -= self.toast_gap

    def _on_toast_closed(self, toast: ToastNotification):
        if toast in self.active_toasts:
            self.active_toasts.remove(toast)
            self._reposition_toasts()
