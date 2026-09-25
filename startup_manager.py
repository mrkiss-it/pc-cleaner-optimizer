import sys
import os
import winreg

APP_NAME = "PCAutoCleaner"
OLD_APP_NAME = "PCAuxAutoCleaner"

class StartupManager:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def is_startup_enabled() -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, StartupManager.REG_PATH, 0, winreg.KEY_READ) as key:
                try:
                    val, _ = winreg.QueryValueEx(key, APP_NAME)
                    return bool(val)
                except FileNotFoundError:
                    val, _ = winreg.QueryValueEx(key, OLD_APP_NAME)
                    return bool(val)
        except (FileNotFoundError, OSError):
            return False

    @staticmethod
    def set_startup(enable: bool, target_path: str = None) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, StartupManager.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    if not target_path:
                        if getattr(sys, 'frozen', False):
                            target_path = f'"{sys.executable}" --minimized'
                        else:
                            current_dir = os.path.dirname(os.path.abspath(__file__))
                            dist_exe = os.path.join(current_dir, "dist", "PCAutoCleaner", "PCAutoCleaner.exe")
                            if os.path.exists(dist_exe):
                                target_path = f'"{dist_exe}" --minimized'
                            else:
                                python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                                main_py = os.path.join(current_dir, "main.py")
                                target_path = f'"{python_exe}" "{main_py}" --minimized'

                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, target_path)
                    try:
                        winreg.DeleteValue(key, OLD_APP_NAME)
                    except FileNotFoundError:
                        pass
                    print(f"[StartupManager] Enabled startup with command: {target_path}")
                else:
                    for name in (APP_NAME, OLD_APP_NAME):
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                    print("[StartupManager] Disabled startup.")
            return True
        except Exception as e:
            print(f"[StartupManager] Error configuring startup: {e}")
            return False


# Chỉ tài khoản hiện tại. Không đọc HKLM.
HKCU_RUN_PATH = StartupManager.REG_PATH
HKCU_DISABLED_RUN_PATH = r"Software\PCAutoCleaner\DisabledStartup\Run"
STARTUP_FOLDER_OFF_SUFFIX = ".pcac-off"
IMPACT_UNKNOWN_VI = "không rõ"
OWN_STARTUP_NAMES = {APP_NAME.lower(), OLD_APP_NAME.lower()}

STARTUP_SCOPE_VI = (
    "Chỉ mục khởi động của tài khoản này: khóa Run trong HKCU "
    "(Software\\Microsoft\\Windows\\CurrentVersion\\Run) và thư mục Startup. "
    "Không đọc HKLM, không cần Admin. "
    "Mục khởi động của chính ứng dụng này vẫn ở tab Tự động, không nằm trong danh sách. "
    "App không đo thời gian khởi động — cột tác động luôn là «không rõ»."
)


def user_startup_dir(environ=None) -> str:
    env = os.environ if environ is None else environ
    appdata = str(env.get("APPDATA") or "")
    if appdata:
        return os.path.join(
            appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
        )
    return os.path.join(
        os.path.expanduser("~"),
        "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


class Win32StartupRegistry:
    """Đọc/ghi giá trị chuỗi trên HKCU. Cùng kiểu quyền với StartupManager.set_startup."""

    def list_values(self, path: str):
        items = []
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except OSError:
            return items
        try:
            index = 0
            while True:
                try:
                    name, value, typ = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                reg_sz = getattr(winreg, "REG_SZ", 1)
                reg_expand = getattr(winreg, "REG_EXPAND_SZ", 2)
                if typ in (reg_sz, reg_expand) and isinstance(value, str):
                    items.append((str(name), value, int(typ)))
        finally:
            winreg.CloseKey(key)
        return items

    def set_value(self, path: str, name: str, value: str, typ=None) -> None:
        reg_sz = getattr(winreg, "REG_SZ", 1)
        access = getattr(winreg, "KEY_WRITE", None) or winreg.KEY_SET_VALUE
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, access)
        try:
            winreg.SetValueEx(key, name, 0, reg_sz if typ is None else int(typ), value)
        finally:
            winreg.CloseKey(key)

    def delete_value(self, path: str, name: str) -> None:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, name)
        finally:
            winreg.CloseKey(key)


def _as_triples(values):
    triples = []
    for item in values or []:
        if len(item) == 2:
            name, value = item
            typ = getattr(winreg, "REG_SZ", 1)
        else:
            name, value, typ = item[0], item[1], item[2]
        triples.append((str(name), str(value), int(typ)))
    return triples


def _command_target(command: str) -> str:
    text = os.path.expandvars(str(command or "").strip())
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            return text[1:end]
        return ""
    return text.split()[0]


def _target_exists(command: str):
    target = _command_target(command)
    if not target:
        return None
    try:
        return os.path.exists(target)
    except OSError:
        return None


