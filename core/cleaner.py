import os
import glob
import shutil
import ctypes
import stat
from ctypes import wintypes
from typing import Dict, Any, List, Callable, Optional
from core.logger import logger

def remove_readonly(func, path, exc_info):
    """
    Xóa cờ Read-Only trên Windows khi gặp lỗi xóa tệp tạm thời
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

# Win32 Recycle Bin Structures & Flags
SHERB_NOCONFIRMATION = 0x00000001
SHERB_NOPROGRESSUI = 0x00000002
SHERB_NOSOUND = 0x00000004

class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('i64Size', ctypes.c_int64),
        ('i64NumItems', ctypes.c_int64)
    ]

class JunkCleaner:
    @staticmethod
    def get_target_paths() -> Dict[str, List[str]]:
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        app_data = os.environ.get("APPDATA", "")
        user_temp = os.environ.get("TEMP", "")
        system_root = os.environ.get("SystemRoot", "C:\\Windows")

        targets = {
            "user_temp": [],
            "system_temp": [],
            "browser_cache": [],
            "crash_dumps": [],
            "windows_update": [],
            "app_caches": []
        }

        # 1. User Temp
        if user_temp and os.path.exists(user_temp):
            targets["user_temp"].append(user_temp)

        # 2. System Temp
        sys_temp = os.path.join(system_root, "Temp")
        if os.path.exists(sys_temp):
            targets["system_temp"].append(sys_temp)

        # 3. Browser Caches (Hỗ trợ Default và mọi Profile 1, 2,...)
        if local_app_data:
            # Google Chrome
            chrome_user_data = os.path.join(local_app_data, r"Google\Chrome\User Data")
            if os.path.exists(chrome_user_data):
                profiles = glob.glob(os.path.join(chrome_user_data, "Default")) + glob.glob(os.path.join(chrome_user_data, "Profile *"))
                for prof in profiles:
                    for sub in ["Cache", "Code Cache", "GPUCache"]:
                        p_dir = os.path.join(prof, sub)
                        if os.path.exists(p_dir):
                            targets["browser_cache"].append(p_dir)

            # Microsoft Edge
            edge_user_data = os.path.join(local_app_data, r"Microsoft\Edge\User Data")
            if os.path.exists(edge_user_data):
                profiles = glob.glob(os.path.join(edge_user_data, "Default")) + glob.glob(os.path.join(edge_user_data, "Profile *"))
                for prof in profiles:
                    for sub in ["Cache", "Code Cache", "GPUCache"]:
                        p_dir = os.path.join(prof, sub)
                        if os.path.exists(p_dir):
                            targets["browser_cache"].append(p_dir)

            # Brave Browser
            brave_user_data = os.path.join(local_app_data, r"BraveSoftware\Brave-Browser\User Data")
            if os.path.exists(brave_user_data):
                profiles = glob.glob(os.path.join(brave_user_data, "Default")) + glob.glob(os.path.join(brave_user_data, "Profile *"))
                for prof in profiles:
                    for sub in ["Cache", "Code Cache", "GPUCache"]:
                        p_dir = os.path.join(prof, sub)
                        if os.path.exists(p_dir):
                            targets["browser_cache"].append(p_dir)

            # Firefox Cache (profiles)
            firefox_profiles = os.path.join(local_app_data, r"Mozilla\Firefox\Profiles")
            if os.path.exists(firefox_profiles):
                for p in glob.glob(os.path.join(firefox_profiles, "*", "cache2")):
                    targets["browser_cache"].append(p)

        # 4. Crash Dumps & Windows Error Reporting
        if local_app_data:
            crash_dumps = os.path.join(local_app_data, "CrashDumps")
            wer_archive = os.path.join(local_app_data, r"Microsoft\Windows\WER\ReportArchive")
            wer_queue = os.path.join(local_app_data, r"Microsoft\Windows\WER\ReportQueue")
            targets["crash_dumps"].extend([crash_dumps, wer_archive, wer_queue])

        # 5. Windows Update Download Cache (C:\Windows\SoftwareDistribution\Download)
        win_update = os.path.join(system_root, r"SoftwareDistribution\Download")
        if os.path.exists(win_update):
            targets["windows_update"].append(win_update)

        # 6. Popular App Caches (Zalo safe cache, Discord, Telegram Desktop, VS Code, Pip, Npm)
        if app_data:
            # Zalo Safe Cache (TUYỆT ĐỐI KHÔNG XÓA Database hoặc ZaloDownloads)
            zalo_base = os.path.join(app_data, "ZaloData")
            if os.path.exists(zalo_base):
                zalo_safe_subs = [
                    "Cache", "Code Cache", "GPUCache", "DawnCache", "logs",
                    r"media\temp", r"media\update", "resp_cache",
                    r"Partitions\zalo\Cache", r"Partitions\zalo\Code Cache", r"Partitions\zalo\GPUCache"
                ]
                for sub in zalo_safe_subs:
                    p = os.path.join(zalo_base, sub)
                    if os.path.exists(p):
                        targets["app_caches"].append(p)

            # Discord Cache
            discord_base = os.path.join(app_data, "discord")
            if os.path.exists(discord_base):
                for sub in ["Cache", "Code Cache", "GPUCache"]:
                    p = os.path.join(discord_base, sub)
                    if os.path.exists(p):
                        targets["app_caches"].append(p)

            # Telegram Desktop Cache
            tele_base = os.path.join(app_data, r"Telegram Desktop\tdata")
            if os.path.exists(tele_base):
                for sub in [r"user_data\cache", "temp"]:
                    p = os.path.join(tele_base, sub)
                    if os.path.exists(p):
                        targets["app_caches"].append(p)

            # VS Code Cache
            code_base = os.path.join(app_data, "Code")
            if os.path.exists(code_base):
                for sub in ["Cache", "CachedData", "CachedExtensionVSIXs", "GPUCache", "logs"]:
                    p = os.path.join(code_base, sub)
                    if os.path.exists(p):
                        targets["app_caches"].append(p)

            # Roaming npm-cache if present
            npm_roaming = os.path.join(app_data, "npm-cache")
            if os.path.exists(npm_roaming):
                targets["app_caches"].append(npm_roaming)

        if local_app_data:
            # Python pip cache
            pip_cache = os.path.join(local_app_data, r"pip\cache")
            if os.path.exists(pip_cache):
                targets["app_caches"].append(pip_cache)

            # Local npm-cache
            npm_local = os.path.join(local_app_data, "npm-cache")
            if os.path.exists(npm_local):
                targets["app_caches"].append(npm_local)

            # Programs\Zalo\logs
            zalo_prog_logs = os.path.join(local_app_data, r"Programs\Zalo\logs")
            if os.path.exists(zalo_prog_logs):
                targets["app_caches"].append(zalo_prog_logs)

        return targets

    @staticmethod
    def get_recycle_bin_info() -> Dict[str, Any]:
        """
        Lấy thông tin dung lượng và số lượng file trong Thùng Rác (Recycle Bin)
        """
        try:
            rb = SHQUERYRBINFO()
            rb.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            res = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(rb))
            if res == 0:
                return {
                    "size_bytes": rb.i64Size,
                    "size_mb": round(rb.i64Size / (1024 ** 2), 2),
                    "items": rb.i64NumItems
                }
        except Exception as e:
            print(f"[JunkCleaner] Error querying recycle bin: {e}")
        return {"size_bytes": 0, "size_mb": 0.0, "items": 0}

    @staticmethod
    def empty_recycle_bin() -> Dict[str, Any]:
        """
        Dọn sạch Thùng Rác thông qua Win32 API mà không hiện hộp thoại xác nhận phiền phức
        """
        info_before = JunkCleaner.get_recycle_bin_info()
        try:
            res = ctypes.windll.shell32.SHEmptyRecycleBinW(
                None, 
                None, 
                SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
            )
            if res == 0 or res == -2147418113:  # 0 is S_OK, -2147418113 is E_UNEXPECTED (often when already empty)
                return {
                    "success": True,
                    "freed_bytes": info_before["size_bytes"],
                    "freed_mb": info_before["size_mb"],
                    "items": info_before["items"]
                }
        except Exception as e:
            print(f"[JunkCleaner] Error emptying recycle bin: {e}")
        return {"success": False, "freed_bytes": 0, "freed_mb": 0.0, "items": 0}

    @staticmethod
    def scan_directory(directory: str) -> Dict[str, Any]:
        total_size = 0
        file_count = 0
        if not os.path.exists(directory):
            return {"size_bytes": 0, "file_count": 0}

        try:
            for root, dirs, files in os.walk(directory):
                for f in files:
                    try:
                        filepath = os.path.join(root, f)
                        # Avoid following symlinks outside
                        if not os.path.islink(filepath):
                            total_size += os.path.getsize(filepath)
                            file_count += 1
                    except (OSError, PermissionError):
                        continue
        except Exception:
            pass
        return {"size_bytes": total_size, "file_count": file_count}

    @classmethod
    def scan(cls, enabled_targets: Dict[str, bool]) -> Dict[str, Any]:
        """
        Quét sơ bộ dung lượng rác và số file có thể dọn dẹp
        """
        target_paths = cls.get_target_paths()
        results = {
            "categories": {},
            "total_bytes": 0,
            "total_mb": 0.0,
            "total_files": 0
        }

        for cat_key, is_enabled in enabled_targets.items():
            if not is_enabled:
                continue

            if cat_key == "recycle_bin":
                rb_info = cls.get_recycle_bin_info()
                results["categories"]["recycle_bin"] = {
                    "name": "Thùng rác (Recycle Bin)",
                    "size_bytes": rb_info["size_bytes"],
                    "size_mb": rb_info["size_mb"],
                    "file_count": rb_info["items"]
                }
                results["total_bytes"] += rb_info["size_bytes"]
                results["total_files"] += rb_info["items"]
                continue

            if cat_key in target_paths:
                cat_bytes = 0
                cat_files = 0
                for path in target_paths[cat_key]:
                    stat = cls.scan_directory(path)
                    cat_bytes += stat["size_bytes"]
                    cat_files += stat["file_count"]

                name_map = {
                    "user_temp": "File tạm người dùng (User Temp)",
                    "system_temp": "File tạm hệ thống (System Temp)",
                    "browser_cache": "Bộ nhớ đệm trình duyệt (Browser Cache)",
                    "crash_dumps": "File kết xuất lỗi (Crash Dumps & WER)",
                    "windows_update": "Bộ nhớ đệm Windows Update (SoftwareDistribution\\Download)",
                    "app_caches": "Bộ nhớ đệm ứng dụng (Zalo, VS Code, Discord, Pip, Npm)"
                }

                results["categories"][cat_key] = {
                    "name": name_map.get(cat_key, cat_key),
                    "size_bytes": cat_bytes,
                    "size_mb": round(cat_bytes / (1024 ** 2), 2),
                    "file_count": cat_files
                }
                results["total_bytes"] += cat_bytes
                results["total_files"] += cat_files

        results["total_mb"] = round(results["total_bytes"] / (1024 ** 2), 2)
        return results

    @classmethod
    def clean(cls, enabled_targets: Dict[str, bool], progress_callback: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
        """
        Thực hiện dọn dẹp an toàn các mục tiêu được chỉ định
        """
        target_paths = cls.get_target_paths()
        total_freed_bytes = 0
        total_deleted_files = 0
        details = {}

        # 1. Dọn Thùng Rác
        if enabled_targets.get("recycle_bin", False):
            if progress_callback:
                progress_callback("Đang dọn sạch Thùng rác...", 10)
            rb_res = cls.empty_recycle_bin()
            total_freed_bytes += rb_res["freed_bytes"]
            total_deleted_files += rb_res["items"]
            details["recycle_bin"] = rb_res

        # 2. Dọn các thư mục tạm & cache
        cat_order = ["user_temp", "system_temp", "browser_cache", "crash_dumps", "windows_update", "app_caches"]
        pct_step = 80 // max(1, len(cat_order))
        current_pct = 15

        for cat_key in cat_order:
            if not enabled_targets.get(cat_key, False):
                continue

            if progress_callback:
                display_name = {
                    "user_temp": "File tạm người dùng",
                    "system_temp": "File tạm hệ thống",
                    "browser_cache": "Cache trình duyệt",
                    "crash_dumps": "Crash dumps & WER",
                    "windows_update": "Cache Windows Update",
                    "app_caches": "Cache ứng dụng (Zalo, VS Code, Discord, Pip, Npm)"
                }.get(cat_key, cat_key)
                progress_callback(f"Đang dọn dẹp {display_name}...", current_pct)

            cat_freed_bytes = 0
            cat_deleted_files = 0

            for base_dir in target_paths.get(cat_key, []):
                if not os.path.exists(base_dir):
                    continue

                # Xóa các file và thư mục con bên trong base_dir
                try:
                    for item in os.listdir(base_dir):
                        item_path = os.path.join(base_dir, item)
                        try:
                            if os.path.isfile(item_path) or os.path.islink(item_path):
                                file_size = os.path.getsize(item_path)
                                try:
                                    os.unlink(item_path)
                                except PermissionError:
                                    try:
                                        os.chmod(item_path, stat.S_IWRITE)
                                        os.unlink(item_path)
                                    except Exception:
                                        continue
                                cat_freed_bytes += file_size
                                cat_deleted_files += 1
                            elif os.path.isdir(item_path):
                                dir_size = cls.scan_directory(item_path)["size_bytes"]
                                shutil.rmtree(item_path, onerror=remove_readonly)
                                if not os.path.exists(item_path):
                                    cat_freed_bytes += dir_size
                                    cat_deleted_files += 1
                        except (PermissionError, OSError):
                            continue
                except Exception:
                    continue

            total_freed_bytes += cat_freed_bytes
            total_deleted_files += cat_deleted_files
            details[cat_key] = {
                "freed_bytes": cat_freed_bytes,
                "freed_mb": round(cat_freed_bytes / (1024 ** 2), 2),
                "deleted_files": cat_deleted_files
            }
            current_pct += pct_step

        if progress_callback:
            progress_callback("Hoàn tất dọn dẹp!", 100)

        freed_mb = round(total_freed_bytes / (1024 ** 2), 2)
        logger.info(f"[JunkCleaner] Hoàn tất dọn dẹp: Đã xóa {total_deleted_files} files, giải phóng {freed_mb} MB.")

        return {
            "total_freed_bytes": total_freed_bytes,
            "total_freed_mb": freed_mb,
            "total_deleted_files": total_deleted_files,
            "details": details
        }


# ==============================================================================
# LARGE FILE SCANNER & MANAGER (Giai đoạn 1)
# ==============================================================================

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040        # Move to Recycle Bin (cho phép Ctrl+Z)
FOF_NOCONFIRMATION = 0x0010   # Không hiện popup Windows xác nhận
FOF_SILENT = 0x0004           # Không hiện progress dialog Windows

def format_file_size(size_bytes: int) -> str:
    """Định dạng kích thước file sang GB, MB hoặc KB dễ đọc"""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.2f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"

class LargeFileScanner:
    """
    Quét và quản lý các file có dung lượng lớn (>100MB, >500MB, >1GB)
    Hỗ trợ xóa an toàn vào Thùng Rác (Recycle Bin) qua Win32 API.
    """

    @staticmethod
    def get_default_scan_locations() -> List[str]:
        user_profile = os.environ.get("USERPROFILE", "")
        locs = []
        if user_profile:
            for folder in ["Downloads", "Documents", "Desktop", "Videos", "Music", "Pictures"]:
                p = os.path.join(user_profile, folder)
                if os.path.exists(p):
                    locs.append(p)
        return locs

    @staticmethod
    def scan_large_files(
        root_paths: Optional[List[str]] = None,
        min_size_mb: int = 100,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> List[Dict[str, Any]]:
        """
        Quét đệ quy tìm các file có kích thước >= min_size_mb.
        Bỏ qua các thư mục hệ thống và rác nội bộ (.git, .venv, $Recycle.Bin, node_modules, AppData).
        """
        from datetime import datetime

        if root_paths is None or len(root_paths) == 0:
            root_paths = LargeFileScanner.get_default_scan_locations()

        min_bytes = min_size_mb * 1024 * 1024
        results = []

        ignore_dirs = {
            "$recycle.bin", "system volume information", ".git", 
            ".venv", "node_modules", "appdata", "__pycache__", ".vscode"
        }

        total_roots = len(root_paths)
        for idx, base_dir in enumerate(root_paths):
            if cancel_check and cancel_check():
                break

            if not os.path.exists(base_dir):
                continue

            pct_base = int((idx / max(1, total_roots)) * 90)
            if progress_callback:
                progress_callback(f"Đang quét thư mục: {os.path.basename(base_dir)}...", pct_base)

            try:
                for root, dirs, files in os.walk(base_dir):
                    if cancel_check and cancel_check():
                        break

                    # Loại trừ các thư mục nhạy cảm hoặc nội bộ
                    dirs[:] = [d for d in dirs if d.lower() not in ignore_dirs and not d.startswith("$")]

                    for f in files:
                        try:
                            f_path = os.path.join(root, f)
                            if os.path.islink(f_path):
                                continue

                            f_size = os.path.getsize(f_path)
                            if f_size >= min_bytes:
                                mtime = os.path.getmtime(f_path)
                                mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                                ext = os.path.splitext(f)[1].lower()

                                results.append({
                                    "filename": f,
                                    "path": f_path,
                                    "directory": root,
                                    "size_bytes": f_size,
                                    "size_mb": round(f_size / (1024 ** 2), 2),
                                    "size_formatted": format_file_size(f_size),
                                    "modified": mtime_str,
                                    "mtime": mtime,
                                    "extension": ext if ext else "(Không đuôi)"
                                })
                        except (OSError, PermissionError):
                            continue
            except Exception as e:
                logger.warning(f"[LargeFileScanner] Lỗi quét tại {base_dir}: {e}")

        # Sắp xếp giảm dần theo kích thước file (file lớn nhất đứng đầu)
        results.sort(key=lambda x: x["size_bytes"], reverse=True)

        if progress_callback:
            progress_callback(f"Quét hoàn tất: Tìm thấy {len(results)} file lớn!", 100)

        logger.info(f"[LargeFileScanner] Đã quét xong, tìm thấy {len(results)} file >= {min_size_mb} MB.")
        return results

    @staticmethod
    def send_to_recycle_bin(filepath: str) -> Dict[str, Any]:
        """
        Di chuyển file an toàn vào Thùng Rác Windows (Recycle Bin) qua Win32 SHFileOperationW.
        Người dùng có thể khôi phục lại (Ctrl+Z) bất cứ lúc nào.
        """
        if not os.path.exists(filepath):
            return {"success": False, "error": "File không tồn tại trên đĩa"}

        try:
            # SHFileOperationW yêu cầu chuỗi kết thúc bằng 2 ký tự NULL (\0\0)
            abs_path = os.path.abspath(filepath) + "\0\0"
            file_op = SHFILEOPSTRUCTW()
            file_op.hwnd = None
            file_op.wFunc = FO_DELETE
            file_op.pFrom = abs_path
            file_op.pTo = None
            file_op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
            file_op.fAnyOperationsAborted = False
            file_op.hNameMappings = None
            file_op.lpszProgressTitle = None

            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(file_op))
            if res == 0 and not file_op.fAnyOperationsAborted:
                logger.info(f"[LargeFileScanner] Đã chuyển an toàn vào Thùng rác: {filepath}")
                return {"success": True, "error": None}
            else:
                err_msg = f"Mã lỗi Win32: {res} (aborted={file_op.fAnyOperationsAborted})"
                logger.error(f"[LargeFileScanner] Không thể xóa file {filepath}: {err_msg}")
                return {"success": False, "error": err_msg}
        except Exception as e:
            logger.error(f"[LargeFileScanner] Lỗi ngoại lệ khi xóa file {filepath}: {e}")
            return {"success": False, "error": str(e)}

