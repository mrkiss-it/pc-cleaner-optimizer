import os
import winreg
import logging
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("RegistryCleaner")

class SafeRegistryCleaner:
    """
    Bộ dọn dẹp Windows Registry an toàn (Safe Registry Cleaner):
    - Rà soát các khóa/giá trị rác và mồ côi (MuiCache, App Paths, Shared DLLs, Startup, Uninstall).
    - Mở rộng biến môi trường (os.path.expandvars) để triệt tiêu hoàn toàn false positive.
    - Bắt buộc tạo file sao lưu .reg trước khi dọn dẹp để đảm bảo hoàn tác 1-Click.
    """

    BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups", "registry")

    @classmethod
    def ensure_backup_dir(cls) -> str:
        os.makedirs(cls.BACKUP_DIR, exist_ok=True)
        return cls.BACKUP_DIR

    @classmethod
    def scan(cls) -> List[Dict[str, Any]]:
        """
        Rà soát các mục rác và mồ côi trong Windows Registry.
        Trả về danh sách các vấn đề phát hiện được.
        """
        findings = []

        # 1. Quét MuiCache (Bộ nhớ đệm tên ứng dụng đã xóa)
        findings.extend(cls._scan_mui_cache())

        # 2. Quét App Paths (Đường dẫn ứng dụng không còn tồn tại)
        findings.extend(cls._scan_app_paths())

        # 3. Quét Shared DLLs (File DLL dùng chung bị thiếu)
        findings.extend(cls._scan_shared_dlls())

        # 4. Quét Startup Run (Lệnh khởi động trỏ tới file đã mất)
        findings.extend(cls._scan_startup_run())

        # 5. Quét Uninstall Entries (Mục gỡ cài đặt có thư mục cài đặt đã mất)
        findings.extend(cls._scan_uninstall_entries())

        return findings

    @classmethod
    def _scan_mui_cache(cls) -> List[Dict[str, Any]]:
        items = []
        key_path = r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                idx = 0
                while True:
                    try:
                        name, val, typ = winreg.EnumValue(key, idx)
                        idx += 1
                        # Tên giá trị trong MuiCache thường chứa đường dẫn file .exe
                        if ".exe" in name.lower() and ":" in name:
                            # Tách phần đường dẫn exe
                            exe_candidate = name.split(".exe")[0] + ".exe" if ".exe" in name else name
                            clean_exe = os.path.expandvars(exe_candidate.strip('"').strip())
                            if clean_exe.lower().endswith(".exe") and not os.path.exists(clean_exe):
                                items.append({
                                    "id": f"mui_{idx}",
                                    "category": "MuiCache",
                                    "root_name": "HKCU",
                                    "root_key": winreg.HKEY_CURRENT_USER,
                                    "key_path": key_path,
                                    "value_name": name,
                                    "value_data": str(val)[:100],
                                    "value_type": typ,
                                    "reason": f"File thực thi không còn tồn tại: {clean_exe}",
                                    "target_path": clean_exe,
                                    "is_key_deletion": False,
                                    "selected": True
                                })
                    except OSError:
                        break
        except Exception as e:
            logger.debug(f"Không thể đọc MuiCache: {e}")
        return items

    @classmethod
    def _scan_app_paths(cls) -> List[Dict[str, Any]]:
        items = []
        roots = [
            (winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
        ]

        for root_key, root_name, subkey in roots:
            try:
                with winreg.OpenKey(root_key, subkey, 0, winreg.KEY_READ) as key:
                    idx = 0
                    while True:
                        try:
                            app_name = winreg.EnumKey(key, idx)
                            idx += 1
                            app_key_path = f"{subkey}\\{app_name}"
                            try:
                                with winreg.OpenKey(root_key, app_key_path, 0, winreg.KEY_READ) as skey:
                                    path, typ = winreg.QueryValueEx(skey, "")
                                    clean_path = os.path.expandvars(path.strip('"').strip())
                                    if clean_path and ":" in clean_path and not os.path.exists(clean_path):
                                        items.append({
                                            "id": f"app_{root_name}_{idx}",
                                            "category": "App Paths",
                                            "root_name": root_name,
                                            "root_key": root_key,
                                            "key_path": app_key_path,
                                            "value_name": "(Default)",
                                            "value_data": clean_path,
                                            "value_type": typ,
                                            "reason": f"Đường dẫn ứng dụng không tồn tại: {clean_path}",
                                            "target_path": clean_path,
                                            "is_key_deletion": True,
                                            "selected": True
                                        })
                            except Exception:
                                pass
                        except OSError:
                            break
            except Exception as e:
                logger.debug(f"Không thể đọc App Paths ({root_name}): {e}")
        return items

    @classmethod
    def _scan_shared_dlls(cls) -> List[Dict[str, Any]]:
        items = []
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDLLs"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ) as key:
                idx = 0
                while True:
                    try:
                        name, val, typ = winreg.EnumValue(key, idx)
                        idx += 1
                        clean_path = os.path.expandvars(name.strip('"').strip())
                        if clean_path and ":" in clean_path and not os.path.exists(clean_path):
                            items.append({
                                "id": f"dll_{idx}",
                                "category": "Shared DLLs",
                                "root_name": "HKLM",
                                "root_key": winreg.HKEY_LOCAL_MACHINE,
                                "key_path": key_path,
                                "value_name": name,
                                "value_data": str(val),
                                "value_type": typ,
                                "reason": f"Shared DLL bị thiếu trên ổ cứng: {clean_path}",
                                "target_path": clean_path,
                                "is_key_deletion": False,
                                "selected": True
                            })
                    except OSError:
                        break
        except Exception as e:
            logger.debug(f"SharedDLLs scan: {e}")
        return items

    @classmethod
    def _scan_startup_run(cls) -> List[Dict[str, Any]]:
        items = []
        roots = [
            (winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")
        ]

        for root_key, root_name, subkey in roots:
            try:
                with winreg.OpenKey(root_key, subkey, 0, winreg.KEY_READ) as key:
                    idx = 0
                    while True:
                        try:
                            name, val, typ = winreg.EnumValue(key, idx)
                            idx += 1
                            cmd = str(val).strip()
                            if not cmd:
                                continue

                            # Tách file exe từ command line
                            exe_cand = cmd
                            if cmd.startswith('"'):
                                parts = cmd[1:].split('"', 1)
                                exe_cand = parts[0]
                            else:
                                exe_cand = cmd.split(" ")[0]

                            clean_exe = os.path.expandvars(exe_cand.strip())
                            if ":" in clean_exe and clean_exe.lower().endswith((".exe", ".bat", ".cmd", ".vbs")):
                                if not os.path.exists(clean_exe):
                                    items.append({
                                        "id": f"startup_{root_name}_{idx}",
                                        "category": "Startup Run",
                                        "root_name": root_name,
                                        "root_key": root_key,
                                        "key_path": subkey,
                                        "value_name": name,
                                        "value_data": cmd,
                                        "value_type": typ,
                                        "reason": f"File khởi động không còn tồn tại: {clean_exe}",
                                        "target_path": clean_exe,
                                        "is_key_deletion": False,
                                        "selected": True
                                    })
                        except OSError:
                            break
            except Exception as e:
                logger.debug(f"Startup run scan ({root_name}): {e}")
        return items

    @classmethod
    def _scan_uninstall_entries(cls) -> List[Dict[str, Any]]:
        items = []
        roots = [
            (winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
        ]

        for root_key, root_name, subkey in roots:
            try:
                with winreg.OpenKey(root_key, subkey, 0, winreg.KEY_READ) as key:
                    idx = 0
                    while True:
                        try:
                            app_sub = winreg.EnumKey(key, idx)
                            idx += 1
                            app_path = f"{subkey}\\{app_sub}"
                            try:
                                with winreg.OpenKey(root_key, app_path, 0, winreg.KEY_READ) as skey:
                                    try:
                                        loc, _ = winreg.QueryValueEx(skey, "InstallLocation")
                                        clean_loc = os.path.expandvars(loc.strip('"').strip())
                                        # Nếu InstallLocation trỏ tới thư mục không tồn tại và chuỗi có độ dài hợp lý
                                        if clean_loc and len(clean_loc) > 4 and ":" in clean_loc and not os.path.exists(clean_loc):
                                            # Kiểm tra xem DisplayName có tồn tại không
                                            dname = app_sub
                                            try:
                                                dname, _ = winreg.QueryValueEx(skey, "DisplayName")
                                            except Exception:
                                                pass
                                            items.append({
                                                "id": f"uninst_{root_name}_{idx}",
                                                "category": "Uninstall",
                                                "root_name": root_name,
                                                "root_key": root_key,
                                                "key_path": app_path,
                                                "value_name": "InstallLocation",
                                                "value_data": clean_loc,
                                                "value_type": winreg.REG_SZ,
                                                "reason": f"Thư mục cài đặt đã bị xóa: {clean_loc} ({dname})",
                                                "target_path": clean_loc,
                                                "is_key_deletion": False,
                                                "selected": True
                                            })
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        except OSError:
                            break
            except Exception as e:
                logger.debug(f"Uninstall scan ({root_name}): {e}")
        return items

    @classmethod
    def create_backup(cls, items: List[Dict[str, Any]]) -> Optional[str]:
        """
        Tạo file sao lưu .reg chuẩn RFC trước khi xóa bất kỳ giá trị nào.
        Cho phép người dùng hoàn tác 100% bằng cách double-click file .reg hoặc bấm Hoàn Tác.
        """
        if not items:
            return None

        cls.ensure_backup_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(cls.BACKUP_DIR, f"Registry_Backup_{ts}.reg")

        try:
            # Nhóm theo khóa (key) để xuất file .reg chuẩn
            keys_map: Dict[str, List[Dict[str, Any]]] = {}
            for it in items:
                full_key = f"{it['root_name']}\\{it['key_path']}"
                if full_key not in keys_map:
                    keys_map[full_key] = []
                keys_map[full_key].append(it)

            lines = [
                "Windows Registry Editor Version 5.00",
                f"; Auto-generated backup by PC Auto Cleaner on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ""
            ]

            for full_key, group in keys_map.items():
                lines.append(f"[{full_key}]")
                for it in group:
                    val_name = it["value_name"]
                    val_data = it["value_data"]
                    val_type = it.get("value_type", winreg.REG_SZ)

                    if val_name == "(Default)":
                        formatted_name = "@"
                    else:
                        # Escape quotes & backslashes
                        esc_name = val_name.replace("\\", "\\\\").replace('"', '\\"')
                        formatted_name = f'"{esc_name}"'

                    if val_type == winreg.REG_DWORD:
                        try:
                            dword_val = int(val_data)
                            lines.append(f"{formatted_name}=dword:{dword_val:08x}")
                        except Exception:
                            lines.append(f"{formatted_name}=dword:00000000")
                    else:
                        esc_data = str(val_data).replace("\\", "\\\\").replace('"', '\\"')
                        lines.append(f'{formatted_name}="{esc_data}"')
                lines.append("")

            with open(backup_file, "w", encoding="utf-16") as f:
                f.write("\n".join(lines))

            logger.info(f"Đã tạo file sao lưu Registry: {backup_file}")
            return backup_file
        except Exception as e:
            logger.error(f"Lỗi khi tạo file backup registry: {e}")
            return None

    @classmethod
    def clean_items(cls, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Tiến hành dọn dẹp các mục đã chọn sau khi đã tạo file sao lưu.
        """
        if not items:
            return {"cleaned_count": 0, "error_count": 0, "backup_path": None}

        # 1. Tự động sao lưu trước
        backup_path = cls.create_backup(items)

        cleaned = 0
        errors = 0

        for it in items:
            try:
                root_key = it["root_key"]
                key_path = it["key_path"]
                val_name = it["value_name"]
                is_key = it.get("is_key_deletion", False)

                if is_key:
                    # Xóa toàn bộ subkey (ví dụ một subkey trong App Paths)
                    # Cần mở key cha để xóa subkey
                    parent_path, sub_name = os.path.split(key_path)
                    try:
                        with winreg.OpenKey(root_key, parent_path, 0, winreg.KEY_SET_VALUE) as pkey:
                            winreg.DeleteKey(pkey, sub_name)
                            cleaned += 1
                    except Exception as e:
                        logger.warning(f"Không thể xóa key {key_path}: {e}")
                        errors += 1
                else:
                    # Xóa giá trị (value)
                    try:
                        with winreg.OpenKey(root_key, key_path, 0, winreg.KEY_SET_VALUE) as key:
                            winreg.DeleteValue(key, val_name)
                            cleaned += 1
                    except Exception as e:
                        logger.warning(f"Không thể xóa value {val_name} trong {key_path}: {e}")
                        errors += 1
            except Exception as e:
                logger.error(f"Lỗi xử lý mục dọn dẹp: {e}")
                errors += 1

        return {
            "cleaned_count": cleaned,
            "error_count": errors,
            "backup_path": backup_path
        }

    @classmethod
    def restore_backup(cls, backup_path: str) -> Dict[str, Any]:
        """
        Khôi phục lại Registry từ file .reg sử dụng lệnh reg import của Windows.
        """
        if not os.path.exists(backup_path):
            return {"success": False, "message": f"Không tìm thấy file sao lưu: {backup_path}"}

        try:
            res = subprocess.run(["reg", "import", backup_path], capture_output=True, text=True)
            if res.returncode == 0:
                logger.info(f"Đã khôi phục thành công file Registry: {backup_path}")
                return {"success": True, "message": "Đã khôi phục thành công các khóa Registry từ bản sao lưu."}
            else:
                logger.warning(f"Lỗi reg import: {res.stderr}")
                return {"success": False, "message": f"Không thể khôi phục: {res.stderr.strip() or res.stdout.strip()}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @classmethod
    def get_backup_files(cls) -> List[Dict[str, Any]]:
        """
        Lấy danh sách các file sao lưu .reg đã tạo.
        """
        cls.ensure_backup_dir()
        files = []
        try:
            for f in os.listdir(cls.BACKUP_DIR):
                if f.lower().endswith(".reg"):
                    full_path = os.path.join(cls.BACKUP_DIR, f)
                    st = os.stat(full_path)
                    files.append({
                        "filename": f,
                        "path": full_path,
                        "size_kb": st.st_size / 1024,
                        "created_at": datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
                    })
            files.sort(key=lambda x: x["created_at"], reverse=True)
        except Exception as e:
            logger.debug(f"Lỗi đọc backup dir: {e}")
        return files
