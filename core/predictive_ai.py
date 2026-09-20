"""
core/predictive_ai.py – Predictive AI & Anomaly Detection Engine (v3.8 Pro)
==========================================================================
Engine trí tuệ nhân tạo dự đoán xu hướng hệ thống và phát hiện bất thường:
  1. Disk Exhaustion Forecaster: Phân tích chuỗi thời gian (time-series slope/burn rate),
     ước tính số ngày còn lại trước khi ổ C đầy, cảnh báo sớm.
  2. Diurnal Habit Learner: Phân tích tải hệ thống theo khung giờ (Sáng, Chiều, Tối, Đêm),
     học thói quen sử dụng và tự động đề xuất chế độ (Game Boost, Cân Bằng, Tiết Kiệm Pin).
  3. Process Anomaly Detector: Tính toán Z-Score thống kê (Z = (x - mean) / stdev)
     phát hiện các tiến trình chạy ngầm bất thường, ngốn RAM/CPU đột biến hoặc rò rỉ.

Hoàn toàn offline, nhẹ nhàng, tốc độ cao (<5ms), không phụ thuộc thư viện ngoài.
"""
from __future__ import annotations

import os
import sys
import time
import math
import statistics
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import psutil

from core.logger import logger
from core.process_manager import PROTECTED_PROCESSES


# ---------------------------------------------------------------------------
# Constants & Enums
# ---------------------------------------------------------------------------

STATUS_CRITICAL_DEPLETION = "CRITICAL_DEPLETION"  # < 7 ngày
STATUS_WARNING_DEPLETION  = "WARNING_DEPLETION"   # < 14 ngày
STATUS_STABLE             = "STABLE"              # Ổn định
STATUS_HEALTHY_EXPANDING  = "HEALTHY_EXPANDING"   # Đang tăng dung lượng trống

SLOT_MORNING   = "morning"    # 06:00 - 12:00
SLOT_AFTERNOON = "afternoon"  # 12:00 - 18:00
SLOT_EVENING   = "evening"    # 18:00 - 23:00
SLOT_NIGHT     = "night"      # 23:00 - 06:00

SLOT_LABELS = {
    SLOT_MORNING:   "Buổi Sáng (06:00 - 12:00)",
    SLOT_AFTERNOON: "Buổi Chiều (12:00 - 18:00)",
    SLOT_EVENING:   "Buổi Tối (18:00 - 23:00)",
    SLOT_NIGHT:     "Ban Đêm (23:00 - 06:00)",
}

KNOWN_SAFE_PROCESSES = {
    # IDEs, Trình soạn thảo mã nguồn & Công cụ lập trình
    "antigravity ide.exe", "antigravity.exe", "cursor.exe", "windsurf.exe",
    "code.exe", "pycharm64.exe", "idea64.exe", "devenv.exe", "studio64.exe",
    "eclipse.exe", "sublime_text.exe", "notepad++.exe", "rider64.exe",
    "webstorm64.exe", "clion64.exe", "rustrover64.exe", "goland64.exe", "datagrip64.exe",
    # Trình duyệt web
    "chrome.exe", "firefox.exe", "msedge.exe", "brave.exe", "opera.exe", "vivaldi.exe", "tor.exe",
    # Ứng dụng liên lạc, văn phòng & đa phương tiện
    "discord.exe", "telegram.exe", "zalo.exe", "slack.exe", "teams.exe", "spotify.exe",
    # Nền tảng game & launcher
    "steam.exe", "epicgameslauncher.exe", "riotclientservices.exe",
    # Môi trường phát triển & runtimes
    "python.exe", "pythonw.exe", "node.exe", "git.exe", "docker desktop.exe"
}


MODE_GAMING   = "GAMING"
MODE_WORK     = "WORK"
MODE_ECO      = "ECO"
MODE_QUIET    = "QUIET"
MODE_BALANCED = "BALANCED"

KNOWN_GAME_PROCESSES = {
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "riotclientservices.exe",
    "leagueclient.exe", "leagueclientux.exe", "valorant.exe", "cs2.exe", "dota2.exe",
    "genshinimpact.exe", "starrail.exe", "robloxplayerbeta.exe", "minecraft.exe",
    "gta5.exe", "fifa.exe", "fc24.exe", "fc25.exe", "pubg.exe", "tslgame.exe",
    "overwatch.exe", "apex.exe", "r5apex.exe", "eldenring.exe", "cyberpunk2077.exe"
}

KNOWN_WORK_PROCESSES = {
    "antigravity ide.exe", "antigravity.exe", "code.exe", "cursor.exe", "windsurf.exe",
    "pycharm64.exe", "idea64.exe", "devenv.exe", "studio64.exe", "photoshop.exe",
    "illustrator.exe", "premiere.exe", "afterfx.exe", "blender.exe", "autocad.exe",
    "figma.exe", "excel.exe", "winword.exe", "powerpnt.exe"
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class AIHealthReport:
    """Báo cáo chỉ số sức khỏe hệ thống toàn diện 0 - 100 điểm."""
    score: int = 100
    grade: str = "XUẤT SẮC"
    grade_color: str = "#3fb950"
    summary_text: str = ""
    breakdown: Dict[str, int] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    prescription: List[Dict[str, Any]] = field(default_factory=list)
    predicted_score_after: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "grade_color": self.grade_color,
            "summary_text": self.summary_text,
            "breakdown": self.breakdown,
            "issues": self.issues,
            "prescription": self.prescription,
            "predicted_score_after": self.predicted_score_after,
        }


@dataclass
class AutoPilotState:
    """Trạng thái chế độ thích ứng ngữ cảnh tự động."""
    mode: str = MODE_BALANCED
    label: str = "Chế Độ Cân Bằng"
    icon: str = "⚖️"
    badge_text: str = "⚖️ AI Auto-Pilot: Cân Bằng"
    description: str = ""
    active_process: Optional[str] = None
    recommended_tuning: List[str] = field(default_factory=list)
    is_auto_applied: bool = False
    applied_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "label": self.label,
            "icon": self.icon,
            "badge_text": self.badge_text,
            "description": self.description,
            "active_process": self.active_process,
            "recommended_tuning": self.recommended_tuning,
            "is_auto_applied": self.is_auto_applied,
            "applied_actions": list(self.applied_actions),
        }


@dataclass
class DiskForecast:
    """Kết quả dự báo dung lượng ổ đĩa."""
    drive_letter: str = "C:"
    current_free_gb: float = 0.0
    total_gb: float = 0.0
    free_percent: float = 0.0
    daily_burn_rate_gb: float = 0.0        # GB/ngày (dương = tiêu hao, âm = được giải phóng)
    days_until_exhaustion: Optional[float] = None  # None = không có nguy cơ đầy
    trend_status: str = STATUS_STABLE
    summary_text: str = ""
    confidence_score: float = 0.85          # 0.0 -> 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drive_letter": self.drive_letter,
            "current_free_gb": self.current_free_gb,
            "total_gb": self.total_gb,
            "free_percent": self.free_percent,
            "daily_burn_rate_gb": self.daily_burn_rate_gb,
            "days_until_exhaustion": self.days_until_exhaustion,
            "trend_status": self.trend_status,
            "summary_text": self.summary_text,
            "confidence_score": self.confidence_score,
        }


