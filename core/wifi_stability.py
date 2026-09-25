"""
Ổn định Wi-Fi: gợi ý Windows + chế độ theo dõi (không phải VPN).

Gợi ý (thẻ / toast): 5 GHz, driver, tiết kiệm pin, Location. Không sửa RF.

Chế độ «Ổn định Wi-Fi» (wifi_stability_enabled, mặc định TẮT) theo dõi ping và
card. Khi mất kết nối thật đủ lâu: reconnect SSID hoặc renew DHCP. Không flush
DNS, không reset stack, không EmptyWorkingSet, không UAC/runas im lặng.
Tắt auto_network_optimize không tắt chế độ này; bật chế độ này cũng không bật
lại vòng flush của WifiRecovery.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional

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


# --- Chế độ theo dõi «Ổn định Wi-Fi» (nhẹ, mặc định tắt) ---
#
# Hai cờ không tranh nhau:
#   auto_network_optimize_enabled  → flush định kỳ, ping cao, vòng WifiRecovery
#   wifi_stability_enabled         → chỉ monitor + reconnect/DHCP khi mất mạng thật
# Bật cờ thứ hai KHÔNG bật lại flush. Tắt cờ thứ nhất KHÔNG tắt monitor.

PUBLIC_CAUSES = ("adapter_down", "no_ping", "dns", "ok")
PUBLIC_CAUSE_LABELS = {
    "adapter_down": "card Wi-Fi không Up",
    "no_ping": "không ping được",
    "dns": "DNS",
    "ok": "ổn",
}

# Sustained loss before the first gentle action. Scheduler ticks every 15s.
GENTLE_MIN_OUTAGE_SEC = 60.0
GENTLE_COOLDOWN_SEC = 300.0
GENTLE_RECOVERED_COOLDOWN_SEC = 900.0
GENTLE_MAX_UNRECOVERED = 2

# The only actions this mode may take. Anything else is a bug.
GENTLE_STEP_WHITELIST = ("reconnect_ssid", "renew_dhcp")
GENTLE_FORBIDDEN_ACTIONS = (
    "flush_dns",
    "purge_arp_netbios",
    "apply_best_dns",
    "disable_net_adapter",
    "empty_working_set",
)

NOTE_DISABLED = (
    "Đang tắt. Bật «Ổn định Wi-Fi» để theo dõi và chỉ sửa khi mất kết nối thật."
)
NOTE_OK = "Mạng ổn. Không flush DNS, không reconnect."
NOTE_DNS = (
    "DNS lỗi. Không flush tự động — dùng «Đổi DNS Siêu Tốc» nếu bạn muốn đổi DNS."
)
NOTE_WAITING = "Đang theo dõi mất kết nối. Chưa sửa vì chưa đủ thời gian."
NOTE_READY = "Mất kết nối đủ lâu. Sẽ sửa nhẹ (reconnect hoặc renew DHCP), không flush DNS."
NOTE_EXTERNAL = (
    "Đường sửa mạng khác đang chạy — không sửa trùng và không flush DNS thêm."
)
NOTE_ADMIN = "Cần quyền Admin — đã bỏ qua, không hiện UAC."
NOTE_LOCATION = (
    "Không reconnect được vì thiếu quyền Location. "
    "Bấm «Gỡ khóa Location» (UAC chỉ khi bạn bấm). App không tự hiện UAC."
)
NOTE_JUST_ENABLED = "Đang bật. Sẽ theo dõi ping và card Wi-Fi ở nhịp kế tiếp."

_ELEVATION_MARKERS = (
    "requires elevation",
    "access is denied",
    "access denied",
    "yêu cầu quyền",
    "yeu cau quyen",
    "error: 740",
)


def guess_public_cause(
    detect: Optional[Dict[str, Any]] = None,
    ping_ok: Optional[bool] = None,
    dns_failed: bool = False,
) -> str:
    """
    Bucket the user can read: adapter_down / no_ping / dns / ok.

    A successful ping, or a down Wi-Fi radio while another link is up
    (false_adapter_down), is always ok — same lesson as not flushing a
    healthy network.
    """
    det = detect if isinstance(detect, dict) else {}
    cause = str(det.get("cause") or "").strip().lower()
    suppressed = bool(det.get("false_adapter_down"))
    if ping_ok is True or suppressed:
        return "ok"
    adapter_down = cause == "adapter_down" or (
        bool(det.get("is_wifi"))
        and ("is_up" in det)
        and (not bool(det.get("is_up")))
        and not suppressed
    )
    if adapter_down and ping_ok is not True:
        return "adapter_down"
    dns = bool(dns_failed) or cause == "dns_fail"
    link_up = bool(det.get("is_up"))
    if dns and link_up and ping_ok is not True:
        return "dns"
    if ping_ok is False:
        return "no_ping"
    if dns:
        return "dns"
    return "ok"


def is_real_wifi_loss(public_cause: str, ping_ok: Optional[bool]) -> bool:
    """True only for a measured outage or a radio that is actually down."""
    cause = str(public_cause or "")
    if cause == "adapter_down" and ping_ok is not True:
        return True
    if cause == "no_ping" and ping_ok is False:
        return True
    return False


def select_gentle_steps(
    public_cause: str,
    *,
    adapter_up: bool = False,
    associated: bool = False,
    raw_cause: str = "",
) -> List[str]:
    """
    One gentle step, or none.

    dns / ok: do nothing (never flush).
    adapter_down: reconnect the SSID. Do not toggle the NIC.
    no_ping while still associated: renew DHCP only (do not kick a live link
    just because it is weak).
    no_ping with the association gone, or a real reconnect loop: reconnect.
    """
    cause = str(public_cause or "")
    raw = str(raw_cause or "").strip().lower()
    if cause in ("ok", "dns", ""):
        return []
    if cause == "adapter_down":
        return ["reconnect_ssid"]
    if cause == "no_ping":
        if raw in ("reconnect_loop", "link_loss") or not associated:
            return ["reconnect_ssid"]
        if adapter_up:
            return ["renew_dhcp"]
        return ["reconnect_ssid"]
    return []


def should_trigger_gentle_wifi_stability(
    state: Optional[Dict[str, Any]],
    *,
    now_ts: float,
    aggressive_repair_owns_tick: bool = False,
    cooldown_sec: float = GENTLE_COOLDOWN_SEC,
    min_outage_sec: float = GENTLE_MIN_OUTAGE_SEC,
    max_unrecovered: int = GENTLE_MAX_UNRECOVERED,
    recovered_cooldown_sec: float = GENTLE_RECOVERED_COOLDOWN_SEC,
) -> bool:
    """
    Gentle repair gate. Does not look at auto_network_optimize_enabled.

    That flag keeps owning flush / WifiRecovery. This gate only cares that
    the dedicated toggle is on, the loss is real, and cooldowns have elapsed.
    If the aggressive path already fired this tick, stand down.
    """
    data = state if isinstance(state, dict) else {}
    if aggressive_repair_owns_tick:
        return False
    if not data.get("enabled"):
        return False
    if not is_real_wifi_loss(str(data.get("cause") or ""), data.get("ping_ok")):
        return False
    if int(data.get("unrecovered") or 0) >= int(max_unrecovered):
        return False
    start = float(data.get("outage_start") or 0)
    if start <= 0 or (float(now_ts) - start) < float(min_outage_sec):
        return False
    last_rec = float(data.get("last_recovered_ts") or 0)
    if last_rec > 0 and (float(now_ts) - last_rec) < float(recovered_cooldown_sec):
        return False
    last_tr = float(data.get("last_trigger_ts") or 0)
    if last_tr > 0 and (float(now_ts) - last_tr) < float(cooldown_sec):
        return False
    return True


def _stability_note(state: Dict[str, Any], now_ts: float, *, external_repair: bool) -> str:
    if not state.get("enabled"):
        return NOTE_DISABLED
    if external_repair and is_real_wifi_loss(str(state.get("cause") or ""), state.get("ping_ok")):
        return NOTE_EXTERNAL
    cause = str(state.get("cause") or "ok")
    if cause == "ok":
        return NOTE_OK
    if cause == "dns":
        return NOTE_DNS
    if cause in ("adapter_down", "no_ping"):
        start = float(state.get("outage_start") or 0)
        elapsed = (float(now_ts) - start) if start > 0 else 0.0
        if elapsed < GENTLE_MIN_OUTAGE_SEC:
            return NOTE_WAITING
        return NOTE_READY
    return NOTE_OK


def reduce_stability_state(
    prev: Optional[Dict[str, Any]],
    *,
    enabled: bool,
    public_cause: str,
    ping_ok: Optional[bool],
    now_ts: float,
    raw_cause: str = "",
    adapter_up: bool = False,
    associated: bool = False,
    adapter_name: str = "",
    ssid: str = "",
    external_repair: bool = False,
) -> Dict[str, Any]:
    """Pure state transition for one monitor sample."""
    state = dict(prev) if isinstance(prev, dict) else {}
    cause = str(public_cause or "ok")
    if cause not in PUBLIC_CAUSES:
        cause = "ok"
    state["enabled"] = bool(enabled)
    state["cause"] = cause
    state["raw_cause"] = str(raw_cause or "")
    state["ping_ok"] = ping_ok
    state["adapter_up"] = bool(adapter_up)
    state["associated"] = bool(associated)
    state["adapter_name"] = str(adapter_name or state.get("adapter_name") or "")
    # Keep the last SSID when this sample is blank (radio just dropped) so a
    # later reconnect still has a profile name.
    state["ssid"] = str(ssid or state.get("ssid") or "")
    state["last_drop_ts"] = float(state.get("last_drop_ts") or 0)
    state["last_action"] = str(state.get("last_action") or "")
    state["last_action_ts"] = float(state.get("last_action_ts") or 0)
    state["last_action_text"] = str(state.get("last_action_text") or "Chưa sửa")
    state["last_trigger_ts"] = float(state.get("last_trigger_ts") or 0)
    state["last_recovered_ts"] = float(state.get("last_recovered_ts") or 0)
    state["unrecovered"] = int(state.get("unrecovered") or 0)
    real = bool(enabled) and is_real_wifi_loss(cause, ping_ok)
    if real:
        if float(state.get("outage_start") or 0) <= 0:
            state["outage_start"] = float(now_ts)
            state["last_drop_ts"] = float(now_ts)
    else:
        state["outage_start"] = 0.0
    state["note"] = _stability_note(state, now_ts, external_repair=bool(external_repair))
    return state


def mark_stability_triggered(state: Optional[Dict[str, Any]], now_ts: float) -> Dict[str, Any]:
    data = dict(state) if isinstance(state, dict) else {}
    data["last_trigger_ts"] = float(now_ts)
    return data


def _format_ts(ts: Any) -> str:
    try:
        value = float(ts or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "—"
    from datetime import datetime
    return datetime.fromtimestamp(value).strftime("%d/%m/%Y %H:%M:%S")


def format_stability_status_text(state: Optional[Dict[str, Any]]) -> str:
    """One paragraph for the settings / network card."""
    data = state if isinstance(state, dict) else {}
    enabled = "Đang bật" if data.get("enabled") else "Đang tắt"
    cause = str(data.get("cause") or "ok")
    if cause not in PUBLIC_CAUSE_LABELS:
        cause = "ok"
    label = PUBLIC_CAUSE_LABELS[cause]
    drop = _format_ts(data.get("last_drop_ts"))
    action = str(data.get("last_action_text") or "Chưa sửa")
    if float(data.get("last_action_ts") or 0) > 0:
        action = f"{action} ({_format_ts(data.get('last_action_ts'))})"
    note = str(data.get("note") or "").strip()
    text = (
        f"{enabled}. Nguyên nhân đoán: {label} ({cause}). "
        f"Lần rớt gần nhất: {drop}. "
        f"Lần sửa gần nhất: {action}."
    )
    if note:
        text = f"{text} {note}"
    return text


def step_needs_admin(step: Optional[Dict[str, Any]]) -> bool:
    """True when Windows refused the command because it wanted elevation."""
    if not isinstance(step, dict) or step.get("success"):
        return False
    blob = " ".join(
        str(step.get(key) or "") for key in ("message", "stderr", "stdout")
    ).lower()
    nested = step.get("renew") if isinstance(step.get("renew"), dict) else {}
    release = step.get("release") if isinstance(step.get("release"), dict) else {}
    for extra in (nested, release):
        blob += " " + " ".join(
            str(extra.get(key) or "") for key in ("message", "stderr", "stdout")
        ).lower()
    return any(token in blob for token in _ELEVATION_MARKERS)


def step_location_blocked(step: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(step, dict):
        return False
    return bool(step.get("location_blocked") or step.get("location_gpo_locked"))


def record_gentle_result(
    state: Optional[Dict[str, Any]],
    *,
    now_ts: float,
    action: str,
    action_text: str,
    success: bool,
    throttled: bool = False,
    needs_admin: bool = False,
    location_blocked: bool = False,
) -> Dict[str, Any]:
    data = dict(state) if isinstance(state, dict) else {}
    data["last_action"] = str(action or "")
    data["last_action_ts"] = float(now_ts)
    data["last_action_text"] = str(action_text or "Chưa sửa")
    if location_blocked:
        data["note"] = NOTE_LOCATION
    elif needs_admin:
        data["note"] = NOTE_ADMIN
    if throttled:
        return data
    if success:
        data["unrecovered"] = 0
        data["last_recovered_ts"] = float(now_ts)
    else:
        data["unrecovered"] = int(data.get("unrecovered") or 0) + 1
    return data


def execute_gentle_recovery(
    state: Optional[Dict[str, Any]],
    *,
    now_ts: float,
    reconnect_fn: Callable[..., Dict[str, Any]],
    renew_fn: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run the planned step via injected callables.

    Callers must pass WifiRecovery.reconnect_wifi_profile / renew_dhcp (or
    test fakes). This function never flush DNS, never resets the stack, never
    touches browser processes, and never requests UAC.
    """
    data = dict(state) if isinstance(state, dict) else {}
    planned = select_gentle_steps(
        str(data.get("cause") or ""),
        adapter_up=bool(data.get("adapter_up")),
        associated=bool(data.get("associated")),
        raw_cause=str(data.get("raw_cause") or ""),
    )
    planned = [step for step in planned if step in GENTLE_STEP_WHITELIST]
    if any(step in GENTLE_FORBIDDEN_ACTIONS for step in planned):
        planned = []
    if not planned:
        return {
            "attempted": False,
            "success": False,
            "steps": [],
            "state": data,
            "message": "Không có bước sửa nhẹ cho trạng thái này.",
            "public_cause": str(data.get("cause") or "ok"),
            "needs_admin": False,
        }
    action = planned[0]
    adapter = str(data.get("adapter_name") or "")
    ssid = str(data.get("ssid") or "")
    if action == "reconnect_ssid":
        step = reconnect_fn(ssid, adapter, float(now_ts))
    else:
        step = renew_fn(adapter)
    if not isinstance(step, dict):
        step = {"action": action, "success": False, "message": "Bước sửa không trả về kết quả."}
    step.setdefault("action", action)
    success = bool(step.get("success"))
    throttled = bool(step.get("throttled"))
    needs_admin = step_needs_admin(step)
    location_blocked = step_location_blocked(step)
    detail = str(step.get("message") or "").strip()
    if needs_admin:
        action_text = NOTE_ADMIN
    elif location_blocked:
        action_text = "Reconnect cần Location — không tự hiện UAC"
    elif throttled:
        action_text = detail or "Bỏ qua reconnect (đang trong thời gian chờ)"
    elif action == "reconnect_ssid":
        action_text = "Đã reconnect Wi-Fi" if success else (detail or "Reconnect Wi-Fi chưa xong")
    else:
        action_text = "Đã renew DHCP" if success else (detail or "Renew DHCP chưa xong")
    new_state = record_gentle_result(
        data,
        now_ts=float(now_ts),
        action=str(step.get("action") or action),
        action_text=action_text,
        success=success,
        throttled=throttled,
        needs_admin=needs_admin,
        location_blocked=location_blocked,
    )
    message = action_text
    if detail and detail not in message:
        message = f"{action_text}. {detail}"
    return {
        "attempted": True,
        "success": success and not throttled,
        "steps": [step],
        "state": new_state,
        "message": message,
        "public_cause": str(data.get("cause") or "ok"),
        "needs_admin": needs_admin,
        "throttled": throttled,
    }


