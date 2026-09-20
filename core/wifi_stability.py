"""
Gợi ý ổn định Wi-Fi (MediaTek MT7921 / 2.4 GHz yếu).

wifi_recovery có thể flush DNS, renew DHCP, reconnect SSID và tắt tiết kiệm pin.
Module này KHÔNG sửa driver hay sóng RF — chỉ hướng dẫn Windows + CTA có cooldown.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from core.wifi_recovery import (
    STABILITY_TIP_TOAST_KIND,
    infer_wifi_band_ghz,
    looks_like_mt7921,
    snapshot_link_mbps,
)

WIFI_STABILITY_CAUSES = frozenset({"weak_link", "reconnect_loop", "link_loss"})
MIN_UNRECOVERED_FOR_GUIDANCE = 1

WINDOWS_STABILITY_TARGETS = {
    "wifi_settings": "ms-settings:network-wifi",
    "network_status": "ms-settings:network-status",
    "location": "ms-settings:privacy-location",
    "windows_update": "ms-settings:windowsupdate",
    "device_manager": "devmgmt.msc",
    "adapter_cpl": "ncpa.cpl",
}

DISCLAIMER = (
    "Ứng dụng không sửa được driver MediaTek hay sóng RF — chỉ gợi ý bước Windows."
)

_BTN_5GHZ = "Mở mạng Wi-Fi"
_BTN_DRIVER = "Device Manager"
_BTN_POWER = "Tắt tiết kiệm pin"
_BTN_LOCATION = "Gỡ khóa Location"


def _cause_of(detect: Optional[Dict[str, Any]], last_report: Optional[Dict[str, Any]]) -> str:
    det = detect if isinstance(detect, dict) else {}
    report = last_report if isinstance(last_report, dict) else {}
    return str(det.get("cause") or report.get("cause") or "").strip().lower()


def should_offer_wifi_stability_guidance(
    detect: Optional[Dict[str, Any]] = None,
    last_report: Optional[Dict[str, Any]] = None,
    unrecovered_repairs: int = 0,
    min_unrecovered: int = MIN_UNRECOVERED_FOR_GUIDANCE,
) -> bool:
    """True when detect is weak/flapping, or repairs keep failing to recover."""
    det = detect if isinstance(detect, dict) else {}
    report = last_report if isinstance(last_report, dict) else {}
    cause = _cause_of(det, report)
    if cause in WIFI_STABILITY_CAUSES:
        return True
    if int(unrecovered_repairs or 0) >= int(min_unrecovered):
        return True
    if str(report.get("stopped_at") or "") == "unrecovered":
        return True
    if report.get("repaired") and not report.get("recovered"):
        return True
    if report.get("needs_wifi_stability_guidance"):
        return True
    return False


def should_toast_wifi_stability_guidance(
    detect: Optional[Dict[str, Any]] = None,
    last_report: Optional[Dict[str, Any]] = None,
    unrecovered_repairs: int = 0,
    repair_running: bool = False,
) -> bool:
    """
    Toast only for chronic weak/flap or unrecovered repairs.

    Skip when a wifi_drop repair is already running this tick (that toast
    carries the same CTA). Cooldown is applied by RecoveryToastGate.
    """
    if repair_running:
        return False
    if not should_offer_wifi_stability_guidance(
        detect=detect,
        last_report=last_report,
        unrecovered_repairs=unrecovered_repairs,
    ):
        return False
    report = last_report if isinstance(last_report, dict) else {}
    if report.get("recovered") and str(report.get("type") or "") == "wifi_drop":
        # Connectivity came back; still toast if the PHY is chronically weak.
        det = detect if isinstance(detect, dict) else {}
        cause = _cause_of(det, report)
        if cause != "weak_link":
            return False
    return True


def build_wifi_stability_guidance(
    detect: Optional[Dict[str, Any]] = None,
    last_report: Optional[Dict[str, Any]] = None,
    unrecovered_repairs: int = 0,
) -> Dict[str, Any]:
    """Vietnamese tip copy + button ids. Honest: app did not fix RF/driver."""
    det = dict(detect) if isinstance(detect, dict) else {}
    report = last_report if isinstance(last_report, dict) else {}
    cause = _cause_of(det, report)
    desc = str(det.get("description") or report.get("wifi", {}).get("description") or "")
    name = str(det.get("name") or report.get("wifi", {}).get("name") or "")
    ssid = str(det.get("ssid") or "")
    mt7921 = looks_like_mt7921(desc, name)
    band_ghz = det.get("band_ghz")
    if band_ghz is None:
        band_ghz = infer_wifi_band_ghz(det) or infer_wifi_band_ghz(
            report.get("wifi") if isinstance(report.get("wifi"), dict) else {}
        )
    try:
        band_ghz_f = float(band_ghz) if band_ghz is not None else None
    except (TypeError, ValueError):
        band_ghz_f = None
    link_mbps = snapshot_link_mbps(det)
    if link_mbps <= 0 and isinstance(report.get("wifi"), dict):
        link_mbps = snapshot_link_mbps(report["wifi"])
    loc_locked = bool(
        det.get("location_gpo_locked")
        or det.get("location_blocked")
        or report.get("location_gpo_locked")
        or report.get("needs_location_unlock")
    )
    chip = "MediaTek MT7921" if mt7921 else (desc.strip() or "card Wi-Fi")
    tips: List[Dict[str, str]] = []

    if band_ghz_f == 5.0 or band_ghz_f == 6.0:
        tips.append({
            "id": "band_5ghz",
            "text": (
                f"Đang ở {band_ghz_f:g} GHz"
                + (f" (SSID «{ssid}»)" if ssid else "")
                + ". Nếu vẫn chậm, đó là tín hiệu/driver — không phải DNS."
            ),
            "action": "wifi_settings",
            "button": _BTN_5GHZ,
        })
    else:
        rate_bit = ""
        if 0 < link_mbps < 50:
            rate_bit = f" Tốc độ liên kết đang ~{link_mbps:.0f} Mbps"
            if band_ghz_f == 2.4:
                rate_bit += " trên 2.4 GHz"
            rate_bit += " — mức này app không tăng được."
        tips.append({
            "id": "band_5ghz",
            "text": (
                "Ưu tiên SSID 5 GHz nếu router có (thường tên …-5G / 5GHz). "
                "2.4 GHz xuyên tường tốt hơn nhưng chậm và dễ nhiễu."
                + rate_bit
            ),
            "action": "wifi_settings",
            "button": _BTN_5GHZ,
        })

    if mt7921:
        driver_text = (
            "Cập nhật hoặc Rollback driver MT7921: Device Manager → Network adapters → "
            "MediaTek Wi-Fi 6 MT7921 → Properties → Driver. "
            "Driver mới đôi khi làm rớt; Rollback nếu vừa cập nhật."
        )
    else:
        driver_text = (
            "Cập nhật hoặc Rollback driver Wi-Fi (MediaTek MT7921 hoặc card khác) "
            "trong Device Manager → Network adapters → Properties → Driver. "
            "Driver mới đôi khi làm rớt; Rollback nếu vừa cập nhật."
        )
    tips.append({
        "id": "mt7921_driver",
        "text": driver_text,
        "action": "device_manager",
        "button": _BTN_DRIVER,
    })

    tips.append({
        "id": "power_save",
        "text": (
            "Tắt tiết kiệm pin card Wi-Fi: Device Manager → Properties → Power Management "
            "bỏ «Allow the computer to turn off this device to save power». "
            "App có thể chạy powercfg (Maximum Performance) — không tắt card."
        ),
        "action": "disable_power_save",
        "button": _BTN_POWER,
    })

    if loc_locked:
        tips.append({
            "id": "location",
            "text": (
                "Location đang bị khóa bởi Group Policy — Settings → Privacy → Location bị xám, "
                "reconnect SSID có thể thất bại. Gỡ khóa một lần (UAC); app không tự sửa GPO."
            ),
            "action": "unlock_location",
            "button": _BTN_LOCATION,
        })

    offer = should_offer_wifi_stability_guidance(
        detect=det, last_report=report, unrecovered_repairs=unrecovered_repairs,
    )
    if cause == "reconnect_loop":
        situation = "Wi-Fi đang rớt / vòng reconnect."
    elif cause == "weak_link":
        situation = "Wi-Fi vẫn kết nối nhưng tín hiệu / tốc độ liên kết yếu."
    elif cause == "link_loss":
        situation = "Mất liên kết Wi-Fi."
    elif int(unrecovered_repairs or 0) > 0:
        situation = "Đã tự sửa vài lần nhưng Wi-Fi chưa ổn định hẳn."
    else:
        situation = "Gợi ý khi Wi-Fi yếu hoặc hay rớt (MT7921 / 2.4 GHz)."

    intro = (
        f"{situation} App có thể flush DNS, renew DHCP, reconnect SSID và tắt tiết kiệm pin. "
        f"{DISCLAIMER}"
    )
    toast_bits = [situation, DISCLAIMER]
    if band_ghz_f == 2.4 or (band_ghz_f is None and 0 < link_mbps < 50):
        toast_bits.append("Ưu tiên SSID 5 GHz nếu có.")
    if mt7921:
        toast_bits.append("Cập nhật/rollback driver MT7921; tắt tiết kiệm pin card.")
    else:
        toast_bits.append("Cập nhật/rollback driver Wi-Fi; tắt tiết kiệm pin card.")
    if loc_locked:
        toast_bits.append("Gỡ khóa Location nếu Settings bị xám.")

    return {
        "offer": offer,
        "title": "Ổn định Wi-Fi",
        "toast_title": "Ổn định Wi-Fi",
        "toast_message": " ".join(toast_bits),
        "intro": intro,
        "disclaimer": DISCLAIMER,
        "tips": tips,
        "chip": chip,
        "mt7921": mt7921,
        "band_ghz": band_ghz_f,
        "link_mbps": link_mbps,
        "cause": cause,
        "ssid": ssid,
        "location_locked": loc_locked,
        "unrecovered_repairs": int(unrecovered_repairs or 0),
    }


def build_wifi_stability_toast_payload(
    detect: Optional[Dict[str, Any]] = None,
    last_report: Optional[Dict[str, Any]] = None,
    unrecovered_repairs: int = 0,
    repair_running: bool = False,
) -> Optional[Dict[str, Any]]:
    if not should_toast_wifi_stability_guidance(
        detect=detect,
        last_report=last_report,
        unrecovered_repairs=unrecovered_repairs,
        repair_running=repair_running,
    ):
        return None
    guidance = build_wifi_stability_guidance(
        detect=detect,
        last_report=last_report,
        unrecovered_repairs=unrecovered_repairs,
    )
    return {
        "type": STABILITY_TIP_TOAST_KIND,
        "success": False,
        "recovered": False,
        "cause": guidance.get("cause") or "",
        "cause_label": "",
        "needs_location_unlock": bool(guidance.get("location_locked")),
        "location_gpo_locked": bool(guidance.get("location_locked")),
        "needs_wifi_stability_guidance": True,
        "guidance": guidance,
        "message": guidance.get("toast_message") or DISCLAIMER,
        "title": guidance.get("toast_title") or "Ổn định Wi-Fi",
    }


def open_windows_target(target: str) -> Dict[str, Any]:
    """Open ms-settings: URI or Device Manager. Safe no-op off Windows."""
    key = str(target or "").strip().lower()
    dest = WINDOWS_STABILITY_TARGETS.get(key)
    if not dest:
        return {
            "success": False,
            "target": key,
            "message": f"Không biết đích Windows «{target}».",
        }
    if sys.platform != "win32":
        return {
            "success": False,
            "skipped": True,
            "target": key,
            "uri": dest,
            "message": f"Chỉ mở được trên Windows ({dest}).",
        }
    try:
        opener = getattr(os, "startfile", None)
        if callable(opener):
            opener(dest)  # type: ignore[misc]
            return {
                "success": True,
                "target": key,
                "uri": dest,
                "message": f"Đã mở {dest}.",
            }
        subprocess.Popen(
            ["cmd", "/c", "start", "", dest],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "success": True,
            "target": key,
            "uri": dest,
            "message": f"Đã mở {dest}.",
        }
    except Exception as exc:
        return {
            "success": False,
            "target": key,
            "uri": dest,
            "message": f"Không mở được {dest}: {exc}",
        }
