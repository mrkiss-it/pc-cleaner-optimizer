"""
core/winsxs_cleaner.py – Windows Component Store (WinSxS), Update Caches & DriverStore Purge Engine (v3.6 Pro).
Cung cấp giải pháp tối ưu hóa chuyên sâu các tệp tin hệ thống ngốn nhiều dung lượng nhất trên ổ C::
1. Quét và dọn dẹp các thư mục đệm của Windows Update (SoftwareDistribution\Download, DeliveryOptimization).
2. Xóa các tệp nhật ký khổng lồ của Windows Servicing (CBS logs, DISM logs) và Crash Dumps (WER).
3. Rà soát kho DriverStore (FileRepository) thông qua pnputil, phát hiện các phiên bản Driver OEM trùng lặp/cũ.
4. Tích hợp chuẩn DISM của Microsoft: StartComponentCleanup, ResetBase (Deep Purge) và RestoreHealth.
"""

import os
import re
import sys
import time
import shutil
import ctypes
import tempfile
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set

from core.logger import logger
from core.service_optimizer import ServiceOptimizer

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0


def _get_silent_kwargs() -> Dict[str, Any]:
    """Trả về các tham số ngăn hoàn toàn việc bật/nháy cửa sổ console (conhost/cmd/pnputil)."""
    kwargs: Dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs



# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class UpdateCacheItem:
    """Đại diện cho một danh mục bộ nhớ đệm cập nhật hoặc nhật ký hệ thống."""
    key: str
    name: str
    path: str
    size_mb: float = 0.0
    file_count: int = 0
    description: str = ""
    safety: str = "safe"             # safe | caution
    is_protected_service: bool = False
    service_name: Optional[str] = None

    @property
    def size_display(self) -> str:
        if self.size_mb >= 1024:
            return f"{self.size_mb / 1024:.2f} GB"
        return f"{self.size_mb:.1f} MB"


@dataclass
class OemDriverItem:
    """Đại diện cho một gói Driver OEM cài đặt trên hệ thống từ pnputil."""
    published_name: str              # VD: oem85.inf
    original_name: str               # VD: ibtusb.inf
    provider: str = "Không rõ"       # VD: Intel
    class_name: str = "Khác"         # VD: Net, Bluetooth, Media
    class_guid: str = ""
    version: str = "Không rõ"        # VD: 22.120.0.3
    date: str = "Không rõ"           # VD: 01/31/2022
    signer: str = ""
    is_duplicate: bool = False       # Có phiên bản mới hơn của cùng original_name
    is_active: bool = False          # Đang là phiên bản mới nhất / đang nạp chính thức
    is_in_use: bool = False          # Đang được phần cứng/thiết bị nạp hoặc liên kết (Windows bảo vệ)

    @property
    def display_title(self) -> str:
        return f"{self.original_name} ({self.class_name})"


@dataclass
class DismReport:
    """Báo cáo phân tích thành phần WinSxS từ DISM."""
    explorer_size_mb: float = 0.0
    actual_size_mb: float = 0.0
    shared_size_mb: float = 0.0
    backups_size_mb: float = 0.0
    cache_size_mb: float = 0.0
    superseded_count: int = 0
    cleanup_recommended: bool = False
    raw_output: str = ""


# ---------------------------------------------------------------------------
# Core Engine: WinSxSCleaner
# ---------------------------------------------------------------------------

