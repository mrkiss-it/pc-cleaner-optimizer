"""
Khôi phục Wi-Fi khi rớt liên tục / vòng reconnect (MediaTek MT7921, v.v.).

Phát hiện: adapter tắt, mất link, tốc độ liên kết yếu (< 50 Mbps),
Up/Down flap, cụm sự kiện WLAN-AutoConfig (11000/11001/8002/8003/11010).

Sửa theo bậc (không dừng vì một lần Ping may mắn khi đang flap/yếu):
  1. Flush DNS + ARP
  2. DHCP renew (ipconfig /release + /renew đúng một adapter)
  3. Đổi DNS nếu đang dùng AdGuard / DNS lọc / DNS tùy chỉnh
  4. Ngắt rồi kết nối lại đúng SSID hiện tại (giới hạn 90 giây/lần)
  5. Tắt tiết kiệm pin Wi-Fi (đảo ngược được, ghi log)
Không Disable-NetAdapter / bật-tắt NIC trong vòng lặp.
Sau sửa: cửa sổ ổn định N giây (Up liên tục + probe).
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.logger import logger
from core.windows_location import (
    get_location_lock_status,
    is_location_gpo_locked,
    looks_like_location_permission_error,
)

WIFI_WEAK_LINK_MBPS = 50.0
FLAP_WINDOW_SEC = 120.0
MIN_STATUS_FLAPS = 4
MIN_WLAN_EVENTS = 4
STABILITY_WINDOW_SEC = 8.0
STABILITY_POLL_SEC = 2.0
RECONNECT_MIN_INTERVAL_SEC = 90.0

WLAN_FLAP_EVENT_IDS = frozenset({11000, 11001, 8002, 8003, 11010})

# GUID powercfg: SUB_WIFI / "Power Saving Mode" → 0 = Maximum Performance
WIFI_POWER_SUBGROUP = "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1"
WIFI_POWER_SAVE_SETTING = "12bbebe6-58d6-4636-95bb-3217ef867c1a"

WIFI_NAME_MARKERS = ("wi-fi", "wifi", "wireless", "wlan", "802.11")
WIFI_DESC_MARKERS = WIFI_NAME_MARKERS + (
    "mediatek", "mt7921", "mt7922", "intel(r) wi-fi", "realtek 882", "qualcomm",
)

FILTERING_DNS_EXACT = {
    "94.140.14.14", "94.140.15.15",  # AdGuard
    "1.1.1.2", "1.0.0.2",            # Cloudflare malware
    "1.1.1.3", "1.0.0.3",            # Cloudflare family
}
FILTERING_DNS_PREFIXES = ("94.140.", "45.90.")  # AdGuard / NextDNS
PUBLIC_OK_DNS = {
    "1.1.1.1", "1.0.0.1",
    "8.8.8.8", "8.8.4.4",
    "9.9.9.9", "149.112.112.112",
    "208.67.222.222", "208.67.220.220",
}

CAUSE_LABELS = {
    "adapter_down": "card Wi-Fi tắt / không Up",
    "reconnect_loop": "Wi-Fi rớt liên tục / vòng reconnect (WLAN flap)",
    "link_loss": "mất liên kết Wi-Fi (không còn SSID / link)",
    "weak_link": "Wi-Fi tín hiệu yếu / tốc độ liên kết thấp",
    "no_gateway": "không có default gateway",
    "dns_fail": "DNS không phân giải được tên miền",
    "tcp_fail": "TCP tới DNS/HTTPS công cộng thất bại",
    "ok": "Wi-Fi ổn định",
}

_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_EVENT_ID_RE = re.compile(r"Event\s*ID\s*[:#]?\s*(\d+)", re.IGNORECASE)


def parse_link_mbps(value: Any) -> float:
    """Chuẩn hóa LinkSpeed PowerShell / netsh về Mbps. -1 nếu không đọc được."""
    if value is None or value == "":
        return -1.0
    if isinstance(value, bool):
        return -1.0
    if isinstance(value, (int, float)):
        v = float(value)
        if v < 0:
            return -1.0
        # Get-NetAdapter.LinkSpeed đôi khi là bit/s
        if v > 10_000:
            return round(v / 1_000_000.0, 1)
        return float(v)
    text = str(value).strip().lower().replace(",", ".")
    match = re.search(r"([\d.]+)\s*(gbps|mbps|kbps|b/s|bps)?", text)
    if not match:
        return -1.0
    number = float(match.group(1))
    unit = match.group(2) or "mbps"
    if unit in ("gbps",):
        return number * 1000.0
    if unit in ("kbps",):
        return number / 1000.0
    if unit in ("b/s", "bps"):
        return number / 1_000_000.0
    return number


def parse_wlan_event_ids(event_text: str) -> List[int]:
    """Lấy danh sách Event ID từ wevtutil / Get-WinEvent text."""
    if not event_text:
        return []
    ids: List[int] = []
    for match in _EVENT_ID_RE.finditer(event_text):
        try:
            ids.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return ids


def count_wlan_auth_flaps(event_text: str) -> int:
    """Số sự kiện WLAN-AutoConfig mang tính disconnect/reconnect."""
    return sum(1 for eid in parse_wlan_event_ids(event_text) if eid in WLAN_FLAP_EVENT_IDS)


def count_status_flaps(
    history: Sequence[Tuple[float, bool]],
    now: Optional[float] = None,
    window_sec: float = FLAP_WINDOW_SEC,
) -> int:
    """Đếm số lần đảo Up↔Down trong cửa sổ thời gian."""
    now_ts = time.time() if now is None else float(now)
    recent = [(t, bool(up)) for t, up in history if (now_ts - float(t)) <= float(window_sec)]
    if len(recent) < 2:
        return 0
    flaps = 0
    for i in range(1, len(recent)):
        if recent[i][1] != recent[i - 1][1]:
            flaps += 1
    return flaps


def is_filtering_or_custom_dns(servers: Sequence[str]) -> bool:
    """AdGuard / NextDNS / Cloudflare lọc / DNS lạ (không phải DHCP nội bộ hay Google/CF thường)."""
    for raw in servers or []:
        ip = str(raw or "").strip()
        if not ip:
            continue
        if ip in FILTERING_DNS_EXACT:
            return True
        if any(ip.startswith(prefix) for prefix in FILTERING_DNS_PREFIXES):
            return True
        if ip in PUBLIC_OK_DNS:
            continue
        if ip.startswith(("192.168.", "10.", "172.16.", "172.17.", "172.18.",
                          "172.19.", "172.2", "127.", "169.254.")):
            continue
        if _IPV4_RE.fullmatch(ip):
            return True
    return False


def looks_like_wifi_name(name: str, description: str = "") -> bool:
    blob = f"{name} {description}".lower()
    return any(token in blob for token in WIFI_DESC_MARKERS)


def classify_wifi_cause(
    snapshot: Dict[str, Any],
    health: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    Nguyên nhân chính (tiếng Việt).
    Ưu tiên: adapter_down → reconnect_loop → link_loss → weak_link → gateway → DNS → TCP.
    """
    health = health or {}
    issues = list(health.get("issues") or [])
    checks = health.get("checks") or {}
    gateway = checks.get("gateway") or {}
    dns = checks.get("dns") or {}
    conn = checks.get("connectivity") or {}

    is_up = bool(snapshot.get("is_up"))
    ssid = str(snapshot.get("ssid") or "").strip()
    state = str(snapshot.get("state") or "").strip().lower()
    link_mbps = float(snapshot.get("link_mbps") or -1)
    flaps = int(snapshot.get("status_flaps") or 0)
    wlan_flaps = int(snapshot.get("wlan_flaps") or 0)

    if snapshot.get("is_wifi") and ("is_up" in snapshot) and not is_up:
        cause = "adapter_down"
    elif flaps >= MIN_STATUS_FLAPS or wlan_flaps >= MIN_WLAN_EVENTS:
        cause = "reconnect_loop"
    elif is_up and (
        state in ("disconnected", "disconnecting", "authenticating")
        or (not ssid and state not in ("", "connected"))
        or snapshot.get("link_loss")
    ):
        cause = "link_loss"
    elif is_up and 0 < link_mbps < WIFI_WEAK_LINK_MBPS:
        cause = "weak_link"
    elif "no_gateway" in issues or gateway.get("ok") is False:
        cause = "no_gateway"
    elif "dns_fail" in issues or dns.get("ok") is False:
        cause = "dns_fail"
    elif "no_connectivity" in issues or conn.get("ok") is False:
        cause = "tcp_fail"
    else:
        cause = "ok"
    return cause, CAUSE_LABELS.get(cause, CAUSE_LABELS["ok"])


