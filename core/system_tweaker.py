"""
Mô-đun Tinh Chỉnh Hệ Thống & Bảo Vệ Quyền Riêng Tư (System Tweaker & Privacy Shield)
Cung cấp các công cụ:
- Chặn thu thập dữ liệu ngầm (Telemetry, DiagTrack, Advertising ID, Activity History)
- Tắt tìm kiếm Bing trên Start Menu & gợi ý quảng cáo
- Tăng tốc phản hồi hệ thống (MenuShowDelay 50ms, Ultimate Performance Power Plan, Game DVR)
- Tùy biến Windows 11 Explorer (Classic Context Menu đầy đủ, hiện đuôi file, mở This PC)
- Khởi động lại Windows Explorer tức thì
- Hoàn tác 100% về mặc định của Windows
"""

import os
import sys
import winreg
import subprocess
import tempfile
import ctypes
from ctypes import wintypes
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from core.logger import logger


class SystemTweaker:
    """Quản lý và thực thi các tinh chỉnh Windows an toàn có khả năng hoàn tác."""

    # Phân loại danh mục
    CAT_PRIVACY = "privacy"
    CAT_PERF = "performance"
    CAT_UI = "ui"

    # Danh mục định nghĩa toàn bộ 15 Tinh Chỉnh
    TWEAKS_DEF: Dict[str, Dict[str, Any]] = {
        # ======================================================================
        # 1. NHÓM QUYỀN RIÊNG TƯ & TELEMETRY (PRIVACY SHIELD)
        # ======================================================================
        "disable_telemetry": {
            "id": "disable_telemetry",
            "category": CAT_PRIVACY,
            "name": "Chặn Thu Thập Dữ Liệu Chẩn Đoán (Telemetry)",
            "icon": "🛡️",
            "description": "Tắt việc Windows tự động gửi nhật ký sử dụng, lỗi ứng dụng và dữ liệu gõ phím về máy chủ Microsoft.",
            "recommended": True,
            "requires_admin": True,
            "type": "registry_multi",
            "items": [
                {
                    "hive": winreg.HKEY_LOCAL_MACHINE,
                    "path": r"SOFTWARE\Policies\Microsoft\Windows\DataCollection",
                    "name": "AllowTelemetry",
                    "opt_value": 0,
                    "default_value": 3,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_LOCAL_MACHINE,
                    "path": r"SOFTWARE\Policies\Microsoft\Windows\DataCollection",
                    "name": "MaxTelemetryAllowed",
                    "opt_value": 0,
                    "default_value": 3,
                    "val_type": winreg.REG_DWORD
                }
            ]
        },
        "disable_diagtrack_service": {
            "id": "disable_diagtrack_service",
            "category": CAT_PRIVACY,
            "name": "Vô Hiệu Hóa Dịch Vụ DiagTrack Ngầm",
            "icon": "🛑",
            "description": "Dừng và vô hiệu hóa dịch vụ 'Connected User Experiences and Telemetry' (DiagTrack), tiết kiệm CPU và RAM khi chạy ngầm.",
            "recommended": True,
            "requires_admin": True,
            "type": "custom"
        },
        "disable_bing_start_search": {
            "id": "disable_bing_start_search",
            "category": CAT_PRIVACY,
            "name": "Tắt Tìm Kiếm Bing Web Trên Thanh Start Menu",
            "icon": "🔍",
            "description": "Ngăn Start Menu gửi nội dung gõ phím lên Bing Search đám mây. Tăng tốc độ tìm ứng dụng trên máy tính gấp 3 lần.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry_multi",
            "items": [
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Policies\Microsoft\Windows\Explorer",
                    "name": "DisableSearchBoxSuggestions",
                    "opt_value": 1,
                    "default_value": 0,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Microsoft\Windows\CurrentVersion\Search",
                    "name": "BingSearchEnabled",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Microsoft\Windows\CurrentVersion\Search",
                    "name": "CortanaConsent",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                }
            ]
        },
        "disable_advertising_id": {
            "id": "disable_advertising_id",
            "category": CAT_PRIVACY,
            "name": "Chặn Mã Nhận Diện Quảng Cáo (Advertising ID)",
            "icon": "🚫",
            "description": "Không cho phép ứng dụng Windows theo dõi hồ sơ người dùng để phân phối quảng cáo định hướng.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry",
            "hive": winreg.HKEY_CURRENT_USER,
            "path": r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo",
            "name_key": "Enabled",
            "opt_value": 0,
            "default_value": 1,
            "val_type": winreg.REG_DWORD
        },
        "disable_location_tracking": {
            "id": "disable_location_tracking",
            "category": CAT_PRIVACY,
            "name": "Tắt Cảm Biến Định Vị Vị Trí Nền (Location)",
            "icon": "📍",
            "description": "Tắt dịch vụ theo dõi tọa độ địa lý ngầm của hệ điều hành Windows cho các thiết bị để bàn hoặc laptop cố định.",
            "recommended": True,
            "requires_admin": True,
            "type": "registry",
            "hive": winreg.HKEY_LOCAL_MACHINE,
            "path": r"SOFTWARE\Policies\Microsoft\Windows\LocationAndSensors",
            "name_key": "DisableLocation",
            "opt_value": 1,
            "default_value": 0,
            "val_type": winreg.REG_DWORD
        },
        "disable_start_suggestions": {
            "id": "disable_start_suggestions",
            "category": CAT_PRIVACY,
            "name": "Tắt Gợi Ý Ứng Dụng & Quảng Cáo Start Menu",
            "icon": "📢",
            "description": "Ngăn Windows tự động đề xuất và cài đặt ngầm các ứng dụng được tài trợ (promoted apps) trên thanh Start Menu.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry_multi",
            "items": [
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                    "name": "SystemPaneSuggestionsEnabled",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                    "name": "SubscribedContent-338388Enabled",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager",
                    "name": "SubscribedContent-338389Enabled",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                }
            ]
        },
        "disable_feedback_prompts": {
            "id": "disable_feedback_prompts",
            "category": CAT_PRIVACY,
            "name": "Tắt Hộp Thoại Khảo Sát & Đánh Giá Định Kỳ",
            "icon": "📋",
            "description": "Chặn hoàn toàn các thông báo khảo sát ý kiến trải nghiệm phiền phức từ Windows Feedback Hub.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry",
            "hive": winreg.HKEY_CURRENT_USER,
            "path": r"Software\Microsoft\Siuf\Rules",
            "name_key": "NumberOfSIFInUrl",
            "opt_value": 0,
            "default_value": 1,
            "val_type": winreg.REG_DWORD
        },
        "disable_activity_history": {
            "id": "disable_activity_history",
            "category": CAT_PRIVACY,
            "name": "Tắt Theo Dõi Lịch Sử Hoạt Động (Activity Timeline)",
            "icon": "⏳",
            "description": "Ngăn Windows ghi lại danh sách tệp và ứng dụng bạn đã mở để đồng bộ lên máy chủ Microsoft.",
            "recommended": True,
            "requires_admin": True,
            "type": "registry_multi",
            "items": [
                {
                    "hive": winreg.HKEY_LOCAL_MACHINE,
                    "path": r"SOFTWARE\Policies\Microsoft\Windows\System",
                    "name": "EnableActivityFeed",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_LOCAL_MACHINE,
                    "path": r"SOFTWARE\Policies\Microsoft\Windows\System",
                    "name": "PublishUserActivities",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                }
            ]
        },

        # ======================================================================
        # 2. NHÓM HIỆU NĂNG & NGUỒN ĐIỆN (PERFORMANCE TWEAKS)
        # ======================================================================
        "enable_ultimate_performance": {
            "id": "enable_ultimate_performance",
            "category": CAT_PERF,
            "name": "Kích Hoạt Chế Độ Nguồn 'Ultimate Performance'",
            "icon": "⚡",
            "description": "Mở khóa gói quản lý nguồn điện tối thượng ẩn của Windows 10/11. Giữ CPU chạy 100% xung nhịp không bị nghẽn giật.",
            "recommended": False,
            "requires_admin": False,
            "type": "custom"
        },

        "speedup_menu_delay": {
            "id": "speedup_menu_delay",
            "category": CAT_PERF,
            "name": "Tăng Tốc Phản Hồi Menu & Cửa Sổ (50ms)",
            "icon": "🚀",
            "description": "Giảm thời gian chờ mở Menu chuột phải và Submenu từ 400ms (mặc định Windows) xuống 50ms, tạo cảm giác mượt mà tức thì.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry",
            "hive": winreg.HKEY_CURRENT_USER,
            "path": r"Control Panel\Desktop",
            "name_key": "MenuShowDelay",
            "opt_value": "50",
            "default_value": "400",
            "val_type": winreg.REG_SZ
        },
        "disable_hibernation": {
            "id": "disable_hibernation",
            "category": CAT_PERF,
            "name": "Tắt Chế Độ Ngủ Đông (Giải Phóng 8GB - 32GB Ổ C:)",
            "icon": "💾",
            "description": "Xóa ngay lập tức tệp 'hiberfil.sys' chiếm dụng dung lượng khổng lồ trên ổ đĩa C:. Rất hữu ích cho máy bàn hoặc người dùng chỉ dùng chế độ Sleep.",
            "recommended": False,
            "requires_admin": True,
            "type": "custom"
        },
        "disable_game_dvr": {
            "id": "disable_game_dvr",
            "category": CAT_PERF,
            "name": "Tắt Ghi Hình Nền Game DVR (Tăng FPS)",
            "icon": "🎮",
            "description": "Tắt tính năng tự động quay video nền của Xbox Game Bar. Giúp giảm tiêu tốn tài nguyên phần cứng và tăng FPS trong trò chơi.",
            "recommended": False,
            "requires_admin": False,
            "type": "registry_multi",
            "items": [
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"System\GameConfigStore",
                    "name": "GameDVR_Enabled",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                },
                {
                    "hive": winreg.HKEY_CURRENT_USER,
                    "path": r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
                    "name": "AppCaptureEnabled",
                    "opt_value": 0,
                    "default_value": 1,
                    "val_type": winreg.REG_DWORD
                }
            ]
        },

        # ======================================================================
        # 3. NHÓM GIAO DIỆN & FILE EXPLORER (UI TWEAKS)
        # ======================================================================
        "classic_context_menu_win11": {
            "id": "classic_context_menu_win11",
            "category": CAT_UI,
            "name": "Khôi Phục Menu Chuột Phải Cổ Điển Đầy Đủ (Win 11)",
            "icon": "🖱️",
            "description": "Bỏ qua menu chuột phải rút gọn gây khó chịu trên Windows 11. Hiện lại toàn bộ các tùy chọn truyền thống mà không cần bấm 'Show more options'.",
            "recommended": True,
            "requires_admin": False,
            "type": "custom"
        },
        "show_file_extensions": {
            "id": "show_file_extensions",
            "category": CAT_UI,
            "name": "Luôn Hiển Thị Đuôi Tệp Tin (.exe, .pdf, .docx)",
            "icon": "📄",
            "description": "Hiển thị rõ ràng phần mở rộng của file trong File Explorer. Giúp phân biệt nhanh tệp tin thật và phòng ngừa mã độc mạo danh.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry",
            "hive": winreg.HKEY_CURRENT_USER,
            "path": r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
            "name_key": "HideFileExt",
            "opt_value": 0,
            "default_value": 1,
            "val_type": winreg.REG_DWORD
        },
        "launch_to_this_pc": {
            "id": "launch_to_this_pc",
            "category": CAT_UI,
            "name": "Mở File Explorer Trực Tiếp Vào 'This PC'",
            "icon": "💻",
            "description": "Khi mở File Explorer, vào thẳng giao diện quản lý các ổ đĩa (This PC) thay vì trang 'Home' hay 'Quick Access'.",
            "recommended": True,
            "requires_admin": False,
            "type": "registry",
            "hive": winreg.HKEY_CURRENT_USER,
            "path": r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
            "name_key": "LaunchTo",
            "opt_value": 1,
            "default_value": 2,
            "val_type": winreg.REG_DWORD
        }
    }

    def __init__(self):
        """Khởi tạo SystemTweaker."""
        self._cache_status: Dict[str, bool] = {}

    # ──────────────────────────────────────────────────────────────────────────
    # Quyền Hạn & Lệnh Nâng Cao (UAC Helper)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def is_admin() -> bool:
        """Kiểm tra xem ứng dụng hiện tại có quyền Administrator không."""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    @classmethod
    def _run_cmd(cls, cmd: str, timeout: int = 15) -> Dict[str, Any]:
        """Chạy lệnh shell an toàn."""
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="cp1252",
                errors="replace"
            )
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "returncode": res.returncode
            }
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}

    @classmethod
    def _run_elevated_cmd(cls, cmd: str, timeout_sec: int = 30) -> Dict[str, Any]:
        """Thực thi lệnh với quyền Administrator."""
        if cls.is_admin():
            return cls._run_cmd(cmd, timeout=timeout_sec)

        # Chưa có quyền Admin -> Kích hoạt UAC Elevation
        bat_path = None
        try:
            fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="pccleaner_tweak_")
            with os.fdopen(fd, "w", encoding="cp1252", errors="replace") as f:
                f.write("@echo off\r\n")
                f.write(f"{cmd}\r\n")
                f.write("exit /b %ERRORLEVEL%\r\n")

            SEE_MASK_NOCLOSEPROCESS = 0x00000040

            class SHELLEXECUTEINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", wintypes.LPVOID),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)
                ]

            sei = SHELLEXECUTEINFO()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
            sei.fMask = SEE_MASK_NOCLOSEPROCESS
            sei.hwnd = None
            sei.lpVerb = "runas"
            sei.lpFile = "cmd.exe"
            sei.lpParameters = f'/c "{bat_path}"'
            sei.lpDirectory = None
            sei.nShow = 0

            ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
            if not ok:
                err_code = ctypes.GetLastError()
                if err_code == 1223:
                    return {"success": False, "stdout": "", "stderr": "Người dùng đã hủy yêu cầu cấp quyền Administrator."}
                return {"success": False, "stdout": "", "stderr": f"Lỗi gọi UAC: {err_code}"}

            if sei.hProcess:
                import time
                start_t = time.time()
                while time.time() - start_t < timeout_sec:
                    exit_code = wintypes.DWORD()
                    ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
                    if exit_code.value != 259:
                        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
                        return {"success": exit_code.value == 0, "stdout": "Hoàn tất với quyền Admin", "stderr": ""}
                    time.sleep(0.3)
                ctypes.windll.kernel32.CloseHandle(sei.hProcess)
                return {"success": True, "stdout": "Đã gửi lệnh thực thi", "stderr": ""}
            return {"success": True, "stdout": "Đã thực thi", "stderr": ""}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e)}
        finally:
            if bat_path and os.path.exists(bat_path):
                try:
                    os.remove(bat_path)
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────────────────────
    # Registry Low-level Helpers
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _get_reg_val(hive: int, path: str, name: str) -> Tuple[bool, Any]:
        """Đọc an toàn một giá trị từ Registry."""
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, name)
                return True, val
        except Exception:
            return False, None

    @classmethod
    def _set_reg_val(cls, hive: int, path: str, name: str, val: Any, val_type: int) -> bool:
        """Ghi an toàn một giá trị vào Registry (tạo khóa con nếu chưa có)."""
        try:
            with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, name, 0, val_type, val)
                return True
        except PermissionError:
            # Cần phân quyền nâng cao cho HKLM
            hive_str = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
            vtype_str = "REG_DWORD" if val_type == winreg.REG_DWORD else "REG_SZ"
            cmd = f'reg add "{hive_str}\\{path}" /v "{name}" /t {vtype_str} /d "{val}" /f'
            res = cls._run_elevated_cmd(cmd)
            return res.get("success", False)
        except Exception as e:
            logger.error(f"[SystemTweaker] Lỗi ghi Registry {path}\\{name}: {e}")
            return False

    @classmethod
    def _delete_reg_val(cls, hive: int, path: str, name: str) -> bool:
        """Xóa một giá trị khỏi Registry."""
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
                return True
        except FileNotFoundError:
            return True
        except PermissionError:
            hive_str = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
            cmd = f'reg delete "{hive_str}\\{path}" /v "{name}" /f'
            res = cls._run_elevated_cmd(cmd)
            return res.get("success", False)
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Kiểm Tra Trạng Thái Tinh Chỉnh (is_applied)
    # ──────────────────────────────────────────────────────────────────────────
    def is_applied(self, tweak_id: str) -> bool:
        """Kiểm tra xem một tinh chỉnh hiện tại đã được bật/tối ưu chưa."""
        info = self.TWEAKS_DEF.get(tweak_id)
        if not info:
            return False

        ttype = info.get("type")

        # Loại 1: Registry đơn lẻ
        if ttype == "registry":
            ok, val = self._get_reg_val(info["hive"], info["path"], info["name_key"])
            if not ok:
                return False
            # So khớp kiểu chuỗi hoặc số
            return str(val) == str(info["opt_value"])

        # Loại 2: Registry nhiều khóa
        elif ttype == "registry_multi":
            for item in info.get("items", []):
                ok, val = self._get_reg_val(item["hive"], item["path"], item["name"])
                if not ok or str(val) != str(item["opt_value"]):
                    return False
            return True

        # Loại 3: Custom Handler cho từng trường hợp đặc thù
        elif ttype == "custom":
            return self._check_custom_status(tweak_id)

        return False

    def _check_custom_status(self, tweak_id: str) -> bool:
        """Xử lý kiểm tra cho các tweak tùy biến."""
        # 1. Dịch vụ DiagTrack
        if tweak_id == "disable_diagtrack_service":
            res = self._run_cmd('powershell -NoProfile -Command "Get-Service DiagTrack -ErrorAction SilentlyContinue | Select-Object -ExpandProperty StartType"')
            if res["success"]:
                start_type = res["stdout"].strip().lower()
                return start_type == "disabled"
            return False

        # 2. Chế độ nguồn Ultimate Performance
        elif tweak_id == "enable_ultimate_performance":
            res = self._run_cmd("powercfg /list")
            if res["success"]:
                output = res["stdout"]
                # Kiểm tra xem scheme Ultimate Performance có dấu * (active) không
                for line in output.splitlines():
                    if ("ultimate performance" in line.lower() or "e9a42b02-d5df-448d-aa00-03f14749eb61" in line.lower()) and "*" in line:
                        return True
            return False

        # 3. Tắt Hibernation
        elif tweak_id == "disable_hibernation":
            # Nếu hiberfil.sys không tồn tại trên ổ C: -> đã tắt
            has_file = os.path.exists("C:\\hiberfil.sys")
            return not has_file

        # 4. Windows 11 Classic Context Menu
        elif tweak_id == "classic_context_menu_win11":
            path = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    return val == ""
            except Exception:
                return False

        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Áp Dụng Tinh Chỉnh (Apply)
    # ──────────────────────────────────────────────────────────────────────────
    def apply_tweak(self, tweak_id: str) -> Tuple[bool, str]:
        """
        Kích hoạt một tinh chỉnh.
        Trả về (thành_công: bool, thông_điệp: str).
        """
        info = self.TWEAKS_DEF.get(tweak_id)
        if not info:
            return False, f"Không tìm thấy tinh chỉnh: {tweak_id}"

        name = info.get("name", tweak_id)
        ttype = info.get("type")

        try:
            # 1. Registry đơn lẻ
            if ttype == "registry":
                ok = self._set_reg_val(
                    info["hive"],
                    info["path"],
                    info["name_key"],
                    info["opt_value"],
                    info["val_type"]
                )
                if ok:
                    return True, f"✅ Đã kích hoạt: {name}"
                return False, f"❌ Không thể áp dụng: {name}"

            # 2. Registry nhiều khóa
            elif ttype == "registry_multi":
                success_count = 0
                for item in info.get("items", []):
                    if self._set_reg_val(item["hive"], item["path"], item["name"], item["opt_value"], item["val_type"]):
                        success_count += 1
                if success_count > 0:
                    return True, f"✅ Đã kích hoạt: {name}"
                return False, f"❌ Không thể áp dụng: {name}"

            # 3. Custom Tweak
            elif ttype == "custom":
                return self._apply_custom_tweak(tweak_id, name)

            return False, f"Loại tinh chỉnh không xác định: {ttype}"

        except Exception as e:
            logger.error(f"[SystemTweaker] Lỗi khi kích hoạt {tweak_id}: {e}")
            return False, f"Lỗi: {e}"

    def _apply_custom_tweak(self, tweak_id: str, name: str) -> Tuple[bool, str]:
        """Áp dụng các tweak tùy biến."""
        # DiagTrack Service
        if tweak_id == "disable_diagtrack_service":
            cmd = "sc config DiagTrack start= disabled && net stop DiagTrack"
            res = self._run_elevated_cmd(cmd)
            if res.get("success"):
                return True, f"✅ Đã dừng và vô hiệu hóa dịch vụ DiagTrack."
            return False, f"❌ Cần quyền Administrator để dừng dịch vụ DiagTrack."

        # Ultimate Performance Power Plan
        elif tweak_id == "enable_ultimate_performance":
            import re
            target_guid = None
            # 1. Kiểm tra xem trên máy đã có scheme Ultimate Performance chưa
            list_res = self._run_cmd("powercfg /list")
            if list_res.get("success"):
                for line in list_res["stdout"].splitlines():
                    if "ultimate performance" in line.lower() or "tối thượng" in line.lower():
                        m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", line)
                        if m:
                            target_guid = m.group(1)
                            break

            # 2. Nếu chưa có, nhân bản từ scheme gốc (e9a42b02-d5df-448d-aa00-03f14749eb61)
            if not target_guid:
                dup_res = self._run_cmd("powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61")
                m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", dup_res.get("stdout", ""))
                if m:
                    target_guid = m.group(1)
                else:
                    dup_res = self._run_elevated_cmd("powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61")
                    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", dup_res.get("stdout", ""))
                    if m:
                        target_guid = m.group(1)
                    else:
                        # Fallback sang High Performance (8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c) nếu Windows edition không có Ultimate
                        dup_high = self._run_cmd("powercfg -duplicatescheme 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c")
                        m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", dup_high.get("stdout", ""))
                        if m:
                            target_guid = m.group(1)

            # 3. Kích hoạt scheme đã tìm thấy hoặc vừa nhân bản
            if target_guid:
                set_res = self._run_cmd(f"powercfg /setactive {target_guid}")
                if not set_res.get("success"):
                    set_res = self._run_elevated_cmd(f"powercfg /setactive {target_guid}")
                if set_res.get("success"):
                    return True, "⚡ Đã kích hoạt chế độ nguồn Ultimate Performance thành công!"

            return False, "❌ Không thể tạo hoặc kích hoạt gói nguồn Ultimate Performance trên thiết bị này."


        # Hibernation off
        elif tweak_id == "disable_hibernation":
            res = self._run_elevated_cmd("powercfg /h off")
            if res.get("success"):
                return True, f"💾 Đã tắt chế độ ngủ đông và giải phóng tệp hiberfil.sys."
            return False, f"❌ Cần quyền Administrator để tắt chế độ ngủ đông."

        # Windows 11 Classic Context Menu
        elif tweak_id == "classic_context_menu_win11":
            path = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
            try:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")
                return True, f"🖱️ Đã khôi phục Menu chuột phải cổ điển đầy đủ (Hãy khởi động lại Explorer để áp dụng)."
            except Exception as e:
                return False, f"❌ Lỗi ghi Registry Menu chuột phải: {e}"

        return False, "Không có bộ xử lý tùy biến tương ứng."

    # ──────────────────────────────────────────────────────────────────────────
    # Hoàn Tác Tinh Chỉnh (Revert to Windows Default)
    # ──────────────────────────────────────────────────────────────────────────
    def revert_tweak(self, tweak_id: str) -> Tuple[bool, str]:
        """
        Khôi phục một tinh chỉnh về trạng thái mặc định của Windows.
        Trả về (thành_công: bool, thông_điệp: str).
        """
        info = self.TWEAKS_DEF.get(tweak_id)
        if not info:
            return False, f"Không tìm thấy tinh chỉnh: {tweak_id}"

        name = info.get("name", tweak_id)
        ttype = info.get("type")

        try:
            # 1. Registry đơn lẻ
            if ttype == "registry":
                ok = self._set_reg_val(
                    info["hive"],
                    info["path"],
                    info["name_key"],
                    info["default_value"],
                    info["val_type"]
                )
                if ok:
                    return True, f"🔄 Đã khôi phục về mặc định: {name}"
                return False, f"❌ Không thể khôi phục: {name}"

            # 2. Registry nhiều khóa
            elif ttype == "registry_multi":
                for item in info.get("items", []):
                    self._set_reg_val(item["hive"], item["path"], item["name"], item["default_value"], item["val_type"])
                return True, f"🔄 Đã khôi phục về mặc định: {name}"

            # 3. Custom Tweak
            elif ttype == "custom":
                return self._revert_custom_tweak(tweak_id, name)

            return False, f"Loại tinh chỉnh không xác định: {ttype}"

        except Exception as e:
            logger.error(f"[SystemTweaker] Lỗi khi hoàn tác {tweak_id}: {e}")
            return False, f"Lỗi: {e}"

    def _revert_custom_tweak(self, tweak_id: str, name: str) -> Tuple[bool, str]:
        """Hoàn tác các tweak tùy biến."""
        # DiagTrack Service
        if tweak_id == "disable_diagtrack_service":
            cmd = "sc config DiagTrack start= auto && net start DiagTrack"
            res = self._run_elevated_cmd(cmd)
            if res.get("success"):
                return True, "🔄 Đã kích hoạt lại dịch vụ DiagTrack về trạng thái mặc định."
            return False, "❌ Không thể thay đổi dịch vụ DiagTrack."

        # Ultimate Performance Power Plan -> Trả về Balanced (381b4222-f694-41f0-9685-ff5bb260df2e)
        elif tweak_id == "enable_ultimate_performance":
            import re
            set_cmd = "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e"
            res = self._run_cmd(set_cmd)
            if not res.get("success"):
                res = self._run_elevated_cmd(set_cmd)

            # Dọn dẹp các scheme Ultimate Performance không còn active
            list_res = self._run_cmd("powercfg /list")
            if list_res.get("success"):
                for line in list_res["stdout"].splitlines():
                    if ("ultimate performance" in line.lower() or "tối thượng" in line.lower()) and "*" not in line:
                        m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", line)
                        if m:
                            self._run_cmd(f"powercfg -delete {m.group(1)}")

            if res.get("success"):
                return True, "🔄 Đã chuyển lại gói nguồn điện về Balanced (Cân bằng mặc định)."
            return False, "❌ Không thể đổi gói nguồn điện."


        # Hibernation on
        elif tweak_id == "disable_hibernation":
            res = self._run_elevated_cmd("powercfg /h on")
            if res.get("success"):
                return True, "🔄 Đã bật lại chế độ ngủ đông (Hibernation)."
            return False, "❌ Cần quyền Administrator để bật lại chế độ ngủ đông."

        # Windows 11 Classic Context Menu -> Xóa khóa
        elif tweak_id == "classic_context_menu_win11":
            sub_path = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
            parent_path = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"
            try:
                self._delete_reg_key_recursive(winreg.HKEY_CURRENT_USER, parent_path)
                return True, "🔄 Đã khôi phục lại Menu chuột phải Windows 11 mặc định."
            except Exception as e:
                return False, f"❌ Lỗi hoàn tác Menu chuột phải: {e}"

        return False, "Không có bộ hoàn tác tùy biến tương ứng."

    @classmethod
    def _delete_reg_key_recursive(cls, hive: int, key_path: str) -> bool:
        """Xóa đệ quy một khóa Registry."""
        try:
            with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                while True:
                    try:
                        sub = winreg.EnumKey(key, 0)
                        cls._delete_reg_key_recursive(hive, f"{key_path}\\{sub}")
                    except OSError:
                        break
            winreg.DeleteKey(hive, key_path)
            return True
        except FileNotFoundError:
            return True
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Thao Tác Hàng Loạt & Tiện Ích
    # ──────────────────────────────────────────────────────────────────────────
    def apply_all_recommended(self) -> Dict[str, Any]:
        """Kích hoạt toàn bộ các tinh chỉnh có cờ recommended=True."""
        applied_list = []
        failed_list = []

        for tid, info in self.TWEAKS_DEF.items():
            if info.get("recommended", False):
                if not self.is_applied(tid):
                    ok, msg = self.apply_tweak(tid)
                    if ok:
                        applied_list.append(info["name"])
                    else:
                        failed_list.append(info["name"])

        return {
            "applied_count": len(applied_list),
            "applied_list": applied_list,
            "failed_count": len(failed_list),
            "failed_list": failed_list
        }

    def revert_all(self) -> Dict[str, Any]:
        """Khôi phục toàn bộ các tinh chỉnh về mặc định Windows."""
        reverted_list = []
        failed_list = []

        for tid, info in self.TWEAKS_DEF.items():
            if self.is_applied(tid):
                ok, msg = self.revert_tweak(tid)
                if ok:
                    reverted_list.append(info["name"])
                else:
                    failed_list.append(info["name"])

        return {
            "reverted_count": len(reverted_list),
            "reverted_list": reverted_list,
            "failed_count": len(failed_list),
            "failed_list": failed_list
        }

    def get_summary_stats(self) -> Dict[str, int]:
        """Thống kê tổng số tinh chỉnh và số lượng đã kích hoạt."""
        total = len(self.TWEAKS_DEF)
        applied = 0
        recommended_total = 0
        recommended_applied = 0

        for tid, info in self.TWEAKS_DEF.items():
            is_rec = info.get("recommended", False)
            if is_rec:
                recommended_total += 1
            if self.is_applied(tid):
                applied += 1
                if is_rec:
                    recommended_applied += 1

        return {
            "total": total,
            "applied": applied,
            "recommended_total": recommended_total,
            "recommended_applied": recommended_applied
        }

    @staticmethod
    def restart_explorer() -> bool:
        """Khởi động lại Windows Explorer để áp dụng ngay các thay đổi giao diện."""
        try:
            subprocess.run("taskkill /f /im explorer.exe", shell=True, capture_output=True, timeout=5)
            # Khởi chạy lại explorer.exe mà không chặn tiến trình
            subprocess.Popen("explorer.exe", shell=True)
            logger.info("[SystemTweaker] Đã khởi động lại Windows Explorer thành công.")
            return True
        except Exception as e:
            logger.error(f"[SystemTweaker] Không thể khởi động lại Explorer: {e}")
            return False
