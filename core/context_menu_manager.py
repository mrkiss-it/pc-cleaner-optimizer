"""
core/context_menu_manager.py – Context Menu Cleaner (v3.4 Pro)
===============================================================
Rà soát và quản lý các Shell Extension trong menu chuột phải của Windows
(Tập tin, Thư mục, Nền Desktop, Ổ đĩa).
Hỗ trợ:
- Phát hiện các menu mồ côi (Orphan - file DLL đã bị xóa nhưng menu vẫn còn).
- Bật/Tắt an toàn menu chuột phải thông qua nhánh Shell Extensions\\Blocked.
- Dọn dẹp sạch sẽ các mục menu mồ côi giúp File Explorer phản hồi nhanh tức thì.
"""
from __future__ import annotations

import os
import sys
import winreg
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple


LOCATIONS = [
    {
        "key": "file",
        "title": "Tập Tin (*)",
        "reg_path": r"*\shellex\ContextMenuHandlers",
    },
    {
        "key": "directory",
        "title": "Thư Mục (Folder)",
        "reg_path": r"Directory\shellex\ContextMenuHandlers",
    },
    {
        "key": "background",
        "title": "Nền Desktop / Thư Mục",
        "reg_path": r"Directory\Background\shellex\ContextMenuHandlers",
    },
    {
        "key": "drive",
        "title": "Ổ Đĩa (Drive)",
        "reg_path": r"Drive\shellex\ContextMenuHandlers",
    },
]

BLOCKED_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Blocked"


@dataclass
class ContextMenuItem:
    """Đại diện một mục trong menu chuột phải."""
    id: str                 # Unique ID: {loc_key}::{key_name}
    name: str               # Tên handler
    location_key: str       # 'file', 'directory', 'background', 'drive'
    location_title: str     # Tiêu đề vị trí
    reg_path: str           # Đường dẫn registry đầy đủ
    clsid: Optional[str]    # CLSID dạng {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
    dll_path: Optional[str] # Đường dẫn file DLL thực thi
    company: str            # Tên ứng dụng / Nhà phát triển ước lượng
    is_enabled: bool        # True = Đang bật, False = Đã tắt
    is_orphan: bool         # True = File DLL không còn tồn tại!

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "location_key": self.location_key,
            "location_title": self.location_title,
            "reg_path": self.reg_path,
            "clsid": self.clsid,
            "dll_path": self.dll_path,
            "company": self.company,
            "is_enabled": self.is_enabled,
            "is_orphan": self.is_orphan,
        }