def parse_netadapter_payload(raw: Any) -> List[Dict[str, Any]]:
    """PowerShell ConvertTo-Json → list adapter dicts."""
    import json

    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        return [raw]
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def parse_wlan_interfaces(text: str) -> Dict[str, Any]:
    """Parse `netsh wlan show interfaces`."""
    info: Dict[str, Any] = {
        "name": "",
        "ssid": "",
        "state": "",
        "description": "",
        "rx_mbps": -1.0,
        "signal": "",
        "location_blocked": looks_like_location_permission_error(text or ""),
    }
    if not text:
        return info
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key_n = key.strip().lower()
        val = val.strip()
        if key_n == "name" and not info["name"]:
            info["name"] = val
        elif key_n == "description":
            info["description"] = val
        elif key_n == "ssid":
            info["ssid"] = val
        elif key_n == "state":
            info["state"] = val.lower()
        elif "receive rate" in key_n:
            info["rx_mbps"] = parse_link_mbps(val if not val.replace(".", "", 1).isdigit() else f"{val} Mbps")
        elif key_n == "signal":
            info["signal"] = val
    return info


def parse_dns_servers(text: str) -> List[str]:
    """Lấy IPv4 DNS từ netsh / PowerShell output."""
    found: List[str] = []
    for ip in _IPV4_RE.findall(text or ""):
        parts = ip.split(".")
        if any(not p.isdigit() or int(p) > 255 for p in parts):
            continue
        if ip.startswith("0.") or ip in found:
            continue
        found.append(ip)
    return found