@dataclass
class UsageHabit:
    """Mô hình thói quen sử dụng máy tính theo khung giờ."""
    current_time_slot: str = SLOT_AFTERNOON
    time_slot_label: str = ""
    predicted_workload: str = "Làm Việc / Cân Bằng"
    confidence: float = 0.85
    recommended_mode: str = "balanced"  # game_boost, balanced, battery_saver, eco_clean
    recommended_mode_label: str = "Chế Độ Cân Bằng"
    reason: str = ""
    slot_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_time_slot": self.current_time_slot,
            "time_slot_label": self.time_slot_label,
            "predicted_workload": self.predicted_workload,
            "confidence": self.confidence,
            "recommended_mode": self.recommended_mode,
            "recommended_mode_label": self.recommended_mode_label,
            "reason": self.reason,
            "slot_stats": self.slot_stats,
        }


@dataclass
class ProcessAnomaly:
    """Tiến trình có biểu hiện bất thường thống kê (Outlier / Runaway)."""
    pid: int
    name: str
    cpu_percent: float
    ram_mb: float
    ram_z_score: float
    cpu_z_score: float
    anomaly_score: float  # 0.0 -> 100.0
    risk_level: str       # HIGH, MEDIUM, LOW
    anomaly_reason: str
    is_system_protected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "cpu_percent": self.cpu_percent,
            "ram_mb": self.ram_mb,
            "ram_z_score": self.ram_z_score,
            "cpu_z_score": self.cpu_z_score,
            "anomaly_score": self.anomaly_score,
            "risk_level": self.risk_level,
            "anomaly_reason": self.anomaly_reason,
            "is_system_protected": self.is_system_protected,
        }


# ---------------------------------------------------------------------------
# 1. Disk Exhaustion Forecaster
# ---------------------------------------------------------------------------

class DiskForecaster:
    """
    Thuật toán dự báo cạn kiệt dung lượng ổ cứng (Time-series Regression Forecaster).
    Lưu trữ lịch sử dung lượng trống và tính toán tốc độ tiêu hao thực tế (GB/ngày).
    """

    def __init__(self, config_manager: Optional[Any] = None):
        self.config_manager = config_manager
        self._history: List[Dict[str, Any]] = []
        self._load_history()

    def _load_history(self):
        if self.config_manager:
            raw = self.config_manager.get("predictive_disk_history", [])
            if isinstance(raw, list):
                self._history = raw[-100:]  # Giữ tối đa 100 điểm gần nhất

    def _save_history(self):
        if self.config_manager:
            self.config_manager.set("predictive_disk_history", self._history[-100:])

    def record_sample(self, free_gb: float, total_gb: float, ts: Optional[float] = None) -> None:
        """Ghi nhận một mẫu dung lượng ổ C."""
        now = ts or time.time()
        # Tránh ghi liên tục nếu mẫu trước đó cách dưới 10 phút và dung lượng không đổi
        if self._history:
            last = self._history[-1]
            if now - last.get("ts", 0) < 600 and abs(last.get("free_gb", 0) - free_gb) < 0.05:
                return

        self._history.append({
            "ts": now,
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2)
        })
        self._save_history()

    def calculate_forecast(self, drive_letter: str = "C:", auto_record: bool = True) -> DiskForecast:
        """
        Tính toán dự báo xu hướng tiêu hao và số ngày còn lại trước khi đầy ổ đĩa.
        """
        # Lấy thông số ổ đĩa thực tế hiện tại
        try:
            path = drive_letter if drive_letter.endswith(("\\", "/")) else f"{drive_letter}\\"
            usage = psutil.disk_usage(path)
            total_gb = usage.total / (1024 ** 3)
            free_gb  = usage.free / (1024 ** 3)
            free_pct = (free_gb / total_gb * 100.0) if total_gb > 0 else 0.0
        except Exception:
            total_gb = 256.0
            free_gb  = 35.0
            free_pct = 13.6

        # Ghi nhận mẫu hiện tại nếu bật auto_record
        if auto_record:
            self.record_sample(free_gb, total_gb)
        elif self._history:
            free_gb = self._history[-1]["free_gb"]
            total_gb = self._history[-1].get("total_gb", total_gb)
            free_pct = (free_gb / total_gb * 100.0) if total_gb > 0 else 0.0

        # Nếu chưa đủ 2 điểm dữ liệu, tạo dự báo sơ bộ dựa trên dung lượng hiện hữu
        if len(self._history) < 2:
            return self._fallback_forecast(drive_letter, free_gb, total_gb, free_pct)

        # Lọc các điểm dữ liệu liên tiếp trong cửa sổ hồi quy
        # Bỏ qua các bước nhảy dương lớn (do người dùng dọn dẹp)
        valid_points: List[Tuple[float, float]] = []  # (days_from_start, free_gb)
        first_ts = self._history[0]["ts"]

        for item in self._history:
            t = (item["ts"] - first_ts) / 86400.0  # chuyển sang đơn vị Ngày
            valid_points.append((t, item["free_gb"]))

        span_days = valid_points[-1][0] - valid_points[0][0]

        # Nếu span thời gian quá ngắn (< 0.05 ngày ~ 1.2 giờ), ước tính theo tốc độ vi sai
        if span_days < 0.05 or len(valid_points) < 3:
            return self._fallback_forecast(drive_letter, free_gb, total_gb, free_pct)

        # Tính toán độ dốc (Slope) qua hồi quy tuyến tính: y = m*x + b
        # y: free_gb, x: days
        n = len(valid_points)
        sum_x = sum(p[0] for p in valid_points)
        sum_y = sum(p[1] for p in valid_points)
        sum_xx = sum(p[0] ** 2 for p in valid_points)
        sum_xy = sum(p[0] * p[1] for p in valid_points)

        denom = n * sum_xx - sum_x ** 2
        if abs(denom) < 1e-6:
            slope = 0.0
        else:
            slope = (n * sum_xy - sum_x * sum_y) / denom

        # slope < 0 nghĩa là dung lượng trống đang giảm theo ngày
        # burn_rate = -slope (GB tiêu hao mỗi ngày)
        burn_rate = -slope

        if burn_rate > 0.05:  # Đang tiêu thụ trên 50MB/ngày
            days_left = max(0.5, round(free_gb / burn_rate, 1))
            if days_left <= 7.0 or free_gb < 10.0:
                status = STATUS_CRITICAL_DEPLETION
                summary = (
                    f"Cảnh báo khẩn: Ổ {drive_letter} đang tiêu hao ~{burn_rate:.2f} GB/ngày, "
                    f"dự kiến cạn kiệt trong {days_left:.1f} ngày! Hãy dọn dẹp ngay."
                )
            elif days_left <= 14.0 or free_gb < 20.0:
                status = STATUS_WARNING_DEPLETION
                summary = (
                    f"Ổ {drive_letter} đang tiêu thụ ~{burn_rate:.2f} GB/ngày, "
                    f"dự kiến đầy sau khoảng {days_left:.0f} ngày. Khuyến nghị dọn WinSxS & rác hệ thống."
                )
            else:
                status = STATUS_STABLE
                summary = (
                    f"Ổ {drive_letter} tiêu thụ trung bình {burn_rate:.2f} GB/ngày. "
                    f"Dự kiến còn an toàn trong hơn {days_left:.0f} ngày."
                )
            return DiskForecast(
                drive_letter=drive_letter,
                current_free_gb=round(free_gb, 2),
                total_gb=round(total_gb, 2),
                free_percent=round(free_pct, 1),
                daily_burn_rate_gb=round(burn_rate, 2),
                days_until_exhaustion=days_left,
                trend_status=status,
                summary_text=summary,
                confidence_score=min(0.95, 0.6 + 0.05 * len(valid_points)),
            )
        else:
            # Dung lượng đang tăng hoặc ổn định tuyệt đối
            return DiskForecast(
                drive_letter=drive_letter,
                current_free_gb=round(free_gb, 2),
                total_gb=round(total_gb, 2),
                free_percent=round(free_pct, 1),
                daily_burn_rate_gb=round(burn_rate, 2),
                days_until_exhaustion=None,
                trend_status=STATUS_HEALTHY_EXPANDING if burn_rate < -0.05 else STATUS_STABLE,
                summary_text=f"Dung lượng ổ {drive_letter} rất ổn định, không có nguy cơ đầy đĩa trong thời gian tới.",
                confidence_score=0.88,
            )

    def _fallback_forecast(self, drive: str, free_gb: float, total_gb: float, free_pct: float) -> DiskForecast:
        """Dự báo sơ bộ dựa trên dung lượng tuyệt đối khi mới cài đặt."""
        if free_gb < 10.0 or free_pct < 8.0:
            return DiskForecast(
                drive_letter=drive,
                current_free_gb=round(free_gb, 2),
                total_gb=round(total_gb, 2),
                free_percent=round(free_pct, 1),
                daily_burn_rate_gb=1.2,
                days_until_exhaustion=round(free_gb / 1.2, 1),
                trend_status=STATUS_CRITICAL_DEPLETION,
                summary_text=f"Ổ {drive} còn rất ít dung lượng trống ({free_gb:.1f} GB - {free_pct:.1f}%). Cần dọn rác khẩn cấp!",
                confidence_score=0.75,
            )
        elif free_gb < 25.0 or free_pct < 15.0:
            return DiskForecast(
                drive_letter=drive,
                current_free_gb=round(free_gb, 2),
                total_gb=round(total_gb, 2),
                free_percent=round(free_pct, 1),
                daily_burn_rate_gb=0.8,
                days_until_exhaustion=round(free_gb / 0.8, 1),
                trend_status=STATUS_WARNING_DEPLETION,
                summary_text=f"Ổ {drive} còn {free_gb:.1f} GB ({free_pct:.1f}%). Dự kiến có thể đầy trong khoảng 1 tháng.",
                confidence_score=0.70,
            )
        else:
            return DiskForecast(
                drive_letter=drive,
                current_free_gb=round(free_gb, 2),
                total_gb=round(total_gb, 2),
                free_percent=round(free_pct, 1),
                daily_burn_rate_gb=0.2,
                days_until_exhaustion=None,
                trend_status=STATUS_STABLE,
                summary_text=f"Ổ {drive} có {free_gb:.1f} GB trống ({free_pct:.1f}%). Trạng thái hoàn toàn khỏe mạnh.",
                confidence_score=0.80,
            )


