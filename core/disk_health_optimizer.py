import os
import sys
import json
import ctypes
import logging
import subprocess
from typing import List, Dict, Any, Optional

logger = logging.getLogger("DiskHealthOptimizer")

class DiskHealthOptimizer:
    """
    Quản lý & Tối ưu hóa Sức khỏe Ổ cứng (SSD Health & TRIM Optimizer):
    - Đọc dữ liệu phần cứng ổ đĩa vật lý: NVMe, SSD, HDD qua S.M.A.R.T.
    - Quét chi tiết dung lượng các phân vùng ổ đĩa (C:, D:, ...).
    - Gửi lệnh SSD TRIM (Re-Trim / defrag /L) giải phóng cell nhớ NAND, duy trì tốc độ ghi tối đa.
    """

    @classmethod
    def is_admin(cls) -> bool:
        """Kiểm tra quyền Administrator (dual check)."""
        try:
            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
                return True
        except Exception:
            pass
        try:
            import subprocess
            _no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            r = subprocess.run("net session", shell=True, capture_output=True, timeout=2, creationflags=_no_win)
            return r.returncode == 0
        except Exception:
            return False

    @classmethod
    def get_physical_disks(cls) -> List[Dict[str, Any]]:
        """
        Lấy danh sách các ổ cứng vật lý trên hệ thống (SSD, NVMe, HDD).
        """
        disks = []
        ps_cmd = (
            "Get-PhysicalDisk | Select-Object DeviceId, FriendlyName, MediaType, BusType, "
            "OperationalStatus, HealthStatus, Size | ConvertTo-Json -Compress"
        )

        try:
            _no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=_no_win
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]

                for d in data:
                    raw_size = d.get("Size") or 0
                    size_gb = raw_size / (1024**3)

                    media_type = str(d.get("MediaType") or "SSD").strip()
                    bus_type = str(d.get("BusType") or "NVMe").strip()
                    name = str(d.get("FriendlyName") or "Ổ cứng vật lý").strip()

                    # Đôi khi Windows nhận NVMe là MediaType "Unspecified" nhưng BusType là "NVMe"
                    if bus_type.upper() == "NVME" and media_type.upper() in ["UNSPECIFIED", "UNKNOWN"]:
                        media_type = "SSD (NVMe)"
                    elif media_type.upper() == "SSD":
                        media_type = f"SSD ({bus_type})"

                    health = str(d.get("HealthStatus") or "Healthy").strip()
                    status = str(d.get("OperationalStatus") or "OK").strip()

                    disks.append({
                        "device_id": str(d.get("DeviceId") or "0"),
                        "name": name,
                        "media_type": media_type,
                        "bus_type": bus_type,
                        "health_status": health,
                        "operational_status": status,
                        "size_bytes": raw_size,
                        "size_gb": size_gb,
                        "is_ssd": "SSD" in media_type.upper() or "NVME" in bus_type.upper()
                    })
        except Exception as e:
            logger.warning(f"Lỗi lấy thông tin PhysicalDisk qua PowerShell: {e}")

        # Fallback qua WMIC nếu PowerShell không trả về ổ
        if not disks:
            disks = cls._fallback_wmic_disks()

        return disks

    @classmethod
    def _fallback_wmic_disks(cls) -> List[Dict[str, Any]]:
        disks = []
        try:
            _no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            res = subprocess.run(
                ["wmic", "diskdrive", "get", "DeviceID,Model,Size,Status,InterfaceType", "/format:list"],
                capture_output=True, text=True, timeout=8,
                creationflags=_no_win
            )
            if res.returncode == 0:
                current: Dict[str, str] = {}
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        current[k.strip().lower()] = v.strip()
                    elif not line and current:
                        if "model" in current:
                            size_bytes = int(current.get("size") or 0)
                            disks.append({
                                "device_id": current.get("deviceid", "0"),
                                "name": current.get("model", "Ổ cứng"),
                                "media_type": "Ổ Cứng",
                                "bus_type": current.get("interfacetype", "SATA"),
                                "health_status": "Healthy" if current.get("status", "").upper() == "OK" else "Warning",
                                "operational_status": current.get("status", "OK"),
                                "size_bytes": size_bytes,
                                "size_gb": size_bytes / (1024**3),
                                "is_ssd": True
                            })
                        current = {}
        except Exception as e:
            logger.debug(f"WMIC fallback error: {e}")
        return disks

    @classmethod
    def get_volumes(cls) -> List[Dict[str, Any]]:
        """
        Lấy danh sách các phân vùng ổ đĩa cố định (C:, D:, ...).
        """
        volumes = []
        ps_cmd = (
            "Get-Volume | Where-Object { $_.DriveType -eq 'Fixed' -and $_.DriveLetter } | "
            "Select-Object DriveLetter, FileSystemLabel, FileSystem, SizeRemaining, Size | ConvertTo-Json -Compress"
        )

        try:
            _no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=8,
                creationflags=_no_win
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]

                for v in data:
                    letter = str(v.get("DriveLetter") or "").strip()
                    if not letter:
                        continue

                    total_bytes = v.get("Size") or 0
                    free_bytes = v.get("SizeRemaining") or 0
                    used_bytes = total_bytes - free_bytes

                    total_gb = total_bytes / (1024**3)
                    free_gb = free_bytes / (1024**3)
                    used_gb = used_bytes / (1024**3)
                    used_pct = (used_bytes / total_bytes * 100) if total_bytes > 0 else 0

                    label = v.get("FileSystemLabel") or ("Hệ điều hành" if letter.upper() == "C" else "Dữ liệu")
                    fs = v.get("FileSystem") or "NTFS"

                    volumes.append({
                        "letter": letter.upper(),
                        "path": f"{letter.upper()}:",
                        "label": label,
                        "file_system": fs,
                        "total_gb": total_gb,
                        "used_gb": used_gb,
                        "free_gb": free_gb,
                        "used_pct": used_pct
                    })
        except Exception as e:
            logger.warning(f"Lỗi lấy volume list qua PowerShell: {e}")

        volumes.sort(key=lambda x: x["letter"])
        return volumes

    @classmethod
    def run_trim(cls, drive_letter: str) -> Dict[str, Any]:
        """
        Gửi lệnh TRIM (ReTrim) cho phân vùng ổ cứng SSD.
        Lệnh tương đương: defrag <Drive>: /L
        """
        letter = drive_letter.replace(":", "").strip().upper()
        drive_path = f"{letter}:"

        logger.info(f"Đang gửi lệnh SSD TRIM cho phân vùng {drive_path}...")

        is_elevated = cls.is_admin()

        if is_elevated:
            try:
                _no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
                res = subprocess.run(
                    ["defrag", drive_path, "/L"],
                    capture_output=True, text=True, timeout=45,
                    creationflags=_no_win
                )
                if res.returncode == 0 and "insufficient privileges" not in res.stdout.lower():
                    logger.info(f"Tối ưu TRIM {drive_path} thành công:\n{res.stdout.strip()}")
                    return {
                        "success": True,
                        "drive": drive_path,
                        "message": f"Tối ưu hóa SSD TRIM hoàn tất cho ổ {drive_path}. Các cell nhớ trống đã được làm mới.",
                        "output": res.stdout.strip()
                    }
                else:
                    err_msg = res.stdout.strip() or res.stderr.strip()
                    logger.warning(f"Lỗi khi defrag /L {drive_path}: {err_msg}")
                    return {
                        "success": False,
                        "drive": drive_path,
                        "message": f"Không thể thực thi TRIM: {err_msg}"
                    }
            except Exception as e:
                return {"success": False, "drive": drive_path, "message": str(e)}
        else:
            # Yêu cầu quyền Administrator qua ShellExecute
            try:
                # Chạy defrag /L qua UAC RunAs
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", "defrag", f"{drive_path} /L", None, 1
                )
                if ret > 32:
                    return {
                        "success": True,
                        "drive": drive_path,
                        "message": f"Đã gửi yêu cầu quyền Admin để thực thi SSD TRIM cho ổ {drive_path}."
                    }
                else:
                    return {
                        "success": False,
                        "drive": drive_path,
                        "message": "Người dùng đã từ chối cấp quyền Administrator (UAC Prompt)."
                    }
            except Exception as e:
                return {"success": False, "drive": drive_path, "message": str(e)}

    @classmethod
    def run_trim_all(cls) -> Dict[str, Any]:
        """
        Tự động gửi lệnh TRIM cho tất cả các phân vùng SSD trên hệ thống.
        """
        vols = cls.get_volumes()
        results = []
        success_count = 0

        for v in vols:
            res = cls.run_trim(v["letter"])
            results.append(res)
            if res.get("success"):
                success_count += 1

        return {
            "total_drives": len(vols),
            "success_count": success_count,
            "results": results
        }

    @classmethod
    def get_summary(cls) -> Dict[str, Any]:
        """
        Báo cáo tổng quan về sức khỏe ổ cứng & lưu trữ.
        """
        disks = cls.get_physical_disks()
        vols = cls.get_volumes()

        total_storage_gb = sum(d.get("size_gb", 0) for d in disks)
        total_free_gb = sum(v.get("free_gb", 0) for v in vols)

        ssd_count = sum(1 for d in disks if d.get("is_ssd"))
        hdd_count = len(disks) - ssd_count

        all_healthy = all(d.get("health_status", "").upper() == "HEALTHY" for d in disks)
        overall_status = "HEALTHY" if all_healthy else "WARNING"

        return {
            "overall_status": overall_status,
            "disk_count": len(disks),
            "ssd_count": ssd_count,
            "hdd_count": hdd_count,
            "total_storage_gb": total_storage_gb,
            "total_free_gb": total_free_gb,
            "disks": disks,
            "volumes": vols
        }
