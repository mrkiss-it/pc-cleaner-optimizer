"""
core/ai_advisor.py – AI Smart Suggestions Engine (v3.3 Pro)
=============================================================
Phân tích hành vi hệ thống theo rolling window và sinh gợi ý tối ưu
dựa trên rule-based engine hoàn toàn offline, không cần internet/cloud.

Categories: RAM, CPU, DISK, NETWORK, BATTERY, SECURITY, CLEANUP
Priority  : CRITICAL (đỏ) > WARNING (vàng) > TIP (xanh)
"""
from __future__ import annotations

import time
import json
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Deque


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

PRIORITY_CRITICAL = "CRITICAL"
PRIORITY_WARNING  = "WARNING"
PRIORITY_TIP      = "TIP"

CATEGORY_RAM      = "RAM"
CATEGORY_CPU      = "CPU"
CATEGORY_DISK     = "DISK"
CATEGORY_NETWORK  = "NETWORK"
CATEGORY_BATTERY  = "BATTERY"
CATEGORY_SECURITY = "SECURITY"
CATEGORY_CLEANUP  = "CLEANUP"
CATEGORY_PROCESS  = "PROCESS"
CATEGORY_SERVICES   = "SERVICES"
CATEGORY_UNINSTALLER = "UNINSTALLER"
CATEGORY_WINSXS     = "WINSXS"
CATEGORY_PREDICTIVE = "PREDICTIVE"
CATEGORY_ANOMALY    = "ANOMALY"

CATEGORY_ICONS = {
    CATEGORY_RAM:         "⚡",
    CATEGORY_CPU:         "🖥️",
    CATEGORY_DISK:        "💾",
    CATEGORY_NETWORK:     "🌐",
    CATEGORY_BATTERY:     "🔋",
    CATEGORY_SECURITY:    "🛡️",
    CATEGORY_CLEANUP:     "🗑️",
    CATEGORY_PROCESS:     "🔄",
    CATEGORY_SERVICES:    "⚙️",
    CATEGORY_UNINSTALLER: "📦",
    CATEGORY_WINSXS:      "🗄️",
    CATEGORY_PREDICTIVE:  "🔮",
    CATEGORY_ANOMALY:     "🚨",
}

PRIORITY_ORDER = {PRIORITY_CRITICAL: 0, PRIORITY_WARNING: 1, PRIORITY_TIP: 2}


@dataclass
class Suggestion:
    """Một gợi ý tối ưu từ AI Advisor."""
    category:   str          # CATEGORY_* constant
    priority:   str          # PRIORITY_* constant
    title:      str          # Tiêu đề ngắn (≤ 60 ký tự)
    detail:     str          # Mô tả chi tiết
    action_key: Optional[str] = None   # Key để MainWindow dispatch action
    action_label: str = "Áp Dụng Ngay"
    timestamp:  float = field(default_factory=time.time)

    @property
    def icon(self) -> str:
        return CATEGORY_ICONS.get(self.category, "💡")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category":     self.category,
            "priority":     self.priority,
            "title":        self.title,
            "detail":       self.detail,
            "action_key":   self.action_key,
            "action_label": self.action_label,
        }


# ---------------------------------------------------------------------------
# Rolling Window Snapshot Buffer
# ---------------------------------------------------------------------------

_BUFFER_SIZE = 100   # ~80 giây @ 800ms polling


@dataclass
class _Snapshot:
    ts:          float
    ram_pct:     float
    cpu_pct:     float
    disk_free_gb: float
    net_ping_ms: float
    process_count: int
    net_ping_measured: bool = False


# ---------------------------------------------------------------------------
# AI Advisor – Rule Engine
# ---------------------------------------------------------------------------

