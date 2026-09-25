"""
Thẻ / khối «Ổn định Wi-Fi»: gợi ý 5 GHz, driver MT7921, tiết kiệm pin, Location.

Không tuyên bố app đã sửa driver hay sóng RF.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core.wifi_stability import (
    DISCLAIMER,
    NOTE_DISABLED,
    NOTE_JUST_ENABLED,
    build_wifi_stability_guidance,
    format_stability_status_text,
    open_windows_target,
)


_BTN_STYLE = """
    QPushButton {
        background-color: #334155;
        color: #f8fafc;
        font-weight: 600;
        padding: 7px 12px;
        border-radius: 6px;
        font-size: 11px;
        border: 1px solid #475569;
    }
    QPushButton:hover { background-color: #475569; border-color: #38bdf8; }
    QPushButton:disabled {
        background-color: #1e293b;
        color: #64748b;
        border: 1px solid #334155;
    }
"""


def _notify(title: str, message: str, ok: bool = True) -> None:
    try:
        from ui.toast_notification import ToastManager, LEVEL_SUCCESS, LEVEL_INFO, LEVEL_WARNING
        ToastManager.show_toast(
            title=title,
            message=message,
            level=LEVEL_SUCCESS if ok else LEVEL_WARNING,
            icon="📶",
            duration_ms=4200,
        )
    except Exception:
        pass


class WifiStabilityCard(QFrame):
    """Tip card plus the Ổn định Wi-Fi monitor toggle (default off)."""

    def __init__(self, parent=None, *, always_visible: bool = False, show_monitor: bool = True):
        super().__init__(parent)
        self.setObjectName("WifiStabilityCard")
        self.always_visible = bool(always_visible)
        self.show_monitor = bool(show_monitor)
        self._unlock_location: Optional[Callable[[], Any]] = None
        self._disable_power_save: Optional[Callable[[], Any]] = None
        self._on_monitor_toggle: Optional[Callable[[bool], Any]] = None
        self._guidance: Dict[str, Any] = {}
        self.setStyleSheet("""
            QFrame#WifiStabilityCard {
                background-color: #0f2a3a;
                border: 1px solid #155e75;
                border-radius: 8px;
            }
            QLabel { background: transparent; border: none; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.lbl_title = QLabel("📶 Ổn định Wi-Fi")
        self.lbl_title.setStyleSheet("color: #67e8f9; font-size: 13px; font-weight: 800;")
        layout.addWidget(self.lbl_title)

        self.chk_monitor = QCheckBox("Bật Ổn định Wi-Fi (theo dõi kết nối, mặc định tắt)")
        self.chk_monitor.setStyleSheet("font-weight: bold; font-size: 12px; color: #67e8f9;")
        self.chk_monitor.setChecked(False)
        self.chk_monitor.setVisible(self.show_monitor)
        layout.addWidget(self.chk_monitor)

        self.lbl_monitor_help = QLabel(
            "Khi bật: theo dõi ping và card Wi-Fi. Chỉ reconnect hoặc renew DHCP khi mất mạng thật "
            "và đã kéo dài. Không Flush DNS, không reset stack, không đụng trình duyệt, không VPN, "
            "không tự hiện UAC. Tắt «tự động tối ưu mạng» không tắt chế độ này; bật chế độ này cũng "
            "không bật lại vòng Flush DNS. Nếu ô «Khi Ping / Wi-Fi rớt» đang bật, đường đó vẫn có thể "
            "flush khi ping thật sự mất — tắt ô đó nếu bạn chỉ muốn sửa nhẹ."
        )
        self.lbl_monitor_help.setWordWrap(True)
        self.lbl_monitor_help.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.lbl_monitor_help.setVisible(self.show_monitor)
        layout.addWidget(self.lbl_monitor_help)

        self.lbl_monitor_status = QLabel(NOTE_DISABLED)
        self.lbl_monitor_status.setWordWrap(True)
        self.lbl_monitor_status.setStyleSheet("color: #e2e8f0; font-size: 11px;")
        self.lbl_monitor_status.setVisible(self.show_monitor)
        layout.addWidget(self.lbl_monitor_status)
        self.chk_monitor.toggled.connect(self._emit_monitor_toggle)

        self.lbl_intro = QLabel(DISCLAIMER)
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setStyleSheet("color: #a5f3fc; font-size: 11px;")
        layout.addWidget(self.lbl_intro)

        self.lbl_tips = QLabel("")
        self.lbl_tips.setWordWrap(True)
        self.lbl_tips.setTextFormat(Qt.RichText)
        self.lbl_tips.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        layout.addWidget(self.lbl_tips)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_5ghz = QPushButton("Mở mạng Wi-Fi")
        self.btn_driver = QPushButton("Device Manager")
        self.btn_power = QPushButton("Tắt tiết kiệm pin")
        self.btn_location = QPushButton("Gỡ khóa Location")
        for btn in (self.btn_5ghz, self.btn_driver, self.btn_power, self.btn_location):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(_BTN_STYLE)
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.btn_5ghz.clicked.connect(lambda: self._open_target("wifi_settings"))
        self.btn_driver.clicked.connect(lambda: self._open_target("device_manager"))
        self.btn_power.clicked.connect(self._on_power_save)
        self.btn_location.clicked.connect(self._on_unlock_location)
        self.btn_location.setVisible(False)

        self.apply_guidance(build_wifi_stability_guidance())
        if self.always_visible or self.show_monitor:
            self.setVisible(True)

    def bind(
        self,
        *,
        unlock_location: Optional[Callable[[], Any]] = None,
        disable_power_save: Optional[Callable[[], Any]] = None,
        on_monitor_toggle: Optional[Callable[[bool], Any]] = None,
    ) -> None:
        self._unlock_location = unlock_location
        self._disable_power_save = disable_power_save
        if on_monitor_toggle is not None:
            self._on_monitor_toggle = on_monitor_toggle

    def set_monitor_enabled(self, enabled: bool) -> None:
        """Sync the checkbox without writing config again."""
        enabled = bool(enabled)
        if self.chk_monitor.isChecked() == enabled:
            return
        self.chk_monitor.blockSignals(True)
        self.chk_monitor.setChecked(enabled)
        self.chk_monitor.blockSignals(False)

    def apply_monitor_status(self, status: Optional[Dict[str, Any]] = None) -> None:
        data = status if isinstance(status, dict) else {}
        if not data:
            self.lbl_monitor_status.setText(NOTE_DISABLED if not self.chk_monitor.isChecked() else NOTE_JUST_ENABLED)
            return
        shown = dict(data)
        shown["enabled"] = bool(self.chk_monitor.isChecked()) if self.show_monitor else bool(data.get("enabled"))
        if shown["enabled"] and shown.get("note") == NOTE_DISABLED:
            shown["note"] = NOTE_JUST_ENABLED
        if not shown["enabled"]:
            shown["note"] = NOTE_DISABLED
        self.lbl_monitor_status.setText(format_stability_status_text(shown))

    def _emit_monitor_toggle(self, checked: bool) -> None:
        if checked:
            self.lbl_monitor_status.setText(NOTE_JUST_ENABLED)
        else:
            self.lbl_monitor_status.setText(NOTE_DISABLED)
        if self._on_monitor_toggle:
            self._on_monitor_toggle(bool(checked))

    def apply_guidance(self, guidance: Optional[Dict[str, Any]] = None) -> None:
        data = guidance if isinstance(guidance, dict) else build_wifi_stability_guidance()
        self._guidance = data
        self.lbl_title.setText(f"📶 {data.get('title') or 'Ổn định Wi-Fi'}")
        self.lbl_intro.setText(str(data.get("intro") or DISCLAIMER))
        bullets = []
        for tip in data.get("tips") or []:
            text = str(tip.get("text") or "").strip()
            if text:
                bullets.append(f"• {text}")
        self.lbl_tips.setText("<br/>".join(bullets))
        loc_on = bool(data.get("location_locked"))
        show_guidance = self.always_visible or bool(data.get("offer")) or loc_on
        self.lbl_intro.setVisible(show_guidance)
        self.lbl_tips.setVisible(show_guidance)
        self.btn_5ghz.setVisible(show_guidance)
        self.btn_driver.setVisible(show_guidance)
        self.btn_power.setVisible(show_guidance)
        self.btn_location.setVisible(show_guidance and loc_on)
        if self.always_visible or self.show_monitor or show_guidance:
            self.setVisible(True)
        else:
            self.setVisible(False)

    def refresh_from_detect(
        self,
        detect: Optional[Dict[str, Any]] = None,
        last_report: Optional[Dict[str, Any]] = None,
        unrecovered_repairs: int = 0,
        force_show: bool = False,
    ) -> None:
        guidance = build_wifi_stability_guidance(
            detect=detect,
            last_report=last_report,
            unrecovered_repairs=unrecovered_repairs,
        )
        self.apply_guidance(guidance)
        if force_show:
            self.setVisible(True)

    def _open_target(self, target: str) -> None:
        result = open_windows_target(target)
        msg = str(result.get("message") or "")
        if result.get("success"):
            _notify("Đã mở Windows", msg, ok=True)
        else:
            _notify("Không mở được trên máy này", msg, ok=False)

    def _on_power_save(self) -> None:
        if self._disable_power_save:
            self._disable_power_save()
            return
        try:
            from core.wifi_recovery import WifiRecovery
            snap = getattr(WifiRecovery, "last_detect", None) or {}
            adapter = str(snap.get("name") or "")
            result = WifiRecovery.disable_wifi_power_saving(adapter)
            msg = str(result.get("message") or "")
            extra = " Ứng dụng không sửa được driver hay sóng RF."
            _notify(
                "Tiết kiệm pin Wi-Fi",
                msg + extra,
                ok=bool(result.get("success")),
            )
        except Exception as exc:
            _notify("Tiết kiệm pin Wi-Fi", str(exc), ok=False)
        open_windows_target("device_manager")

    def _on_unlock_location(self) -> None:
        if self._unlock_location:
            self._unlock_location()
            return
        self._open_target("location")
