import os
import sys
import ctypes
import psutil
import time
from typing import Dict, Any

from core.logger import logger

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100

class MemoryOptimizer:
    _last_run_time = 0.0
    _last_result = None

    @classmethod
    def optimize_ram(cls, whitelist: set = None) -> Dict[str, Any]:
        """
        Tối ưu hóa RAM bằng cách gọi EmptyWorkingSet trên các tiến trình người dùng đang chạy.
        Giúp đẩy các trang bộ nhớ không hoạt động ra khỏi RAM vật lý, trả lại RAM trống cho hệ thống.

        Args:
            whitelist: Tập hợp tên tiến trình (chữ thường) được bỏ qua (bảo vệ khỏi EmptyWorkingSet).
        """
        now = time.time()
        if cls._last_result is not None and (now - cls._last_run_time < 2.5):
            logger.info("[RAM Optimizer] Tránh gọi lặp quá nhanh (Debounced). Trả kết quả trước đó.")
            return cls._last_result

        safe_whitelist = whitelist or set()

        mem_before = psutil.virtual_memory()
        used_before_mb = (mem_before.total - mem_before.available) / (1024 ** 2)
        percent_before = mem_before.percent
        
        processes_flushed = 0
        skipped_whitelist = 0
        current_pid = os.getpid()

        # Duyệt qua các tiến trình đang chạy
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                pid = proc.info['pid']
                name = (proc.info['name'] or "").lower()
                # Bỏ qua tiến trình hệ thống (0, 4) và chính ứng dụng này
                if pid <= 4 or pid == current_pid:
                    continue
                # Bỏ qua tiến trình trong whitelist
                if name in safe_whitelist:
                    skipped_whitelist += 1
                    continue
                
                # Mở tiến trình với quyền truy vấn và đặt hạn mức bộ nhớ
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, 
                    False, 
                    pid
                )
                if handle:
                    try:
                        res = ctypes.windll.psapi.EmptyWorkingSet(handle)
                        if res:
                            processes_flushed += 1
                    finally:
                        ctypes.windll.kernel32.CloseHandle(handle)
            except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError):
                continue
            except Exception:
                continue

        # Đo lại thông số RAM sau khi giải phóng
        mem_after = psutil.virtual_memory()
        used_after_mb = (mem_after.total - mem_after.available) / (1024 ** 2)
        percent_after = mem_after.percent

        freed_mb = max(0.0, used_before_mb - used_after_mb)
        logger.info(
            f"[RAM Optimizer] Đã thu hồi bộ nhớ từ {processes_flushed} tiến trình. "
            f"RAM: {percent_before:.1f}% -> {percent_after:.1f}% (Giải phóng: {freed_mb:.1f} MB)"
            + (f" | Bỏ qua {skipped_whitelist} tiến trình trong Whitelist." if skipped_whitelist else "")
        )

        result = {
            "success": True,
            "processes_flushed": processes_flushed,
            "used_before_mb": round(used_before_mb, 1),
            "used_after_mb": round(used_after_mb, 1),
            "freed_mb": round(freed_mb, 1),
            "percent_before": percent_before,
            "percent_after": percent_after
        }
        cls._last_run_time = time.time()
        cls._last_result = result
        return result
