"""
Thẻ / khối «Ổn định Wi-Fi»: gợi ý 5 GHz, driver MT7921, tiết kiệm pin, Location.

Không tuyên bố app đã sửa driver hay sóng RF.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core.wifi_stability import (
    DISCLAIMER,
    build_wifi_stability_guidance,
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
    """Tip card used by Network dialog (conditional) and Settings (always on)."""

    def __init__(self, parent=None, *, always_visible: bool = False):
        super().__init__(parent)
        self.setObjectName("WifiStabilityCard")
        self.always_visible = bool(always_visible)
        self._unlock_location: Optional[Callable[[], Any]] = None
        self._disable_power_save: Optional[Callable[[], Any]] = None
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

        if self.always_visible:
            self.apply_guidance(build_wifi_stability_guidance())
            self.setVisible(True)
        else:
            self.setVisible(False)

    def bind(
        self,
        *,
        unlock_location: Optional[Callable[[], Any]] = None,
        disable_power_save: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._unlock_location = unlock_location
        self._disable_power_save = disable_power_save

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
        self.btn_location.setVisible(loc_on)
        if self.always_visible:
            self.setVisible(True)
        else:
            self.setVisible(bool(data.get("offer")) or loc_on)

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