# ---------------------------------------------------------------------------
# 2. Usage Habit Learner (Diurnal Time Slot Model)
# ---------------------------------------------------------------------------

class HabitLearner:
    """
    Mô hình học máy thói quen sử dụng máy tính theo 4 khung giờ trong ngày:
    Sáng, Chiều, Tối, Đêm. Tự động nhận diện nhu cầu làm việc hay chơi game.
    """

    _SAVE_INTERVAL_SEC = 30.0  # avoid rewriting config.json on every 800ms poll

    def __init__(self, config_manager: Optional[Any] = None):
        self.config_manager = config_manager
        self._profiles: Dict[str, Dict[str, Any]] = self._load_profiles()
        self._last_save_ts: float = 0.0

    def _load_profiles(self) -> Dict[str, Dict[str, Any]]:
        default_profiles = {
            SLOT_MORNING:   {"cpu_sum": 0.0, "ram_sum": 0.0, "samples": 0, "gaming_hits": 0},
            SLOT_AFTERNOON: {"cpu_sum": 0.0, "ram_sum": 0.0, "samples": 0, "gaming_hits": 0},
            SLOT_EVENING:   {"cpu_sum": 0.0, "ram_sum": 0.0, "samples": 0, "gaming_hits": 0},
            SLOT_NIGHT:     {"cpu_sum": 0.0, "ram_sum": 0.0, "samples": 0, "gaming_hits": 0},
        }
        if self.config_manager:
            stored = self.config_manager.get("predictive_habits_profile", {})
            if isinstance(stored, dict) and stored:
                for k in default_profiles:
                    if k in stored:
                        default_profiles[k].update(stored[k])
        return default_profiles

    def _save_profiles(self):
        if self.config_manager:
            self.config_manager.set("predictive_habits_profile", self._profiles)

    @staticmethod
    def get_current_slot(dt: Optional[datetime] = None) -> str:
        """Xác định khung giờ hiện tại."""
        now = dt or datetime.now()
        hour = now.hour
        if 6 <= hour < 12:
            return SLOT_MORNING
        elif 12 <= hour < 18:
            return SLOT_AFTERNOON
        elif 18 <= hour < 23:
            return SLOT_EVENING
        else:
            return SLOT_NIGHT

    def feed_sample(self, cpu_pct: float, ram_pct: float, has_game: bool = False):
        """Học một mẫu dữ liệu vào khung giờ hiện tại."""
        slot = self.get_current_slot()
        data = self._profiles[slot]
        data["cpu_sum"] += cpu_pct
        data["ram_sum"] += ram_pct
        data["samples"] += 1
        if has_game:
            data["gaming_hits"] += 1

        # Giữ mẫu trung bình trôi (EMA-like) khi vượt quá 500 mẫu
        if data["samples"] > 500:
            data["cpu_sum"] /= 2.0
            data["ram_sum"] /= 2.0
            data["samples"] = int(data["samples"] / 2)
            data["gaming_hits"] = int(data["gaming_hits"] / 2)

        now = time.time()
        if now - self._last_save_ts >= self._SAVE_INTERVAL_SEC:
            self._save_profiles()
            self._last_save_ts = now

    def analyze_current_habit(
        self,
        current_cpu: float = 0.0,
        current_ram: float = 0.0,
        on_battery: bool = False,
        battery_pct: int = 100
    ) -> UsageHabit:
        """
        Phân tích thói quen hiện tại và đề xuất chế độ hoạt động tối ưu.
        """
        slot = self.get_current_slot()
        slot_label = SLOT_LABELS.get(slot, "Không xác định")
        prof = self._profiles[slot]
        samples = max(1, prof.get("samples", 1))
        avg_cpu = prof.get("cpu_sum", 0.0) / samples
        avg_ram = prof.get("ram_sum", 0.0) / samples
        gaming_ratio = prof.get("gaming_hits", 0) / samples

        # Kiểm tra điều kiện Gaming / Tải nặng
        is_gaming_load = (current_cpu >= 55.0 or gaming_ratio >= 0.25) and (slot in (SLOT_EVENING, SLOT_NIGHT))

        # Kiểm tra điều kiện Pin / Di động
        if on_battery and battery_pct <= 40:
            return UsageHabit(
                current_time_slot=slot,
                time_slot_label=slot_label,
                predicted_workload="Làm Việc Di Động (Pin Yếu)",
                confidence=0.92,
                recommended_mode="battery_saver",
                recommended_mode_label="Tiết Kiệm Pin Tối Đa",
                reason=f"Máy đang dùng pin ({battery_pct}%). Nên tắt bớt hiệu ứng và hạ xung CPU.",
                slot_stats={"avg_cpu": round(avg_cpu, 1), "avg_ram": round(avg_ram, 1)}
            )

        if is_gaming_load or current_cpu >= 65.0:
            return UsageHabit(
                current_time_slot=slot,
                time_slot_label=slot_label,
                predicted_workload="Gaming / Đồ Họa Nặng",
                confidence=0.88,
                recommended_mode="game_boost",
                recommended_mode_label="Kích Hoạt Game Boost",
                reason=f"Phát hiện tải CPU cao ({current_cpu:.0f}%) vào {slot_label.lower()}. Kích hoạt Game Boost sẽ ưu tiên tối đa CPU & RAM.",
                slot_stats={"avg_cpu": round(avg_cpu, 1), "avg_ram": round(avg_ram, 1)}
            )

        if current_cpu <= 12.0 and current_ram <= 45.0:
            return UsageHabit(
                current_time_slot=slot,
                time_slot_label=slot_label,
                predicted_workload="Chế Độ Chờ / Nghỉ Ngơi",
                confidence=0.82,
                recommended_mode="eco_clean",
                recommended_mode_label="Dọn Dẹp Nền Eco",
                reason=f"Hệ thống đang rảnh rỗi. Đây là thời điểm vàng để dọn dẹp bộ nhớ đệm mà không ảnh hưởng công việc.",
                slot_stats={"avg_cpu": round(avg_cpu, 1), "avg_ram": round(avg_ram, 1)}
            )

        # Mặc định: Làm việc / Cân bằng
        return UsageHabit(
            current_time_slot=slot,
            time_slot_label=slot_label,
            predicted_workload="Làm Việc Văn Phòng / Lướt Web",
            confidence=0.85,
            recommended_mode="balanced",
            recommended_mode_label="Chế Độ Cân Bằng",
            reason=f"Hệ thống hoạt động ổn định trong {slot_label.lower()}. Duy trì giám sát tài nguyên tiêu chuẩn.",
            slot_stats={"avg_cpu": round(avg_cpu, 1), "avg_ram": round(avg_ram, 1)}
        )


