"""
core/ai_copilot.py – Interactive AI System Copilot & Doctor Engine (v4.5 Pro)
=============================================================================
Trợ lý AI tương tác thông minh cho PC Cleaner & Optimizer:
  - Tự động trích xuất telemetry phần cứng thời gian thực (CPU, RAM, Ổ C, Ping, Pin, Tiến trình).
  - Kiến trúc Hybrid 2 tầng:
      1. Offline Expert Brain: Suy luận chuyên gia máy tính offline, siêu tốc (<0.05s), 100% riêng tư.
      2. Cloud Brain: Hỗ trợ kết nối Google Gemini API / OpenAI API khi người dùng cấu hình key.
  - Sinh các nút tương tác 1-Click Actionable Buttons trực tiếp trong câu trả lời.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

import psutil

from core.logger import logger
from core.predictive_ai import (
    PredictiveAIEngine, AIHealthReport, AutoPilotState,
    STATUS_CRITICAL_DEPLETION, STATUS_WARNING_DEPLETION
)
from config_manager import DEFAULT_GEMINI_MODEL, canonicalize_gemini_model

# Gemini 2.5 Flash returns HTTP 404 for many new AI Studio keys (Sep 2026).
# Prefer the documented Flash alias, then current stable Flash / Flash-Lite IDs.
GEMINI_FALLBACK_MODELS = (
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.0-flash",
)
GEMINI_KNOWN_MODELS = (
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.0-flash",
)
_GEMINI_MODEL_RE = re.compile(r"[A-Za-z0-9._-]+")
_GEMINI_ERROR_MSG_MAX = 240


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class CopilotAction:
    """Nút hành động 1-click trả về trong câu trả lời của AI."""
    key: str            # Action key (ví dụ: 'optimize_ram', 'clean_disk', 'toggle_game_boost')
    label: str          # Nhãn nút (ví dụ: '⚡ Thu Hồi RAM Ngay')
    icon: str = "⚡"
    description: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "icon": self.icon,
            "description": self.description,
        }


@dataclass
class ChatMessage:
    """Một tin nhắn trong hội thoại với AI Copilot."""
    role: str           # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    actions: List[CopilotAction] = field(default_factory=list)
    telemetry_badge: Optional[str] = None
    source: str = "offline_expert"   # "offline_expert" | "cloud_gemini" | "cloud_openai"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "actions": [a.to_dict() for a in self.actions],
            "telemetry_badge": self.telemetry_badge,
            "source": self.source,
        }


@dataclass
class CopilotResult:
    """Kết quả trả lời từ AI Copilot."""
    reply: str
    actions: List[CopilotAction]
    telemetry_summary: Dict[str, Any]
    source: str = "offline_expert"


# ---------------------------------------------------------------------------
# Quick Prompts gợi ý cho người dùng
# ---------------------------------------------------------------------------

QUICK_PROMPTS = [
    "🩺 Khám sức khỏe toàn diện máy tính",
    "⚡ Tại sao máy tôi bị ngốn RAM?",
    "🎮 Tối ưu hệ thống để chơi game mượt",
    "💾 Ổ C bị đầy, cần xóa những gì?",
    "📶 Kiểm tra mạng và giảm giật ping",
    "🔋 Làm sao để kéo dài thời lượng pin?",
    "🛡️ Quét kiểm tra tiến trình lạ và an ninh",
]


# ---------------------------------------------------------------------------
# Telemetry Collector
# ---------------------------------------------------------------------------

class TelemetryCollector:
    """Thu thập thông số phần cứng thực tế phục vụ AI chẩn đoán."""

    @staticmethod
    def collect() -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "ram": {"percent": 50.0, "used_gb": 4.0, "total_gb": 8.0, "free_mb": 4096},
            "cpu": {"percent": 20.0, "count": os.cpu_count() or 4},
            "disk": {"free_gb": 50.0, "total_gb": 256.0, "free_percent": 20.0},
            "net": {"ping_ms": -1.0, "ping_status": "unknown", "ping_measured": False, "adapter": ""},
            "battery": {"percent": 100, "power_plugged": True},
            "top_ram_procs": [],
            "top_cpu_procs": [],
        }

        # RAM
        try:
            vm = psutil.virtual_memory()
            result["ram"] = {
                "percent": round(vm.percent, 1),
                "used_gb": round((vm.total - vm.available) / (1024 ** 3), 2),
                "total_gb": round(vm.total / (1024 ** 3), 2),
                "free_mb": round(vm.available / (1024 ** 2)),
            }
        except Exception:
            pass

        # CPU
        try:
            result["cpu"] = {
                "percent": round(psutil.cpu_percent(interval=None), 1),
                "count": os.cpu_count() or 4,
            }
        except Exception:
            pass

        # Disk C:
        try:
            du = psutil.disk_usage("C:\\")
            free_gb = du.free / (1024 ** 3)
            total_gb = du.total / (1024 ** 3)
            free_pct = (free_gb / total_gb * 100.0) if total_gb > 0 else 0.0
            result["disk"] = {
                "free_gb": round(free_gb, 1),
                "total_gb": round(total_gb, 1),
                "free_percent": round(free_pct, 1),
            }
        except Exception:
            pass

        # Network ping — reuse SystemMonitor so Copilot never stays stuck at -1
        # just because the meter was never called.
        try:
            from core.system_monitor import SystemMonitor
            net_info = SystemMonitor.get_network_info()
            ping_ms = float(net_info.get("ping_ms", -1.0))
            ping_measured = bool(net_info.get("ping_measured", False))
            if not ping_measured:
                ping_ms = float(SystemMonitor.measure_ping_now())
                ping_measured = True
            result["net"] = {
                "ping_ms": ping_ms,
                "ping_status": SystemMonitor._ping_status,
                "ping_measured": ping_measured,
                "adapter": net_info.get("adapter") or SystemMonitor._cached_adapter or "",
            }
        except Exception:
            pass

        # Battery
        try:
            bat = psutil.sensors_battery()
            if bat:
                result["battery"] = {
                    "percent": int(bat.percent),
                    "power_plugged": bool(bat.power_plugged),
                }
        except Exception:
            pass

        # Top processes by RAM & CPU
        try:
            procs = []
            for p in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
                try:
                    name = p.info['name'] or ""
                    mem_mb = (p.info['memory_info'].rss / (1024 * 1024)) if p.info['memory_info'] else 0
                    cpu_p = p.info['cpu_percent'] or 0.0
                    procs.append({"name": name, "ram_mb": mem_mb, "cpu_pct": cpu_p})
                except Exception:
                    continue

            procs_by_ram = sorted(procs, key=lambda x: x["ram_mb"], reverse=True)[:5]
            procs_by_cpu = sorted(procs, key=lambda x: x["cpu_pct"], reverse=True)[:3]

            result["top_ram_procs"] = [f"{p['name']} ({p['ram_mb']:.0f} MB)" for p in procs_by_ram if p["ram_mb"] > 80]
            result["top_cpu_procs"] = [f"{p['name']} ({p['cpu_pct']:.1f}%)" for p in procs_by_cpu if p["cpu_pct"] > 5]
        except Exception:
            pass

        return result


def _normalize_text(s: str) -> str:
    """Chuyển văn bản về chữ thường và ghép phiên bản không dấu để hỗ trợ gõ có/không dấu."""
    s = s.lower().strip()
    replacements = {
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'đ': 'd',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
    }
    unaccented = s
    for k, v in replacements.items():
        unaccented = unaccented.replace(k, v)
    return s + " " + unaccented


# ---------------------------------------------------------------------------
# Offline Expert Brain (Suy luận chuyên gia máy tính cục bộ)
# ---------------------------------------------------------------------------

class OfflineExpertBrain:
    """
    Bộ não chuyên gia máy tính offline:
    Nhận diện câu hỏi tiếng Việt, phân tích telemetry và sinh lời khuyên kèm nút hành động.
    """

    @classmethod
    def answer(
        cls,
        user_text: str,
        telemetry: Dict[str, Any],
        health_report: Optional[AIHealthReport] = None,
        autopilot_state: Optional[AutoPilotState] = None
    ) -> CopilotResult:
        norm_text = _normalize_text(user_text)
        actions: List[CopilotAction] = []

        ram = telemetry.get("ram", {})
        ram_pct = ram.get("percent", 50.0)
        ram_used = ram.get("used_gb", 4.0)
        ram_total = ram.get("total_gb", 8.0)
        top_ram = telemetry.get("top_ram_procs", [])

        cpu = telemetry.get("cpu", {})
        cpu_pct = cpu.get("percent", 20.0)
        top_cpu = telemetry.get("top_cpu_procs", [])

        disk = telemetry.get("disk", {})
        disk_free = disk.get("free_gb", 50.0)
        disk_total = disk.get("total_gb", 256.0)

        bat = telemetry.get("battery", {})
        bat_pct = bat.get("percent", 100)
        bat_plugged = bat.get("power_plugged", True)

        net = telemetry.get("net", {})
        ping_ms = float(net.get("ping_ms", -1.0))
        ping_measured = bool(net.get("ping_measured", ping_ms > 0))
        ping_status = str(net.get("ping_status", "unknown"))

        score = health_report.score if health_report else 85
        grade = health_report.grade if health_report else "TỐT"

        # ── 1. Câu hỏi về RAM / Máy đơ / Chậm / Lag ──
        if any(k in norm_text for k in ("ram", "ngon ram", "ngốn ram", "giai phong ram", "giải phóng ram", "bo nho", "bộ nhớ", "do may", "đơ máy", "bi do", "bị đơ", "treo may", "treo máy", "cham", "chậm", "lag")):
            reply_lines = [
                f"### ⚡ Phân Tích Hiện Trạng Bộ Nhớ RAM",
                f"- **Mức tiêu thụ hiện tại:** **{ram_pct:.1f}%** ({ram_used:.1f} GB / {ram_total:.1f} GB)",
            ]
            if top_ram:
                reply_lines.append(f"- **Ứng dụng chiếm nhiều RAM nhất:** {', '.join(top_ram[:3])}")

            if ram_pct >= 80.0:
                reply_lines.append(
                    "\n> ⚠️ **Cảnh báo:** Mức RAM trên 80% khiến Windows phải dùng bộ nhớ ảo (Pagefile) trên ổ đĩa, "
                    "dẫn tới hiện tượng giật đơ (Micro-stutter) và trễ phản hồi khi chuyển tab."
                )
            else:
                reply_lines.append(
                    "\n> ✅ **Đánh giá:** Mức RAM đang ở ngưỡng ổn định. Bạn có thể thu hồi bộ nhớ đệm (Standby List) "
                    "để làm sạch không gian bộ nhớ cho ứng dụng nặng."
                )

            reply_lines.append("\n**Khuyến nghị:** Nhấn nút bên dưới để giải phóng RAM tức thì không làm tắt app đang dùng:")
            actions.append(CopilotAction(key="optimize_ram", label="⚡ Thu Hồi RAM Ngay", icon="⚡"))
            actions.append(CopilotAction(key="manage_processes", label="🔄 Quản Lý Tiến Trình", icon="🔄"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 2. Câu hỏi về Chơi Game / Tụt FPS / Tăng tốc game ──
        if any(k in norm_text for k in ("game", "choi game", "chơi game", "fps", "giat fps", "giật fps", "tut fps", "tụt fps", "tang toc game", "tăng tốc game", "gaming")):
            reply_lines = [
                f"### 🎮 Đánh Giá Hiệu Năng Phục Vụ Gaming",
                f"- **Tải CPU hiện tại:** **{cpu_pct:.1f}%** | **RAM đang dùng:** **{ram_pct:.1f}%**",
            ]
            if top_cpu:
                reply_lines.append(f"- **Tác vụ chạy nền ngốn CPU:** {', '.join(top_cpu)}")

            reply_lines.append(
                "\n**Giải pháp tối ưu hóa để tăng FPS:**\n"
                "1. **Kích hoạt Game Boost**: Đẩy luồng xử lý game lên mức ưu tiên cao nhất (`HIGH_PRIORITY_CLASS`), "
                "dừng các dịch vụ chạy ngầm không cần thiết.\n"
                "2. **Làm sạch Standby Memory**: Tránh hiện tượng tụt khung hình đột ngột khi game load map mới.\n"
                "3. **Tối ưu Network Ping**: Làm sạch DNS cache giúp ổn định đường truyền khi chơi game online."
            )
            actions.append(CopilotAction(key="toggle_game_boost", label="🎮 Kích Hoạt Game Boost", icon="🎮"))
            actions.append(CopilotAction(key="optimize_ram", label="⚡ Thu Hồi RAM Standby", icon="⚡"))
            actions.append(CopilotAction(key="optimize_network", label="📶 Tối Ưu Mạng Ping", icon="📶"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 3. Câu hỏi về Ổ C / Dung Lượng / File Rác / WinSxS ──
        if any(k in norm_text for k in ("o c", "ổ c", "dung luong", "dung lượng", "het dung luong", "hết dung lượng", "bao do", "báo đỏ", "day o", "đầy ổ", "don rac", "dọn rác", "xoa rac", "xóa rác", "xoa gi", "xóa gì", "xoa", "xóa", "temp", "winsxs", "o dia", "ổ đĩa", "disk")):
            free_pct = (disk_free / disk_total * 100.0) if disk_total > 0 else 20.0
            reply_lines = [
                f"### 💾 Báo Cáo Không Gian Ổ Đĩa C:",
                f"- **Dung lượng trống:** **{disk_free:.1f} GB** / {disk_total:.1f} GB ({free_pct:.1f}% còn trống)",
            ]
            if disk_free < 15.0:
                reply_lines.append(
                    "\n> 🚨 **Nguy cơ cao:** Ổ C dưới 15 GB trống sẽ ngăn cản Windows Update cài đặt bản vá, "
                    "làm tê liệt bộ nhớ ảo và gây đơ máy khi xử lý file nặng!"
                )
            else:
                reply_lines.append(
                    "\n> 🟢 **Tình trạng:** Ổ C còn đủ dung lượng an toàn, nhưng việc dọn dẹp định kỳ sẽ giúp SSD duy trì tốc độ đọc ghi cao nhất."
                )

            reply_lines.append(
                "\n**Các mục nên dọn dẹp ngay:**\n"
                "- Thư mục Temp & Crash Dumps của hệ thống.\n"
                "- Bộ đệm cập nhật Windows Update cũ.\n"
                "- Dọn dẹp nén các gói cập nhật tích lũy trong thư mục **WinSxS** (có thể lấy lại 2 - 8 GB)."
            )
            actions.append(CopilotAction(key="clean_disk", label="🧹 Dọn Rác Ổ C", icon="🧹"))
            actions.append(CopilotAction(key="winsxs_cleanup", label="🗄️ Dọn Dẹp WinSxS", icon="🗄️"))
            actions.append(CopilotAction(key="manage_uninstaller", label="📦 Gỡ Ứng Dụng Rác", icon="📦"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 4. Câu hỏi về Mạng / Ping / Wifi / Internet ──
        if any(k in norm_text for k in ("mang", "mạng", "ping", "lag mang", "lag mạng", "cham mang", "chậm mạng", "dns", "wifi", "internet", "mat mang", "mất mạng")):
            if ping_ms > 0:
                ping_line = f"- **Ping hiện tại:** **{ping_ms:.0f} ms**"
                if ping_ms < 50:
                    ping_line += " (thấp — mạng mượt)"
                elif ping_ms < 120:
                    ping_line += " (ổn định)"
                else:
                    ping_line += " (cao — dễ giật lag)"
            elif ping_measured:
                ping_line = (
                    f"- **Ping hiện tại:** **không đo được** "
                    f"({ping_status or 'timeout'}) — mạng có thể mất kết nối, DNS lỗi, hoặc firewall chặn."
                )
            else:
                ping_line = "- **Ping hiện tại:** đang đo..."

            reply_lines = [
                f"### 🌐 Tình Trạng Kết Nối Mạng & Băng Thông",
                ping_line,
                "Hệ thống tự động kiểm tra độ trễ mạng Internet, DNS, gateway và card mạng.",
            ]
            if ping_measured and ping_ms <= 0:
                cause_line = ""
                applied_line = ""
                try:
                    from core.network_optimizer import NetworkOptimizer
                    from core.wifi_recovery import WifiRecovery
                    report = (
                        getattr(NetworkOptimizer, "last_wifi_drop_report", None)
                        or getattr(NetworkOptimizer, "last_missing_ping_report", None)
                        or {}
                    )
                    det = getattr(WifiRecovery, "last_detect", None) or {}
                    if report.get("cause_label") or det.get("cause_label"):
                        cause_line = f"\n> 🔍 **Nguyên nhân:** {report.get('cause_label') or det.get('cause_label')}."
                    if report.get("applied_summary"):
                        applied_line = f"\n> 🛠️ **Đã sửa:** {report.get('applied_summary')}."
                except Exception:
                    cause_line = ""
                    applied_line = ""
                reply_lines.append(
                    "\n> ⚠️ **Ping không có / Wi-Fi có thể rớt:** Tôi sẽ chẩn đoán rồi sửa ngay "
                    "(flush DNS → DHCP → reconnect SSID → tắt tiết kiệm pin Wi-Fi nếu flap; "
                    "không reset Winsock, không tắt-bật card)."
                    f"{cause_line}{applied_line}"
                )
                reply_lines.append(
                    "\n**Các bước an toàn:**\n"
                    "1. **Kiểm tra & sửa ngay**: chẩn đoán nguyên nhân + flush DNS / DHCP / reconnect Wi-Fi.\n"
                    "2. **Đổi DNS Siêu Tốc** nếu đang dùng AdGuard hoặc Windows hỏi quyền Administrator (UAC)."
                )
                actions.append(CopilotAction(key="repair_network_now", label="🛠️ Kiểm Tra & Sửa Mạng", icon="🛠️"))
                actions.append(CopilotAction(key="switch_dns", label="🌐 Đổi DNS Siêu Tốc", icon="🌐"))
                try:
                    from core.windows_location import is_location_gpo_locked
                    if is_location_gpo_locked():
                        reply_lines.append(
                            "\n> 📍 **Location bị khóa bởi Group Policy** — reconnect SSID có thể thất bại "
                            "cho đến khi gỡ khóa (UAC một lần, không tự chạy khi Wi-Fi rớt)."
                        )
                        actions.append(CopilotAction(key="unlock_location", label="📍 Gỡ khóa Location", icon="📍"))
                except Exception:
                    pass
                return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

            wifi_note = ""
            try:
                from core.wifi_recovery import WifiRecovery
                det = getattr(WifiRecovery, "last_detect", None) or {}
                if det.get("unstable"):
                    wifi_note = (
                        f"\n> ⚠️ **Wi-Fi:** {det.get('cause_label')}. "
                        "Ping TCP vẫn có thể OK khi WLAN đang flap — nên sửa Wi-Fi (DHCP / reconnect SSID / tắt tiết kiệm pin)."
                    )
            except Exception:
                wifi_note = ""
            reply_lines.append(
                "\n**Giải pháp khắc phục giật lag mạng:**\n"
                "1. **Xóa DNS Cache (`ipconfig /flushdns`)**: Loại bỏ các bản ghi phân giải tên miền cũ hoặc bị lỗi.\n"
                "2. **Chuyển sang DNS Siêu Tốc (Cloudflare 1.1.1.1 hoặc Google 8.8.8.8)**: "
                "Tăng tốc độ tải trang web lên 20 - 40% và giảm hiện tượng nghẽn mạng giờ cao điểm."
                f"{wifi_note}"
            )
            if wifi_note:
                actions.append(CopilotAction(key="repair_network_now", label="🛠️ Sửa Wi-Fi Ngay", icon="🛠️"))
            try:
                from core.windows_location import is_location_gpo_locked
                if is_location_gpo_locked():
                    reply_lines.append(
                        "\n> 📍 **Location bị khóa bởi Group Policy** — Settings → Privacy → Location bị xám, "
                        "`netsh wlan show interfaces` có thể lỗi quyền Location nên reconnect SSID thất bại. "
                        "Bấm **Gỡ khóa Location** (UAC một lần). Ứng dụng không tự gỡ khi Wi-Fi rớt."
                    )
                    actions.append(CopilotAction(key="unlock_location", label="📍 Gỡ khóa Location", icon="📍"))
            except Exception:
                pass
            actions.append(CopilotAction(key="optimize_network", label="📶 Tối Ưu Mạng Ngay", icon="📶"))
            actions.append(CopilotAction(key="switch_dns", label="🌐 Đổi DNS Siêu Tốc", icon="🌐"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 5. Câu hỏi về Nhiệt Độ / Quạt To / Nóng Máy / Pin ──
        if any(k in norm_text for k in ("nong", "nóng", "quat", "quạt", "nhiet do", "nhiệt độ", "pin", "tut pin", "tụt pin", "chai pin", "nong may", "nóng máy", "quat keu", "quạt kêu", "battery")):
            status_plug = "Đang cắm sạc (AC)" if bat_plugged else "Đang dùng PIN (Discharging)"
            reply_lines = [
                f"### 🔋 Phân Tích Nhiệt Độ & Năng Lượng",
                f"- **Trạng thái Pin:** **{bat_pct}%** ({status_plug})",
                f"- **Tải CPU hiện tại:** **{cpu_pct:.1f}%**",
                "\n**Nguyên nhân quạt quay to và máy nóng:**\n"
                "- Thường do một hoặc nhiều tiến trình nền chạy vô tận (Runaway CPU process).\n"
                "- Bụi bẩn bám tản nhiệt hoặc keo tản nhiệt đã khô.\n"
                "- Khi dùng pin, kích hoạt chế độ Tiết Kiệm Pin sẽ hạ xung nhịp nhàn rỗi, giúp máy mát hơn và tăng thời gian sử dụng."
            ]
            actions.append(CopilotAction(key="battery_saver", label="🔋 Bật Tiết Kiệm Pin", icon="🔋"))
            actions.append(CopilotAction(key="view_hardware", label="🌡️ Xem Giám Sát Phần Cứng", icon="🌡️"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 6. Câu hỏi về An Ninh / Virus / Tiến trình lạ ──
        if any(k in norm_text for k in ("virus", "bao mat", "bảo mật", "an ninh", "tien trinh la", "tiến trình lạ", "ma doc", "mã độc", "nguy hiem", "nguy hiểm", "bat thuong", "bất thường", "hacker")):
            reply_lines = [
                f"### 🛡️ Rà Soát An Ninh & Nhận Diện Dị Biệt",
                "Mô hình AI Z-Score liên tục theo dõi các tiến trình lạ khởi chạy trong nền.",
                "\n**Hệ thống phòng vệ đề xuất:**\n"
                "1. **Rà soát an ninh hệ thống**: Kiểm tra trạng thái Windows Defender, UAC, tường lửa Firewall.\n"
                "2. **Kiểm tra Startup Items**: Vô hiệu hóa các phần mềm không rõ nguồn gốc tự khởi động cùng Windows.\n"
                "3. **Tắt dịch vụ Telemetry theo dõi**: Khóa các dịch vụ theo dõi hành vi ẩn của bên thứ 3."
            ]
            actions.append(CopilotAction(key="scan_security", label="🛡️ Rà Soát An Ninh Ngay", icon="🛡️"))
            actions.append(CopilotAction(key="manage_startup", label="🚀 Quản Lý Khởi Động", icon="🚀"))
            actions.append(CopilotAction(key="manage_services", label="⚙️ Tinh Chỉnh Dịch Vụ", icon="⚙️"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 7. Khám Bệnh Máy Tính Toàn Diện / Chẩn Đoán Tổng Quan ──
        if any(k in norm_text for k in ("kham benh", "khám bệnh", "kiem tra", "kiểm tra", "tong quan", "tổng quan", "suc khoe", "sức khỏe", "tinh trang", "tình trạng", "danh gia", "đánh giá", "help", "xin chao", "xin chào", "chao", "chào")):
            reply_lines = [
                f"### 🩺 Hồ Sơ Khám Sức Khỏe Máy Tính Toàn Diện",
                f"- **Chỉ số sức khỏe AI Health Score:** **{score}/100 Điểm** (Xếp loại: **{grade}**)",
                f"- **Bộ nhớ RAM:** {ram_pct:.1f}% ({ram_used:.1f} GB / {ram_total:.1f} GB)",
                f"- **Vi xử lý CPU:** {cpu_pct:.1f}% ({cpu.get('count', 4)} Luồng)",
                f"- **Ổ đĩa C:** {disk_free:.1f} GB trống ({disk_total:.1f} GB tổng)",
            ]
            if autopilot_state:
                reply_lines.append(f"- **Chế độ Auto-Pilot hiện tại:** {autopilot_state.badge_text}")

            if score >= 85:
                reply_lines.append("\n🎉 **Kết luận:** Máy tính của bạn đang ở trạng thái rất khỏe mạnh và mượt mà!")
            elif score >= 60:
                reply_lines.append("\n⚠️ **Kết luận:** Máy hoạt động khá ổn nhưng bắt đầu có dấu hiệu nghẽn nhẹ RAM hoặc ổ C cần dọn dẹp.")
            else:
                reply_lines.append("\n🚨 **Kết luận:** Hệ thống đang bị quá tải nghiêm trọng, cần giải phóng tài nguyên ngay lập tức!")

            actions.append(CopilotAction(key="auto_optimize_all", label="✨ Tối Ưu Hóa Toàn Diện", icon="✨"))
            actions.append(CopilotAction(key="optimize_ram", label="⚡ Thu Hồi RAM", icon="⚡"))
            actions.append(CopilotAction(key="clean_disk", label="🧹 Dọn Rác Ổ C", icon="🧹"))
            return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")

        # ── 8. Mặc định nếu câu hỏi chưa có mẫu cụ thể ──
        reply_lines = [
            f"Tôi là **AI Copilot & Bác Sĩ Hệ Thống** của bạn. Tôi đang liên tục theo dõi hệ thống:",
            f"- Điểm sức khỏe: **{score}/100** ({grade})",
            f"- RAM: **{ram_pct:.1f}%** | CPU: **{cpu_pct:.1f}%** | Ổ C: **{disk_free:.1f} GB trống**",
            "\nTôi có thể giúp bạn giải quyết các vấn đề sau:\n"
            "- *Tại sao máy bị lag / giật / ngốn RAM?*\n"
            "- *Cách tối ưu chơi game mượt nhất?*\n"
            "- *Ổ C bị đầy, dọn dẹp file rác và WinSxS?*\n"
            "- *Khắc phục mạng giật ping cao / đổi DNS?*\n"
            "- *Quét kiểm tra an ninh và tắt dịch vụ chạy ngầm?*"
        ]
        actions.append(CopilotAction(key="auto_optimize_all", label="✨ Tối Ưu Hóa Nhanh", icon="✨"))
        actions.append(CopilotAction(key="optimize_ram", label="⚡ Tối Ưu RAM", icon="⚡"))
        return CopilotResult(reply="\n".join(reply_lines), actions=actions, telemetry_summary=telemetry, source="offline_expert")


# ---------------------------------------------------------------------------
# Cloud Brain (Google Gemini API / OpenAI API Client)
# ---------------------------------------------------------------------------

def normalize_gemini_model(model: Optional[str]) -> str:
    """Sanitize a Gemini model id; strip models/ prefix; fall back to the default."""
    raw = (model or "").strip()
    if raw.lower().startswith("models/"):
        raw = raw[7:]
    if not raw or not _GEMINI_MODEL_RE.fullmatch(raw):
        return DEFAULT_GEMINI_MODEL
    return raw


def gemini_model_fallback_chain(preferred: Optional[str] = None) -> List[str]:
    """Configured model first, then documented Flash aliases that still work for new keys."""
    ordered: List[str] = []
    seen = set()
    for candidate in (preferred, *GEMINI_FALLBACK_MODELS):
        model = normalize_gemini_model(candidate)
        key = model.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(model)
    return ordered


def parse_gemini_error_message(body: str) -> str:
    """Extract Google's JSON error.message (or a compact fallback) from an HTTP body."""
    raw = (body or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    message = ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or "").strip()
        elif isinstance(err, str):
            message = err.strip()
        if not message:
            message = str(data.get("message") or "").strip()
    if not message:
        message = re.sub(r"\s+", " ", raw)
    message = re.sub(r"\s+", " ", message).strip()
    if len(message) > _GEMINI_ERROR_MSG_MAX:
        message = message[: _GEMINI_ERROR_MSG_MAX - 1].rstrip() + "…"
    return message


