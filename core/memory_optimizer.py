import os
import ctypes
import psutil
import time
from typing import Any, Callable, Dict, Iterable, Optional

from core.logger import logger
from core.process_manager import PROTECTED_PROCESSES

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100

# Working set nhỏ hơn mức này gần như không trả RAM trống, nhưng vẫn chạm tiến trình.
MIN_WORKING_SET_BYTES = 8 * 1024 * 1024
# Chỉ bỏ qua khi mẫu CPU đã biết và đang cao. 0 nghĩa là chưa có mẫu, không phải "rảnh".
BUSY_CPU_SKIP_PERCENT = 30.0

RAM_TRIM_NOTE_VI = (
    "EmptyWorkingSet (API Win32 có tài liệu) chỉ thu nhỏ working set — bộ nhớ tiến trình đang giữ. "
    "Không tắt ứng dụng. Không xóa standby list: app không gọi NtSetSystemInformation vì lệnh đó "
    "không có tài liệu chính thức và có thể lỗi trên Windows mới. "
    "Windows có thể cấp lại RAM ngay nếu ứng dụng cần, nên số trống có thể không giữ lâu."
)


def format_mb_vi(mb: float) -> str:
    value = float(mb or 0.0)
    if abs(value) >= 1024.0:
        return f"{value / 1024.0:.2f} GB"
    return f"{value:.0f} MB"


def format_ram_report_vi(result: Dict[str, Any]) -> str:
    """Báo cáo trước/sau RAM trống. Không bịa điểm hiệu năng."""
    before = result.get("available_before_mb")
    after = result.get("available_after_mb")
    lines = []
    if result.get("debounced"):
        lines.append("Chưa đo lại — số liệu là lần thu hồi vừa chạy (dưới 3 giây trước).")

    if before is None or after is None:
        lines.append("Không đọc được RAM trống trước và sau.")
    else:
        delta = float(after) - float(before)
        lines.append(f"RAM trống (khả dụng) trước: {format_mb_vi(float(before))}")
        lines.append(f"RAM trống (khả dụng) sau: {format_mb_vi(float(after))}")
        if delta > 0.5:
            lines.append(f"Chênh lệch: +{format_mb_vi(delta)}")
        elif delta < -0.5:
            lines.append(
                f"Chênh lệch: -{format_mb_vi(abs(delta))} "
                "(Windows đã dùng lại bộ nhớ trong lúc thu hồi)."
            )
        else:
            lines.append("Chênh lệch: gần như không đổi.")

    flushed = int(result.get("processes_flushed") or 0)
    lines.append(f"Đã gọi EmptyWorkingSet trên {flushed} tiến trình.")

    skipped_bits = []
    pinned = int(result.get("skipped_whitelist") or 0)
    if pinned:
        names = result.get("skipped_whitelist_names") or []
        shown = ", ".join(str(n) for n in list(names)[:8])
        extra = f" ({shown})" if shown else ""
        skipped_bits.append(f"{pinned} tiến trình bạn đã ghim{extra}")
    protected = int(result.get("skipped_protected") or 0)
    if protected:
        skipped_bits.append(f"{protected} tiến trình hệ thống")
    small = int(result.get("skipped_small") or 0)
    if small:
        skipped_bits.append(f"{small} tiến trình có working set dưới 8 MB")
    busy = int(result.get("skipped_busy") or 0)
    if busy:
        skipped_bits.append(f"{busy} tiến trình đang dùng CPU từ {BUSY_CPU_SKIP_PERCENT:.0f}%")
    denied = int(result.get("skipped_access") or 0)
    if denied:
        skipped_bits.append(f"{denied} tiến trình không mở được (thiếu quyền hoặc không phải Windows)")
    if skipped_bits:
        lines.append("Bỏ qua: " + ", ".join(skipped_bits) + ".")

    lines.append(RAM_TRIM_NOTE_VI)
    return "\n".join(lines)


def _memory_sample():
    mem = psutil.virtual_memory()
    return mem


def _default_open_process(pid: int):
    if os.name != "nt":
        return None
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA,
        False,
        int(pid),
    )
    return handle or None


def _default_empty_working_set(handle) -> bool:
    return bool(ctypes.windll.psapi.EmptyWorkingSet(handle))


def _default_close_handle(handle) -> None:
    ctypes.windll.kernel32.CloseHandle(handle)