def _entry_note(source: str, target_exists, command: str) -> str:
    note = "Thời gian khởi động: không rõ. Ứng dụng không đo mili-giây."
    lower = str(command or "").lower()
    if source == "startup_folder" and ".lnk" in lower:
        return note + " Không đọc shortcut .lnk nên không biết file đích còn hay không."
    if target_exists is False:
        return note + " Không thấy file được trỏ tới."
    if target_exists is None:
        return note + " Không tách được đường dẫn file."
    return note


def _safe_child(startup_dir: str, filename: str):
    if not filename or os.path.basename(filename) != filename:
        return None
    if filename in (".", "..") or "/" in filename or "\\" in filename:
        return None
    root = os.path.normcase(os.path.realpath(startup_dir))
    path = os.path.normcase(os.path.realpath(os.path.join(startup_dir, filename)))
    try:
        if os.path.commonpath([root, path]) != root:
            return None
    except ValueError:
        return None
    return os.path.join(startup_dir, filename)


def list_user_startup_entries(*, registry=None, startup_dir=None, environ=None) -> dict:
    """
    Liệt kê Run HKCU và thư mục Startup của tài khoản này.
    impact luôn là «không rõ» — không bịa mili-giây.
    """
    reg = registry or Win32StartupRegistry()
    folder = startup_dir or user_startup_dir(environ)
    entries = []
    errors = []
    omitted_own_app = False

    try:
        enabled_values = _as_triples(reg.list_values(HKCU_RUN_PATH))
    except Exception as exc:
        enabled_values = []
        errors.append(f"Không đọc được khóa Run: {exc}")
    try:
        disabled_values = _as_triples(reg.list_values(HKCU_DISABLED_RUN_PATH))
    except Exception as exc:
        disabled_values = []
        errors.append(f"Không đọc được khóa đã tắt: {exc}")

    enabled_names = {name.lower() for name, _value, _typ in enabled_values}
    for name, value, _typ in enabled_values:
        if name.lower() in OWN_STARTUP_NAMES:
            omitted_own_app = True
            continue
        exists = _target_exists(value)
        entries.append({
            "id": f"hkcu:{name}",
            "name": name,
            "command": value,
            "source": "hkcu_run",
            "source_vi": "Run (HKCU)",
            "enabled": True,
            "impact": IMPACT_UNKNOWN_VI,
            "target_exists": exists,
            "note_vi": _entry_note("hkcu_run", exists, value),
        })
    for name, value, _typ in disabled_values:
        if name.lower() in OWN_STARTUP_NAMES:
            omitted_own_app = True
            continue
        if name.lower() in enabled_names:
            continue
        exists = _target_exists(value)
        entries.append({
            "id": f"hkcu:{name}",
            "name": name,
            "command": value,
            "source": "hkcu_run",
            "source_vi": "Run (HKCU) — đang cất ở khóa tắt của app",
            "enabled": False,
            "impact": IMPACT_UNKNOWN_VI,
            "target_exists": exists,
            "note_vi": _entry_note("hkcu_run", exists, value),
        })

    if os.path.isdir(folder):
        try:
            names = sorted(os.listdir(folder))
        except OSError as exc:
            names = []
            errors.append(f"Không đọc được thư mục Startup: {exc}")
        for filename in names:
            if filename.lower() in ("desktop.ini",):
                continue
            full = os.path.join(folder, filename)
            if not os.path.isfile(full):
                continue
            enabled = not filename.lower().endswith(STARTUP_FOLDER_OFF_SUFFIX)
            display = filename[:-len(STARTUP_FOLDER_OFF_SUFFIX)] if not enabled else filename
            exists = None if ".lnk" in filename.lower() else True
            entries.append({
                "id": f"folder:{filename}",
                "name": display,
                "command": full,
                "source": "startup_folder",
                "source_vi": "Thư mục Startup",
                "enabled": enabled,
                "impact": IMPACT_UNKNOWN_VI,
                "target_exists": exists,
                "note_vi": _entry_note("startup_folder", exists, filename),
            })
    else:
        errors.append("Không thấy thư mục Startup của tài khoản này.")

    entries.sort(key=lambda item: (not item["enabled"], item["name"].casefold()))
    return {
        "entries": entries,
        "impact_note_vi": STARTUP_SCOPE_VI,
        "scope_vi": STARTUP_SCOPE_VI,
        "omitted_own_app": omitted_own_app,
        "startup_dir": folder,
        "errors": errors,
    }


def _lookup(reg, path: str, name: str):
    for item_name, value, typ in _as_triples(reg.list_values(path)):
        if item_name.lower() == name.lower():
            return item_name, value, typ
    return None


