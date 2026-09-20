"""
Thẻ giám sát nhiệt laptop — Fluent Dark, tiếng Việt.

Hiện số khi có cảm biến; empty-state trung thực khi Windows không lộ sensor.
Không bịa °C.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.thermal_monitor import (
    DEFAULT_WARN_CELSIUS,
    EMPTY_HINT_VI,
    EMPTY_STATE_VI,
    build_thermal_snapshot,
    ensure_snapshot_async,
    format_celsius,
    peek_cached_snapshot,
    pending_snapshot,
)


_STATUS_COLORS = {
    "ok": "#34d399",
    "warm": "#f59e0b",
    "hot": "#f87171",
    "unavailable": "#94a3b8",
    "pending": "#38bdf8",
}

_BTN_STYLE = """
    QPushButton {
        background-color: #334155;
        color: #f8fafc;
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 11px;
        border: 1px solid #475569;
    }
    QPushButton:hover { background-color: #475569; border-color: #38bdf8; }
"""


class ThermalCard(QFrame):
    """Dashboard / Hardware / Settings card for laptop temperatures."""

    snapshot_applied = pyqtSignal(dict)

    def __init__(
        self,
        parent=None,
        *,
        compact: bool = False,
        show_sensors: bool = False,
        warn_celsius: float = DEFAULT_WARN_CELSIUS,
        open_hardware: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(parent)
        self.setObjectName("ThermalCard")
        self.compact = bool(compact)
        self.show_sensors = bool(show_sensors)
        self.warn_celsius = float(warn_celsius)
        self._open_hardware = open_hardware
        self._snapshot: Dict[str, Any] = pending_snapshot(self.warn_celsius)
        self.setStyleSheet(self._frame_style("pending"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.lbl_title = QLabel("🌡️ Nhiệt laptop")
        self.lbl_title.setStyleSheet("color: #67e8f9; font-size: 13px; font-weight: 800; background: transparent; border: none;")
        header.addWidget(self.lbl_title)
        header.addStretch()
        self.lbl_badge = QLabel("Đang kiểm tra")
        self.lbl_badge.setStyleSheet(self._badge_style("pending"))
        header.addWidget(self.lbl_badge)
        layout.addLayout(header)

        self.lbl_temps = QLabel("CPU —   ·   GPU —")
        self.lbl_temps.setStyleSheet("color: #f8fafc; font-size: 16px; font-weight: 700; background: transparent; border: none;")
        layout.addWidget(self.lbl_temps)

        self.lbl_body = QLabel("Đang kiểm tra cảm biến nhiệt trên máy này…")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setStyleSheet("color: #cbd5e1; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_body)

        self.lbl_sensors = QLabel("")
        self.lbl_sensors.setWordWrap(True)
        self.lbl_sensors.setTextFormat(Qt.RichText)
        self.lbl_sensors.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent; border: none;")
        self.lbl_sensors.setVisible(self.show_sensors)
        layout.addWidget(self.lbl_sensors)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_refresh = QPushButton("Làm mới")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setStyleSheet(_BTN_STYLE)
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        btn_row.addWidget(self.btn_refresh)

        self.btn_hardware = QPushButton("Xem phần cứng")
        self.btn_hardware.setCursor(Qt.PointingHandCursor)
        self.btn_hardware.setStyleSheet(_BTN_STYLE)
        self.btn_hardware.clicked.connect(self._on_open_hardware)
        self.btn_hardware.setVisible(open_hardware is not None)
        btn_row.addWidget(self.btn_hardware)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Thread-safe apply from background collect.
        self._ready = _SnapshotBridge(self)
        self._ready.ready.connect(self.apply_snapshot)

        self.apply_snapshot(self._snapshot)

    def set_warn_celsius(self, value: float) -> None:
        try:
            self.warn_celsius = float(value)
        except (TypeError, ValueError):
            self.warn_celsius = DEFAULT_WARN_CELSIUS
        cached = peek_cached_snapshot()
        if cached:
            self.apply_snapshot(cached)

    def apply_snapshot(self, snapshot: Optional[Dict[str, Any]] = None) -> None:
        snap = snapshot if isinstance(snapshot, dict) else pending_snapshot(self.warn_celsius)
        # Re-evaluate hot/status against the current Settings threshold.
        warn = self.warn_celsius
        if snap.get("available"):
            snap = dict(snap)
            snap["warn_celsius"] = warn
            hottest = snap.get("hottest_celsius")
            try:
                snap["hot"] = hottest is not None and float(hottest) >= float(warn)
            except (TypeError, ValueError):
                snap["hot"] = False
            from core.thermal_monitor import classify_status, STATUS_LABELS_VI
            snap["status"] = classify_status(
                snap.get("hottest_celsius"), warn, available=True
            )
            snap["status_label"] = STATUS_LABELS_VI.get(snap["status"], snap["status"])
        self._snapshot = snap
        status = str(snap.get("status") or "unavailable")
        self.setStyleSheet(self._frame_style(status))
        self.lbl_badge.setText(str(snap.get("status_label") or "—"))
        self.lbl_badge.setStyleSheet(self._badge_style(status))

        if snap.get("pending") and not snap.get("available"):
            self.lbl_temps.setText("CPU —   ·   GPU —")
            self.lbl_body.setText(str(snap.get("empty_message") or "Đang kiểm tra cảm biến nhiệt…"))
            self.lbl_sensors.setText("")
            self.snapshot_applied.emit(snap)
            return

        if not snap.get("available"):
            self.lbl_temps.setText("Không có số nhiệt độ")
            self.lbl_temps.setStyleSheet(
                "color: #94a3b8; font-size: 15px; font-weight: 700; background: transparent; border: none;"
            )
            body = str(snap.get("empty_message") or EMPTY_STATE_VI)
            hint = str(snap.get("hint") or EMPTY_HINT_VI)
            self.lbl_body.setText(f"{body} {hint}".strip())
            self.lbl_sensors.setText("")
            self.snapshot_applied.emit(snap)
            return

        cpu = snap.get("cpu_celsius")
        gpu = snap.get("gpu_celsius")
        hottest = snap.get("hottest_celsius")
        color = _STATUS_COLORS.get(status, "#38bdf8")
        self.lbl_temps.setStyleSheet(
            f"color: {color}; font-size: 16px; font-weight: 700; background: transparent; border: none;"
        )
        self.lbl_temps.setText(
            f"CPU {format_celsius(cpu)}   ·   GPU {format_celsius(gpu)}"
            + (f"   ·   Nóng nhất {format_celsius(hottest)}" if hottest is not None else "")
        )
        src = str(snap.get("source_label") or "")
        bits = []
        if snap.get("hot"):
            bits.append(
                f"Vượt ngưỡng {int(warn)}°C — đặt máy trên bề mặt cứng, kiểm tra quạt / khe gió."
            )
        elif status == "warm":
            bits.append(f"Ấm (gần ngưỡng {int(warn)}°C). Theo dõi khi chơi game / render.")
        else:
            bits.append("Nhiệt đang ổn định.")
        if src:
            bits.append(f"Nguồn: {src}.")
        self.lbl_body.setText(" ".join(bits))

        if self.show_sensors:
            lines = []
            for item in snap.get("sensors") or []:
                kind = str(item.get("kind") or "other")
                kind_vi = {"package": "Package", "cpu": "CPU", "gpu": "GPU", "other": "Khác"}.get(kind, kind)
                lines.append(
                    f"• {item.get('name')} — {format_celsius(item.get('celsius'))} "
                    f"<span style='color:#64748b'>({kind_vi})</span>"
                )
            self.lbl_sensors.setText("<br/>".join(lines[:12]))
        self.snapshot_applied.emit(snap)

    def refresh(self, force: bool = False) -> None:
        cached = peek_cached_snapshot()
        if cached and not force:
            self.apply_snapshot(cached)
        elif force:
            self.apply_snapshot(pending_snapshot(self.warn_celsius))

        def _done(snap: Dict[str, Any]) -> None:
            self._ready.ready.emit(snap)

        ensure_snapshot_async(_done, force_refresh=force, warn_celsius=self.warn_celsius)

    def current_snapshot(self) -> Dict[str, Any]:
        return dict(self._snapshot)

    def _on_open_hardware(self) -> None:
        if self._open_hardware:
            self._open_hardware()

    def _frame_style(self, status: str) -> str:
        border = {
            "hot": "#b91c1c",
            "warm": "#b45309",
            "ok": "#155e75",
            "unavailable": "#334155",
            "pending": "#155e75",
        }.get(status, "#334155")
        bg = {
            "hot": "#3f1214",
            "warm": "#2a1d0a",
            "ok": "#0f2a3a",
            "unavailable": "#1e293b",
            "pending": "#0f2a3a",
        }.get(status, "#1e293b")
        return f"""
            QFrame#ThermalCard {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """

    def _badge_style(self, status: str) -> str:
        bg = _STATUS_COLORS.get(status, "#334155")
        fg = "#0f172a" if status in ("ok", "warm", "pending") else "#ffffff"
        if status == "unavailable":
            fg = "#0f172a"
        return (
            f"background-color: {bg}; color: {fg}; font-size: 10px; font-weight: 800; "
            f"border-radius: 4px; padding: 3px 8px;"
        )


class _SnapshotBridge(QFrame):
    """Tiny QObject-ish widget whose signal can be emitted from a worker thread."""

    ready = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()


def snapshot_or_empty(sensors=None, **kwargs) -> Dict[str, Any]:
    return build_thermal_snapshot(sensors or [], **kwargs)