# ---------------------------------------------------------------------------
# 3. Process Anomaly Detector (Z-Score & Outlier Engine)
# ---------------------------------------------------------------------------

class ProcessAnomalyDetector:
    """
    Phát hiện bất thường thống kê (Statistical Outlier & Anomaly Detection)
    dựa trên Z-Score chuẩn tắc: Z = (x - mean) / stdev.
    Bắt trọn các tiến trình chạy ngầm lạ, ngốn RAM/CPU đột biến hoặc runaway loops.
    """

    def __init__(self, config_manager: Optional[Any] = None):
        self.config_manager = config_manager

    def get_whitelist(self) -> set:
        if self.config_manager:
            return set(n.lower() for n in self.config_manager.get("process_whitelist", []))
        return set()

    def detect_anomalies(self, limit: int = 5) -> List[ProcessAnomaly]:
        """
        Quét và nhận diện các tiến trình bất thường trên toàn bộ hệ thống.
        """
        whitelist = self.get_whitelist()
        procs_data: List[Dict[str, Any]] = []

        # 1. Thu thập dữ liệu toàn bộ tiến trình
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
            try:
                info = p.info
                pid = info.get('pid', 0)
                name = (info.get('name') or f"proc_{pid}").lower()
                mem_info = info.get('memory_info')
                if not mem_info:
                    continue
                ram_mb = mem_info.rss / (1024 ** 2)
                cpu_pct = float(info.get('cpu_percent') or 0.0)

                procs_data.append({
                    "pid": pid,
                    "name": name,
                    "ram_mb": ram_mb,
                    "cpu_pct": cpu_pct,
                })
            except Exception:
                continue

        if len(procs_data) < 5:
            return []

        # 2. Tính toán thống kê hệ thống (Mean & Standard Deviation)
        ram_vals = [p["ram_mb"] for p in procs_data]
        cpu_vals = [p["cpu_pct"] for p in procs_data]

        mean_ram = statistics.mean(ram_vals)
        stdev_ram = statistics.stdev(ram_vals) if len(ram_vals) > 1 else 1.0
        stdev_ram = max(stdev_ram, 10.0)  # Ngưỡng epsilon tối thiểu

        mean_cpu = statistics.mean(cpu_vals)
        stdev_cpu = statistics.stdev(cpu_vals) if len(cpu_vals) > 1 else 1.0
        stdev_cpu = max(stdev_cpu, 1.0)

        anomalies: List[ProcessAnomaly] = []

        # 3. Tính Z-Score và lọc dị biệt
        for p in procs_data:
            name = p["name"]
            pid = p["pid"]
            is_protected = (name in PROTECTED_PROCESSES) or (pid in (0, 4))
            is_whitelisted = name in whitelist

            z_ram = (p["ram_mb"] - mean_ram) / stdev_ram
            z_cpu = (p["cpu_pct"] - mean_cpu) / stdev_cpu

            # Bỏ qua các ứng dụng hệ điều hành được bảo vệ hoặc trong whitelist
            if is_protected or is_whitelisted:
                continue

            # Nhận diện nếu là phần mềm quen thuộc (IDE, Trình duyệt, Trình soạn thảo)
            is_known_safe = (name in KNOWN_SAFE_PROCESSES) or any(
                k in name for k in ("ide", "studio", "code", "browser", "python")
            )

            is_anomaly = False
            reasons = []

            if is_known_safe:
                # Ứng dụng an toàn đã biết: Mức RAM 300MB - 1.5GB là hoàn toàn bình thường khi làm việc.
                # Chỉ cảnh báo nếu CPU bị nghẽn (runaway/treo máy >= 45%) hoặc RAM phình to bất thường (>3GB)
                if p["cpu_pct"] >= 45.0 and z_cpu >= 2.5:
                    is_anomaly = True
                    reasons.append(f"CPU bị nghẽn tải nặng ({p['cpu_pct']:.1f}%, Z={z_cpu:.1f})")
                elif p["ram_mb"] >= 3000.0 and z_ram >= 3.5:
                    is_anomaly = True
                    reasons.append(f"RAM phình to bất thường ({p['ram_mb']:.0f} MB, Z={z_ram:.1f})")
            else:
                # Tiến trình chạy ngầm lạ:
                if z_cpu >= 2.5 and p["cpu_pct"] >= 20.0:
                    is_anomaly = True
                    reasons.append(f"CPU tăng đột biến ({p['cpu_pct']:.1f}%, Z={z_cpu:.1f})")

                if z_ram >= 2.5 and p["ram_mb"] >= 500.0:
                    is_anomaly = True
                    reasons.append(f"RAM tiêu thụ bất thường ({p['ram_mb']:.0f} MB, Z={z_ram:.1f})")

                if z_cpu >= 1.8 and z_ram >= 1.8 and p["cpu_pct"] >= 12.0:
                    is_anomaly = True
                    reasons.append("Tiến trình lạ tiêu hao đồng thời cả CPU lẫn RAM (Z-score kết hợp cao)")

            if is_anomaly:
                # Composite anomaly score (0 -> 100)
                score = min(100.0, max(15.0, (z_ram * 12.0) + (z_cpu * 15.0)))
                risk = "HIGH" if score >= 65.0 else ("MEDIUM" if score >= 40.0 else "LOW")
                reason_text = " & ".join(reasons)

                anomalies.append(ProcessAnomaly(
                    pid=pid,
                    name=name,
                    cpu_percent=round(p["cpu_pct"], 1),
                    ram_mb=round(p["ram_mb"], 1),
                    ram_z_score=round(z_ram, 2),
                    cpu_z_score=round(z_cpu, 2),
                    anomaly_score=round(score, 1),
                    risk_level=risk,
                    anomaly_reason=reason_text,
                    is_system_protected=is_protected,
                ))

        # Sắp xếp theo mức độ rủi ro (anomaly_score giảm dần)
        anomalies.sort(key=lambda a: a.anomaly_score, reverse=True)
        return anomalies[:limit]