class AIAdvisor:
    """
    Singleton-style class nhận snapshot từ SystemMonitorHub và sinh suggestions.

    Cách dùng:
        advisor = AIAdvisor()
        advisor.feed_snapshot(stats_dict)      # gọi từ SystemMonitorHub signal
        suggestions = advisor.get_suggestions()
    """

    def __init__(self, config_path: Optional[str] = None, config_manager: Optional[Any] = None):
        self._buffer: Deque[_Snapshot] = deque(maxlen=_BUFFER_SIZE)
        self._last_battery_info: Dict[str, Any] = {}
        self._last_security_info: Dict[str, Any] = {}
        self._last_leak_info: List[Dict] = []
        self._config_manager = config_manager
        self._config_path = config_path or self._default_config_path()
        from core.predictive_ai import PredictiveAIEngine, STATUS_CRITICAL_DEPLETION, STATUS_WARNING_DEPLETION, STATUS_STABLE
        self.predictive_engine = PredictiveAIEngine(config_manager=self._config_manager)
        self._suggestions_cache: List[Suggestion] = []
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 8.0   # giây – refresh suggestions mỗi 8s

    def invalidate_cache(self) -> None:
        """Xóa cache gợi ý để tính toán lại ngay lập tức."""
        self._cache_ts = 0.0
        self._suggestions_cache = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed_snapshot(self, stats: Dict[str, Any]) -> None:
        """Nhận một snapshot stats từ SystemMonitorHub."""
        try:
            ram  = stats.get("ram", {})
            cpu  = stats.get("cpu", {})
            disk = stats.get("disk", {})
            net  = stats.get("net", {})
            snap = _Snapshot(
                ts=time.time(),
                ram_pct=float(ram.get("percent", 0)),
                cpu_pct=float(cpu.get("percent", 0)),
                disk_free_gb=float(disk.get("free_gb", 999)),
                net_ping_ms=float(net.get("ping_ms", -1)),
                process_count=int(stats.get("process_count", 0)),
                net_ping_measured=bool(net.get("ping_measured", False)),
            )
            self._buffer.append(snap)
            # Đồng bộ sang PredictiveAIEngine
            try:
                self.predictive_engine.feed_snapshot(stats)
            except Exception:
                pass
            # Invalidate cache
            self._cache_ts = 0.0
        except Exception:
            pass

    def update_battery_info(self, battery_data: Dict[str, Any]) -> None:
        """Cập nhật thông tin pin từ HardwareMonitor."""
        self._last_battery_info = battery_data or {}
        self._cache_ts = 0.0

    def update_security_info(self, security_result: Dict[str, Any]) -> None:
        """Cập nhật kết quả quét bảo mật."""
        self._last_security_info = security_result or {}
        self._cache_ts = 0.0

    def update_leak_info(self, leaks: List[Dict]) -> None:
        """Cập nhật danh sách tiến trình nghi ngờ rò rỉ bộ nhớ."""
        self._last_leak_info = leaks or []
        self._cache_ts = 0.0

    def get_suggestions(self) -> List[Suggestion]:
        """Trả về danh sách suggestions đã sắp xếp theo priority."""
        now = time.time()
        if now - self._cache_ts < self._cache_ttl and self._suggestions_cache:
            return self._suggestions_cache

        suggestions = self._run_rules()
        # Sắp xếp: CRITICAL → WARNING → TIP, sau đó theo thứ tự sinh
        suggestions.sort(key=lambda s: PRIORITY_ORDER.get(s.priority, 99))
        self._suggestions_cache = suggestions
        self._cache_ts = now
        return suggestions

    def get_suggestions_count_by_priority(self) -> Dict[str, int]:
        """Trả về số lượng suggestions theo từng mức ưu tiên."""
        sug = self.get_suggestions()
        return {
            PRIORITY_CRITICAL: sum(1 for s in sug if s.priority == PRIORITY_CRITICAL),
            PRIORITY_WARNING:  sum(1 for s in sug if s.priority == PRIORITY_WARNING),
            PRIORITY_TIP:      sum(1 for s in sug if s.priority == PRIORITY_TIP),
        }

    def get_health_report(self, force_refresh: bool = False):
        """Trả về AIHealthReport tổng thể 0-100 điểm kèm Toa Thuốc AI."""
        latest_snap = self._buffer[-1] if self._buffer else None
        stats = {}
        if latest_snap:
            stats = {
                "ram": {"percent": latest_snap.ram_pct},
                "cpu": {"percent": latest_snap.cpu_pct},
                "disk": {"free_gb": latest_snap.disk_free_gb, "total_gb": 256.0},
                "net": {"ping_ms": latest_snap.net_ping_ms},
                "process_count": latest_snap.process_count,
            }
        return self.predictive_engine.calculate_health_score(
            stats=stats,
            leaks=self._last_leak_info,
            security_info=self._last_security_info,
            force_refresh=force_refresh
        )

    def get_autopilot_state(self):
        """Trả về trạng thái AutoPilotState từ PredictiveEngine."""
        latest_snap = self._buffer[-1] if self._buffer else None
        stats = {}
        if latest_snap:
            stats = {
                "ram": {"percent": latest_snap.ram_pct},
                "cpu": {"percent": latest_snap.cpu_pct},
            }
        battery_pct = int(self._last_battery_info.get("percent", 100)) if self._last_battery_info else 100
        on_battery = not bool(self._last_battery_info.get("power_plugged", True)) if self._last_battery_info else False
        return self.predictive_engine.get_autopilot_state(
            current_stats=stats,
            on_battery=on_battery,
            battery_pct=battery_pct
        )

    # ------------------------------------------------------------------
    # Rule Engine (private)
    # ------------------------------------------------------------------

    def _run_rules(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        buf = list(self._buffer)

        if buf:
            results += self._rule_ram(buf)
            results += self._rule_cpu(buf)
            results += self._rule_disk(buf)
            results += self._rule_network(buf)

        results += self._rule_battery()
        results += self._rule_security()
        results += self._rule_memory_leak()
        results += self._rule_cleanup_timing()
        results += self._rule_services()
        results += self._rule_uninstaller()
        results += self._rule_winsxs()
        results += self._rule_predictive_disk()
        results += self._rule_predictive_habit()
        results += self._rule_process_anomalies()

        return results

    # --- RAM ---
    def _rule_ram(self, buf: List[_Snapshot]) -> List[Suggestion]:
        recent = buf[-10:]  # 10 mẫu gần nhất (~8 giây)
        if not recent:
            return []
        avg_ram = sum(s.ram_pct for s in recent) / len(recent)
        sustained_high = all(s.ram_pct >= 85 for s in recent)
        results = []

        if sustained_high:
            results.append(Suggestion(
                category=CATEGORY_RAM,
                priority=PRIORITY_CRITICAL,
                title="RAM quá tải nghiêm trọng (>85% liên tục)",
                detail=(
                    f"RAM trung bình {avg_ram:.1f}% trong 8 giây qua. "
                    "Hệ thống đang dùng bộ nhớ ảo (pagefile) làm chậm máy đáng kể. "
                    "Khuyến nghị tối ưu RAM ngay để giải phóng bộ nhớ."
                ),
                action_key="optimize_ram",
                action_label="Tối Ưu RAM Ngay",
            ))
        elif avg_ram >= 75:
            results.append(Suggestion(
                category=CATEGORY_RAM,
                priority=PRIORITY_WARNING,
                title=f"RAM cao ({avg_ram:.0f}%) – Cần theo dõi",
                detail=(
                    f"RAM đang ở mức {avg_ram:.1f}%. Nếu tiếp tục tăng, "
                    "hiệu năng sẽ bị ảnh hưởng. Có thể tối ưu RAM để cải thiện."
                ),
                action_key="optimize_ram",
                action_label="Tối Ưu RAM",
            ))
        return results

    # --- CPU ---
    def _rule_cpu(self, buf: List[_Snapshot]) -> List[Suggestion]:
        recent = buf[-15:]  # ~12 giây
        if not recent:
            return []
        avg_cpu = sum(s.cpu_pct for s in recent) / len(recent)
        results = []

        if avg_cpu >= 80:
            results.append(Suggestion(
                category=CATEGORY_CPU,
                priority=PRIORITY_WARNING,
                title=f"CPU tải cao ({avg_cpu:.0f}%) – Kiểm tra tiến trình",
                detail=(
                    f"CPU trung bình {avg_cpu:.1f}% trong 12 giây. "
                    "Có thể có tiến trình nền ngốn tài nguyên. "
                    "Mở tab Tiến Trình để xem và dừng các process không cần thiết."
                ),
                action_key="open_process_tab",
                action_label="Xem Tiến Trình",
            ))
        elif avg_cpu >= 60:
            results.append(Suggestion(
                category=CATEGORY_CPU,
                priority=PRIORITY_TIP,
                title=f"CPU ở mức trung bình ({avg_cpu:.0f}%)",
                detail=(
                    "CPU đang hoạt động ổn định. "
                    "Nếu không chạy tác vụ nặng, có thể có phần mềm nền hoạt động không cần thiết."
                ),
                action_key=None,
            ))
        return results

    # --- DISK ---
    def _rule_disk(self, buf: List[_Snapshot]) -> List[Suggestion]:
        if not buf:
            return []
        latest = buf[-1]
        results = []

        if latest.disk_free_gb < 5:
            results.append(Suggestion(
                category=CATEGORY_DISK,
                priority=PRIORITY_CRITICAL,
                title=f"Ổ C: chỉ còn {latest.disk_free_gb:.1f} GB – Khẩn cấp!",
                detail=(
                    f"Ổ đĩa C: chỉ còn {latest.disk_free_gb:.1f} GB. "
                    "Windows cần ít nhất 10 GB để hoạt động ổn định. "
                    "Dọn rác ngay để tránh hệ thống bị treo."
                ),
                action_key="clean_junk",
                action_label="Dọn Rác Ngay",
            ))
        elif latest.disk_free_gb < 15:
            results.append(Suggestion(
                category=CATEGORY_DISK,
                priority=PRIORITY_WARNING,
                title=f"Ổ C: sắp đầy ({latest.disk_free_gb:.1f} GB còn trống)",
                detail=(
                    f"Ổ đĩa C: còn {latest.disk_free_gb:.1f} GB. "
                    "Nên dọn rác và kiểm tra file lớn để tránh hết dung lượng."
                ),
                action_key="clean_junk",
                action_label="Dọn Rác",
            ))
        return results

    # --- NETWORK ---
    def _rule_network(self, buf: List[_Snapshot]) -> List[Suggestion]:
        results = []
        recent = buf[-5:]
        if len(recent) >= 3:
            missing_tail = recent[-3:]
            if all(s.net_ping_ms <= 0 and s.net_ping_measured for s in missing_tail):
                results.append(Suggestion(
                    category=CATEGORY_NETWORK,
                    priority=PRIORITY_WARNING,
                    title="Không đo được Ping – mạng có thể bị lỗi",
                    detail=(
                        "Độ trễ mạng không đo được (timeout / unreachable). "
                        "Ứng dụng sẽ tự kiểm tra card mạng, DNS, gateway rồi làm mới DNS cache. "
                        "Bạn cũng có thể bấm để chạy kiểm tra & sửa ngay."
                    ),
                    action_key="repair_network_now",
                    action_label="Kiểm Tra & Sửa Mạng",
                ))
                return results

        recent_pings = [s.net_ping_ms for s in recent if s.net_ping_ms > 0]
        if not recent_pings:
            return results
        avg_ping = sum(recent_pings) / len(recent_pings)

        if avg_ping > 200:
            results.append(Suggestion(
                category=CATEGORY_NETWORK,
                priority=PRIORITY_WARNING,
                title=f"Độ trễ mạng cao ({avg_ping:.0f} ms)",
                detail=(
                    f"Ping trung bình {avg_ping:.0f} ms. "
                    "Thử đổi sang DNS nhanh hơn (Google 8.8.8.8 / Cloudflare 1.1.1.1) "
                    "để cải thiện tốc độ browsing và gaming."
                ),
                action_key="open_network_dialog",
                action_label="Tối Ưu Mạng",
            ))
        elif avg_ping > 100:
            results.append(Suggestion(
                category=CATEGORY_NETWORK,
                priority=PRIORITY_TIP,
                title=f"Ping ở mức trung bình ({avg_ping:.0f} ms)",
                detail=(
                    "Có thể cải thiện tốc độ mạng bằng cách đổi DNS "
                    "hoặc flush DNS cache."
                ),
                action_key="open_network_dialog",
                action_label="Xem Tùy Chọn Mạng",
            ))
        return results

    # --- BATTERY ---
    def _rule_battery(self) -> List[Suggestion]:
        batt = self._last_battery_info
        if not batt:
            return []
        results = []

        wear = batt.get("wear_level_pct", 0)
        cycles = batt.get("cycle_count", 0)

        if wear > 40:
            results.append(Suggestion(
                category=CATEGORY_BATTERY,
                priority=PRIORITY_WARNING,
                title=f"Pin đã hao mòn {wear:.1f}% – Cần kiểm tra",
                detail=(
                    f"Pin đã qua {cycles} chu kỳ sạc và hao mòn {wear:.1f}%. "
                    "Dung lượng thực giảm đáng kể. Hãy bật Battery Care Mode "
                    "và tránh để pin dưới 20% thường xuyên."
                ),
                action_key="open_hardware_dialog",
                action_label="Xem Chi Tiết Pin",
            ))
        elif wear > 20:
            results.append(Suggestion(
                category=CATEGORY_BATTERY,
                priority=PRIORITY_TIP,
                title=f"Pin hao mòn {wear:.1f}% – Theo dõi thêm",
                detail=(
                    f"Pin đã qua {cycles} chu kỳ sạc. "
                    "Để kéo dài tuổi thọ, tránh sạc đầy 100% liên tục, "
                    "giữ pin ở mức 20–80%."
                ),
                action_key="open_hardware_dialog",
                action_label="Xem Sức Khỏe Pin",
            ))
        return results

    # --- SECURITY ---
    def _rule_security(self) -> List[Suggestion]:
        sec = self._last_security_info
        if not sec:
            # Đọc từ config.json nếu chưa có
            sec = self._load_last_security_from_config()
        if not sec:
            return []
        results = []

        critical_count = sec.get("critical_count", 0)
        warning_count  = sec.get("warning_count", 0)
        overall        = sec.get("overall", "SAFE")
        timestamp      = sec.get("timestamp", "")

        if critical_count > 0:
            results.append(Suggestion(
                category=CATEGORY_SECURITY,
                priority=PRIORITY_CRITICAL,
                title=f"Phát hiện {critical_count} vấn đề bảo mật nghiêm trọng!",
                detail=(
                    f"Quét bảo mật ({timestamp}) phát hiện {critical_count} lỗi nghiêm trọng "
                    f"và {warning_count} cảnh báo. Cần kiểm tra và xử lý ngay."
                ),
                action_key="open_security_dialog",
                action_label="Xem Báo Cáo Bảo Mật",
            ))
        elif warning_count > 0:
            results.append(Suggestion(
                category=CATEGORY_SECURITY,
                priority=PRIORITY_WARNING,
                title=f"Có {warning_count} cảnh báo bảo mật",
                detail=(
                    f"Quét bảo mật ({timestamp}) phát hiện {warning_count} điểm cần lưu ý. "
                    "Nên xem lại báo cáo để đảm bảo an toàn hệ thống."
                ),
                action_key="open_security_dialog",
                action_label="Xem Cảnh Báo",
            ))
        return results

    # --- MEMORY LEAK ---
    def _rule_memory_leak(self) -> List[Suggestion]:
        leaks = self._last_leak_info
        if not leaks:
            return []
        results = []
        for leak in leaks[:3]:  # Tối đa 3 cảnh báo leak
            name   = leak.get("name", "Unknown")
            growth = leak.get("growth_mb", 0)
            cur    = leak.get("current_mb", 0)
            results.append(Suggestion(
                category=CATEGORY_PROCESS,
                priority=PRIORITY_WARNING,
                title=f"Tiến trình '{name}' có dấu hiệu rò rỉ RAM",
                detail=(
                    f"'{name}' đang dùng {cur:.0f} MB RAM và tăng liên tục "
                    f"+{growth:.0f} MB. Nên khởi động lại tiến trình này."
                ),
                action_key="open_process_tab",
                action_label="Xem Tiến Trình",
            ))
        return results

    # --- CLEANUP TIMING ---
    def _parse_history_ts(self, record: Dict) -> float:
        """Parse timestamp từ record lịch sử ra Unix epoch time (giây)."""
        if "ts" in record:
            try:
                return float(record["ts"])
            except (ValueError, TypeError):
                pass
        ts_str = record.get("timestamp", "")
        if ts_str:
            from datetime import datetime
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(ts_str, fmt).timestamp()
                except ValueError:
                    continue
        return 0.0

    def _rule_cleanup_timing(self) -> List[Suggestion]:
        """Phân tích lịch sử dọn rác để gợi ý thời điểm tối ưu."""
        try:
            history = self._load_cleanup_history()
            if not history:
                # Chưa từng dọn → gợi ý dọn ngay
                return [Suggestion(
                    category=CATEGORY_CLEANUP,
                    priority=PRIORITY_TIP,
                    title="Chưa có lần dọn rác nào được ghi nhận",
                    detail=(
                        "Hãy thực hiện dọn dẹp hệ thống lần đầu để kiểm tra "
                        "dung lượng rác đang chiếm. Click '1-Click Dọn Dẹp' trên Dashboard."
                    ),
                    action_key="clean_junk",
                    action_label="Dọn Rác Ngay",
                )]

            # Kiểm tra lần cuối dọn rác
            timestamps = [self._parse_history_ts(h) for h in history]
            latest_ts = max(timestamps, default=0.0)
            if latest_ts <= 0:
                # Có bản ghi trong history nhưng không parse được thời gian -> coi như đã từng dọn
                return []

            hours_since = (time.time() - latest_ts) / 3600
            if hours_since > 168:  # > 7 ngày
                days = max(1, int(hours_since / 24))
                return [Suggestion(
                    category=CATEGORY_CLEANUP,
                    priority=PRIORITY_TIP,
                    title=f"Đã {days} ngày chưa dọn rác",
                    detail=(
                        f"Lần dọn rác gần nhất cách đây {days} ngày. "
                        "Rác hệ thống có thể đã tích lũy đáng kể. "
                        "Khuyến nghị dọn định kỳ mỗi 3-7 ngày."
                    ),
                    action_key="clean_junk",
                    action_label="Dọn Rác Ngay",
                )]
        except Exception:
            pass
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _default_config_path(self) -> str:
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "config.json")

    def _load_cleanup_history(self) -> List[Dict]:
        if self._config_manager is not None:
            return self._config_manager.get("history", [])
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("history", [])
        except Exception:
            return []

    def _load_last_security_from_config(self) -> Dict[str, Any]:
        if self._config_manager is not None:
            return self._config_manager.get("last_security_scan_result", {})
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg.get("last_security_scan_result", {})
        except Exception:
            return {}

    # --- SERVICES & CONTEXT MENU ---
    def _rule_services(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        try:
            from core.service_optimizer import ServiceOptimizer
            candidates = ServiceOptimizer.get_services(only_candidates=True)
            if candidates:
                candidate_names = [c.name for c in candidates[:3]]
                names_str = ", ".join(candidate_names)
                has_critical = any(c.name.lower() in ("diagtrack", "sysmain") for c in candidates)
                results.append(Suggestion(
                    category=CATEGORY_SERVICES,
                    priority=PRIORITY_WARNING if has_critical else PRIORITY_TIP,
                    title=f"Phát hiện {len(candidates)} dịch vụ Windows có thể tối ưu",
                    detail=(
                        f"Các dịch vụ như {names_str}... đang tự động chạy ngầm. "
                        "Tối ưu các dịch vụ này để giảm tải CPU/Disk và bảo vệ quyền riêng tư."
                    ),
                    action_key="open_services_dialog",
                    action_label="Tối Ưu Dịch Vụ",
                ))
        except Exception:
            pass

        try:
            from core.context_menu_manager import ContextMenuManager
            menu_summary = ContextMenuManager.get_summary()
            orphans = menu_summary.get("orphan", 0)
            if orphans > 0:
                results.append(Suggestion(
                    category=CATEGORY_SERVICES,
                    priority=PRIORITY_TIP,
                    title=f"Có {orphans} mục menu chuột phải mồ côi (file bị xóa)",
                    detail=(
                        f"Phát hiện {orphans} menu chuột phải của các phần mềm đã gỡ cài đặt nhưng vẫn còn sót lại trong Registry. "
                        "Dọn dẹp chúng để File Explorer phản hồi nhanh hơn khi nhấp chuột phải."
                    ),
                    action_key="open_services_dialog",
                    action_label="Dọn Menu Chuột Phải",
                ))
        except Exception:
            pass

        return results

    # --- UNINSTALLER & BLOATWARE ---
    def _rule_uninstaller(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        try:
            from core.uninstaller_manager import UninstallerManager
            bloat = UninstallerManager.get_bloatware_apps()
            if bloat:
                results.append(Suggestion(
                    category=CATEGORY_UNINSTALLER,
                    priority=PRIORITY_TIP,
                    title=f"Phát hiện {len(bloat)} ứng dụng Bloatware Windows có thể gỡ bỏ",
                    detail=(
                        f"Windows đang cài sẵn {len(bloat)} ứng dụng rác (như {bloat[0].name}...). "
                        "Gỡ bỏ các ứng dụng không dùng giúp giải phóng bộ nhớ và giảm tiến trình ngầm."
                    ),
                    action_key="open_uninstaller_dialog",
                    action_label="Gỡ Bloatware",
                ))

            summary = UninstallerManager.get_summary()
            largest_size = summary.get("largest_size_mb", 0)
            largest_name = summary.get("largest_name", "")
            if largest_size >= 3000:
                results.append(Suggestion(
                    category=CATEGORY_UNINSTALLER,
                    priority=PRIORITY_TIP,
                    title=f"Ứng dụng dung lượng lớn: {largest_name} ({largest_size/1024:.1f} GB)",
                    detail=(
                        f"Phần mềm '{largest_name}' đang chiếm tới {largest_size/1024:.1f} GB dung lượng ổ đĩa. "
                        "Nếu không còn nhu cầu sử dụng, bạn có thể gỡ bỏ tận gốc qua Trình Gỡ Cài Đặt."
                    ),
                    action_key="open_uninstaller_dialog",
                    action_label="Quản Lý Ứng Dụng",
                ))
        except Exception:
            pass

        return results

    # --- WINSXS & UPDATE CACHE ---
    def _rule_winsxs(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        try:
            from core.winsxs_cleaner import WinSxSCleaner
            # Background rule: use cached scan (CACHE_TTL). Do not force-refresh
            # here — AI badge / dialog auto-refresh every ~10s would flood I/O.
            summary = WinSxSCleaner.get_summary()
            cache_mb = summary.get("total_cache_mb", 0.0)
            dup_drivers = summary.get("duplicate_drivers_count", 0)

            if cache_mb >= 300:
                results.append(Suggestion(
                    category=CATEGORY_WINSXS,
                    priority=PRIORITY_WARNING if cache_mb >= 1024 else PRIORITY_TIP,
                    title=f"Bộ đệm cập nhật & Servicing Logs lớn: {cache_mb:.1f} MB",
                    detail=(
                        f"Phát hiện {cache_mb:.1f} MB tệp đệm tải về của Windows Update và nhật ký CBS/DISM. "
                        "Dọn dẹp các tệp này giúp giải phóng dung lượng quý giá trên ổ C: mà không ảnh hưởng hệ điều hành."
                    ),
                    action_key="open_winsxs_dialog",
                    action_label="Dọn Bộ Đệm Cập Nhật",
                ))

            cleanable_drivers = summary.get("cleanable_drivers_count", 0)
            if cleanable_drivers >= 3:
                results.append(Suggestion(
                    category=CATEGORY_WINSXS,
                    priority=PRIORITY_TIP,
                    title=f"Phát hiện {cleanable_drivers} phiên bản Driver cũ có thể dọn dẹp",
                    detail=(
                        f"Kho DriverStore đang lưu {cleanable_drivers} gói Driver OEM phiên bản cũ không còn thiết bị nào sử dụng. "
                        "Dọn dẹp các driver này giúp giải phóng dung lượng thư mục FileRepository."
                    ),
                    action_key="open_winsxs_dialog",
                    action_label="Dọn DriverStore",
                ))
        except Exception:
            pass

        return results

    # --- PREDICTIVE AI: DISK EXHAUSTION ---
    def _rule_predictive_disk(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        try:
            from core.predictive_ai import STATUS_CRITICAL_DEPLETION, STATUS_WARNING_DEPLETION
            forecast = self.predictive_engine.get_disk_forecast()
            if forecast.trend_status == STATUS_CRITICAL_DEPLETION and forecast.days_until_exhaustion is not None:
                results.append(Suggestion(
                    category=CATEGORY_PREDICTIVE,
                    priority=PRIORITY_CRITICAL,
                    title=f"Dự Báo: Ổ {forecast.drive_letter} sẽ đầy trong ~{forecast.days_until_exhaustion:.0f} ngày!",
                    detail=(
                        f"{forecast.summary_text} Tốc độ tiêu thụ ghi nhận ~{forecast.daily_burn_rate_gb:.2f} GB/ngày. "
                        "Hệ thống đang tích tụ rác và bộ đệm quá nhanh, cần dọn WinSxS hoặc rác ngay."
                    ),
                    action_key="open_winsxs_dialog",
                    action_label="Dọn Sâu WinSxS",
                ))
            elif forecast.trend_status == STATUS_WARNING_DEPLETION and forecast.days_until_exhaustion is not None:
                results.append(Suggestion(
                    category=CATEGORY_PREDICTIVE,
                    priority=PRIORITY_WARNING,
                    title=f"Dự Báo: Ổ {forecast.drive_letter} có xu hướng đầy sau ~{forecast.days_until_exhaustion:.0f} ngày",
                    detail=(
                        f"{forecast.summary_text} Tốc độ tiêu thụ bình quân ~{forecast.daily_burn_rate_gb:.2f} GB/ngày. "
                        "Khuyến nghị kích hoạt dọn rác định kỳ để duy trì dung lượng trống an toàn."
                    ),
                    action_key="clean_junk",
                    action_label="Dọn Rác Hệ Thống",
                ))
        except Exception:
            pass
        return results

    # --- PREDICTIVE AI: USAGE HABIT LEARNING ---
    def _rule_predictive_habit(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        try:
            buf = list(self._buffer)
            current_cpu = buf[-1].cpu_pct if buf else 0.0
            current_ram = buf[-1].ram_pct if buf else 0.0
            bat_info = self._last_battery_info or {}
            on_battery = not bat_info.get("power_plugged", True)
            bat_pct = int(bat_info.get("percent", 100))

            habit = self.predictive_engine.get_habit_profile(
                current_cpu=current_cpu,
                current_ram=current_ram,
                on_battery=on_battery,
                battery_pct=bat_pct
            )

            if habit.recommended_mode == "game_boost":
                results.append(Suggestion(
                    category=CATEGORY_PREDICTIVE,
                    priority=PRIORITY_WARNING,
                    title=f"AI Nhận Diện: {habit.predicted_workload} – Đề xuất Game Boost",
                    detail=(
                        f"{habit.reason} Kích hoạt Game Boost sẽ tự động tối ưu hóa tài nguyên CPU & RAM cho bạn."
                    ),
                    action_key="enable_game_boost",
                    action_label="Bật Game Boost",
                ))
            elif habit.recommended_mode == "battery_saver":
                results.append(Suggestion(
                    category=CATEGORY_PREDICTIVE,
                    priority=PRIORITY_WARNING,
                    title=f"AI Nhận Diện: {habit.predicted_workload} – Tiết kiệm pin",
                    detail=(
                        f"{habit.reason} Tối ưu hóa bộ nhớ và giảm tải nền giúp tiết kiệm 20-30% điện năng."
                    ),
                    action_key="optimize_ram",
                    action_label="Tối Ưu Pin & RAM",
                ))
            elif habit.recommended_mode == "eco_clean":
                results.append(Suggestion(
                    category=CATEGORY_PREDICTIVE,
                    priority=PRIORITY_TIP,
                    title=f"AI Đề Xuất: Thời Điểm Vàng Tối Ưu Nền ({habit.time_slot_label})",
                    detail=(
                        f"{habit.reason} Tối ưu RAM ngay bây giờ sẽ giúp giải phóng bộ nhớ đệm mà không hề gián đoạn công việc."
                    ),
                    action_key="optimize_ram",
                    action_label="Tối Ưu Nền Ngay",
                ))
        except Exception:
            pass
        return results

    # --- PREDICTIVE AI: PROCESS ANOMALIES (Z-SCORE) ---
    def _rule_process_anomalies(self) -> List[Suggestion]:
        results: List[Suggestion] = []
        try:
            anomalies = self.predictive_engine.detect_anomalies(limit=3)
            for a in anomalies:
                if a.risk_level in ("HIGH", "MEDIUM"):
                    prio = PRIORITY_CRITICAL if a.risk_level == "HIGH" else PRIORITY_WARNING
                    results.append(Suggestion(
                        category=CATEGORY_ANOMALY,
                        priority=prio,
                        title=f"Cảnh Báo Bất Thường: {a.name} (Z-Score: {max(a.ram_z_score, a.cpu_z_score):.1f})",
                        detail=(
                            f"Tiến trình {a.name} (PID: {a.pid}) chiếm {a.ram_mb:.0f} MB RAM và {a.cpu_percent:.1f}% CPU. "
                            f"Lý do: {a.anomaly_reason}. Nếu đây là ứng dụng quen thuộc bạn đang chạy, hãy nhấn 'Tin Cậy' để đưa vào Whitelist."
                        ),
                        action_key=f"whitelist_proc:{a.name}",
                        action_label=f"🛡️ Tin Cậy {a.name}",
                    ))
        except Exception:
            pass
        return results

