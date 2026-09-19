"""
core/service_optimizer.py – Windows Services Optimizer (v3.4 Pro)
===================================================================
Quản lý và tối ưu hóa các dịch vụ Windows chạy ngầm gây hao tốn tài nguyên
(Telemetry thu thập dữ liệu, SysMain/Superfetch, Indexing, Xbox thừa,...).
Cung cấp chế độ 1-Click Tối Ưu An Toàn và khả năng khôi phục nguyên trạng.
"""
from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

try:
    import psutil
except ImportError:
    psutil = None

from core.network_optimizer import NetworkOptimizer


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

RECOMMENDATION_SAFE_DISABLE   = "safe_disable"     # Tắt hoàn toàn không ảnh hưởng máy
RECOMMENDATION_MANUAL         = "recommend_manual" # Chuyển sang Thủ công (khi cần mới chạy)
RECOMMENDATION_KEEP           = "keep"             # Giữ nguyên / Cốt lõi hệ thống

CATEGORY_TELEMETRY  = "telemetry"
CATEGORY_INDEXING   = "indexing"
CATEGORY_GAMING     = "gaming"
CATEGORY_DIAGNOSTIC = "diagnostic"
CATEGORY_SYSTEM     = "system"
CATEGORY_OTHER      = "other"

CATEGORY_TITLES = {
    CATEGORY_TELEMETRY:  "🛡️ Giám Sát & Telemetry",
    CATEGORY_INDEXING:   "🔍 Tìm Kiếm & Chỉ Mục",
    CATEGORY_GAMING:     "🎮 Dịch Vụ Gaming & Xbox",
    CATEGORY_DIAGNOSTIC: "🩺 Báo Cáo & Chẩn Đoán",
    CATEGORY_SYSTEM:     "⚙️ Dịch Vụ Hệ Thống",
    CATEGORY_OTHER:      "📦 Dịch Vụ Khác",
}


@dataclass
class WindowsService:
    """Đại diện một dịch vụ Windows."""
    name: str
    display_name: str
    status: str              # 'running', 'stopped', 'paused', etc.
    start_type: str          # 'automatic', 'manual', 'disabled'
    description: str
    category: str = CATEGORY_OTHER
    recommendation: str = RECOMMENDATION_KEEP
    advice_note: str = ""
    target_start_type: str = "keep"

    @property
    def is_running(self) -> bool:
        return self.status.lower() == "running"

    @property
    def is_candidate(self) -> bool:
        """Kiểm tra dịch vụ có đang ở trạng thái cần tối ưu không."""
        st = self.start_type.lower()
        if self.recommendation == RECOMMENDATION_SAFE_DISABLE:
            return st != "disabled" or self.is_running
        if self.recommendation == RECOMMENDATION_MANUAL:
            return st == "automatic"
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status,
            "start_type": self.start_type,
            "description": self.description,
            "category": self.category,
            "recommendation": self.recommendation,
            "advice_note": self.advice_note,
            "is_candidate": self.is_candidate,
        }


# ---------------------------------------------------------------------------
# Curated Knowledge Base
# ---------------------------------------------------------------------------