# ---------------------------------------------------------------------------
# 4. Master Engine Orchestrator: PredictiveAIEngine
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 4. Context-Aware AI Auto-Pilot Engine
# ---------------------------------------------------------------------------

class AIAutoPilotEngine:
    """
    Engine AI tự động thích ứng ngữ cảnh (Gaming vs Work vs Battery Eco vs Quiet Night).
    Nhận diện tiến trình đang chạy và môi trường năng lượng để đề xuất hoặc tự động điều chỉnh.
    """

    def __init__(self, config_manager: Optional[Any] = None):
        self.config_manager = config_manager
        self._current_state = AutoPilotState()
        self._last_evaluated_ts = 0.0

    def evaluate_context(
        self,
        current_stats: Optional[Dict[str, Any]] = None,
        on_battery: bool = False,
        battery_pct: int = 100,
        running_process_names: Optional[List[str]] = None
    ) -> AutoPilotState:
        stats = current_stats or {}
        cpu_pct = float(stats.get("cpu", {}).get("percent", 0.0))

        # Lấy danh sách tên tiến trình nếu chưa có
        if running_process_names is None:
            try:
                running_process_names = [p.name().lower() for p in psutil.process_iter(['name'])]
            except Exception:
                running_process_names = []

        proc_set = set(running_process_names)
        hour = datetime.now().hour

        # 1. Kiểm tra Gaming Mode (Ưu tiên cao nhất khi phát hiện Game đang mở)
        active_game = next((p for p in KNOWN_GAME_PROCESSES if p in proc_set), None)
        if active_game:
            state = AutoPilotState(
                mode=MODE_GAMING,
                label="Chế Độ Game Thần Tốc (Game Boost)",
                icon="🎮",
                badge_text="🎮 AI Auto-Pilot: Game Boost",
                description=f"Phát hiện game đang chạy ({active_game}). Tự động thu hồi RAM standby và ưu tiên 100% CPU.",
                active_process=active_game,
                recommended_tuning=["Tối ưu RAM standby", "Ưu tiên luồng CPU cao nhất", "Tạm dừng tác vụ nền"],
                is_auto_applied=False
            )
            self._current_state = state
            return state

        # 2. Kiểm tra Eco Battery Mode (Khi rút sạc và pin dưới 50%)
        if on_battery and battery_pct <= 50:
            state = AutoPilotState(
                mode=MODE_ECO,
                label="Chế Độ Tiết Kiệm Pin Cơ Động (Eco Saver)",
                icon="🔋",
                badge_text="🔋 AI Auto-Pilot: Tiết Kiệm Pin",
                description=f"Đang dùng pin ({battery_pct}%). Giảm xung nhịp nhàn rỗi và hạn chế quét ổ đĩa nền.",
                active_process=None,
                recommended_tuning=["Hạ tải I/O đĩa", "Giảm tác vụ ngầm", "Tắt hoạt ảnh nặng"],
                is_auto_applied=False
            )
            self._current_state = state
            return state

        # 3. Kiểm tra Work / Coding / Design Mode
        active_work = next((p for p in KNOWN_WORK_PROCESSES if p in proc_set), None)
        if active_work:
            state = AutoPilotState(
                mode=MODE_WORK,
                label="Chế Độ Làm Việc & Sáng Tạo (Workstation)",
                icon="💼",
                badge_text="💼 AI Auto-Pilot: Làm Việc",
                description=f"Phát hiện ứng dụng công việc ({active_work}). Cân đối phân bổ RAM cho bộ đệm tập tin.",
                active_process=active_work,
                recommended_tuning=["Cấp phát RAM ổn định", "Ổn định mạng độ trễ thấp", "Tối ưu I/O đĩa"],
                is_auto_applied=False
            )
            self._current_state = state
            return state

        # 4. Kiểm tra Quiet Night Mode (Ban đêm 23h - 6h sáng)
        if (hour >= 23 or hour < 6) and cpu_pct < 40.0:
            state = AutoPilotState(
                mode=MODE_QUIET,
                label="Chế Độ Ban Đêm Tĩnh Lặng (Quiet Night)",
                icon="🌙",
                badge_text="🌙 AI Auto-Pilot: Ban Đêm",
                description="Khung giờ đêm muộn. Tắt âm thanh thông báo và kích hoạt dọn rác tự động nhàn rỗi.",
                active_process=None,
                recommended_tuning=["Tắt âm thanh cảnh báo", "Dọn rác tự động nhàn rỗi"],
                is_auto_applied=False
            )
            self._current_state = state
            return state

        # 5. Chế độ cân bằng mặc định
        state = AutoPilotState(
            mode=MODE_BALANCED,
            label="Chế Độ Cân Bằng Thông Minh (Balanced)",
            icon="⚖️",
            badge_text="⚖️ AI Auto-Pilot: Cân Bằng",
            description="Hệ thống đang hoạt động ở mức tải tiêu chuẩn, tự động cân bằng giữa hiệu năng và nhiệt độ.",
            active_process=None,
            recommended_tuning=["Duy trì trạng thái tối ưu"],
            is_auto_applied=False
        )
        self._current_state = state
        return state


# ---------------------------------------------------------------------------
# 4b. Auto-Pilot applicator (reversible Game Boost + undo)
# ---------------------------------------------------------------------------

_MODE_ALIASES = {
    "auto": None,
    "off": "OFF",
    "disabled": "OFF",
    "gaming": MODE_GAMING,
    "game": MODE_GAMING,
    "game_boost": MODE_GAMING,
    "eco": MODE_ECO,
    "battery": MODE_ECO,
    "battery_saver": MODE_ECO,
    "work": MODE_WORK,
    "quiet": MODE_QUIET,
    "night": MODE_QUIET,
    "balanced": MODE_BALANCED,
}