class WinSxSCleaner:
    """
    Trình quản lý dọn dẹp kho thành phần WinSxS, bộ đệm cập nhật Windows
    và kho lưu trữ DriverStore OEM Driver.
    """

    _cached_drivers: Optional[Tuple[List[OemDriverItem], List[OemDriverItem]]] = None
    _cached_drivers_ts: float = 0.0
    _cached_in_use: Optional[Set[str]] = None
    _cached_in_use_ts: float = 0.0
    _cached_caches: Optional[List[UpdateCacheItem]] = None
    _cached_caches_ts: float = 0.0
    _cached_caches_fingerprint: Optional[Tuple[Tuple[str, float, int], ...]] = None
    _cached_summary: Optional[Dict[str, Any]] = None
    _cached_summary_ts: float = 0.0
    # Idle AI badge / Smart Suggestions refresh every ~10s. A full SoftwareDistribution
    # walk must not run on that cadence — cache scans for CACHE_TTL (5 minutes).
    # Manual/on-demand paths pass force_refresh=True (dialog open, Làm mới, after clean).
    CACHE_TTL: float = 300.0

    @classmethod
    def invalidate_cache(cls) -> None:
        """Xóa sạch cache quét drivers, update caches và get_summary để quét mới."""
        cls._cached_drivers = None
        cls._cached_drivers_ts = 0.0
        cls._cached_in_use = None
        cls._cached_in_use_ts = 0.0
        cls._cached_caches = None
        cls._cached_caches_ts = 0.0
        cls._cached_caches_fingerprint = None
        cls._cached_summary = None
        cls._cached_summary_ts = 0.0

    # Danh mục các đường dẫn đệm Windows Update & System Logs
    CACHE_TARGETS = [
        {
            "key": "update_download",
            "name": "Tệp Tải Về Windows Update",
            "path": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SoftwareDistribution", "Download"),
            "desc": "Các file cài đặt cập nhật đã tải về hoàn tất, an toàn để xóa sạch.",
            "safety": "safe",
            "is_protected_service": True,
            "service_name": "wuauserv",
        },
        {
            "key": "delivery_optimization",
            "name": "Bộ Nhớ Đệm Delivery Optimization",
            "path": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SoftwareDistribution", "DeliveryOptimization"),
            "desc": "Bộ nhớ đệm chia sẻ tải cập nhật ngang hàng (P2P Update Cache).",
            "safety": "safe",
            "is_protected_service": False,
            "service_name": None,
        },
        {
            "key": "cbs_logs",
            "name": "Nhật Ký Servicing (CBS Logs)",
            "path": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Logs", "CBS"),
            "desc": "Các file log ghi nhận quá trình cài đặt cập nhật Windows (thường phình to nhiều GB).",
            "safety": "safe",
            "is_protected_service": False,
            "service_name": None,
        },
        {
            "key": "dism_logs",
            "name": "Nhật Ký Quản Trị DISM Logs",
            "path": os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Logs", "DISM"),
            "desc": "File log lịch sử chạy công cụ DISM của hệ thống.",
            "safety": "safe",
            "is_protected_service": False,
            "service_name": None,
        },
        {
            "key": "wer_dumps",
            "name": "Báo Cáo Lỗi Windows (WER Reports)",
            "path": os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows", "WER"),
            "desc": "Các tệp ghi nhận sự cố, crash dump và báo cáo lỗi phần mềm.",
            "safety": "safe",
            "is_protected_service": False,
            "service_name": None,
        },
        {
            "key": "windows_old",
            "name": "Bản Sao Lưu Windows Cũ (Windows.old)",
            "path": os.path.join(os.environ.get("SystemDrive", "C:"), "Windows.old"),
            "desc": "Bản sao lưu phiên bản Windows cũ sau khi nâng cấp lớn (thường chiếm 10-30 GB).",
            "safety": "caution",
            "is_protected_service": False,
            "service_name": None,
        },
        {
            "key": "windows_bt",
            "name": "File Tạm Cài Đặt Windows ($WINDOWS.~BT)",
            "path": os.path.join(os.environ.get("SystemDrive", "C:"), "$WINDOWS.~BT"),
            "desc": "Thư mục tạm sinh ra trong các đợt nâng cấp Windows.",
            "safety": "safe",
            "is_protected_service": False,
            "service_name": None,
        },
        {
            "key": "windows_ws",
            "name": "File Tạm Nâng Cấp Windows ($WINDOWS.~WS)",
            "path": os.path.join(os.environ.get("SystemDrive", "C:"), "$WINDOWS.~WS"),
            "desc": "Thư mục tạm của Windows Setup Media Creation Tool.",
            "safety": "safe",
            "is_protected_service": False,
            "service_name": None,
        },
    ]

    # ------------------------------------------------------------------
    # 1. Update Caches Scanner & Cleaner
    # ------------------------------------------------------------------

    @staticmethod
    def _caches_fingerprint(items: List[UpdateCacheItem]) -> Tuple[Tuple[str, float, int], ...]:
        return tuple((c.key, round(c.size_mb, 2), c.file_count) for c in items)

    @classmethod
    def scan_update_caches(cls, force_refresh: bool = False) -> List[UpdateCacheItem]:
        """
        Quét dung lượng và số lượng tệp của các thư mục đệm Windows Update & Logs.
        Hoạt động hoàn toàn Offline, tốc độ cao, không yêu cầu quyền Admin để đọc.

        Kết quả được cache ``CACHE_TTL`` giây (5 phút) vì AI badge / Smart Suggestions
        gọi ``get_summary()`` mỗi ~10 giây khi idle. Truyền ``force_refresh=True``
        khi người dùng mở dialog, bấm Làm mới, hoặc sau khi dọn dẹp.
        """
        now = time.time()
        if (
            not force_refresh
            and cls._cached_caches is not None
            and (now - cls._cached_caches_ts < cls.CACHE_TTL)
        ):
            logger.debug(
                f"[WinSxSCleaner] Dùng cache {len(cls._cached_caches)} danh mục đệm "
                f"(TTL {cls.CACHE_TTL:.0f}s, tránh quét lại mỗi ~10s)."
            )
            return cls._cached_caches

        results: List[UpdateCacheItem] = []

        for target in cls.CACHE_TARGETS:
            path = target["path"]
            if not os.path.exists(path):
                continue

            size_bytes = 0
            file_count = 0
            try:
                for root, _, files in os.walk(path):
                    for f in files:
                        try:
                            fp = os.path.join(root, f)
                            size_bytes += os.path.getsize(fp)
                            file_count += 1
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"[WinSxSCleaner] Không thể quét sâu {path}: {e}")

            size_mb = round(size_bytes / (1024 * 1024), 2)
            results.append(UpdateCacheItem(
                key=target["key"],
                name=target["name"],
                path=path,
                size_mb=size_mb,
                file_count=file_count,
                description=target["desc"],
                safety=target["safety"],
                is_protected_service=target.get("is_protected_service", False),
                service_name=target.get("service_name"),
            ))

        fingerprint = cls._caches_fingerprint(results)
        changed = (
            cls._cached_caches_fingerprint is not None
            and fingerprint != cls._cached_caches_fingerprint
        )
        msg = f"[WinSxSCleaner] Đã quét {len(results)} danh mục đệm hệ thống & cập nhật."
        # Routine idle scans stay at DEBUG so app.log is not flooded.
        # INFO only for user-initiated refresh or when totals actually changed.
        if force_refresh or changed:
            logger.info(msg)
        else:
            logger.debug(msg)

        cls._cached_caches = results
        cls._cached_caches_ts = now
        cls._cached_caches_fingerprint = fingerprint
        return results

    @classmethod
    def clean_cache_item(cls, item: UpdateCacheItem, dry_run: bool = False) -> Tuple[bool, str, int, float]:
        """
        Dọn dẹp một mục bộ nhớ đệm cập nhật.
        Nếu mục yêu cầu tạm dừng service (wuauserv), hệ thống sẽ dừng an toàn và khởi động lại sau khi dọn.
        Trả về: (thành công, thông báo, số file đã xóa, dung lượng MB giải phóng).
        """
        if dry_run:
            return True, f"[Dry-run] Sẽ xóa {item.file_count} tệp ({item.size_display}) tại {item.path}", item.file_count, item.size_mb

        if not os.path.exists(item.path):
            return True, f"Thư mục không tồn tại: {item.path}", 0, 0.0

        need_stop_svc = item.is_protected_service and item.service_name
        if need_stop_svc:
            ServiceOptimizer.set_service_status(item.service_name, start=False)

        deleted_files = 0
        freed_bytes = 0
        errors = []

        # Tiến hành xóa các file và thư mục con bên trong item.path
        try:
            for entry in os.scandir(item.path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        sz = entry.stat().st_size
                        os.remove(entry.path)
                        deleted_files += 1
                        freed_bytes += sz
                    elif entry.is_dir(follow_symlinks=False):
                        # Tính dung lượng thư mục con trước khi xóa
                        sub_sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(entry.path) for f in fs)
                        shutil.rmtree(entry.path, ignore_errors=False)
                        deleted_files += 1
                        freed_bytes += sub_sz
                except Exception as e:
                    errors.append(str(e))
        except Exception as e:
            errors.append(f"Không thể mở thư mục: {str(e)}")

        # Nếu còn file bị khóa hoặc không đủ quyền, thử chạy lệnh elevated rmdir
        if errors and os.path.exists(item.path):
            cmd = f'/c del /f /s /q "{item.path}\\*" & for /d %i in ("{item.path}\\*") do rmdir /s /q "%i"'
            ServiceOptimizer._run_elevated_cmd(cmd)

        if need_stop_svc:
            ServiceOptimizer.set_service_status(item.service_name, start=True)

        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        msg = f"Đã dọn dẹp {deleted_files} tệp ({freed_mb:.1f} MB) tại {item.name}."
        if errors:
            msg += f" (Một số tệp hệ thống đang mở không thể xóa)."

        logger.info(f"[WinSxSCleaner] {msg}")
        cls.invalidate_cache()
        return True, msg, deleted_files, freed_mb

    # ------------------------------------------------------------------
    # 2. DriverStore & OEM Drivers Scanner & Deduplicator
    # ------------------------------------------------------------------

    @classmethod
    def scan_oem_drivers(cls, force_refresh: bool = False) -> Tuple[List[OemDriverItem], List[OemDriverItem]]:
        """
        Rà soát toàn bộ các gói Driver OEM của bên thứ 3 trong kho DriverStore qua `pnputil /enum-drivers`.
        Tự động nhóm theo tên gốc (original_name) để phát hiện các phiên bản driver cũ bị bỏ lại.
        Trả về: (tất cả_driver_oem, driver_trùng_lặp_khuyên_dọn).
        """
        now = time.time()
        if not force_refresh and cls._cached_drivers is not None and (now - cls._cached_drivers_ts < cls.CACHE_TTL):
            return cls._cached_drivers

        all_drivers: List[OemDriverItem] = []
        try:
            res = subprocess.run(
                ["pnputil", "/enum-drivers"],
                capture_output=True,
                text=True,
                **_get_silent_kwargs()
            )
            output = res.stdout or ""
        except Exception as e:
            logger.error(f"[WinSxSCleaner] Lỗi khi thực thi pnputil: {e}")
            return [], []

        current: Dict[str, str] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line:
                if current and "published_name" in current:
                    all_drivers.append(cls._parse_oem_driver_dict(current))
                    current = {}
                continue

            if ":" in line:
                parts = line.split(":", 1)
                k = parts[0].strip().lower()
                v = parts[1].strip() if len(parts) > 1 else ""

                if "published name" in k:
                    current["published_name"] = v
                elif "original name" in k:
                    current["original_name"] = v
                elif "provider name" in k:
                    current["provider_name"] = v
                elif "class name" in k:
                    current["class_name"] = v
                elif "class guid" in k:
                    current["class_guid"] = v
                elif "driver version" in k:
                    current["driver_version"] = v
                elif "signer name" in k:
                    current["signer_name"] = v

        if current and "published_name" in current:
            all_drivers.append(cls._parse_oem_driver_dict(current))

        in_use_infs = cls.get_in_use_driver_infs(force_refresh=force_refresh)

        # Nhóm theo (original_name, class_name) để phát hiện bản trùng lặp
        from collections import defaultdict
        groups = defaultdict(list)
        for d in all_drivers:
            d.is_in_use = (d.published_name.lower() in in_use_infs)
            if d.original_name:
                key = (d.original_name.lower(), d.class_name.lower())
                groups[key].append(d)

        duplicates: List[OemDriverItem] = []
        for (orig, cls_name), list_d in groups.items():
            if len(list_d) > 1:
                # Sắp xếp giảm dần theo ngày và số hiệu phiên bản: phần tử đầu tiên là phiên bản mới nhất
                list_d.sort(
                    key=lambda x: (cls._parse_date(x.date), cls._parse_version_tuple(x.version)),
                    reverse=True
                )
                list_d[0].is_active = True
                for drv in list_d[1:]:
                    drv.is_duplicate = True
                    duplicates.append(drv)

        cleanable_count = sum(1 for d in duplicates if not d.is_in_use)
        logger.info(
            f"[WinSxSCleaner] Nhận diện {len(all_drivers)} OEM Drivers, trong đó {len(duplicates)} gói phiên bản cũ "
            f"({cleanable_count} gói có thể dọn dẹp, {len(duplicates) - cleanable_count} gói được Windows bảo vệ an toàn)."
        )
        cls._cached_drivers = (all_drivers, duplicates)
        cls._cached_drivers_ts = now
        return all_drivers, duplicates

    @staticmethod
    def _parse_version_tuple(ver_str: str) -> tuple:
        parts = []
        for p in ver_str.replace("-", ".").split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    @staticmethod
    def _parse_date(date_str: str) -> str:
        try:
            m, d, y = date_str.split("/")
            return f"{y.zfill(4)}{m.zfill(2)}{d.zfill(2)}"
        except Exception:
            return "00000000"

    @classmethod
    def get_in_use_driver_infs(cls, force_refresh: bool = False) -> Set[str]:
        """
        Lấy danh sách các tệp INF đang được liên kết hoặc sử dụng bởi các thiết bị phần cứng thực tế.
        Windows PnP sẽ tự động từ chối xóa các gói driver này để bảo vệ an toàn phần cứng.
        """
        now = time.time()
        if not force_refresh and cls._cached_in_use is not None and (now - cls._cached_in_use_ts < cls.CACHE_TTL):
            return cls._cached_in_use

        in_use = set()
        try:
            res = subprocess.run(
                ["pnputil", "/enum-devices", "/drivers"],
                capture_output=True,
                text=True,
                **_get_silent_kwargs()
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("Driver Name:"):
                        inf = line.split(":", 1)[1].strip().lower()
                        if inf.endswith(".inf"):
                            in_use.add(inf)
        except Exception as e:
            logger.debug(f"[WinSxSCleaner] Lỗi kiểm tra in-use drivers: {e}")

        cls._cached_in_use = in_use
        cls._cached_in_use_ts = now
        return in_use

    @staticmethod
    def _parse_oem_driver_dict(d: Dict[str, str]) -> OemDriverItem:
        ver_raw = d.get("driver_version", "")
        # Tách date và version từ "01/31/2022 22.120.0.3"
        parts = ver_raw.split()
        date_part = parts[0] if len(parts) >= 1 else "Không rõ"
        version_part = parts[1] if len(parts) >= 2 else ver_raw

        return OemDriverItem(
            published_name=d.get("published_name", ""),
            original_name=d.get("original_name", ""),
            provider=d.get("provider_name", "Không rõ"),
            class_name=d.get("class_name", "Khác"),
            class_guid=d.get("class_guid", ""),
            version=version_part,
            date=date_part,
            signer=d.get("signer_name", ""),
            is_duplicate=False,
            is_active=False,
            is_in_use=False,
        )

    @classmethod
    def clean_duplicate_drivers(cls, drivers_to_clean: List[OemDriverItem], dry_run: bool = False) -> Tuple[int, int, str]:
        """
        Dọn dẹp các gói Driver OEM cũ thông qua lệnh `pnputil /delete-driver <oemN.inf>`.
        Lưu ý: Nếu một driver đang được sử dụng trực tiếp bởi thiết bị, Windows sẽ tự động
        từ chối xóa để đảm bảo an toàn tuyệt đối cho phần cứng.
        Trả về: (số driver đã xóa thành công, số driver bị từ chối/bảo vệ, thông báo).
        """
        if dry_run:
            return len(drivers_to_clean), 0, f"[Dry-run] Sẽ yêu cầu xóa {len(drivers_to_clean)} gói driver OEM cũ."

        in_use_blocked = [d for d in drivers_to_clean if d.is_in_use]
        eligible_to_clean = [d for d in drivers_to_clean if not d.is_in_use]

        if not eligible_to_clean:
            msg = (
                f"Tất cả {len(in_use_blocked)} gói driver OEM này hiện đang được phần cứng máy tính "
                "(Bluetooth, Wi-Fi, Máy in...) trực tiếp sử dụng. "
                "Windows đã tự động kích hoạt cơ chế bảo vệ phần cứng để đảm bảo kết nối hoạt động 100% ổn định."
            )
            logger.info(f"[WinSxSCleaner] {msg}")
            return 0, len(in_use_blocked), msg

        success_count = 0
        failed_count = len(in_use_blocked)

        for drv in eligible_to_clean:
            if not drv.published_name or not drv.published_name.endswith(".inf"):
                continue

            res = subprocess.run(
                ["pnputil", "/delete-driver", drv.published_name],
                capture_output=True,
                text=True,
                **_get_silent_kwargs()
            )

            if res.returncode == 0:
                success_count += 1
            else:
                # Nếu thiếu quyền Administrator, thử chạy qua elevated
                cmd = f"pnputil /delete-driver {drv.published_name}"
                ok, _ = ServiceOptimizer._run_elevated_cmd(f"/c {cmd}")
                if ok:
                    success_count += 1
                else:
                    failed_count += 1

        cls.invalidate_cache()

        msg = f"Đã dọn dẹp thành công {success_count} gói driver OEM cũ."
        if failed_count > 0:
            msg += f" ({failed_count} gói được Windows giữ lại an toàn do phần cứng đang sử dụng)."

        logger.info(f"[WinSxSCleaner] {msg}")
        return success_count, failed_count, msg

    # ------------------------------------------------------------------
    # 3. WinSxS & DISM Engine
    # ------------------------------------------------------------------

    @classmethod
    def get_winsxs_info(cls) -> Dict[str, Any]:
        """
        Lấy thông tin cơ bản về thư mục WinSxS (đường dẫn, dung lượng ước tính).
        """
        winsxs_path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "WinSxS")
        exists = os.path.exists(winsxs_path)
        return {
            "path": winsxs_path,
            "exists": exists,
        }

    @classmethod
    def run_dism_cleanup(cls, reset_base: bool = False) -> Tuple[bool, str]:
        """
        Thực thi chuẩn DISM StartComponentCleanup của Microsoft:
        - reset_base=False: Dọn dẹp các thành phần bị thay thế nhưng vẫn giữ khả năng gỡ bỏ bản cập nhật trước đó.
        - reset_base=True: Deep Purge - Xóa bỏ hoàn toàn các bản sao lưu cập nhật cũ, giải phóng dung lượng tối đa.
        """
        flag = "/ResetBase" if reset_base else ""
        cmd = f"dism.exe /Online /Cleanup-Image /StartComponentCleanup {flag}".strip()

        logger.info(f"[WinSxSCleaner] Bắt đầu dọn dẹp WinSxS qua DISM: {cmd}")

        # Thử chạy trực tiếp nếu process đã có quyền Admin
        if ctypes.windll.shell32.IsUserAnAdmin() != 0:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, **_get_silent_kwargs())
            if res.returncode == 0:
                return True, "Dọn dẹp kho thành phần WinSxS hoàn tất thành công!"
            return False, f"Lỗi DISM (Mã: {res.returncode}): {res.stderr or res.stdout}"

        # Nếu chưa có quyền Admin -> Kích hoạt UAC Elevation
        temp_log = os.path.join(tempfile.gettempdir(), "pc_cleaner_dism_cleanup.log")
        elevated_cmd = f'/c {cmd} > "{temp_log}" 2>&1'

        ok, msg = ServiceOptimizer._run_elevated_cmd(elevated_cmd, timeout_ms=600000) # 10 phút tối đa cho DISM
        if ok:
            log_content = ""
            if os.path.exists(temp_log):
                try:
                    with open(temp_log, "r", encoding="utf-8", errors="ignore") as f:
                        log_content = f.read()
                except Exception:
                    pass

            if "The operation completed successfully" in log_content or "Thao tác đã hoàn thành" in log_content:
                return True, "Dọn dẹp WinSxS qua DISM hoàn tất thành công!"
            return True, f"Lệnh DISM đã thực thi. Báo cáo: {log_content[:300]}..."
        else:
            return False, f"Không thể thực thi lệnh DISM: {msg}"

    @classmethod
    def run_dism_health_repair(cls) -> Tuple[bool, str]:
        """
        Kiểm tra và sửa chữa tính toàn vẹn hệ thống qua DISM RestoreHealth & SFC Scannow.
        """
        cmd = "dism.exe /Online /Cleanup-Image /RestoreHealth & sfc /scannow"
        logger.info("[WinSxSCleaner] Bắt đầu kiểm tra và sửa lỗi hệ thống (RestoreHealth + SFC)...")

        if ctypes.windll.shell32.IsUserAnAdmin() != 0:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, **_get_silent_kwargs())
            if res.returncode == 0:
                return True, "Kiểm tra và phục hồi tính toàn vẹn hệ thống thành công!"
            return False, f"Lỗi RestoreHealth: {res.stderr or res.stdout}"

        temp_log = os.path.join(tempfile.gettempdir(), "pc_cleaner_restore_health.log")
        elevated_cmd = f'/c {cmd} > "{temp_log}" 2>&1'
        ok, msg = ServiceOptimizer._run_elevated_cmd(elevated_cmd, timeout_ms=600000)
        return ok, f"Kết quả kiểm tra hệ thống: {msg}"

    # ------------------------------------------------------------------
    # 4. Summary Aggregator
    # ------------------------------------------------------------------

    @classmethod
    def get_summary(cls, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Tổng hợp nhanh toàn bộ số liệu:
        - Tổng dung lượng bộ đệm cập nhật và nhật ký servicing có thể dọn ngay.
        - Số lượng gói driver OEM cũ trùng lặp.

        Cache ``CACHE_TTL`` (5 phút). AIAdvisor._rule_winsxs / badge 10s must
        hit this cache — do not walk or call pnputil on that cadence.
        ``force_refresh=True`` for dialog / Làm mới / after clean.
        """
        now = time.time()
        if (
            not force_refresh
            and cls._cached_summary is not None
            and (now - cls._cached_summary_ts < cls.CACHE_TTL)
        ):
            return cls._cached_summary

        caches = cls.scan_update_caches(force_refresh=force_refresh)
        total_cache_mb = sum(c.size_mb for c in caches)
        total_files = sum(c.file_count for c in caches)

        _, duplicate_drivers = cls.scan_oem_drivers(force_refresh=force_refresh)
        cleanable_count = sum(1 for d in duplicate_drivers if not d.is_in_use)
        protected_count = sum(1 for d in duplicate_drivers if d.is_in_use)

        summary = {
            "total_cache_mb": round(total_cache_mb, 2),
            "total_cache_files": total_files,
            "cache_categories_count": len(caches),
            "duplicate_drivers_count": len(duplicate_drivers),
            "cleanable_drivers_count": cleanable_count,
            "protected_drivers_count": protected_count,
            "caches": caches,
            "duplicate_drivers": duplicate_drivers,
        }
        cls._cached_summary = summary
        cls._cached_summary_ts = now
        return summary