KNOWN_SERVICES: Dict[str, Dict[str, str]] = {
    "diagtrack": {
        "category": CATEGORY_TELEMETRY,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Connected User Experiences and Telemetry thu thập dữ liệu người dùng gửi về máy chủ. An toàn tắt hoàn toàn để bảo vệ riêng tư và tiết kiệm CPU/RAM.",
    },
    "dmwappushservice": {
        "category": CATEGORY_TELEMETRY,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "WAP Push Message Routing Service hỗ trợ thu thập và gửi dữ liệu chẩn đoán. An toàn tắt hoàn toàn.",
    },
    "sysmain": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Superfetch / SysMain tải trước ứng dụng vào RAM, thường gây lỗi 100% Disk trên ổ HDD/SATA SSD và ngốn RAM. Khuyên chuyển sang Thủ công (Manual).",
    },
    "wsearch": {
        "category": CATEGORY_INDEXING,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Windows Search lập chỉ mục tập tin chạy ngầm liên tục, gây tiêu tốn Disk I/O và CPU. Khuyên chuyển sang Thủ công.",
    },
    "xblauthmanager": {
        "category": CATEGORY_GAMING,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Quản lý xác thực đăng nhập Xbox Live. Nếu bạn không chơi game từ Microsoft Store/Xbox, khuyên chuyển sang Thủ công.",
    },
    "xblgamesave": {
        "category": CATEGORY_GAMING,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Đồng bộ lưu file save game Xbox Live. Chuyển sang Thủ công khi không sử dụng.",
    },
    "xboxnetapisvc": {
        "category": CATEGORY_GAMING,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Dịch vụ mạng kết nối Xbox Live. Chuyển sang Thủ công để giảm tải nền.",
    },
    "xboxgipsvc": {
        "category": CATEGORY_GAMING,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Quản lý phụ kiện và tay cầm Xbox. Chuyển sang Thủ công nếu không cắm tay cầm chơi game.",
    },
    "fax": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Dịch vụ gửi và nhận Fax. Hầu hết máy tính hiện đại không sử dụng. An toàn tắt hoàn toàn.",
    },
    "remoteregistry": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Cho phép người dùng từ xa chỉnh sửa Registry qua mạng. Tiềm ẩn rủi ro bảo mật nghiêm trọng. Khuyên tắt hoàn toàn.",
    },
    "retaildemo": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Chế độ trải nghiệm thử nghiệm tại cửa hàng bán lẻ của Windows. Hoàn toàn thừa đối với người dùng cá nhân. An toàn tắt.",
    },
    "mapsbroker": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Downloaded Maps Manager quản lý tải về bản đồ offline. An toàn tắt nếu dùng Google Maps trên trình duyệt.",
    },
    "wisvc": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Windows Insider Service phục vụ nhận bản dựng Windows thử nghiệm không ổn định. An toàn tắt.",
    },
    "wersvc": {
        "category": CATEGORY_DIAGNOSTIC,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Windows Error Reporting gửi nhật ký crash về Microsoft. Chuyển sang Thủ công để tránh giật lag khi có sự cố ứng dụng.",
    },
    "printnotify": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_SAFE_DISABLE,
        "target_start_type": "disabled",
        "advice_note": "Print Spooler Notification phục vụ thông báo máy in mạng doanh nghiệp. An toàn tắt nếu chỉ in nội bộ gia đình/văn phòng.",
    },
    "bdesvc": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "BitLocker Drive Encryption Service. Chuyển sang Thủ công nếu máy không sử dụng mã hóa ổ đĩa BitLocker.",
    },
    "sensrsvc": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Sensor Service quản lý cảm biến ánh sáng, xoay màn hình (thường chỉ dùng trên laptop lai 2-in-1 hoặc tablet).",
    },
    "lfsvc": {
        "category": CATEGORY_SYSTEM,
        "recommendation": RECOMMENDATION_MANUAL,
        "target_start_type": "manual",
        "advice_note": "Geolocation Service định vị vị trí máy tính. Chuyển sang Thủ công để tiết kiệm pin và bảo vệ vị trí cá nhân.",
    },
}


# ---------------------------------------------------------------------------
# ServiceOptimizer Engine
# ---------------------------------------------------------------------------

