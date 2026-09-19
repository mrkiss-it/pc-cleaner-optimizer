import math
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QCheckBox
)

class CircularGauge(QWidget):
    def __init__(self, title="RAM", unit="%", parent=None):
        super().__init__(parent)
        self.title = title
        self.unit = unit
        self.value = 0.0
        self.subtitle = ""
        self.setMinimumSize(160, 160)

    def set_value(self, val: float, subtitle: str = ""):
        self.value = max(0.0, min(100.0, val))
        self.subtitle = subtitle
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        side = min(width, height)
        painter.translate(width / 2, height / 2)

        stroke_width = 12
        radius = (side - stroke_width - 16) / 2
        rect = QRectF(-radius, -radius, radius * 2, radius * 2)

        # 1. Background Track Arc (Slate-800)
        bg_pen = QPen(QColor("#1e293b"), stroke_width)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, -210 * 16, 240 * 16)

        # 2. Progress Arc with Dynamic Gradient
        if self.value > 0:
            # Color logic based on value
            if self.value < 65:
                color_start = QColor("#06b6d4")  # Cyan
                color_end = QColor("#10b981")    # Emerald
            elif self.value < 85:
                color_start = QColor("#38bdf8")  # Sky
                color_end = QColor("#f59e0b")    # Amber
            else:
                color_start = QColor("#f59e0b")  # Amber
                color_end = QColor("#f43f5e")    # Rose

            gradient = QLinearGradient(-radius, -radius, radius, radius)
            gradient.setColorAt(0.0, color_start)
            gradient.setColorAt(1.0, color_end)

            prog_pen = QPen(gradient, stroke_width)
            prog_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(prog_pen)

            span_angle = int(-(self.value / 100.0) * 240 * 16)
            painter.drawArc(rect, -210 * 16, span_angle)

        # 3. Center Text
        painter.setPen(QColor("#f8fafc"))
        font = QFont("Segoe UI", 16, QFont.Bold)
        painter.setFont(font)
        val_str = f"{int(self.value)}{self.unit}"
        painter.drawText(QRectF(-radius, -radius - 8, radius * 2, radius), Qt.AlignCenter, val_str)

        # Title
        painter.setPen(QColor("#94a3b8"))
        font_title = QFont("Segoe UI", 9, QFont.DemiBold)
        painter.setFont(font_title)
        painter.drawText(QRectF(-radius, -radius + 32, radius * 2, radius), Qt.AlignCenter, self.title)

        # Subtitle
        if self.subtitle:
            painter.setPen(QColor("#64748b"))
            font_sub = QFont("Segoe UI", 8)
            painter.setFont(font_sub)
            painter.drawText(QRectF(-radius, radius - 20, radius * 2, 20), Qt.AlignCenter, self.subtitle)


class StatCard(QFrame):
    def __init__(self, icon: str, title: str, initial_value: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("StatCardBox")
        self.setStyleSheet("""
            QFrame#StatCardBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
            }
            QFrame#StatCardBox:hover {
                border-color: #475569;
                background-color: #243044;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        # Header (Icon + Title)
        header_layout = QHBoxLayout()
        self.lbl_icon = QLabel(icon)
        self.lbl_icon.setStyleSheet("font-size: 20px; background: transparent; border: none;")
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #94a3b8; font-size: 13px; font-weight: 600; background: transparent; border: none;")
        header_layout.addWidget(self.lbl_icon)
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()

        # Value
        self.lbl_value = QLabel(initial_value)
        self.lbl_value.setStyleSheet("color: #38bdf8; font-size: 24px; font-weight: bold; background: transparent; border: none;")

        # Subtitle
        self.lbl_subtitle = QLabel(subtitle)
        self.lbl_subtitle.setStyleSheet("color: #64748b; font-size: 11px; background: transparent; border: none;")

        layout.addLayout(header_layout)
        layout.addWidget(self.lbl_value)
        layout.addWidget(self.lbl_subtitle)

    def set_value(self, val: str, sub: str = None):
        self.lbl_value.setText(val)
        if sub is not None:
            self.lbl_subtitle.setText(sub)


class CleanerTargetRow(QFrame):
    def __init__(self, key: str, title: str, description: str, checked: bool = True, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("TargetRowBox")
        self.setStyleSheet("""
            QFrame#TargetRowBox {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QFrame#TargetRowBox:hover {
                border-color: #475569;
                background-color: #243044;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #f8fafc; font-weight: 600; font-size: 13px;")
        self.lbl_desc = QLabel(description)
        self.lbl_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        info_layout.addWidget(self.lbl_title)
        info_layout.addWidget(self.lbl_desc)

        self.lbl_badge = QLabel("Chưa quét")
        self.lbl_badge.setStyleSheet("""
            background-color: #0f172a;
            color: #94a3b8;
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
        """)

        layout.addWidget(self.checkbox)
        layout.addLayout(info_layout, stretch=1)
        layout.addWidget(self.lbl_badge)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_badge(self, text: str, is_warning: bool = False):
        self.lbl_badge.setText(text)
        if is_warning:
            self.lbl_badge.setStyleSheet("""
                background-color: #451a03;
                color: #fbbf24;
                padding: 4px 8px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #78350f;
            """)
        else:
            self.lbl_badge.setStyleSheet("""
                background-color: #0f172a;
                color: #38bdf8;
                padding: 4px 8px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            """)