def format_gemini_http_error(code: int, body: str, reason: str = "") -> str:
    """Human-readable HTTP error: parsed Google message, never truncated raw JSON."""
    detail = parse_gemini_error_message(body) or (reason or "").strip()
    blob = f"{body or ''} {detail}"
    is_not_found = int(code) == 404 or "not found" in detail.lower() or "NOT_FOUND" in blob
    if is_not_found:
        model_id = ""
        m = re.search(r"models/([A-Za-z0-9._-]+)", detail) or re.search(
            r"\b(gemini-[A-Za-z0-9._-]+)\b", detail
        )
        if m:
            model_id = m.group(1)
        if model_id:
            return (
                f"HTTP {code}: Mô hình Gemini không khả dụng cho API key này "
                f"({model_id})."
            )
        return f"HTTP {code}: Mô hình Gemini không tồn tại hoặc không khả dụng cho API key này."
    if detail:
        return f"HTTP {code}: {detail}"
    return f"HTTP {code}"


class CloudAIBrain:
    """Kết nối mô hình ngôn ngữ lớn trên đám mây (Google Gemini Flash)."""

    last_error: str = ""
    last_error_short: str = ""
    last_working_model: str = ""

    @classmethod
    def query_gemini(
        cls,
        api_key: str,
        user_prompt: str,
        telemetry: Dict[str, Any],
        health_report: Optional[AIHealthReport] = None,
        timeout: float = 8.0,
        model: str = DEFAULT_GEMINI_MODEL,
        persist_model: Optional[Any] = None,
    ) -> Optional[str]:
        cls.last_error = ""
        cls.last_error_short = ""
        cls.last_working_model = ""
        if not api_key:
            cls.last_error = "Chưa có Gemini API Key."
            cls.last_error_short = cls.last_error
            return None

        requested = normalize_gemini_model(model)
        chain = gemini_model_fallback_chain(requested)

        ram = telemetry.get("ram", {}) if isinstance(telemetry, dict) else {}
        cpu = telemetry.get("cpu", {}) if isinstance(telemetry, dict) else {}
        disk = telemetry.get("disk", {}) if isinstance(telemetry, dict) else {}
        score = health_report.score if health_report else 80

        system_instruction = (
            "Bạn là một kỹ sư máy tính và trợ lý AI thông minh tích hợp trong phần mềm 'PC Cleaner & Optimizer'. "
            "Trả lời ngắn gọn, chuẩn xác bằng tiếng Việt, đưa ra giải thích kỹ thuật dễ hiểu và các bước hành động cụ thể.\n"
            f"Thông số PC hiện tại: RAM {ram.get('percent', 0)}%, CPU {cpu.get('percent', 0)}%, "
            f"Ổ C còn trống {disk.get('free_gb', 0)} GB, Điểm sức khỏe {score}/100."
        )

        payload_bytes = json.dumps({
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\nNgười dùng hỏi: {user_prompt}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 600,
            }
        }).encode("utf-8")

        tried: List[str] = []
        last_http_detail = ""

        for candidate in chain:
            tried.append(candidate)
            # API key is sent in a header so it is not written to proxy/access logs.
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{candidate}:generateContent"
            try:
                req = urllib.request.Request(
                    url,
                    data=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": api_key,
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    if getattr(response, "status", 200) != 200:
                        last_http_detail = format_gemini_http_error(response.status, raw)
                        logger.debug(f"[CloudAI] Gemini HTTP {response.status} model={candidate}: {last_http_detail}")
                        if int(response.status) == 404:
                            continue
                        cls.last_error = last_http_detail
                        cls.last_error_short = last_http_detail
                        return None
                    resp_data = json.loads(raw)
                    candidates = resp_data.get("candidates", [])
                    if not candidates:
                        prompt_fb = (resp_data.get("promptFeedback") or {}).get("blockReason")
                        cls.last_error = f"Gemini không trả lời ({prompt_fb or 'phản hồi rỗng'})."
                        cls.last_error_short = cls.last_error
                        return None
                    finish = candidates[0].get("finishReason") or ""
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = parts[0].get("text", "") if parts else ""
                    if text:
                        cls.last_error = ""
                        cls.last_error_short = ""
                        cls.last_working_model = candidate
                        cls._persist_working_model(persist_model, requested, candidate)
                        return text
                    cls.last_error = f"Gemini trả về rỗng ({finish or 'no text'})."
                    cls.last_error_short = cls.last_error
                    return None
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                last_http_detail = format_gemini_http_error(e.code, body, reason=str(getattr(e, "reason", "") or ""))
                logger.debug(f"[CloudAI] Gemini HTTPError model={candidate}: {last_http_detail}")
                if int(e.code) == 404:
                    continue
                cls.last_error = last_http_detail
                cls.last_error_short = last_http_detail
                return None
            except urllib.error.URLError as e:
                cls.last_error = f"Lỗi mạng: {getattr(e, 'reason', e)}"
                cls.last_error_short = "Lỗi mạng khi gọi Cloud Gemini."
                logger.debug(f"[CloudAI] Gemini URLError: {e}")
                return None
            except Exception as e:
                cls.last_error = f"{type(e).__name__}: {e}"
                cls.last_error_short = "Cloud Gemini gặp lỗi không xác định."
                logger.debug(f"[CloudAI] Gemini API error: {e}")
                return None

        models_tried = ", ".join(tried) if tried else requested
        cls.last_error_short = "Cloud Gemini: không tìm thấy mô hình khả dụng (HTTP 404)"
        cls.last_error = (
            f"Không tìm thấy mô hình Gemini khả dụng cho API key này (đã thử: {models_tried}). "
            "Hãy chọn mô hình khác trong Cấu Hình AI hoặc kiểm tra quyền truy cập tại Google AI Studio."
        )
        if last_http_detail and "Mô hình Gemini không" in last_http_detail:
            cls.last_error = f"{cls.last_error} {last_http_detail}"
        return None

    @staticmethod
    def _persist_working_model(persist_model: Optional[Any], requested: str, working: str) -> None:
        working = canonicalize_gemini_model(working)
        requested = str(requested or "").strip()
        if not persist_model or not working or working == requested:
            return
        try:
            persist_model(working)
        except Exception as e:
            logger.debug(f"[CloudAI] Không lưu được mô hình Gemini {working}: {e}")


# ---------------------------------------------------------------------------
# Master AI Copilot Engine
# ---------------------------------------------------------------------------

class AICopilotEngine:
    """
    Điều phối viên trung tâm AI Copilot:
    - Quản lý lịch sử hội thoại.
    - Tự động lấy telemetry thời gian thực.
    - Quyết định gọi Cloud Brain hay Offline Expert Brain.
    - Gắn các nút hành động tương tác 1-click.
    """

    def __init__(self, config_manager: Optional[Any] = None, predictive_engine: Optional[PredictiveAIEngine] = None):
        self.config_manager = config_manager
        self.predictive_engine = predictive_engine
        self.chat_history: List[ChatMessage] = []
        self._init_welcome_message()

    def _init_welcome_message(self):
        """Tin nhắn chào mừng ban đầu."""
        welcome_text = (
            "👋 **Xin chào! Tôi là AI Copilot & Bác Sĩ Hệ Thống của bạn.**\n\n"
            "Tôi liên tục giám sát trạng thái phần cứng, RAM, CPU, ổ C và tiến trình ngầm để bảo vệ máy tính của bạn.\n\n"
            "💡 *Bạn có thể hỏi tôi bất kỳ điều gì về máy tính, hoặc bấm vào các câu hỏi nhanh bên dưới!*"
        )
        actions = [
            CopilotAction(key="auto_optimize_all", label="✨ Khám Sức Khỏe & Tối Ưu", icon="✨"),
            CopilotAction(key="optimize_ram", label="⚡ Thu Hồi RAM Standby", icon="⚡"),
            CopilotAction(key="clean_disk", label="🧹 Dọn Rác Ổ C", icon="🧹"),
        ]
        self.chat_history.append(ChatMessage(
            role="assistant",
            content=welcome_text,
            actions=actions,
            telemetry_badge="Sẵn sàng hỗ trợ 24/7"
        ))

    def ask(self, user_prompt: str, append_user: bool = True) -> ChatMessage:
        """Gửi câu hỏi tới AI Copilot và nhận phản hồi kèm nút hành động."""
        user_prompt_clean = user_prompt.strip()
        if not user_prompt_clean:
            user_prompt_clean = "Khám sức khỏe máy tính"

        if append_user:
            self.chat_history.append(ChatMessage(role="user", content=user_prompt_clean))

        telemetry = TelemetryCollector.collect()

        health_report = None
        autopilot_state = None
        if self.predictive_engine:
            try:
                health_report = self.predictive_engine.calculate_health_score(stats=telemetry)
                autopilot_state = self.predictive_engine.get_autopilot_state(current_stats=telemetry)
            except Exception:
                pass

        cloud_reply = None
        cloud_failed = False
        is_cloud_enabled = False
        api_key = ""
        if self.config_manager:
            is_cloud_enabled = bool(self.config_manager.get("ai_copilot_cloud_enabled", False))
            api_key = str(self.config_manager.get("ai_copilot_gemini_api_key", "")).strip()

        if is_cloud_enabled and api_key:
            model = str(self.config_manager.get("ai_copilot_gemini_model", DEFAULT_GEMINI_MODEL)).strip()
            persist_cb = None
            if hasattr(self.config_manager, "set"):
                cm = self.config_manager

                def _persist_working(working: str, _cm=cm) -> None:
                    fixed = canonicalize_gemini_model(working)
                    current = str(_cm.get("ai_copilot_gemini_model", "")).strip()
                    if fixed and fixed != current:
                        _cm.set("ai_copilot_gemini_model", fixed)

                persist_cb = _persist_working

            cloud_reply = CloudAIBrain.query_gemini(
                api_key=api_key,
                user_prompt=user_prompt_clean,
                telemetry=telemetry,
                health_report=health_report,
                model=model or DEFAULT_GEMINI_MODEL,
                persist_model=persist_cb,
            )
            cloud_failed = not bool(cloud_reply)
        elif is_cloud_enabled and not api_key:
            CloudAIBrain.last_error = "Đã bật Cloud Gemini nhưng chưa nhập API Key."
            CloudAIBrain.last_error_short = CloudAIBrain.last_error
            cloud_failed = True

        if cloud_reply:
            source = "cloud_gemini"
            reply_text = cloud_reply
            actions = self._extract_actions_from_text(reply_text + " " + user_prompt_clean)
        else:
            res = OfflineExpertBrain.answer(
                user_text=user_prompt_clean,
                telemetry=telemetry,
                health_report=health_report,
                autopilot_state=autopilot_state
            )
            reply_text = res.reply
            actions = res.actions
            source = res.source
            if cloud_failed:
                err = CloudAIBrain.last_error or "Cloud Gemini không phản hồi."
                reply_text = (
                    f"⚠️ Cloud Gemini lỗi: {err}\n"
                    f"Đang dùng Offline Expert Brain.\n\n---\n\n{res.reply}"
                )

        badge = (
            f"RAM {telemetry.get('ram', {}).get('percent', 0)}% • "
            f"CPU {telemetry.get('cpu', {}).get('percent', 0)}% • "
            f"Ổ C {telemetry.get('disk', {}).get('free_gb', 0)}GB"
        )
        ping_ms = float(telemetry.get("net", {}).get("ping_ms", -1))
        if ping_ms > 0:
            badge += f" • Ping {ping_ms:.0f}ms"
        elif telemetry.get("net", {}).get("ping_measured"):
            status = telemetry.get("net", {}).get("ping_status") or "timeout"
            badge += f" • Ping {status}"
        if cloud_failed:
            badge = f"Cloud lỗi • {badge}"

        assistant_msg = ChatMessage(
            role="assistant",
            content=reply_text,
            actions=actions,
            telemetry_badge=badge,
            source=source
        )
        self.chat_history.append(assistant_msg)
        return assistant_msg

    def _extract_actions_from_text(self, text: str) -> List[CopilotAction]:
        """Tự động trích xuất các nút hành động phù hợp từ nội dung câu trả lời."""
        t = _normalize_text(text)
        actions = []
        if any(k in t for k in ("ram", "thu hoi", "thu hồi", "giai phong", "giải phóng", "bo nho", "bộ nhớ")):
            actions.append(CopilotAction(key="optimize_ram", label="⚡ Thu Hồi RAM Ngay", icon="⚡"))
        if any(k in t for k in ("rac", "rác", "o c", "ổ c", "dung luong", "dung lượng", "temp", "don dep", "dọn dẹp", "winsxs")):
            actions.append(CopilotAction(key="clean_disk", label="🧹 Dọn Rác Ổ C", icon="🧹"))
        if any(k in t for k in ("game", "fps", "boost")):
            actions.append(CopilotAction(key="enable_game_boost", label="🎮 Kích Hoạt Game Boost", icon="🎮"))
        if any(k in t for k in ("mang", "mạng", "ping", "dns", "mat mang", "mất mạng")):
            if any(k in t for k in ("khong do", "không đo", "timeout", "mat mang", "mất mạng", "unreachable")):
                actions.append(CopilotAction(key="repair_network_now", label="🛠️ Kiểm Tra & Sửa Mạng", icon="🛠️"))
            else:
                actions.append(CopilotAction(key="optimize_network", label="📶 Tối Ưu Mạng", icon="📶"))
        if any(k in t for k in ("an ninh", "virus", "bao mat", "bảo mật")):
            actions.append(CopilotAction(key="scan_security", label="🛡️ Rà Soát Bảo Mật", icon="🛡️"))
        if not actions:
            actions.append(CopilotAction(key="auto_optimize_all", label="✨ Tối Ưu Toàn Diện", icon="✨"))
        return actions[:3]

    def clear_history(self):
        """Xóa lịch sử trò chuyện và đặt lại lời chào."""
        self.chat_history = []
        self._init_welcome_message()
