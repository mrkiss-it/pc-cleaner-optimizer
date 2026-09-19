"""
core/uninstaller_manager.py – Software Uninstaller & Residual Junk Hunter (v3.5 Pro)
===================================================================================
Quản lý gỡ cài đặt phần mềm chuyên sâu & Dọn dẹp tàn dư rác hệ thống:
1. Quét toàn diện phần mềm Desktop đã cài đặt (32-bit, 64-bit, HKCU/HKLM).
2. Nhận diện & 1-Click gỡ bỏ Bloatware Windows 10/11 (Xbox, Cortana, Tips, News...).
3. Residual Junk Hunter: Quét sâu AppData, ProgramData, Program Files & Registry
   để phát hiện và xóa sạch 100% tàn dư của phần mềm đã gỡ bỏ.
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import winreg
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set

from core.logger import logger
from core.network_optimizer import NetworkOptimizer
from core.service_optimizer import ServiceOptimizer


# ---------------------------------------------------------------------------
# Curated Windows Bloatware Knowledge Base
# ---------------------------------------------------------------------------
KNOWN_BLOATWARE: Dict[str, Dict[str, Any]] = {
    "Microsoft.BingWeather": {
        "title": "Thời Tiết (Bing Weather)",
        "desc": "Ứng dụng dự báo thời tiết tích hợp sẵn của Microsoft",
        "safety": "safe",
    },
    "Microsoft.BingNews": {
        "title": "Tin Tức & Tài Chính (Bing News)",
        "desc": "Ứng dụng cập nhật tin tức đẩy thông báo nền",
        "safety": "safe",
    },
    "Microsoft.GetHelp": {
        "title": "Trợ Giúp (Get Help)",
        "desc": "Trợ lý hỗ trợ kỹ thuật trực tuyến của Windows",
        "safety": "safe",
    },
    "Microsoft.Getstarted": {
        "title": "Mẹo & Hướng Dẫn (Tips)",
        "desc": "Ứng dụng hiển thị mẹo vặt sử dụng Windows định kỳ",
        "safety": "safe",
    },
    "Microsoft.MicrosoftSolitaireCollection": {
        "title": "Trò Chơi Solitaire Collection",
        "desc": "Bộ bài xếp mặc định kèm quảng cáo",
        "safety": "safe",
    },
    "Microsoft.XboxApp": {
        "title": "Ứng Dụng Xbox Companion",
        "desc": "Trình quản lý tài khoản chơi game Xbox Console",
        "safety": "safe",
    },
    "Microsoft.XboxSpeechToTextOverlay": {
        "title": "Xbox Speech Overlay",
        "desc": "Dịch vụ chuyển đổi giọng nói sang văn bản khi chơi game",
        "safety": "safe",
    },
    "Microsoft.XboxGamingOverlay": {
        "title": "Xbox Game Bar",
        "desc": "Thanh công cụ quay màn hình (Win + G)",
        "safety": "caution",
    },
    "Microsoft.YourPhone": {
        "title": "Liên Kết Điện Thoại (Phone Link)",
        "desc": "Đồng bộ tin nhắn và ảnh từ điện thoại Android/iOS",
        "safety": "safe",
    },
    "Microsoft.ZuneVideo": {
        "title": "Phim & TV (Movies & TV)",
        "desc": "Trình xem video mặc định của Windows",
        "safety": "safe",
    },
    "Microsoft.ZuneMusic": {
        "title": "Media Player (Zune Music)",
        "desc": "Trình phát nhạc tích hợp",
        "safety": "safe",
    },
    "Microsoft.People": {
        "title": "Danh Bạ (People)",
        "desc": "Sổ địa chỉ và liên hệ của Windows",
        "safety": "safe",
    },
    "Microsoft.WindowsFeedbackHub": {
        "title": "Trung Tâm Phản Hồi (Feedback Hub)",
        "desc": "Công cụ gửi đánh giá phản hồi về lỗi tới Microsoft",
        "safety": "safe",
    },
    "Microsoft.Microsoft3DViewer": {
        "title": "3D Viewer",
        "desc": "Trình xem mô hình 3D mặc định",
        "safety": "safe",
    },
    "Microsoft.MixedReality.Portal": {
        "title": "Cổng Mixed Reality Portal",
        "desc": "Phần mềm kính thực tế ảo VR của Windows",
        "safety": "safe",
    },
    "Microsoft.SkypeApp": {
        "title": "Skype for Windows",
        "desc": "Ứng dụng chat/gọi video Skype cài sẵn",
        "safety": "safe",
    },
    "Clipchamp.Clipchamp": {
        "title": "Clipchamp Video Editor",
        "desc": "Trình biên tập video trực tuyến của Microsoft",
        "safety": "safe",
    },
    "Microsoft.549981C3F5F10": {
        "title": "Trợ Lý Ảo Cortana",
        "desc": "Trợ lý giọng nói Cortana đã ngừng phát triển",
        "safety": "safe",
    },
    "Microsoft.WindowsMaps": {
        "title": "Bản Đồ (Windows Maps)",
        "desc": "Ứng dụng bản đồ ngoại tuyến của Windows",
        "safety": "safe",
    },
    "Microsoft.SoundRecorder": {
        "title": "Ghi Âm (Sound Recorder)",
        "desc": "Công cụ ghi âm âm thanh đơn giản",
        "safety": "safe",
    },
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------
@dataclass
class InstalledApp:
    """Đại diện cho một phần mềm đã cài đặt trên hệ điều hành."""
    id: str
    name: str
    publisher: str = "Không rõ"
    version: str = "Không rõ"
    install_date: str = ""
    size_mb: float = 0.0
    install_loc: str = ""
    uninstall_string: Optional[str] = None
    quiet_uninstall_string: Optional[str] = None
    is_uwp: bool = False
    package_full_name: Optional[str] = None
    safety_rating: str = "safe"        # safe | caution | system
    category: str = "desktop"          # desktop | bloatware
    description: str = ""

    @property
    def app_type(self) -> str:
        return self.category

    @property
    def is_bloatware(self) -> bool:
        return self.category == "bloatware"

    @property
    def size_display(self) -> str:
        if self.size_mb <= 0:
            return "Không rõ"
        if self.size_mb >= 1024:
            return f"{self.size_mb / 1024:.2f} GB"
        return f"{self.size_mb:.1f} MB"

    @property
    def date_display(self) -> str:
        if not self.install_date:
            return "Không rõ"
        d = self.install_date.replace("-", "").strip()
        if len(d) == 8 and d.isdigit():
            return f"{d[6:8]}/{d[4:6]}/{d[0:4]}"
        return self.install_date


# ---------------------------------------------------------------------------
# Manager Implementation
# ---------------------------------------------------------------------------
class UninstallerManager:
    """Quản lý phần mềm, gỡ bỏ ứng dụng rác và truy quét tàn dư."""

    _cached_desktop_apps: Optional[List[InstalledApp]] = None
    _cached_bloatware_apps: Optional[List[InstalledApp]] = None

    # ------------------------------------------------------------------
    # 1. Desktop Apps Discovery
    # ------------------------------------------------------------------

    @classmethod
    def get_installed_desktop_apps(cls, force_refresh: bool = False) -> List[InstalledApp]:
        """
        Quét toàn bộ phần mềm desktop từ cả 3 nhánh Registry chính của Windows.
        Lọc bỏ hotfix, driver hoặc system components ẩn.
        """
        if cls._cached_desktop_apps is not None and not force_refresh:
            return cls._cached_desktop_apps

        registry_targets = [
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]

        apps: List[InstalledApp] = []
        seen_names: Set[str] = set()

        for root_key, sub_path in registry_targets:
            try:
                with winreg.OpenKey(root_key, sub_path) as base_key:
                    num_keys = winreg.QueryInfoKey(base_key)[0]
                    for i in range(num_keys):
                        try:
                            key_name = winreg.EnumKey(base_key, i)
                            with winreg.OpenKey(base_key, key_name) as app_key:
                                # Tên phần mềm
                                try:
                                    name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                                except FileNotFoundError:
                                    continue

                                if not name or not str(name).strip():
                                    continue

                                clean_name = str(name).strip()
                                norm_key = clean_name.lower()
                                if norm_key in seen_names:
                                    continue

                                # Bỏ qua system components & Windows updates
                                try:
                                    sys_comp, _ = winreg.QueryValueEx(app_key, "SystemComponent")
                                    if sys_comp == 1:
                                        continue
                                except FileNotFoundError:
                                    pass

                                try:
                                    parent_key, _ = winreg.QueryValueEx(app_key, "ParentKeyName")
                                    if parent_key:
                                        continue
                                except FileNotFoundError:
                                    pass

                                # Lệnh gỡ cài đặt
                                try:
                                    uninst, _ = winreg.QueryValueEx(app_key, "UninstallString")
                                except FileNotFoundError:
                                    uninst = None

                                try:
                                    quiet_uninst, _ = winreg.QueryValueEx(app_key, "QuietUninstallString")
                                except FileNotFoundError:
                                    quiet_uninst = None

                                if not uninst and not quiet_uninst:
                                    continue

                                # Phiên bản & Nhà phát triển
                                try:
                                    ver, _ = winreg.QueryValueEx(app_key, "DisplayVersion")
                                    ver_str = str(ver).strip()
                                except FileNotFoundError:
                                    ver_str = "Không rõ"

                                try:
                                    pub, _ = winreg.QueryValueEx(app_key, "Publisher")
                                    pub_str = str(pub).strip()
                                except FileNotFoundError:
                                    pub_str = "Không rõ"

                                # Dung lượng (EstimatedSize tính bằng KB)
                                size_mb = 0.0
                                try:
                                    size_kb, _ = winreg.QueryValueEx(app_key, "EstimatedSize")
                                    if size_kb and size_kb > 0:
                                        size_mb = round(float(size_kb) / 1024.0, 1)
                                except FileNotFoundError:
                                    pass

                                # Thư mục cài đặt
                                try:
                                    loc, _ = winreg.QueryValueEx(app_key, "InstallLocation")
                                    loc_str = str(loc).strip()
                                except FileNotFoundError:
                                    loc_str = ""

                                # Ngày cài đặt
                                try:
                                    inst_date, _ = winreg.QueryValueEx(app_key, "InstallDate")
                                    inst_date_str = str(inst_date).strip()
                                except FileNotFoundError:
                                    inst_date_str = ""

                                seen_names.add(norm_key)
                                app_id = f"desktop::{key_name}"
                                apps.append(InstalledApp(
                                    id=app_id,
                                    name=clean_name,
                                    publisher=pub_str,
                                    version=ver_str,
                                    install_date=inst_date_str,
                                    size_mb=size_mb,
                                    install_loc=loc_str,
                                    uninstall_string=uninst,
                                    quiet_uninstall_string=quiet_uninst,
                                    is_uwp=False,
                                    category="desktop",
                                    safety_rating="safe",
                                ))
                        except Exception:
                            continue
            except Exception:
                continue

        # Sắp xếp mặc định: Dung lượng lớn nhất lên đầu
        apps.sort(key=lambda x: x.size_mb, reverse=True)
        cls._cached_desktop_apps = apps
        logger.info(f"[UninstallerManager] Đã quét được {len(apps)} phần mềm desktop đã cài đặt.")
        return apps

    # ------------------------------------------------------------------
    # 2. Windows Bloatware (UWP / AppX) Discovery
    # ------------------------------------------------------------------

    @classmethod
    def get_bloatware_apps(cls, force_refresh: bool = False) -> List[InstalledApp]:
        """
        Quét danh sách ứng dụng Universal Windows Platform (UWP) tích hợp sẵn,
        lọc theo cơ sở tri thức KNOWN_BLOATWARE.
        """
        if cls._cached_bloatware_apps is not None and not force_refresh:
            return cls._cached_bloatware_apps

        bloatware_list: List[InstalledApp] = []

        try:
            cmd = [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                "Get-AppxPackage | Select-Object Name, Version, NonRemovable, PackageFullName | ConvertTo-Json"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                try:
                    data = json.loads(res.stdout)
                    if isinstance(data, dict):
                        data = [data]

                    for pkg in data:
                        name = pkg.get("Name", "")
                        if name in KNOWN_BLOATWARE:
                            meta = KNOWN_BLOATWARE[name]
                            full_name = pkg.get("PackageFullName", "")
                            ver = pkg.get("Version", "")
                            non_removable = pkg.get("NonRemovable", False)

                            app_id = f"uwp::{name}"
                            bloatware_list.append(InstalledApp(
                                id=app_id,
                                name=meta["title"],
                                publisher="Microsoft Corporation",
                                version=ver,
                                is_uwp=True,
                                package_full_name=full_name,
                                category="bloatware",
                                safety_rating=meta["safety"],
                                description=meta["desc"],
                            ))
                except Exception as parse_err:
                    logger.warning(f"[UninstallerManager] Lỗi phân tích JSON UWP apps: {parse_err}")
        except Exception as e:
            logger.error(f"[UninstallerManager] Không thể quét UWP bloatware: {e}")

        cls._cached_bloatware_apps = bloatware_list
        logger.info(f"[UninstallerManager] Đã nhận diện {len(bloatware_list)} ứng dụng bloatware Windows.")
        return bloatware_list

    # ------------------------------------------------------------------
    # 3. Uninstall Actions
    # ------------------------------------------------------------------

    @classmethod
    def uninstall_desktop_app(cls, app: InstalledApp, silent: bool = False) -> Tuple[bool, str]:
        """
        Kích hoạt trình gỡ cài đặt gốc của phần mềm desktop.
        """
        cmd = app.quiet_uninstall_string if (silent and app.quiet_uninstall_string) else app.uninstall_string
        if not cmd:
            return False, f"Không tìm thấy lệnh gỡ cài đặt cho '{app.name}'."

        try:
            logger.info(f"[UninstallerManager] Đang kích hoạt gỡ cài đặt cho '{app.name}': {cmd}")
            # Mở tiến trình uninstaller không chặn UI
            subprocess.Popen(cmd, shell=True)
            return True, f"Đã khởi chạy trình gỡ cài đặt cho '{app.name}'. Vui lòng làm theo hướng dẫn trên màn hình."
        except Exception as e:
            return False, f"Lỗi khởi chạy gỡ cài đặt: {str(e)}"

    @classmethod
    def uninstall_uwp_app(cls, app: InstalledApp) -> Tuple[bool, str]:
        """
        Gỡ bỏ ứng dụng UWP Bloatware cho người dùng hiện tại thông qua PowerShell.
        """
        try:
            logger.info(f"[UninstallerManager] Đang gỡ bỏ gói Bloatware: {app.name} ({app.id})")
            # Dùng tên gói gốc nếu có
            pkg_id = app.id.replace("uwp::", "")
            ps_cmd = f"Get-AppxPackage -Name '{pkg_id}' | Remove-AppxPackage"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=30
            )
            if res.returncode == 0:
                # Xóa khỏi cache
                if cls._cached_bloatware_apps:
                    cls._cached_bloatware_apps = [a for a in cls._cached_bloatware_apps if a.id != app.id]
                return True, f"Đã gỡ bỏ ứng dụng '{app.name}' thành công!"
            else:
                err_msg = res.stderr.strip() or res.stdout.strip()
                return False, f"Gỡ bỏ thất bại: {err_msg}"
        except Exception as e:
            return False, f"Lỗi thực thi: {str(e)}"

    # ------------------------------------------------------------------
    # 4. Residual Junk Hunter (Quét & Dọn Tàn Dư)
    # ------------------------------------------------------------------

    @classmethod
    def scan_residuals(cls, app_name: str, publisher: str = "", install_loc: str = "") -> Dict[str, Any]:
        """
        Quét sâu các thư mục và Registry để tìm tàn dư của một phần mềm cụ thể.
        """
        folders_found: List[Dict[str, Any]] = []
        reg_keys_found: List[Dict[str, str]] = []

        clean_kw = app_name.lower().replace("corporation", "").replace("inc.", "").strip()
        keywords = [clean_kw]
        words = clean_kw.split()
        if len(words) > 1 and len(words[0]) >= 4:
            keywords.append(words[0])

        # 1. Quét thư mục Disk
        target_dirs = [
            os.environ.get("APPDATA"),
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("ProgramData"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]

        for base in target_dirs:
            if not base or not os.path.isdir(base):
                continue

            try:
                for entry in os.listdir(base):
                    full_p = os.path.join(base, entry)
                    if not os.path.isdir(full_p):
                        continue

                    entry_lower = entry.lower()
                    for kw in keywords:
                        if kw in entry_lower:
                            size_bytes = 0
                            try:
                                for root, _, files in os.walk(full_p):
                                    for f in files:
                                        fp = os.path.join(root, f)
                                        try:
                                            size_bytes += os.path.getsize(fp)
                                        except Exception:
                                            pass
                            except Exception:
                                pass

                            folders_found.append({
                                "path": full_p,
                                "name": entry,
                                "size_mb": round(size_bytes / (1024 * 1024), 2),
                                "type": "Thư mục còn sót",
                            })
                            break
            except Exception:
                continue

        # Nếu install_loc vẫn còn tồn tại
        if install_loc and os.path.isdir(install_loc) and install_loc not in [f["path"] for f in folders_found]:
            folders_found.append({
                "path": install_loc,
                "name": os.path.basename(install_loc),
                "size_mb": 0.1,
                "type": "Thư mục cài đặt cũ",
            })

        # 2. Quét Registry Keys
        reg_roots = [
            (winreg.HKEY_CURRENT_USER, r"Software", "HKCU"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software", "HKLM"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node", "HKLM_WOW64"),
        ]

        for root_h, root_name, display_root in reg_roots:
            try:
                with winreg.OpenKey(root_h, root_name) as base_k:
                    num_subs = winreg.QueryInfoKey(base_k)[0]
                    for i in range(num_subs):
                        try:
                            sub_n = winreg.EnumKey(base_k, i)
                            sub_lower = sub_n.lower()
                            for kw in keywords:
                                if kw == sub_lower or (len(kw) >= 5 and kw in sub_lower):
                                    reg_keys_found.append({
                                        "root": display_root,
                                        "path": f"{root_name}\\{sub_n}",
                                        "full": f"{display_root}\\{root_name}\\{sub_n}",
                                    })
                                    break
                        except Exception:
                            continue
            except Exception:
                continue

        total_size = sum(f["size_mb"] for f in folders_found)
        return {
            "app_name": app_name,
            "folders": folders_found,
            "reg_keys": reg_keys_found,
            "total_size_mb": round(total_size, 2),
        }

    @classmethod
    def clean_residuals(cls, residuals: Dict[str, Any], allow_elevation: bool = True) -> Tuple[int, int, str]:
        """
        Xóa bỏ các thư mục và khóa registry tàn dư đã quét được.
        """
        folders = residuals.get("folders", [])
        reg_keys = residuals.get("reg_keys", [])

        cleaned_folders = 0
        cleaned_keys = 0
        errors = []

        # 1. Xóa thư mục
        for f in folders:
            p = f.get("path")
            if p and os.path.exists(p):
                try:
                    shutil.rmtree(p, ignore_errors=False)
                    cleaned_folders += 1
                except Exception as e:
                    if allow_elevation:
                        ServiceOptimizer._run_elevated_cmd(f'/c rmdir /s /q "{p}"')
                        if not os.path.exists(p):
                            cleaned_folders += 1
                        else:
                            errors.append(f"Không thể xóa thư mục '{p}': {str(e)}")
                    else:
                        errors.append(f"Không thể xóa thư mục '{p}': {str(e)}")

        # 2. Xóa khóa Registry
        for rk in reg_keys:
            full_reg = rk.get("full", "")
            if not full_reg:
                continue

            root = rk.get("root", "")
            reg_p = rk.get("path", "")
            reg_target = f"HKCU\\{reg_p}" if "HKCU" in root else f"HKLM\\{reg_p}"

            res = subprocess.run(f'reg.exe delete "{reg_target}" /f', shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                cleaned_keys += 1
            else:
                if allow_elevation:
                    ok, _ = ServiceOptimizer._run_elevated_cmd(f'/c reg.exe delete "{reg_target}" /f')
                    if ok:
                        cleaned_keys += 1
                    else:
                        errors.append(f"Không thể xóa Registry key '{reg_target}'")
                else:
                    errors.append(f"Không thể xóa Registry key '{reg_target}'")

        msg = f"Đã dọn dẹp {cleaned_folders} thư mục rác và {cleaned_keys} khóa Registry tàn dư!"
        if errors:
            msg += f" ({len(errors)} mục không thể xóa do đang bị khóa)."

        return cleaned_folders, cleaned_keys, msg

    # ------------------------------------------------------------------
    # 5. Summary
    # ------------------------------------------------------------------

    @classmethod
    def get_summary(cls) -> Dict[str, Any]:
        """Trả về thống kê tổng hợp số lượng và dung lượng ứng dụng."""
        apps = cls.get_installed_desktop_apps()
        bloat = cls.get_bloatware_apps()

        total_mb = sum(a.size_mb for a in apps)
        largest = apps[0] if apps else None

        return {
            "desktop_count": len(apps),
            "bloatware_count": len(bloat),
            "total_size_gb": round(total_mb / 1024.0, 2),
            "largest_name": largest.name if largest else "Không có",
            "largest_size_mb": largest.size_mb if largest else 0,
        }