def gentle_cooldown_settings(config: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    cfg = config if isinstance(config, dict) else {}
    return {
        "cooldown_sec": float(cfg.get("wifi_stability_cooldown_seconds", GENTLE_COOLDOWN_SEC)),
        "min_outage_sec": float(cfg.get("wifi_stability_min_outage_seconds", GENTLE_MIN_OUTAGE_SEC)),
        "recovered_cooldown_sec": float(cfg.get(
            "wifi_stability_recovered_cooldown_seconds",
            GENTLE_RECOVERED_COOLDOWN_SEC,
        )),
        "max_unrecovered": int(cfg.get("wifi_stability_max_unrecovered", GENTLE_MAX_UNRECOVERED)),
    }


class WifiStabilityMonitor:
    """In-memory status the scheduler and the card both read."""

    _state: Dict[str, Any] = {}
    _hydrated = False

    @classmethod
    def reset_state(cls) -> None:
        cls._state = {}
        cls._hydrated = False

    @classmethod
    def hydrate(cls, saved: Optional[Dict[str, Any]]) -> None:
        if cls._hydrated:
            return
        cls._hydrated = True
        if isinstance(saved, dict) and saved:
            cls._state = dict(saved)

    @classmethod
    def snapshot(cls) -> Dict[str, Any]:
        return dict(cls._state)

    @classmethod
    def replace(cls, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cls._state = dict(state) if isinstance(state, dict) else {}
        cls._hydrated = True
        return cls.snapshot()

    @classmethod
    def observe(cls, **kwargs: Any) -> Dict[str, Any]:
        cls._state = reduce_stability_state(cls._state, **kwargs)
        return cls.snapshot()

    @classmethod
    def recovery_due(
        cls,
        *,
        now_ts: float,
        aggressive_repair_owns_tick: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        knobs = gentle_cooldown_settings(config)
        return should_trigger_gentle_wifi_stability(
            cls._state,
            now_ts=now_ts,
            aggressive_repair_owns_tick=aggressive_repair_owns_tick,
            cooldown_sec=knobs["cooldown_sec"],
            min_outage_sec=knobs["min_outage_sec"],
            max_unrecovered=int(knobs["max_unrecovered"]),
            recovered_cooldown_sec=knobs["recovered_cooldown_sec"],
        )

    @classmethod
    def mark_triggered(cls, now_ts: float) -> Dict[str, Any]:
        cls._state = mark_stability_triggered(cls._state, now_ts)
        return cls.snapshot()