class ServiceOptimizer:
    """Lớp điều phối tối ưu hóa Windows Services."""

    @staticmethod
    def get_services(
        category_filter: Optional[str] = None,
        only_candidates: bool = False
    ) -> List[WindowsService]:
        """
        Liệt kê toàn bộ hoặc danh mục dịch vụ Windows được phân loại.
        """
        results: List[WindowsService] = []
        if not psutil:
            return results

        try:
            for s in psutil.win_service_iter():
                try:
                    name = s.name()
                    name_lower = name.lower()
                    display_name = s.display_name() or name
                    status = s.status() or "unknown"
                    start_type = s.start_type() or "unknown"
                    
                    try:
                        desc = s.description() or ""
                    except Exception:
                        desc = ""

                    # Tra cứu cơ sở tri thức
                    meta = KNOWN_SERVICES.get(name_lower)
                    if meta:
                        cat = meta["category"]
                        rec = meta["recommendation"]
                        target_type = meta["target_start_type"]
                        advice = meta["advice_note"]
                    else:
                        cat = CATEGORY_OTHER
                        rec = RECOMMENDATION_KEEP
                        target_type = "keep"
                        advice = ""

                    item = WindowsService(
                        name=name,
                        display_name=display_name,
                        status=status,
                        start_type=start_type,
                        description=desc,
                        category=cat,
                        recommendation=rec,
                        advice_note=advice,
                        target_start_type=target_type,
                    )

                    if only_candidates and not item.is_candidate:
                        continue
                    if category_filter and category_filter != "all" and item.category != category_filter:
                        continue

                    results.append(item)
                except Exception:
                    continue
        except Exception:
            pass

        # Sắp xếp: candidate lên đầu, sau đó theo mức an toàn tắt, rồi theo tên
        results.sort(key=lambda x: (not x.is_candidate, x.recommendation != RECOMMENDATION_SAFE_DISABLE, x.name.lower()))
        return results

    @staticmethod
    def get_summary() -> Dict[str, Any]:
        """Trả về thống kê tổng quan dịch vụ."""
        services = ServiceOptimizer.get_services()
        total = len(services)
        running = sum(1 for s in services if s.is_running)
        stopped = total - running
        candidates = sum(1 for s in services if s.is_candidate)
        safe_to_disable = sum(1 for s in services if s.recommendation == RECOMMENDATION_SAFE_DISABLE and s.is_candidate)
        recommend_manual = sum(1 for s in services if s.recommendation == RECOMMENDATION_MANUAL and s.is_candidate)

        return {
            "total": total,
            "running": running,
            "stopped": stopped,
            "candidates": candidates,
            "safe_to_disable": safe_to_disable,
            "recommend_manual": recommend_manual,
        }

    @staticmethod
    def apply_service_state(
        service_name: str,
        target_start_type: str,
        stop_if_running: bool = True
    ) -> Tuple[bool, str]:
        """
        Thay đổi kiểu khởi động của dịch vụ (disabled / manual / auto).
        Yêu cầu quyền Administrator.
        """
        if not NetworkOptimizer.is_admin():
            return False, "Cần quyền Administrator để thay đổi trạng thái dịch vụ hệ thống."

        target = target_start_type.lower()
        sc_type_map = {
            "disabled": "disabled",
            "manual": "demand",
            "auto": "auto",
            "automatic": "auto",
        }
        sc_type = sc_type_map.get(target)
        if not sc_type:
            return False, f"Kiểu khởi động '{target_start_type}' không hợp lệ."

        try:
            # 1. Cấu hình kiểu khởi động
            cmd_config = ["sc.exe", "config", service_name, f"start= {sc_type}"]
            res1 = subprocess.run(cmd_config, capture_output=True, text=True, timeout=10)
            if res1.returncode != 0:
                err_msg = res1.stderr.strip() or res1.stdout.strip()
                return False, f"Lỗi cấu hình service '{service_name}': {err_msg}"

            # 2. Dừng dịch vụ nếu chọn disabled và dịch vụ đang chạy
            if stop_if_running and target == "disabled":
                cmd_stop = ["sc.exe", "stop", service_name]
                subprocess.run(cmd_stop, capture_output=True, text=True, timeout=10)

            return True, f"Đã chuyển dịch vụ '{service_name}' sang chế độ {target_start_type.upper()} thành công!"
        except Exception as e:
            return False, f"Lỗi thực thi: {str(e)}"

    @staticmethod
    def one_click_optimize() -> Dict[str, Any]:
        """
        1-Click Tối ưu hóa toàn bộ các dịch vụ an toàn khuyên dùng.
        """
        if not NetworkOptimizer.is_admin():
            return {
                "success": False,
                "message": "Vui lòng chạy ứng dụng với quyền Administrator để tối ưu dịch vụ hệ thống.",
                "optimized_count": 0,
                "failed_count": 0,
                "details": [],
            }

        candidates = ServiceOptimizer.get_services(only_candidates=True)
        optimized_count = 0
        failed_count = 0
        details = []

        for s in candidates:
            if s.recommendation not in (RECOMMENDATION_SAFE_DISABLE, RECOMMENDATION_MANUAL):
                continue

            target = s.target_start_type
            if target == "keep":
                continue

            ok, msg = ServiceOptimizer.apply_service_state(s.name, target, stop_if_running=True)
            if ok:
                optimized_count += 1
                details.append(f"✅ {s.name}: {s.start_type} → {target}")
            else:
                failed_count += 1
                details.append(f"❌ {s.name}: {msg}")

        return {
            "success": optimized_count > 0 or failed_count == 0,
            "optimized_count": optimized_count,
            "failed_count": failed_count,
            "message": f"Đã tối ưu hóa thành công {optimized_count} dịch vụ ({failed_count} thất bại).",
            "details": details,
        }