class AutoPilotApplicator:
    """
    Áp dụng an toàn các chế độ Auto-Pilot bằng đường dẫn đã có:
      GAMING → GameBooster.enable (có undo)
      ECO/WORK/QUIET/BALANCED → hoàn tác Game Boost nếu chính Auto-Pilot đã bật
      ECO → thu hồi RAM một lần khi vào chế độ (không đổi gói nguồn Windows)

    Không dọn rác ổ đĩa, không đổi DNS, không sửa registry.
    """

    ENTER_GAMING_GRACE_SEC = 0.0
    LEAVE_GAMING_GRACE_SEC = 30.0
    MODE_DWELL_SEC = 20.0
    RAM_OPT_COOLDOWN_SEC = 600.0

    def __init__(self, config_manager: Optional[Any] = None, booster: Any = None, ram_optimizer: Any = None):
        self.config_manager = config_manager
        self._booster = booster
        self._ram_optimizer = ram_optimizer
        self.held_mode: str = MODE_BALANCED
        self.auto_applied_game_boost: bool = False
        self.last_change_ts: float = 0.0
        self.last_ram_opt_ts: float = 0.0
        self.last_actions: List[str] = []
        self.game_boost_ui_dirty: bool = False

    def _booster_cls(self):
        if self._booster is not None:
            return self._booster
        from core.game_booster import GameBooster
        return GameBooster

    def _ram_cls(self):
        if self._ram_optimizer is not None:
            return self._ram_optimizer
        from core.memory_optimizer import MemoryOptimizer
        return MemoryOptimizer

    def is_enabled(self) -> bool:
        if not self.config_manager:
            return False
        if not bool(self.config_manager.get("ai_autopilot_enabled", True)):
            return False
        raw = str(self.config_manager.get("ai_autopilot_mode", "auto")).strip().lower()
        return raw not in ("off", "disabled")

    def resolve_target_mode(self, evaluated: AutoPilotState) -> str:
        raw = "auto"
        if self.config_manager:
            raw = str(self.config_manager.get("ai_autopilot_mode", "auto")).strip().lower()
        alias = _MODE_ALIASES.get(raw, None)
        if alias == "OFF":
            return MODE_BALANCED
        if alias:
            return alias
        return evaluated.mode

    def annotate(self, state: AutoPilotState) -> AutoPilotState:
        """Gắn nhãn đề xuất vs đã áp dụng mà không thay đổi hệ thống."""
        enabled = self.is_enabled()
        state.is_auto_applied = bool(enabled and self.last_actions)
        if not enabled:
            state.badge_text = state.badge_text.replace("AI Auto-Pilot:", "Đề xuất:")
            if "chỉ đề xuất" not in state.description:
                state.description = (state.description + " (Auto-Pilot đang tắt — chỉ đề xuất, chưa tự áp dụng).").strip()
        elif self.auto_applied_game_boost:
            if "Đã tự bật Game Boost" not in state.description:
                state.description = (state.description + " Đã tự bật Game Boost (có thể hoàn tác).").strip()
            state.is_auto_applied = True
        else:
            state.is_auto_applied = enabled
        state.applied_actions = list(self.last_actions)
        return state

    def undo_auto_effects(self, reason: str = "disabled") -> List[str]:
        actions: List[str] = []
        booster = self._booster_cls()
        if self.auto_applied_game_boost and booster.is_active():
            try:
                booster.disable_game_boost()
                actions.append("disable_game_boost")
                logger.info(f"[AutoPilot] Hoàn tác Game Boost ({reason}).")
            except Exception as e:
                logger.debug(f"[AutoPilot] Undo Game Boost failed: {e}")
            self.auto_applied_game_boost = False
            self.game_boost_ui_dirty = True
        self.last_actions = actions
        self.held_mode = MODE_BALANCED
        return actions

    def sync(self, evaluated: AutoPilotState, whitelist: Optional[set] = None) -> AutoPilotState:
        """Áp dụng/hoàn tác khi chế độ mục tiêu đổi. Trả về state đã annotate."""
        self.game_boost_ui_dirty = False
        now = time.time()
        if not self.is_enabled():
            self.undo_auto_effects("auto-pilot disabled")
            return self.annotate(evaluated)

        target = self.resolve_target_mode(evaluated)
        grace = self.MODE_DWELL_SEC
        if target == MODE_GAMING and self.held_mode != MODE_GAMING:
            grace = self.ENTER_GAMING_GRACE_SEC
        elif self.held_mode == MODE_GAMING and target != MODE_GAMING:
            grace = self.LEAVE_GAMING_GRACE_SEC

        if target != self.held_mode and (now - self.last_change_ts) < grace:
            return self.annotate(evaluated)

        if target == self.held_mode and self.last_change_ts > 0:
            return self.annotate(evaluated)

        actions: List[str] = []
        booster = self._booster_cls()
        whitelist = whitelist or set()

        if target == MODE_GAMING:
            if not booster.is_active():
                try:
                    res = booster.enable_game_boost(whitelist=whitelist)
                    if res.get("success", True):
                        self.auto_applied_game_boost = True
                        self.game_boost_ui_dirty = True
                        actions.append("enable_game_boost")
                        logger.info("[AutoPilot] Đã tự bật Game Boost (phát hiện game).")
                except Exception as e:
                    logger.debug(f"[AutoPilot] enable_game_boost failed: {e}")
            elif not self.auto_applied_game_boost:
                # User already turned it on manually — do not claim ownership
                actions.append("game_boost_already_on")
        else:
            if self.auto_applied_game_boost and booster.is_active():
                try:
                    booster.disable_game_boost()
                    self.game_boost_ui_dirty = True
                    actions.append("disable_game_boost")
                    logger.info(f"[AutoPilot] Hoàn tác Game Boost (chuyển sang {target}).")
                except Exception as e:
                    logger.debug(f"[AutoPilot] disable_game_boost failed: {e}")
                self.auto_applied_game_boost = False

            if target == MODE_ECO and (now - self.last_ram_opt_ts) >= self.RAM_OPT_COOLDOWN_SEC:
                try:
                    ram = self._ram_cls()
                    ram.optimize_ram(whitelist=whitelist)
                    self.last_ram_opt_ts = now
                    actions.append("optimize_ram")
                    logger.info("[AutoPilot] Eco: đã thu hồi RAM standby một lần.")
                except Exception as e:
                    logger.debug(f"[AutoPilot] Eco RAM optimize failed: {e}")

        self.held_mode = target
        self.last_change_ts = now
        self.last_actions = actions
        return self.annotate(evaluated)


# ---------------------------------------------------------------------------
# 5. Master Engine Orchestrator: PredictiveAIEngine
# ---------------------------------------------------------------------------