class WifiRecovery:
    """Phát hiện + sửa Wi-Fi rớt / flap. Stateful vừa đủ cho lịch sử flap & throttle."""

    last_detect: Dict[str, Any] = {}
    last_wifi_drop_report: Dict[str, Any] = {}
    _status_history: List[Tuple[float, bool]] = []
    _last_reconnect_ts: float = 0.0
    _power_save_applied: bool = False
    _cmd_runner: Optional[Callable] = None
    _ps_runner: Optional[Callable] = None

    @classmethod
    def reset_state(cls) -> None:
        cls.last_detect = {}
        cls.last_wifi_drop_report = {}
        cls._status_history = []
        cls._last_reconnect_ts = 0.0
        cls._power_save_applied = False
        cls._cmd_runner = None
        cls._ps_runner = None

    @classmethod
    def _run(cls, cmd: str, timeout: int = 8) -> Dict[str, Any]:
        if cls._cmd_runner is not None:
            return cls._cmd_runner(cmd, timeout)
        from core.network_optimizer import NetworkOptimizer
        return NetworkOptimizer._run_cmd(cmd, timeout=timeout)

    @classmethod
    def _run_ps(cls, command: str, timeout: int = 12) -> Dict[str, Any]:
        if cls._ps_runner is not None:
            return cls._ps_runner(command, timeout)
        if sys.platform != "win32":
            return {"success": False, "stdout": "", "stderr": "not-windows", "returncode": -1}
        import subprocess
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return {
                "returncode": res.returncode,
                "stdout": (res.stdout or "").strip(),
                "stderr": (res.stderr or "").strip(),
                "success": res.returncode == 0,
            }
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}

    @classmethod
    def record_status(cls, is_up: bool, now: Optional[float] = None) -> None:
        ts = time.time() if now is None else float(now)
        cls._status_history.append((ts, bool(is_up)))
        cutoff = ts - (FLAP_WINDOW_SEC * 3)
        cls._status_history = [(t, u) for t, u in cls._status_history if t >= cutoff]

    @classmethod
    def collect_wlan_event_text(cls) -> str:
        """wevtutil 2 phút gần nhất — chỉ Event ID flap. Trả "" nếu không phải Windows."""
        if sys.platform != "win32" and cls._cmd_runner is None:
            return ""
        xpath = (
            "*[System[("
            "EventID=11000 or EventID=11001 or EventID=8002 or EventID=8003 or EventID=11010"
            ") and TimeCreated[timediff(@SystemTime) <= 120000]]]"
        )
        cmd = (
            'wevtutil qe Microsoft-Windows-WLAN-AutoConfig/Operational '
            f'/q:"{xpath}" /c:40 /rd:true /f:text'
        )
        res = cls._run(cmd, timeout=8)
        return str(res.get("stdout") or "")

    @classmethod
    def _read_adapters_windows(cls) -> List[Dict[str, Any]]:
        ps = (
            "Get-NetAdapter | Select-Object Name,Status,LinkSpeed,InterfaceDescription "
            "| ConvertTo-Json -Compress"
        )
        res = cls._run_ps(ps, timeout=8)
        adapters = parse_netadapter_payload(res.get("stdout") or "")
        if adapters:
            return adapters
        # Fallback netsh
        shown = cls._run("netsh interface show interface", timeout=5)
        parsed: List[Dict[str, Any]] = []
        for line in str(shown.get("stdout") or "").splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].lower() in ("enabled", "disabled"):
                connected = parts[1].lower() == "connected"
                name = " ".join(parts[3:])
                parsed.append({
                    "Name": name,
                    "Status": "Up" if connected else "Disconnected",
                    "LinkSpeed": "",
                    "InterfaceDescription": name,
                })
        return parsed

    @classmethod
    def get_wifi_snapshot(
        cls,
        event_text: Optional[str] = None,
        include_events: bool = False,
        now: Optional[float] = None,
        adapters: Optional[List[Dict[str, Any]]] = None,
        wlan_text: Optional[str] = None,
        dns_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ảnh chụp adapter Wi-Fi hiện tại (không sửa hệ thống)."""
        now_ts = time.time() if now is None else float(now)
        wifi_rows: List[Dict[str, Any]] = []

        if adapters is None:
            if sys.platform == "win32" or cls._ps_runner is not None or cls._cmd_runner is not None:
                try:
                    adapters = cls._read_adapters_windows()
                except Exception:
                    adapters = []
            else:
                adapters = []
                try:
                    import psutil
                    stats = psutil.net_if_stats()
                    for name, st in stats.items():
                        if looks_like_wifi_name(name):
                            adapters.append({
                                "Name": name,
                                "Status": "Up" if st.isup else "Disconnected",
                                "LinkSpeed": getattr(st, "speed", 0) or 0,
                                "InterfaceDescription": name,
                            })
                except Exception:
                    adapters = []

        for row in adapters or []:
            name = str(row.get("Name") or row.get("name") or "")
            desc = str(row.get("InterfaceDescription") or row.get("description") or "")
            if looks_like_wifi_name(name, desc):
                wifi_rows.append(row)

        chosen = wifi_rows[0] if wifi_rows else {}
        name = str(chosen.get("Name") or chosen.get("name") or "")
        desc = str(chosen.get("InterfaceDescription") or chosen.get("description") or "")
        status = str(chosen.get("Status") or chosen.get("status") or "").lower()
        is_up = status in ("up", "connected")
        link_mbps = parse_link_mbps(chosen.get("LinkSpeed") if "LinkSpeed" in chosen else chosen.get("link_speed"))

        wlan = parse_wlan_interfaces(wlan_text if wlan_text is not None else "")
        if wlan_text is None and name and (sys.platform == "win32" or cls._cmd_runner is not None):
            wlan = parse_wlan_interfaces(str(cls._run("netsh wlan show interfaces", timeout=6).get("stdout") or ""))
        if wlan.get("name") and not name:
            name = wlan["name"]
        if wlan.get("description") and not desc:
            desc = wlan["description"]
        ssid = str(wlan.get("ssid") or "")
        state = str(wlan.get("state") or status)
        if wlan.get("rx_mbps", -1) > 0:
            link_mbps = float(wlan["rx_mbps"])
        if state in ("connected",):
            is_up = True
        elif state in ("disconnected", "disconnecting"):
            is_up = False

        dns_servers: List[str] = []
        if dns_text is not None:
            dns_servers = parse_dns_servers(dns_text)
        elif name and (sys.platform == "win32" or cls._cmd_runner is not None):
            dns_out = cls._run(f'netsh interface ip show dns name="{name}"', timeout=5)
            dns_servers = parse_dns_servers(str(dns_out.get("stdout") or ""))

        if include_events:
            if event_text is None:
                event_text = cls.collect_wlan_event_text()
        else:
            event_text = event_text or ""

        cls.record_status(is_up, now=now_ts)
        status_flaps = count_status_flaps(cls._status_history, now=now_ts)
        wlan_flaps = count_wlan_auth_flaps(event_text or "")
        link_loss = bool(is_up and not ssid and state in ("disconnected", "disconnecting", "authenticating"))
        if is_up and state == "disconnected":
            link_loss = True
            is_up = False

        location_lock = get_location_lock_status()
        location_blocked = bool(wlan.get("location_blocked")) or looks_like_location_permission_error(
            wlan_text or ""
        )
        snap: Dict[str, Any] = {
            "is_wifi": bool(wifi_rows) or looks_like_wifi_name(name, desc),
            "name": name,
            "description": desc,
            "is_up": is_up,
            "status": status,
            "state": state,
            "ssid": ssid,
            "link_mbps": link_mbps,
            "signal": wlan.get("signal") or "",
            "dns_servers": dns_servers,
            "filtering_dns": is_filtering_or_custom_dns(dns_servers),
            "status_flaps": status_flaps,
            "wlan_flaps": wlan_flaps,
            "link_loss": link_loss,
            "event_text": event_text or "",
            "timestamp": now_ts,
            "location_gpo_locked": bool(location_lock.get("locked")),
            "location_blocked": location_blocked,
            "location_lock": location_lock,
        }
        return snap

    @classmethod
    def detect_wifi_instability(
        cls,
        event_text: Optional[str] = None,
        include_events: bool = True,
        now: Optional[float] = None,
        snapshot: Optional[Dict[str, Any]] = None,
        health: Optional[Dict[str, Any]] = None,
        **collect_kwargs: Any,
    ) -> Dict[str, Any]:
        """Gắn nguyên nhân + cờ unstable vào snapshot Wi-Fi."""
        snap = dict(snapshot) if snapshot else cls.get_wifi_snapshot(
            event_text=event_text,
            include_events=include_events,
            now=now,
            **collect_kwargs,
        )
        if "location_gpo_locked" not in snap:
            loc = get_location_lock_status()
            snap["location_gpo_locked"] = bool(loc.get("locked"))
            snap.setdefault("location_lock", loc)
        if not snap.get("is_wifi"):
            snap.update({
                "unstable": False,
                "cause": "ok",
                "cause_label": CAUSE_LABELS["ok"],
            })
            cls.last_detect = snap
            return snap
        cause, label = classify_wifi_cause(snap, health)
        ping_ok = True
        if health:
            ping_ok = bool(((health.get("checks") or {}).get("ping") or {}).get("ok", True))
            if "ping_missing" in (health.get("issues") or []):
                ping_ok = False
        flaps = int(snap.get("status_flaps") or 0)
        wlan_flaps = int(snap.get("wlan_flaps") or 0)
        loop_like = cause in ("adapter_down", "reconnect_loop", "link_loss")
        weak_with_pain = (
            cause == "weak_link"
            and (
                flaps >= 2
                or wlan_flaps >= 2
                or not ping_ok
                or ((not cls._power_save_applied) and flaps >= 1)
            )
        )
        # After power-save already applied, slow-but-stable link is not a reconnect loop.
        if cause == "weak_link" and cls._power_save_applied and flaps < 2 and wlan_flaps < 2 and ping_ok:
            weak_with_pain = False
        snap["cause"] = cause
        snap["cause_label"] = label
        snap["unstable"] = bool(loop_like or weak_with_pain)
        cls.last_detect = snap
        return snap

    @classmethod
    def renew_dhcp(cls, adapter_name: str) -> Dict[str, Any]:
        """ipconfig /release + /renew đúng một adapter — không đụng NIC khác."""
        name = (adapter_name or "").strip()
        if not name:
            return {"action": "renew_dhcp", "success": False, "message": "Không có tên adapter Wi-Fi để renew DHCP."}
        logger.info(f"[WifiRecovery] DHCP renew adapter '{name}'")
        rel = cls._run(f'ipconfig /release "{name}"', timeout=20)
        ren = cls._run(f'ipconfig /renew "{name}"', timeout=25)
        success = bool(ren.get("success")) or "IPv4" in str(ren.get("stdout") or "")
        msg = (
            f"Đã renew DHCP cho '{name}'."
            if success else
            f"Renew DHCP '{name}' chưa xong: {ren.get('stderr') or ren.get('stdout') or 'timeout'}"
        )
        return {
            "action": "renew_dhcp",
            "success": success,
            "message": msg,
            "release": rel,
            "renew": ren,
        }

    @classmethod
    def reconnect_wifi_profile(
        cls,
        ssid: str,
        adapter_name: str = "",
        now: Optional[float] = None,
        min_interval: float = RECONNECT_MIN_INTERVAL_SEC,
    ) -> Dict[str, Any]:
        """netsh wlan disconnect rồi connect đúng SSID. Throttle 90s."""
        now_ts = time.time() if now is None else float(now)
        elapsed = now_ts - float(cls._last_reconnect_ts or 0)
        if cls._last_reconnect_ts > 0 and elapsed < float(min_interval):
            wait = int(float(min_interval) - elapsed)
            return {
                "action": "reconnect_ssid",
                "success": False,
                "throttled": True,
                "message": f"Bỏ qua reconnect SSID (còn {wait}s throttle, tối thiểu {int(min_interval)}s).",
            }
        profile = (ssid or "").strip()
        iface = (adapter_name or "").strip()
        if not profile:
            shown = cls._run("netsh wlan show interfaces", timeout=6)
            wlan_blob = f"{shown.get('stdout') or ''}\n{shown.get('stderr') or ''}"
            parsed = parse_wlan_interfaces(wlan_blob)
            profile = str(parsed.get("ssid") or "")
            if not profile and (
                parsed.get("location_blocked") or looks_like_location_permission_error(wlan_blob)
            ):
                locked = is_location_gpo_locked()
                hint = (
                    " Location bị khóa bởi Group Policy — bấm «Gỡ khóa Location» (UAC) rồi thử lại."
                    if locked else
                    " netsh wlan cần quyền Location — bấm «Gỡ khóa Location» nếu Settings bị xám."
                )
                logger.warning(f"[WifiRecovery] netsh wlan show interfaces blocked by Location.{hint}")
                return {
                    "action": "reconnect_ssid",
                    "success": False,
                    "throttled": False,
                    "location_blocked": True,
                    "location_gpo_locked": locked,
                    "message": "Không đọc được SSID vì thiếu quyền Location." + hint,
                }
        if not profile:
            extra = ""
            if is_location_gpo_locked():
                extra = " Location đang bị khóa bởi Group Policy — reconnect SSID có thể thất bại cho đến khi gỡ khóa."
            return {
                "action": "reconnect_ssid",
                "success": False,
                "throttled": False,
                "location_gpo_locked": is_location_gpo_locked(),
                "message": "Không có SSID hiện tại để kết nối lại." + extra,
            }
        disc_cmd = "netsh wlan disconnect"
        conn_cmd = f'netsh wlan connect name="{profile}"'
        if iface:
            disc_cmd += f' interface="{iface}"'
            conn_cmd += f' interface="{iface}"'
        logger.info(f"[WifiRecovery] Reconnect SSID '{profile}' on '{iface or '*'}'")
        cls._run(disc_cmd, timeout=8)
        conn = cls._run(conn_cmd, timeout=12)
        cls._last_reconnect_ts = now_ts
        ok = bool(conn.get("success")) or "successfully" in str(conn.get("stdout") or "").lower() or "completed" in str(conn.get("stdout") or "").lower()
        return {
            "action": "reconnect_ssid",
            "success": ok,
            "throttled": False,
            "ssid": profile,
            "message": (
                f"Đã ngắt rồi kết nối lại SSID '{profile}'."
                if ok else
                f"Reconnect SSID '{profile}' chưa chắc thành công."
            ),
        }

    @classmethod
    def disable_wifi_power_saving(cls, adapter_name: str = "") -> Dict[str, Any]:
        """
        Tắt tiết kiệm pin Wi-Fi (Maximum Performance) + Disable-NetAdapterPowerManagement -NoRestart.
        Không Disable-NetAdapter (tắt card). Ghi log để đảo ngược bằng tay nếu cần.
        """
        details: List[str] = []
        ac = cls._run(
            f"powercfg /SETACVALUEINDEX SCHEME_CURRENT {WIFI_POWER_SUBGROUP} {WIFI_POWER_SAVE_SETTING} 0",
            timeout=8,
        )
        dc = cls._run(
            f"powercfg /SETDCVALUEINDEX SCHEME_CURRENT {WIFI_POWER_SUBGROUP} {WIFI_POWER_SAVE_SETTING} 0",
            timeout=8,
        )
        active = cls._run("powercfg /SETACTIVE SCHEME_CURRENT", timeout=8)
        if ac.get("success") or dc.get("success") or active.get("success"):
            details.append("powercfg SUB_WIFI Power Saving Mode = 0 (Maximum Performance)")
            logger.info("[WifiRecovery] Disabled Wi-Fi power-save via powercfg (reversible: set index back to 1/2).")

        ps_name = (adapter_name or "").replace("'", "''")
        if ps_name:
            ps = (
                f"Disable-NetAdapterPowerManagement -Name '{ps_name}' -NoRestart -ErrorAction SilentlyContinue"
            )
        else:
            ps = (
                "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -match "
                "'Wi-Fi|Wireless|WLAN|802.11|MediaTek' } | "
                "Disable-NetAdapterPowerManagement -NoRestart -ErrorAction SilentlyContinue"
            )
        ps_res = cls._run_ps(ps, timeout=10)
        if ps_res.get("success") or not ps_res.get("stderr"):
            details.append("Disable-NetAdapterPowerManagement -NoRestart (không tắt card)")
            logger.info("[WifiRecovery] Disable-NetAdapterPowerManagement -NoRestart applied.")

        success = len(details) > 0
        if success:
            cls._power_save_applied = True
        return {
            "action": "disable_wifi_power_saving",
            "success": success,
            "details": details,
            "message": (
                "Đã tắt tiết kiệm pin Wi-Fi (có thể bật lại trong Power Options / Adapter properties)."
                if success else
                "Không đổi được power-save Wi-Fi (cần Admin hoặc card không hỗ trợ)."
            ),
            "reversible": True,
        }

    @staticmethod
    def wait_for_stable_link(
        get_snapshot: Callable[[], Dict[str, Any]],
        duration_sec: float = STABILITY_WINDOW_SEC,
        interval_sec: float = STABILITY_POLL_SEC,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.time,
        probe_fn: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Cửa sổ ổn định: adapter phải Up liên tục trong duration_sec, probe cuối cửa sổ.
        clock_fn / sleep_fn tiêm được cho unit test.
        """
        duration_sec = max(0.5, float(duration_sec))
        interval_sec = max(0.1, float(interval_sec))
        needed = max(1, int(round(duration_sec / interval_sec)))
        consecutive_up = 0
        samples: List[Dict[str, Any]] = []
        start = clock_fn()
        deadline = start + duration_sec
        while True:
            snap = get_snapshot() or {}
            samples.append(snap)
            if snap.get("is_up"):
                consecutive_up += 1
            else:
                consecutive_up = 0
            now = clock_fn()
            if now >= deadline:
                break
            sleep_fn(min(interval_sec, max(0.0, deadline - now)))
        probe_ok = True
        if probe_fn is not None:
            try:
                probe_ok = bool(probe_fn())
            except Exception:
                probe_ok = False
        last_up = bool(samples[-1].get("is_up")) if samples else False
        stable = last_up and consecutive_up >= needed and probe_ok
        return {
            "action": "wait_stable_link",
            "success": stable,
            "stable": stable,
            "samples": len(samples),
            "consecutive_up": consecutive_up,
            "needed": needed,
            "probe_ok": probe_ok,
            "duration_sec": duration_sec,
            "message": (
                f"Wi-Fi ổn định {duration_sec:.0f}s (Up liên tục + probe)."
                if stable else
                f"Chưa ổn định trong {duration_sec:.0f}s (Up {consecutive_up}/{needed}, probe={'ok' if probe_ok else 'fail'})."
            ),
        }

    @staticmethod
    def skipped_nic_toggle() -> str:
        return "Không tắt/bật card mạng (Disable-NetAdapter) để tránh vòng reconnect."

    @staticmethod
    def format_applied_fixes(steps: List[Dict[str, Any]]) -> str:
        labels = {
            "flush_dns": "flush DNS",
            "purge_arp_netbios": "làm mới ARP/NetBIOS",
            "renew_dhcp": "renew DHCP",
            "apply_best_dns": "đổi DNS (AdGuard/lọc → DNS siêu tốc)",
            "reconnect_ssid": "ngắt rồi kết nối lại SSID",
            "disable_wifi_power_saving": "tắt tiết kiệm pin Wi-Fi",
            "wait_stable_link": "cửa sổ ổn định Wi-Fi",
            "remeasure_long_timeout": "đo lại Ping",
        }
        parts = []
        for step in steps or []:
            action = step.get("action")
            label = labels.get(action, action or "")
            if not label:
                continue
            if step.get("throttled"):
                parts.append(f"{label} (chờ throttle)")
            elif step.get("success"):
                parts.append(label)
            else:
                parts.append(f"{label} (chưa xong)")
        return ", ".join(parts) if parts else "chưa áp dụng bước sửa"

    @classmethod
    def diagnose_and_repair_wifi_drop(
        cls,
        apply_dns: bool = False,
        snapshot: Optional[Dict[str, Any]] = None,
        health: Optional[Dict[str, Any]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.time,
        stability_sec: float = STABILITY_WINDOW_SEC,
    ) -> Dict[str, Any]:
        """
        Sửa Wi-Fi rớt / flap. Không dừng giữa chừng chỉ vì Ping may mắn
        khi nguyên nhân là reconnect_loop hoặc weak_link.
        """
        from core.network_optimizer import NetworkOptimizer
        from core.system_monitor import SystemMonitor, PING_REPAIR_TIMEOUT

        t0 = time.time()
        health = health or NetworkOptimizer.run_health_check(measure_ping=True)
        snap = cls.detect_wifi_instability(
            snapshot=snapshot,
            health=health,
            include_events=bool(snapshot) or True,
        ) if snapshot is None else cls.detect_wifi_instability(
            snapshot=snapshot, health=health, include_events=False,
        )
        cause, cause_label = classify_wifi_cause(snap, health)
        snap["cause"] = cause
        snap["cause_label"] = cause_label
        sticky = cause in ("reconnect_loop", "weak_link", "link_loss")
        ping_before = float(((health.get("checks") or {}).get("ping") or {}).get("ping_ms") or -1)
        steps: List[Dict[str, Any]] = []
        skipped: List[str] = [cls.skipped_nic_toggle()]
        needs_dns_confirm = False
        needs_location_unlock = bool(snap.get("location_gpo_locked") or snap.get("location_blocked"))
        dns_applied = False
        stopped_at = ""
        adapter = str(snap.get("name") or "")
        ssid = str(snap.get("ssid") or "")
        if needs_location_unlock:
            # Never silently edit GPO / ConsentStore on a Wi-Fi flap — user must click the button.
            skipped.append(
                "Location bị khóa bởi Group Policy — không tự gỡ (chỉ khi bấm «Gỡ khóa Location»)."
            )
            logger.info("[WifiRecovery] Location GPO lock detected; skipping auto Location unlock")

        def _remeasure() -> float:
            return float(SystemMonitor.measure_ping_now(timeout=PING_REPAIR_TIMEOUT))

        def _pack(ping_after: float, recovered: bool, repaired: bool, reason: str, msg: str) -> Dict[str, Any]:
            applied = cls.format_applied_fixes(steps)
            report = {
                "success": repaired or recovered or any(s.get("success") for s in steps),
                "repaired": repaired,
                "recovered": recovered,
                "reason": reason,
                "cause": cause,
                "cause_label": cause_label,
                "applied_summary": applied,
                "message": msg,
                "issues": list(health.get("issues") or []) + (["wifi_unstable"] if snap.get("unstable") else []),
                "steps": steps,
                "skipped": skipped,
                "health_before": health,
                "wifi": snap,
                "ping_before": ping_before,
                "ping_after": ping_after,
                "dns_applied": dns_applied,
                "needs_dns_confirm": needs_dns_confirm,
                "needs_location_unlock": needs_location_unlock,
                "location_gpo_locked": bool(snap.get("location_gpo_locked")),
                "stopped_at": stopped_at,
                "duration_ms": round((time.time() - t0) * 1000, 1),
                "timestamp": _datetime_str(),
                "type": "wifi_drop",
            }
            cls.last_wifi_drop_report = report
            try:
                NetworkOptimizer.last_wifi_drop_report = report
                NetworkOptimizer.last_missing_ping_report = report
            except Exception:
                pass
            return report

        if not snap.get("is_wifi"):
            skipped.append("Không phải Wi-Fi — bỏ qua lộ trình sửa Wi-Fi.")
            return _pack(ping_before, ping_before > 0, False, "not_wifi", "Không phát hiện adapter Wi-Fi.")

        if cause == "ok" and not snap.get("unstable"):
            msg = "Wi-Fi đang ổn định. Không cần reconnect hay renew DHCP."
            skipped.append("Bỏ qua sửa vì Wi-Fi không flap / không yếu.")
            return _pack(ping_before if ping_before > 0 else _remeasure(), True, False, "wifi_stable", msg)

        # 1. Flush DNS + ARP (luôn an toàn)
        dns_res = NetworkOptimizer.flush_dns()
        steps.append({"action": "flush_dns", "success": bool(dns_res.get("success")), "message": dns_res.get("message")})
        arp_res = NetworkOptimizer.purge_arp_netbios()
        steps.append({"action": "purge_arp_netbios", "success": bool(arp_res.get("success")), "message": arp_res.get("message")})
        ping_now = _remeasure()
        if ping_now > 0 and not sticky:
            stopped_at = "purge_arp_netbios"
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: {cls.format_applied_fixes(steps)}. "
                f"Ping đo được lại: {ping_now:.0f} ms."
            )
            logger.info(f"[WifiRecovery] {msg}")
            return _pack(ping_now, True, True, "wifi_drop", msg)

        # 2. DHCP renew
        dhcp = cls.renew_dhcp(adapter)
        steps.append(dhcp)
        ping_now = _remeasure()
        if ping_now > 0 and not sticky:
            stopped_at = "renew_dhcp"
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: {cls.format_applied_fixes(steps)}. "
                f"Ping đo được lại: {ping_now:.0f} ms."
            )
            return _pack(ping_now, True, True, "wifi_drop", msg)

        # 3. Đổi DNS chỉ khi AdGuard / DNS lọc / người dùng yêu cầu
        if apply_dns or snap.get("filtering_dns") or is_filtering_or_custom_dns(snap.get("dns_servers") or []):
            best = NetworkOptimizer.apply_best_dns(allow_elevation=bool(apply_dns))
            dns_applied = bool(best.get("success"))
            needs_dns_confirm = (not dns_applied) and (
                bool(best.get("needs_admin"))
                or "Administrator" in str(best.get("message") or "")
                or "quyền" in str(best.get("message") or "").lower()
            )
            steps.append({
                "action": "apply_best_dns",
                "success": dns_applied,
                "message": best.get("message", "Đổi DNS"),
            })
        else:
            skipped.append("Không đổi DNS — không phải AdGuard/DNS lọc. Dùng «Đổi DNS Siêu Tốc» nếu cần.")

        # 4. Reconnect cùng SSID (không bật-tắt NIC)
        if cause in ("reconnect_loop", "link_loss", "adapter_down", "weak_link"):
            recon = cls.reconnect_wifi_profile(ssid, adapter_name=adapter, now=clock_fn())
            steps.append(recon)
            if recon.get("location_blocked") or recon.get("location_gpo_locked"):
                needs_location_unlock = True
        else:
            skipped.append("Không reconnect SSID vì không phải mất link / vòng reconnect.")

        # 5. Tắt tiết kiệm pin Wi-Fi (MT7921 hay rớt khi PSM)
        if cause in ("weak_link", "reconnect_loop", "link_loss"):
            pwr = cls.disable_wifi_power_saving(adapter)
            steps.append(pwr)
        else:
            skipped.append("Không đổi power-save Wi-Fi.")

        # 6. Cửa sổ ổn định sau sửa
        def _snap():
            return cls.get_wifi_snapshot(include_events=False, now=clock_fn())

        def _probe():
            return _remeasure() > 0 or bool(_snap().get("is_up"))

        stable = cls.wait_for_stable_link(
            get_snapshot=_snap,
            duration_sec=stability_sec,
            interval_sec=min(STABILITY_POLL_SEC, max(0.5, stability_sec / 4)),
            sleep_fn=sleep_fn,
            clock_fn=clock_fn,
            probe_fn=_probe,
        )
        steps.append(stable)
        ping_after = _remeasure()
        recovered = bool(stable.get("stable")) and (ping_after > 0 or bool(stable.get("probe_ok")))
        if not recovered:
            recovered = bool(stable.get("stable"))
        stopped_at = "wait_stable_link" if recovered else "unrecovered"
        applied = cls.format_applied_fixes(steps)
        if recovered:
            ping_bit = f" Ping: {ping_after:.0f} ms." if ping_after > 0 else " Link Wi-Fi Up ổn định."
            msg = f"Nguyên nhân: {cause_label}. Đã sửa: {applied}.{ping_bit}"
        else:
            if needs_location_unlock:
                confirm = (
                    " Location bị khóa bởi Group Policy — bấm «Gỡ khóa Location» (UAC) "
                    "để netsh wlan / reconnect SSID hoạt động. Không tự gỡ khi Wi-Fi rớt."
                )
            elif needs_dns_confirm:
                confirm = " Cần quyền Admin để đổi DNS — bấm «Đổi DNS Siêu Tốc»."
            else:
                confirm = " Nếu vẫn rớt, kiểm tra router / kênh Wi-Fi — ứng dụng không tắt-bật card."
            msg = f"Nguyên nhân: {cause_label}. Đã sửa: {applied}. Wi-Fi chưa ổn định hẳn.{confirm}"
        logger.info(f"[WifiRecovery] wifi-drop repair recovered={recovered} ping_after={ping_after} cause={cause}")
        return _pack(ping_after, recovered, True, "wifi_drop", msg)

    @staticmethod
    def should_trigger_wifi_drop_fix(
        enabled: bool,
        unstable: bool,
        now_ts: float,
        last_trigger_ts: float,
        cooldown_sec: float,
        unrecovered_repairs: int,
        max_unrecovered: int = 2,
        first_cooldown_sec: float = 12.0,
    ) -> bool:
        """Kích hoạt auto-fix Wi-Fi. Không phụ thuộc Ping (ICMP vẫn có thể OK khi WLAN flap)."""
        if not enabled:
            return False
        if not unstable:
            return False
        if int(unrecovered_repairs) >= int(max_unrecovered):
            return False
        if int(unrecovered_repairs) <= 0:
            effective_cd = max(0.0, float(first_cooldown_sec))
        else:
            effective_cd = min(float(cooldown_sec) * int(unrecovered_repairs), 600.0)
        if last_trigger_ts > 0 and (now_ts - last_trigger_ts) < float(effective_cd):
            return False
        return True


def _datetime_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