class MemoryOptimizer:
    _last_run_time = 0.0
    _last_result = None

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._last_run_time = 0.0
        cls._last_result = None

    @classmethod
    def optimize_ram(
        cls,
        whitelist: set = None,
        *,
        process_iter: Optional[Callable[..., Iterable]] = None,
        virtual_memory: Optional[Callable[[], Any]] = None,
        open_process: Optional[Callable[[int], Any]] = None,
        empty_working_set: Optional[Callable[[Any], bool]] = None,
        close_handle: Optional[Callable[[Any], None]] = None,
        current_pid: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Thu nhỏ working set bằng EmptyWorkingSet trên tiến trình người dùng.

        Tiến trình trong whitelist (ghim), tiến trình hệ thống, working set nhỏ
        và tiến trình đang dùng nhiều CPU được bỏ qua. Không gọi API xóa standby list.
        """
        now = time.time()
        if cls._last_result is not None and (now - cls._last_run_time < 2.5):
            logger.info("[RAM Optimizer] Tránh gọi lặp quá nhanh (Debounced). Trả kết quả trước đó.")
            cached = dict(cls._last_result)
            cached["debounced"] = True
            return cached

        safe_whitelist = {str(n).lower() for n in (whitelist or set())}
        iterate = process_iter or psutil.process_iter
        read_memory = virtual_memory or _memory_sample
        open_proc = open_process or _default_open_process
        trim = empty_working_set or _default_empty_working_set
        close = close_handle or _default_close_handle
        self_pid = os.getpid() if current_pid is None else int(current_pid)

        mem_before = read_memory()
        available_before_mb = float(mem_before.available) / (1024 ** 2)
        used_before_mb = (float(mem_before.total) - float(mem_before.available)) / (1024 ** 2)
        percent_before = float(mem_before.percent)

        processes_flushed = 0
        skipped_whitelist = 0
        skipped_whitelist_names = []
        skipped_protected = 0
        skipped_small = 0
        skipped_busy = 0
        skipped_access = 0

        for proc in iterate(["pid", "name", "memory_info", "cpu_percent"]):
            try:
                info = getattr(proc, "info", None) or {}
                pid = info.get("pid")
                if pid is None:
                    pid = proc.pid
                pid = int(pid)
                name = (info.get("name") or "").lower()
                if pid <= 4 or pid == self_pid:
                    continue
                if name in safe_whitelist:
                    skipped_whitelist += 1
                    if name and name not in skipped_whitelist_names:
                        skipped_whitelist_names.append(name)
                    continue
                if name in PROTECTED_PROCESSES:
                    skipped_protected += 1
                    continue

                mem_info = info.get("memory_info")
                if mem_info is None and hasattr(proc, "memory_info"):
                    try:
                        mem_info = proc.memory_info()
                    except Exception:
                        mem_info = None
                rss = getattr(mem_info, "rss", None) if mem_info is not None else None
                if rss is not None and int(rss) < MIN_WORKING_SET_BYTES:
                    skipped_small += 1
                    continue

                cpu = info.get("cpu_percent")
                if isinstance(cpu, (int, float)) and float(cpu) >= BUSY_CPU_SKIP_PERCENT:
                    skipped_busy += 1
                    continue

                handle = open_proc(pid)
                if not handle:
                    skipped_access += 1
                    continue
                try:
                    if trim(handle):
                        processes_flushed += 1
                finally:
                    try:
                        close(handle)
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError):
                continue
            except Exception:
                continue

        mem_after = read_memory()
        available_after_mb = float(mem_after.available) / (1024 ** 2)
        used_after_mb = (float(mem_after.total) - float(mem_after.available)) / (1024 ** 2)
        percent_after = float(mem_after.percent)
        freed_mb = max(0.0, available_after_mb - available_before_mb)

        logger.info(
            f"[RAM Optimizer] EmptyWorkingSet trên {processes_flushed} tiến trình. "
            f"RAM trống: {available_before_mb:.1f} -> {available_after_mb:.1f} MB "
            f"(+{freed_mb:.1f} MB). Bỏ qua ghim={skipped_whitelist}, "
            f"hệ thống={skipped_protected}, nhỏ={skipped_small}, bận={skipped_busy}."
        )

        result = {
            "success": True,
            "debounced": False,
            "processes_flushed": processes_flushed,
            "skipped_whitelist": skipped_whitelist,
            "skipped_whitelist_names": skipped_whitelist_names,
            "skipped_protected": skipped_protected,
            "skipped_small": skipped_small,
            "skipped_busy": skipped_busy,
            "skipped_access": skipped_access,
            "available_before_mb": round(available_before_mb, 1),
            "available_after_mb": round(available_after_mb, 1),
            "used_before_mb": round(used_before_mb, 1),
            "used_after_mb": round(used_after_mb, 1),
            "freed_mb": round(freed_mb, 1),
            "percent_before": percent_before,
            "percent_after": percent_after,
            "note_vi": RAM_TRIM_NOTE_VI,
        }
        cls._last_run_time = time.time()
        cls._last_result = result
        return result