class PredictiveAIEngine:
    """
    Trạm điều phối trung tâm Trí Tuệ Nhân Tạo Dự Đoán & Nhận Diện Bất Thường.
    Kết hợp: Dự báo ổ đĩa, Học thói quen, Nhận diện dị biệt tiến trình,
    AI Auto-Pilot thích ứng ngữ cảnh và Thang điểm AI Health Score (0-100).
    """

    def __init__(self, config_manager: Optional[Any] = None):
        self.config_manager = config_manager
        self.forecaster = DiskForecaster(config_manager)
        self.habit_learner = HabitLearner(config_manager)
        self.anomaly_detector = ProcessAnomalyDetector(config_manager)
        self.autopilot = AIAutoPilotEngine(config_manager)
        self.applicator = AutoPilotApplicator(config_manager)

        self._cached_forecast: Optional[DiskForecast] = None
        self._forecast_cache_ts: float = 0.0

        self._cached_anomalies: List[ProcessAnomaly] = []
        self._anomaly_cache_ts: float = 0.0

        self._cached_health: Optional[AIHealthReport] = None
        self._health_cache_ts: float = 0.0

    def feed_snapshot(self, stats: Dict[str, Any]):
        """Nhận dữ liệu từ SystemMonitorHub để huấn luyện mô hình."""
        try:
            ram = stats.get("ram", {})
            cpu = stats.get("cpu", {})
            disk = stats.get("disk", {})

            cpu_pct = float(cpu.get("percent", 0.0))
            ram_pct = float(ram.get("percent", 0.0))
            free_gb = float(disk.get("free_gb", 0.0))
            total_gb = float(disk.get("total_gb", 0.0))

            # Feed habit learner
            self.habit_learner.feed_sample(cpu_pct, ram_pct)

            # Feed disk forecaster
            if free_gb > 0 and total_gb > 0:
                self.forecaster.record_sample(free_gb, total_gb)
        except Exception as e:
            logger.debug(f"[PredictiveAI] Error feeding snapshot: {e}")

    def get_disk_forecast(self, drive: str = "C:", force_refresh: bool = False) -> DiskForecast:
        """Lấy dự báo cạn kiệt dung lượng ổ đĩa."""
        now = time.time()
        if not force_refresh and self._cached_forecast and (now - self._forecast_cache_ts < 30.0):
            return self._cached_forecast

        self._cached_forecast = self.forecaster.calculate_forecast(drive)
        self._forecast_cache_ts = now
        return self._cached_forecast

    def get_habit_profile(
        self,
        current_cpu: float = 0.0,
        current_ram: float = 0.0,
        on_battery: bool = False,
        battery_pct: int = 100
    ) -> UsageHabit:
        """Lấy đánh giá thói quen sử dụng và chế độ khuyến nghị."""
        return self.habit_learner.analyze_current_habit(
            current_cpu=current_cpu,
            current_ram=current_ram,
            on_battery=on_battery,
            battery_pct=battery_pct
        )

    def detect_anomalies(self, limit: int = 5, force_refresh: bool = False) -> List[ProcessAnomaly]:
        """Lấy danh sách tiến trình bất thường mới nhất."""
        now = time.time()
        if not force_refresh and self._cached_anomalies and (now - self._anomaly_cache_ts < 10.0):
            return self._cached_anomalies

        self._cached_anomalies = self.anomaly_detector.detect_anomalies(limit)
        self._anomaly_cache_ts = now
        return self._cached_anomalies

    def get_autopilot_state(
        self,
        current_stats: Optional[Dict[str, Any]] = None,
        on_battery: bool = False,
        battery_pct: int = 100,
        running_process_names: Optional[List[str]] = None
    ) -> AutoPilotState:
        """Lấy trạng thái chế độ tự động thích ứng ngữ cảnh AI Auto-Pilot."""
        state = self.autopilot.evaluate_context(
            current_stats=current_stats,
            on_battery=on_battery,
            battery_pct=battery_pct,
            running_process_names=running_process_names
        )
        return self.applicator.annotate(state)

    def apply_autopilot(
        self,
        current_stats: Optional[Dict[str, Any]] = None,
        on_battery: bool = False,
        battery_pct: int = 100,
        running_process_names: Optional[List[str]] = None,
        whitelist: Optional[set] = None,
    ) -> AutoPilotState:
        """Nhận diện + áp dụng (Game Boost reversible) theo cấu hình Auto-Pilot."""
        state = self.autopilot.evaluate_context(
            current_stats=current_stats,
            on_battery=on_battery,
            battery_pct=battery_pct,
            running_process_names=running_process_names
        )
        return self.applicator.sync(state, whitelist=whitelist)

    def calculate_health_score(
        self,
        stats: Optional[Dict[str, Any]] = None,
        leaks: Optional[List[Dict]] = None,
        security_info: Optional[Dict[str, Any]] = None,
        anomalies: Optional[List[ProcessAnomaly]] = None,
        force_refresh: bool = False
    ) -> AIHealthReport:
        """
        Tính toán chỉ số sức khỏe hệ thống toàn diện từ 0 đến 100 điểm
        kết hợp từ 6 nhóm chỉ số và sinh Toa Thuốc AI (Prescription).
        """
        now = time.time()
        if not force_refresh and self._cached_health and (now - self._health_cache_ts < 4.0):
            return self._cached_health

        stats = stats or {}
        ram = stats.get("ram", {})
        cpu = stats.get("cpu", {})
        disk = stats.get("disk", {})
        net = stats.get("net", {})

        ram_pct = float(ram.get("percent", 50.0))
        cpu_pct = float(cpu.get("percent", 20.0))
        disk_free_gb = float(disk.get("free_gb", 50.0))
        disk_total_gb = float(disk.get("total_gb", 256.0))
        ping_ms = float(net.get("ping_ms", -1.0))
        ping_measured = bool(net.get("ping_measured", False))

        leaks_list = leaks or []
        anom_list = anomalies if anomalies is not None else self.detect_anomalies(limit=3)

        # 1. RAM Score (Max 25 pts)
        if ram_pct < 60:
            s_ram = 25
        elif ram_pct < 75:
            s_ram = 20
        elif ram_pct < 85:
            s_ram = 14
        else:
            s_ram = 5
        if leaks_list:
            s_ram = max(0, s_ram - 5)

        # 2. CPU Score (Max 20 pts)
        if cpu_pct < 35:
            s_cpu = 20
        elif cpu_pct < 60:
            s_cpu = 16
        elif cpu_pct < 80:
            s_cpu = 10
        else:
            s_cpu = 4

        # 3. Disk Score (Max 20 pts)
        free_pct = (disk_free_gb / disk_total_gb * 100.0) if disk_total_gb > 0 else 20.0
        if disk_free_gb >= 30.0 or free_pct >= 20.0:
            s_disk = 20
        elif disk_free_gb >= 15.0 or free_pct >= 12.0:
            s_disk = 15
        elif disk_free_gb >= 8.0:
            s_disk = 10
        else:
            s_disk = 2
        forecast = self.get_disk_forecast()
        if forecast.trend_status == STATUS_CRITICAL_DEPLETION:
            s_disk = max(0, s_disk - 6)
        elif forecast.trend_status == STATUS_WARNING_DEPLETION:
            s_disk = max(0, s_disk - 3)

        # 4. Process & Anomaly Score (Max 15 pts)
        if not anom_list:
            s_proc = 15
        elif len(anom_list) == 1 and anom_list[0].risk_level != "HIGH":
            s_proc = 11
        else:
            s_proc = 5

        # 5. Services & System Overhead (Max 10 pts)
        s_serv = 10
        if cpu_pct >= 70 or ram_pct >= 85:
            s_serv = 6

        # 6. Network Score (Max 10 pts)
        if 0 < ping_ms <= 40:
            s_net = 10
        elif 40 < ping_ms <= 100:
            s_net = 8
        elif ping_ms > 100:
            s_net = 4
        elif ping_measured:
            s_net = 3
        else:
            s_net = 7

        total_score = s_ram + s_cpu + s_disk + s_proc + s_serv + s_net
        total_score = max(5, min(100, total_score))

        # Phân loại mức độ
        if total_score >= 90:
            grade = "XUẤT SẮC"
            grade_color = "#3fb950"
            summary_text = "Hệ thống đang ở trạng thái đỉnh cao, tốc độ mượt mà và tài nguyên dư dả."
        elif total_score >= 75:
            grade = "TỐT"
            grade_color = "#58a6ff"
            summary_text = "Hệ thống vận hành ổn định. Có thể tinh chỉnh nhẹ để đạt hiệu năng tối đa."
        elif total_score >= 55:
            grade = "CẦN TỐI ƯU"
            grade_color = "#e3b341"
            summary_text = "Phát hiện tải cao hoặc nghẽn tài nguyên cục bộ. Khuyến nghị chạy tối ưu hóa."
        else:
            grade = "NGUY CƠ"
            grade_color = "#f85149"
            summary_text = "Cảnh báo quá tải nghiêm trọng! Cần giải phóng RAM/ổ đĩa khẩn cấp để tránh treo máy."

        # Xây dựng danh sách sự cố và Toa Thuốc AI
        issues = []
        prescription = []
        potential_gain = 0

        if ram_pct >= 75 or leaks_list:
            reason = f"RAM đang chiếm {ram_pct:.1f}%"
            if leaks_list:
                reason += f" (có {len(leaks_list)} tiến trình nghi rò rỉ)"
            issues.append(reason)
            prescription.append({
                "title": "Thu Hồi Bộ Nhớ RAM Standby",
                "desc": "Giải phóng bộ nhớ đệm và hoàn trả ngay ~500MB - 1.5GB RAM trống cho máy.",
                "action_key": "optimize_ram",
                "action_label": "⚡ Thu Hồi RAM Ngay",
                "points_gain": 8
            })
            potential_gain += 8

        if disk_free_gb < 20.0 or forecast.trend_status in (STATUS_CRITICAL_DEPLETION, STATUS_WARNING_DEPLETION):
            issues.append(f"Ổ C chỉ còn {disk_free_gb:.1f} GB trống")
            prescription.append({
                "title": "Dọn Dẹp Rác Ổ Đĩa & File Tạm",
                "desc": "Quét sạch temp, cache trình duyệt, log hỏng và crash dump để mở rộng dung lượng.",
                "action_key": "clean_disk",
                "action_label": "🧹 Dọn Rác Ổ C",
                "points_gain": 7
            })
            potential_gain += 7

        if anom_list:
            issues.append(f"Có {len(anom_list)} tiến trình hoạt động bất thường (Z-score cao)")
            prescription.append({
                "title": "Xử Lý Tiến Trình Tiêu Hao Dị Biệt",
                "desc": f"Kiểm tra và ngăn chặn các tiến trình đột biến ({anom_list[0].name}).",
                "action_key": "manage_processes",
                "action_label": "🔄 Xem Tiến Trình",
                "points_gain": 5
            })
            potential_gain += 5

        if cpu_pct >= 60:
            issues.append(f"CPU đang chịu tải cao ({cpu_pct:.1f}%)")
            prescription.append({
                "title": "Kích Hoạt Chế Độ Game Boost",
                "desc": "Ưu tiên 100% sức mạnh CPU cho ứng dụng bạn đang làm việc.",
                "action_key": "toggle_game_boost",
                "action_label": "🎮 Bật Game Boost",
                "points_gain": 6
            })
            potential_gain += 6

        if ping_measured and ping_ms <= 0:
            issues.append("Không đo được Ping (timeout / mất kết nối)")
            desc = (
                "Chẩn đoán nguyên nhân (timeout meter, DNS, gateway, TCP) rồi sửa ngay: "
                "đo lại timeout dài hơn, flush DNS, ARP, đổi DNS tốt nhất nếu vẫn lỗi."
            )
            try:
                from core.network_optimizer import NetworkOptimizer
                report = getattr(NetworkOptimizer, "last_missing_ping_report", None) or {}
                if report.get("cause_label"):
                    desc = (
                        f"Nguyên nhân: {report.get('cause_label')}. "
                        f"Đã sửa: {report.get('applied_summary') or 'chưa có'}. "
                        "Bấm để chạy lại kiểm tra & sửa."
                    )
            except Exception:
                pass
            prescription.append({
                "title": "Kiểm Tra & Sửa Mạng",
                "desc": desc,
                "action_key": "repair_network_now",
                "action_label": "🛠️ Sửa Mạng Ngay",
                "points_gain": 4
            })
            potential_gain += 4
        elif ping_ms > 100:
            issues.append(f"Độ trễ mạng cao ({ping_ms:.0f}ms)")
            prescription.append({
                "title": "Tối Ưu Hóa Mạng & DNS Siêu Tốc",
                "desc": "Làm mới DNS Cache và chuyển sang DNS có phản hồi nhanh nhất.",
                "action_key": "optimize_network",
                "action_label": "📶 Tối Ưu Mạng",
                "points_gain": 4
            })
            potential_gain += 4

        # Nếu hệ thống quá mượt mà và không có issue
        if not prescription:
            prescription.append({
                "title": "Duy Trì Trạng Thái Đỉnh Cao",
                "desc": "Chạy quét bảo mật và tối ưu dịch vụ định kỳ để giữ máy luôn nhanh như mới.",
                "action_key": "auto_optimize_all",
                "action_label": "✨ Tối Ưu Toàn Diện",
                "points_gain": 2
            })
            potential_gain += 2

        predicted_after = min(100, total_score + potential_gain)

        report = AIHealthReport(
            score=total_score,
            grade=grade,
            grade_color=grade_color,
            summary_text=summary_text,
            breakdown={
                "ram": s_ram,
                "cpu": s_cpu,
                "disk": s_disk,
                "process": s_proc,
                "services": s_serv,
                "network": s_net
            },
            issues=issues,
            prescription=prescription,
            predicted_score_after=predicted_after
        )
        self._cached_health = report
        self._health_cache_ts = now
        return report

    def get_summary(self) -> Dict[str, Any]:
        """Tổng hợp toàn bộ chỉ số AI dự báo phục vụ báo cáo và UI."""
        forecast = self.get_disk_forecast()
        habit = self.get_habit_profile()
        anomalies = self.detect_anomalies(limit=3)
        health = self.calculate_health_score()
        autopilot = self.get_autopilot_state()

        return {
            "forecast": forecast.to_dict(),
            "habit": habit.to_dict(),
            "anomalies_count": len(anomalies),
            "top_anomaly": anomalies[0].to_dict() if anomalies else None,
            "health": health.to_dict(),
            "autopilot": autopilot.to_dict(),
        }