def _set_hkcu(reg, name: str, enabled: bool) -> dict:
    if not name or name.lower() in OWN_STARTUP_NAMES:
        return {
            "success": False,
            "message_vi": "Mục khởi động của chính ứng dụng này đổi ở tab Tự động, không tắt ở đây.",
        }
    current = _lookup(reg, HKCU_RUN_PATH, name)
    parked = _lookup(reg, HKCU_DISABLED_RUN_PATH, name)
    if enabled:
        if current and not parked:
            return {"success": True, "enabled": True, "message_vi": f"«{name}» đã đang bật."}
        if not parked:
            return {"success": False, "message_vi": f"Không thấy «{name}» trong danh sách đã tắt."}
        stored_name, value, typ = parked
        try:
            reg.set_value(HKCU_RUN_PATH, stored_name, value, typ)
        except Exception as exc:
            return {"success": False, "message_vi": f"Chưa bật lại «{name}»: {exc}"}
        try:
            reg.delete_value(HKCU_DISABLED_RUN_PATH, stored_name)
        except Exception as exc:
            return {
                "success": False,
                "message_vi": (
                    f"Đã ghi lại «{name}» vào Run nhưng chưa xóa bản tắt: {exc}. "
                    "Hãy bấm làm mới và kiểm tra."
                ),
            }
        return {
            "success": True,
            "enabled": True,
            "message_vi": f"Đã bật lại «{name}». Windows sẽ chạy mục này khi bạn đăng nhập.",
        }

    if parked and not current:
        return {"success": True, "enabled": False, "message_vi": f"«{name}» đã đang tắt."}
    if not current:
        return {"success": False, "message_vi": f"Không thấy «{name}» trong khóa Run."}
    stored_name, value, typ = current
    try:
        reg.set_value(HKCU_DISABLED_RUN_PATH, stored_name, value, typ)
    except Exception as exc:
        return {
            "success": False,
            "message_vi": f"Chưa tắt «{name}» — giá trị Run vẫn giữ nguyên. Lỗi: {exc}",
        }
    try:
        reg.delete_value(HKCU_RUN_PATH, stored_name)
    except Exception as exc:
        return {
            "success": False,
            "message_vi": (
                f"Đã cất bản sao của «{name}» nhưng chưa xóa khỏi Run: {exc}. "
                "Mục có thể vẫn chạy khi đăng nhập."
            ),
        }
    return {
        "success": True,
        "enabled": False,
        "message_vi": (
            f"Đã tắt «{name}». Giá trị được cất trong HKCU "
            f"({HKCU_DISABLED_RUN_PATH}) để bật lại. Không xóa vĩnh viễn."
        ),
    }


def _set_folder(startup_dir: str, filename: str, enabled: bool) -> dict:
    path = _safe_child(startup_dir, filename)
    if path is None:
        return {"success": False, "message_vi": "Tên file không hợp lệ."}
    if not os.path.isfile(path):
        return {"success": False, "message_vi": "Không thấy file trong thư mục Startup."}
    is_off = filename.lower().endswith(STARTUP_FOLDER_OFF_SUFFIX)
    if enabled and not is_off:
        return {"success": True, "enabled": True, "message_vi": "Mục này đã đang bật."}
    if (not enabled) and is_off:
        return {"success": True, "enabled": False, "message_vi": "Mục này đã đang tắt."}
    if enabled:
        new_name = filename[: -len(STARTUP_FOLDER_OFF_SUFFIX)]
    else:
        new_name = filename + STARTUP_FOLDER_OFF_SUFFIX
    dest = _safe_child(startup_dir, new_name)
    if dest is None:
        return {"success": False, "message_vi": "Không đổi được tên file."}
    if os.path.exists(dest):
        return {
            "success": False,
            "message_vi": f"Đã có «{new_name}» trong thư mục Startup — không ghi đè.",
        }
    try:
        os.rename(path, dest)
    except OSError as exc:
        return {"success": False, "message_vi": f"Không đổi được file: {exc}"}
    if enabled:
        return {
            "success": True,
            "enabled": True,
            "message_vi": f"Đã bật lại «{new_name}» bằng cách trả tên file trong thư mục Startup.",
        }
    return {
        "success": True,
        "enabled": False,
        "message_vi": (
            f"Đã tắt bằng cách đổi tên thành «{new_name}». "
            "Windows không chạy file này khi đăng nhập. Bật lại sẽ trả tên cũ."
        ),
    }


def set_user_startup_enabled(entry_id: str, enabled: bool, *, registry=None, startup_dir=None, environ=None) -> dict:
    """Bật/tắt một mục HKCU Run hoặc file trong thư mục Startup. Không đụng HKLM."""
    reg = registry or Win32StartupRegistry()
    folder = startup_dir or user_startup_dir(environ)
    text = str(entry_id or "")
    kind, sep, ident = text.partition(":")
    if not sep or not ident:
        return {"success": False, "message_vi": "Không nhận ra mục này."}
    if kind == "hkcu":
        return _set_hkcu(reg, ident, bool(enabled))
    if kind == "folder":
        return _set_folder(folder, ident, bool(enabled))
    return {"success": False, "message_vi": "Chỉ bật/tắt mục Run HKCU hoặc thư mục Startup."}