class ContextMenuManager:
    """Quản lý và dọn dẹp các Shell Extension trong menu chuột phải."""

    @staticmethod
    def get_blocked_clsids() -> set:
        """Lấy danh sách CLSID đang bị chặn trong Registry (HKCU và HKLM)."""
        blocked = set()

        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, BLOCKED_KEY_PATH) as key:
                    count_vals = winreg.QueryInfoKey(key)[1]
                    for i in range(count_vals):
                        vname, _, _ = winreg.EnumValue(key, i)
                        if vname:
                            blocked.add(vname.strip().upper())
            except Exception:
                pass

        return blocked

    @staticmethod
    def _resolve_clsid_details(clsid_str: str) -> Tuple[Optional[str], str]:
        """Tra cứu đường dẫn DLL và nhà phát triển từ CLSID."""
        if not clsid_str:
            return None, "Windows Shell"

        norm_clsid = clsid_str.strip()
        dll_path = None
        company = "Unknown"

        subkeys = [
            f"CLSID\\{norm_clsid}\\InProcServer32",
            f"CLSID\\{norm_clsid}\\InProcServer",
        ]

        for sk in subkeys:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, sk) as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val:
                        dll_path = os.path.expandvars(val.strip().strip('"'))
                        break
            except Exception:
                pass

        if dll_path:
            # Ước lượng company từ đường dẫn
            lower_p = dll_path.lower()
            if "windows" in lower_p or "system32" in lower_p:
                company = "Microsoft Windows"
            elif "kaspersky" in lower_p:
                company = "Kaspersky Lab"
            elif "google" in lower_p:
                company = "Google LLC"
            elif "winrar" in lower_p:
                company = "WinRAR / RARLab"
            elif "7-zip" in lower_p:
                company = "Igor Pavlov (7-Zip)"
            elif "notepad++" in lower_p:
                company = "Notepad++"
            elif "git" in lower_p:
                company = "Git"
            elif "intel" in lower_p:
                company = "Intel Corporation"
            elif "nvidia" in lower_p:
                company = "NVIDIA Corporation"
            elif "microsoft" in lower_p:
                company = "Microsoft"
            else:
                # Lấy tên thư mục cha
                parts = dll_path.split(os.sep)
                if len(parts) >= 3 and "program files" in parts[1].lower():
                    company = parts[2]
                else:
                    company = os.path.basename(dll_path)
        else:
            company = "System Shell"

        return dll_path, company

    @staticmethod
    def scan_items() -> List[ContextMenuItem]:
        """Quét toàn bộ các mục menu chuột phải trong các vị trí chính."""
        items: List[ContextMenuItem] = []
        blocked_clsids = ContextMenuManager.get_blocked_clsids()

        for loc in LOCATIONS:
            loc_key = loc["key"]
            loc_title = loc["title"]
            rel_path = loc["reg_path"]

            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rel_path) as root_key:
                    subkeys_count = winreg.QueryInfoKey(root_key)[0]
                    for i in range(subkeys_count):
                        key_name = winreg.EnumKey(root_key, i)
                        full_path = f"{rel_path}\\{key_name}"
                        clsid_val = None

                        # Lấy default value (thường là CLSID)
                        try:
                            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, full_path) as sub_key:
                                val, _ = winreg.QueryValueEx(sub_key, "")
                                if val and val.strip().startswith("{") and val.strip().endswith("}"):
                                    clsid_val = val.strip()
                        except Exception:
                            pass

                        # Nếu key_name chính là CLSID
                        if not clsid_val and key_name.startswith("{") and key_name.endswith("}"):
                            clsid_val = key_name

                        dll_path, company = ContextMenuManager._resolve_clsid_details(clsid_val) if clsid_val else (None, "Shell Extension")

                        # Kiểm tra file DLL có tồn tại không
                        is_orphan = False
                        if dll_path:
                            is_orphan = not os.path.exists(dll_path)

                        # Kiểm tra trạng thái enabled
                        is_enabled = True
                        if clsid_val and clsid_val.upper() in blocked_clsids:
                            is_enabled = False
                        if key_name.startswith("-") or (clsid_val and clsid_val.startswith("{-")):
                            is_enabled = False

                        item_id = f"{loc_key}::{key_name}"
                        item = ContextMenuItem(
                            id=item_id,
                            name=key_name.lstrip("-").strip(),
                            location_key=loc_key,
                            location_title=loc_title,
                            reg_path=full_path,
                            clsid=clsid_val,
                            dll_path=dll_path,
                            company=company,
                            is_enabled=is_enabled,
                            is_orphan=is_orphan,
                        )
                        items.append(item)
            except Exception:
                continue

        # Sắp xếp: menu mồ côi (orphan) lên đầu, sau đó theo vị trí và tên
        items.sort(key=lambda x: (not x.is_orphan, x.location_key, x.name.lower()))
        return items

    @staticmethod
    def get_summary() -> Dict[str, Any]:
        """Trả về thống kê tổng quan menu chuột phải."""
        items = ContextMenuManager.scan_items()
        total = len(items)
        enabled_count = sum(1 for x in items if x.is_enabled)
        disabled_count = total - enabled_count
        orphan_count = sum(1 for x in items if x.is_orphan)

        return {
            "total": total,
            "enabled": enabled_count,
            "disabled": disabled_count,
            "orphan": orphan_count,
        }

    @staticmethod
    def toggle_item(item: ContextMenuItem, enable: bool) -> Tuple[bool, str]:
        """
        Bật hoặc tắt một mục menu chuột phải thông qua HKCU Shell Extensions\\Blocked.
        Hoạt động an toàn ở quyền Standard User mà không cần Admin.
        """
        if not item.clsid:
            return False, f"Mục '{item.name}' không có CLSID để điều khiển trạng thái."

        clsid_upper = item.clsid.upper()

        try:
            # Mở hoặc tạo key HKCU
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, BLOCKED_KEY_PATH) as key:
                if enable:
                    # Bật lại -> Xóa khỏi danh sách Blocked
                    try:
                        winreg.DeleteValue(key, clsid_upper)
                    except FileNotFoundError:
                        pass
                    msg = f"Đã bật mục menu '{item.name}'."
                else:
                    # Tắt -> Thêm vào danh sách Blocked
                    winreg.SetValueEx(key, clsid_upper, 0, winreg.REG_SZ, item.name)
                    msg = f"Đã tắt mục menu '{item.name}'."

            return True, msg
        except Exception as e:
            return False, f"Lỗi thao tác: {str(e)}"

    @staticmethod
    def clean_orphan_items() -> Tuple[int, List[str]]:
        """
        Dọn dẹp các mục menu mồ côi (file DLL không còn tồn tại).
        Thực hiện qua việc thêm vào Blocked hoặc xóa khóa nếu có quyền.
        """
        items = ContextMenuManager.scan_items()
        orphans = [it for it in items if it.is_orphan]
        cleaned_count = 0
        details = []

        for it in orphans:
            ok, msg = ContextMenuManager.toggle_item(it, enable=False)
            if ok:
                cleaned_count += 1
                details.append(f"🧹 Đã vô hiệu hóa menu mồ côi: {it.name} ({it.location_title})")
            else:
                details.append(f"⚠️ Thất bại với: {it.name} ({msg})")

        return cleaned_count, details
