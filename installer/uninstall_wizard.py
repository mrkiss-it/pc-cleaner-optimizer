"""
installer/uninstall_wizard.py – Trình Gỡ Cài Đặt Chuẩn Windows (Uninstaller) cho PC Auto Cleaner & Optimizer.

Dọn dẹp:
- Lối tắt Desktop / Start Menu (kể cả lối tắt gỡ cài đặt trong Programs)
- Khóa Registry Uninstall (Windows Settings → Ứng dụng)
- Giá trị Run (khởi động cùng Windows)
- Thư mục chương trình (sau khi process thoát)
- %APPDATA%\\PCAutoCleaner chỉ khi người dùng chọn "Xóa cả cấu hình / dữ liệu cá nhân"

Cờ dòng lệnh:
  --remove-user-data / --remove-data  Xóa cấu hình cá nhân
  --keep-user-data                    Giữ cấu hình (mặc định)
  --confirmed                         Đã xác nhận từ trong app: chạy gỡ ngay (vẫn hiện tiến trình)
  --quiet / /S                        Gỡ im lặng, không UI
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import winreg
except ImportError:  # Linux CI
    winreg = None  # type: ignore

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QMessageBox, QFrame, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

# Tokens (Fluent Dark, cùng họ màu Setup Wizard)
_BG_DARK     = "#0d1117"
_PANEL_BG    = "#161b22"
_CARD_BG     = "#1b212c"
_CARD_BORDER = "#30363d"
_TEXT_WHITE  = "#f0f6fc"
_TEXT_MUTED  = "#8b949e"
_ACCENT_BLUE = "#58a6ff"
_DANGER      = "#f85149"
_SUCCESS     = "#3fb950"

UNINSTALL_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PCAutoCleaner"
UNINSTALL_REG_PATH_WOW = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\PCAutoCleaner"
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAMES = ("PCAutoCleaner", "PCAuxAutoCleaner")
APP_DIR_NAME = "PCAutoCleaner"
UNINSTALL_EXE_NAMES = ("uninstall.exe", "Uninstall.exe")
MAIN_EXE_NAME = "PCAutoCleaner.exe"
UNINSTALL_SHORTCUT_NAME = "PC Auto Cleaner – Gỡ cài đặt.lnk"

SHORTCUT_NAMES = (
    "PC Auto Cleaner.lnk",
    "PC Auto Cleaner & Optimizer.lnk",
    UNINSTALL_SHORTCUT_NAME,
    "PC Auto Cleaner - Gỡ cài đặt.lnk",
    "Gỡ cài đặt PC Auto Cleaner.lnk",
    "Uninstall PC Auto Cleaner.lnk",
)
START_MENU_SUBFOLDERS = (
    "PCAutoCleaner",
    "PC Auto Cleaner",
    "PC Auto Cleaner & Optimizer",
)

RemoveFileFn = Callable[[str], None]
RmtreeFn = Callable[[str], None]
ScheduleFn = Callable[[str], bool]


def qt_literal_ampersand(text: str) -> str:
    """Escape '&' so Qt mnemonics show a literal ampersand (cùng cách Setup Wizard)."""
    return (text or "").replace("&", "&&")


def _ensure_app_meta_import_path():
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and meipass not in sys.path:
            sys.path.insert(0, meipass)
        return
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


_ensure_app_meta_import_path()
try:
    import app_meta
    APP_DISPLAY_NAME = app_meta.APP_NAME
except Exception:
    APP_DISPLAY_NAME = "PC Auto Cleaner & Optimizer"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_uninstall_args(argv: Optional[Sequence[str]] = None) -> Dict[str, bool]:
    raw = [str(a) for a in (argv if argv is not None else sys.argv[1:])]
    lower = {a.lower() for a in raw}
    remove = "--remove-user-data" in raw or "--remove-data" in raw
    keep = "--keep-user-data" in raw
    if remove and keep:
        keep = False
    quiet = (
        "--quiet" in raw
        or "/s" in lower
        or "/silent" in lower
        or "/quiet" in lower
    )
    confirmed = "--confirmed" in raw
    return {
        "remove_user_data": bool(remove),
        "keep_user_data": bool(keep) or not remove,
        "quiet": quiet,
        "confirmed": confirmed,
    }


def uninstall_argv(
    remove_user_data: bool = False,
    confirmed: bool = False,
    quiet: bool = False,
) -> List[str]:
    args: List[str] = []
    if remove_user_data:
        args.append("--remove-user-data")
    else:
        args.append("--keep-user-data")
    if confirmed:
        args.append("--confirmed")
    if quiet:
        args.append("--quiet")
    return args


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _unique_existing(paths: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for p in paths:
        if not p:
            continue
        norm = os.path.normcase(os.path.abspath(p))
        if norm in seen:
            continue
        seen.add(norm)
        out.append(p)
    return out


def desktop_dirs(environ: Optional[dict] = None, home: Optional[str] = None) -> List[str]:
    env = environ if environ is not None else os.environ
    home_dir = home or os.path.expanduser("~")
    userprofile = env.get("USERPROFILE") or home_dir
    public = env.get("PUBLIC") or ""
    candidates = [
        os.path.join(home_dir, "Desktop"),
        os.path.join(userprofile, "Desktop"),
        os.path.join(userprofile, "OneDrive", "Desktop"),
        os.path.join(public, "Desktop") if public else "",
    ]
    return _unique_existing(candidates)


def start_menu_dirs(environ: Optional[dict] = None) -> List[str]:
    env = environ if environ is not None else os.environ
    appdata = env.get("APPDATA") or ""
    programdata = env.get("PROGRAMDATA") or ""
    roots = []
    if appdata:
        roots.append(os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"))
    if programdata:
        roots.append(os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"))
    expanded: List[str] = []
    for root in roots:
        expanded.append(root)
        for sub in START_MENU_SUBFOLDERS:
            expanded.append(os.path.join(root, sub))
    return _unique_existing(expanded)


def user_config_dirs(environ: Optional[dict] = None) -> List[str]:
    """Thư mục dữ liệu cá nhân — chỉ xóa khi người dùng chọn.

    Chính: %APPDATA%\\PCAutoCleaner (config.json, secrets, EULA).
    Phụ: %LOCALAPPDATA%\\PCAutoCleaner (cache cập nhật) — không phải Programs\\PCAutoCleaner.
    """
    env = environ if environ is not None else os.environ
    dirs: List[str] = []
    appdata = env.get("APPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, APP_DIR_NAME))
    local = env.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, APP_DIR_NAME))
    return _unique_existing(dirs)


def unquote_command_exe(command: str) -> str:
    """Lấy đường dẫn exe từ UninstallString, bỏ dấu ngoặc và tham số."""
    s = (command or "").strip()
    if not s:
        return ""
    if s.startswith('"'):
        end = s.find('"', 1)
        if end > 1:
            return s[1:end]
    return s.split()[0]


def format_uninstall_command(uninstaller_path: str, quiet: bool = False) -> str:
    quoted = f'"{os.path.abspath(uninstaller_path)}"'
    if quiet:
        return f"{quoted} --quiet"
    return quoted


def resolve_uninstaller_path(install_dir: str) -> str:
    """uninstall.exe cạnh thư mục cài — không bao giờ trả về PCAutoCleaner.exe."""
    if not install_dir:
        return ""
    for name in UNINSTALL_EXE_NAMES:
        p = os.path.join(install_dir, name)
        if os.path.isfile(p):
            return os.path.abspath(p)
    return ""


def get_install_dir() -> str:
    """Thư mục chứa uninstall.exe / PCAutoCleaner.exe khi chạy bản đóng gói.

    PyInstaller --onefile: __file__ nằm trong _MEIPASS (temp), KHÔNG phải thư mục cài.
    Phải dùng dirname(sys.executable).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return ""


def is_safe_install_dir(path: str) -> bool:
    """Không xóa repo nguồn hay thư mục lạ."""
    if not path:
        return False
    try:
        if not os.path.isdir(path):
            return False
    except Exception:
        return False
    if os.path.isdir(os.path.join(path, ".git")):
        return False
    if os.path.isfile(os.path.join(path, "main.py")) and os.path.isdir(os.path.join(path, "installer")):
        return False
    base = os.path.basename(os.path.normpath(path))
    has_main = os.path.isfile(os.path.join(path, MAIN_EXE_NAME))
    has_uninst = any(os.path.isfile(os.path.join(path, n)) for n in UNINSTALL_EXE_NAMES)
    if base.lower() == APP_DIR_NAME.lower():
        return True
    return bool(has_main or has_uninst)


def find_uninstaller_path(
    app_dir: Optional[str] = None,
    environ: Optional[dict] = None,
    winreg_mod=None,
    frozen: Optional[bool] = None,
    executable: Optional[str] = None,
) -> str:
    """Tìm uninstall.exe: cạnh app → registry → script nguồn (dev). Không trả về main exe."""
    candidates: List[str] = []
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = executable if executable is not None else sys.executable

    if app_dir:
        candidates.append(resolve_uninstaller_path(app_dir))
    if is_frozen and exe:
        candidates.append(resolve_uninstaller_path(os.path.dirname(os.path.abspath(exe))))
    elif exe:
        candidates.append(resolve_uninstaller_path(os.path.dirname(os.path.abspath(exe))))

    registered = read_registered_uninstaller(winreg_mod=winreg_mod)
    if registered:
        if os.path.basename(registered).lower() in {n.lower() for n in UNINSTALL_EXE_NAMES}:
            candidates.append(registered)
        else:
            # Bản Setup cũ từng ghi UninstallString = PCAutoCleaner.exe — tìm cạnh đó.
            candidates.append(resolve_uninstaller_path(os.path.dirname(registered)))

    for c in candidates:
        if c and os.path.isfile(c) and os.path.basename(c).lower() != MAIN_EXE_NAME.lower():
            return os.path.abspath(c)

    if not is_frozen:
        here = os.path.dirname(os.path.abspath(__file__))
        script = os.path.join(here, "uninstall_wizard.py")
        if os.path.isfile(script):
            return os.path.abspath(script)
        dist_u = os.path.join(os.path.dirname(here), "dist", "PCAutoCleaner", "uninstall.exe")
        if os.path.isfile(dist_u):
            return os.path.abspath(dist_u)
    return ""


def read_registered_uninstaller(winreg_mod=None) -> str:
    mod = winreg_mod if winreg_mod is not None else winreg
    if mod is None:
        return ""
    hives = [getattr(mod, "HKEY_CURRENT_USER", None), getattr(mod, "HKEY_LOCAL_MACHINE", None)]
    for hive in hives:
        if hive is None:
            continue
        for key_path in (UNINSTALL_REG_PATH, UNINSTALL_REG_PATH_WOW):
            try:
                with mod.OpenKey(hive, key_path, 0, getattr(mod, "KEY_READ", 0)) as k:
                    val, _ = mod.QueryValueEx(k, "UninstallString")
                exe = unquote_command_exe(str(val or ""))
                if exe:
                    return exe
            except Exception:
                continue
    return ""


def build_uninstaller_command(
    path: str,
    remove_user_data: bool = False,
    confirmed: bool = False,
    quiet: bool = False,
    python_exe: Optional[str] = None,
) -> List[str]:
    if not path:
        return []
    if path.lower().endswith(".py"):
        py = python_exe or sys.executable
        cmd = [py, path]
    else:
        cmd = [path]
    cmd.extend(uninstall_argv(remove_user_data=remove_user_data, confirmed=confirmed, quiet=quiet))
    return cmd


def launch_uninstaller_process(
    path: str,
    remove_user_data: bool = False,
    confirmed: bool = True,
    quiet: bool = False,
    popen: Optional[Callable] = None,
) -> Tuple[bool, str]:
    """Khởi chạy uninstall.exe tách process (sống sót khi app thoát)."""
    if not path or not os.path.isfile(path):
        return False, "Không tìm thấy trình gỡ cài đặt (uninstall.exe) cạnh ứng dụng."
    if os.path.basename(path).lower() == MAIN_EXE_NAME.lower():
        return False, "Đường dẫn gỡ cài đặt không hợp lệ (trỏ nhầm vào ứng dụng chính)."
    cmd = build_uninstaller_command(
        path, remove_user_data=remove_user_data, confirmed=confirmed, quiet=quiet
    )
    launcher = popen or subprocess.Popen
    kwargs: dict = {
        "close_fds": False,
        "cwd": os.path.dirname(os.path.abspath(path)) or None,
    }
    if os.name == "nt":
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        if flags:
            kwargs["creationflags"] = flags
        # Wizard cần cửa sổ — không dùng CREATE_NO_WINDOW.
    else:
        kwargs["start_new_session"] = True
    try:
        launcher(cmd, **kwargs)
        return True, "Đã khởi chạy trình gỡ cài đặt."
    except Exception as e:
        return False, f"Không khởi chạy được trình gỡ cài đặt: {e}"


# ---------------------------------------------------------------------------
# Destructive operations (injectable — unit test trên Linux)
# ---------------------------------------------------------------------------

@dataclass
class UninstallReport:
    shortcuts_removed: List[str] = field(default_factory=list)
    start_menu_folders_removed: List[str] = field(default_factory=list)
    registry_keys_removed: List[str] = field(default_factory=list)
    run_values_removed: List[str] = field(default_factory=list)
    user_data_removed: List[str] = field(default_factory=list)
    user_data_kept: List[str] = field(default_factory=list)
    install_dir: str = ""
    scheduled_dir_removal: bool = False
    skipped_unsafe_install_dir: bool = False


def _try_remove_file(path: str, remove_file: Optional[RemoveFileFn] = None) -> bool:
    fn = remove_file or os.remove
    try:
        if os.path.lexists(path) or os.path.exists(path):
            fn(path)
            return True
    except Exception:
        return False
    return False


def remove_shortcuts(
    environ: Optional[dict] = None,
    home: Optional[str] = None,
    remove_file: Optional[RemoveFileFn] = None,
    rmtree: Optional[RmtreeFn] = None,
) -> Tuple[List[str], List[str]]:
    removed: List[str] = []
    folders_removed: List[str] = []
    locations = desktop_dirs(environ=environ, home=home) + start_menu_dirs(environ=environ)
    for folder in locations:
        if not folder or not os.path.isdir(folder):
            continue
        for name in SHORTCUT_NAMES:
            p = os.path.join(folder, name)
            if os.path.exists(p) or os.path.lexists(p):
                if _try_remove_file(p, remove_file):
                    removed.append(p)
        # Xóa thư mục Programs\PCAutoCleaner nếu còn trống (hoặc chỉ còn file rác)
        base = os.path.basename(folder)
        if base in START_MENU_SUBFOLDERS and os.path.isdir(folder):
            try:
                leftover = [n for n in os.listdir(folder) if n not in (".", "..")]
            except Exception:
                leftover = ["?"]
            if not leftover:
                try:
                    (rmtree or os.rmdir)(folder)
                    folders_removed.append(folder)
                except Exception:
                    pass
    return removed, folders_removed


def remove_uninstall_registry(winreg_mod=None) -> List[str]:
    mod = winreg_mod if winreg_mod is not None else winreg
    removed: List[str] = []
    if mod is None:
        return removed
    hives = []
    for attr in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        h = getattr(mod, attr, None)
        if h is not None:
            hives.append((attr, h))
    for hive_name, hive in hives:
        for key_path in (UNINSTALL_REG_PATH, UNINSTALL_REG_PATH_WOW):
            try:
                mod.DeleteKey(hive, key_path)
                removed.append(f"{hive_name}\\{key_path}")
            except Exception:
                pass
    return removed


def remove_autostart_registry(winreg_mod=None) -> List[str]:
    mod = winreg_mod if winreg_mod is not None else winreg
    removed: List[str] = []
    if mod is None:
        return removed
    hive = getattr(mod, "HKEY_CURRENT_USER", None)
    if hive is None:
        return removed
    try:
        with mod.OpenKey(hive, RUN_REG_PATH, 0, getattr(mod, "KEY_SET_VALUE", 0)) as k:
            for name in RUN_VALUE_NAMES:
                try:
                    mod.DeleteValue(k, name)
                    removed.append(name)
                except Exception:
                    pass
    except Exception:
        pass
    return removed


def remove_user_config_dirs(
    environ: Optional[dict] = None,
    rmtree: Optional[RmtreeFn] = None,
) -> List[str]:
    removed: List[str] = []
    tree = rmtree or (lambda p: shutil.rmtree(p, ignore_errors=True))
    for d in user_config_dirs(environ=environ):
        if os.path.isdir(d):
            try:
                tree(d)
                removed.append(d)
            except Exception:
                pass
    return removed


def schedule_install_dir_removal(install_dir: str, popen: Optional[Callable] = None) -> bool:
    """Sau khi uninstaller thoát, cmd xóa thư mục cài (Windows)."""
    if not is_safe_install_dir(install_dir):
        return False
    if os.name != "nt":
        return False
    launcher = popen or subprocess.Popen
    cleanup_cmd = f'cmd.exe /c timeout /t 2 /nobreak > nul & rmdir /s /q "{install_dir}"'
    kwargs: dict = {"shell": True}
    no_win = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if no_win:
        kwargs["creationflags"] = no_win
    try:
        launcher(cleanup_cmd, **kwargs)
        return True
    except Exception:
        return False


def perform_uninstall(
    *,
    remove_user_data: bool = False,
    environ: Optional[dict] = None,
    home: Optional[str] = None,
    winreg_mod=None,
    remove_file: Optional[RemoveFileFn] = None,
    rmtree: Optional[RmtreeFn] = None,
    install_dir: Optional[str] = None,
    schedule_dir: Optional[ScheduleFn] = None,
) -> UninstallReport:
    """Thực hiện gỡ cài đặt. Không đụng %APPDATA%\\PCAutoCleaner trừ khi remove_user_data=True."""
    report = UninstallReport()
    env = environ if environ is not None else os.environ

    shortcuts, folders = remove_shortcuts(
        environ=env, home=home, remove_file=remove_file, rmtree=rmtree
    )
    report.shortcuts_removed = shortcuts
    report.start_menu_folders_removed = folders

    report.registry_keys_removed = remove_uninstall_registry(winreg_mod=winreg_mod)
    report.run_values_removed = remove_autostart_registry(winreg_mod=winreg_mod)

    config_dirs = user_config_dirs(environ=env)
    if remove_user_data:
        report.user_data_removed = remove_user_config_dirs(environ=env, rmtree=rmtree)
    else:
        # Liệt kê đường dẫn dự kiến; không xóa.
        report.user_data_kept = list(config_dirs)

    target = install_dir if install_dir is not None else get_install_dir()
    report.install_dir = target or ""
    if target and is_safe_install_dir(target):
        scheduler = schedule_dir if schedule_dir is not None else schedule_install_dir_removal
        report.scheduled_dir_removal = bool(scheduler(target))
    elif target:
        report.skipped_unsafe_install_dir = True

    return report


# ---------------------------------------------------------------------------
# Qt UI
# ---------------------------------------------------------------------------

def _dialog_qss() -> str:
    return f"""
        QDialog {{
            background-color: {_BG_DARK};
            color: {_TEXT_WHITE};
        }}
        QLabel {{
            color: {_TEXT_WHITE};
        }}
    """


class SelfUninstallConfirmDialog(QDialog):
    """Hộp thoại xác nhận trong ứng dụng: giữ / xóa dữ liệu rồi mới gọi uninstall.exe."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.remove_user_data = False
        name = APP_DISPLAY_NAME
        self.setWindowTitle(f"Xác nhận gỡ cài đặt – {name}")
        self.setModal(True)
        self.resize(520, 360)
        self.setStyleSheet(_dialog_qss())
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        icon_lbl = QLabel("🗑️")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 26))
        header.addWidget(icon_lbl)
        title_vbox = QVBoxLayout()
        t = QLabel(f"Gỡ cài đặt {APP_DISPLAY_NAME}?")
        t.setTextFormat(Qt.PlainText)
        t.setFont(QFont("Segoe UI", 13, QFont.Bold))
        t.setStyleSheet(f"color: {_TEXT_WHITE};")
        t.setWordWrap(True)
        sub = QLabel("Xác nhận trước khi xóa ứng dụng khỏi máy tính")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(f"color: {_TEXT_MUTED};")
        title_vbox.addWidget(t)
        title_vbox.addWidget(sub)
        header.addLayout(title_vbox)
        header.addStretch()
        layout.addLayout(header)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(14, 12, 14, 12)
        c_lay.setSpacing(8)
        body = QLabel(
            "Thao tác này sẽ:\n"
            "• Xóa tệp chương trình và lối tắt Desktop / Start Menu\n"
            "• Gỡ đăng ký Windows Settings → Ứng dụng\n"
            "• Tắt khởi động cùng Windows (nếu đã bật)\n\n"
            "Cấu hình và dữ liệu cá nhân trong %APPDATA%\\PCAutoCleaner "
            "được giữ lại trừ khi bạn chọn xóa bên dưới."
        )
        body.setWordWrap(True)
        body.setFont(QFont("Segoe UI", 10))
        body.setStyleSheet(f"color: {_TEXT_WHITE};")
        c_lay.addWidget(body)

        self.chk_remove_data = QCheckBox("Xóa cả cấu hình / dữ liệu cá nhân")
        self.chk_remove_data.setChecked(False)
        self.chk_remove_data.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 12px;")
        self.chk_remove_data.setToolTip(
            "Mặc định giữ %APPDATA%\\PCAutoCleaner để cài lại vẫn còn tùy chọn của bạn."
        )
        c_lay.addWidget(self.chk_remove_data)
        layout.addWidget(card)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("Hủy")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_TEXT_WHITE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 16px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #21262d; }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("Gỡ cài đặt")
        self.btn_confirm.setCursor(Qt.PointingHandCursor)
        self.btn_confirm.setFixedHeight(32)
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{
                background: {_DANGER};
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #da3633; }}
        """)
        self.btn_confirm.clicked.connect(self._accept)
        btn_layout.addWidget(self.btn_confirm)
        layout.addLayout(btn_layout)

    def _accept(self):
        self.remove_user_data = bool(self.chk_remove_data.isChecked())
        self.accept()


class UninstallerDialog(QDialog):
    def __init__(self, argv: Optional[Sequence[str]] = None):
        super().__init__()
        self._args = parse_uninstall_args([] if argv is None else argv)
        name = APP_DISPLAY_NAME
        self.setWindowTitle(f"Gỡ Cài Đặt – {name}")
        self.resize(520, 360)
        self.setStyleSheet(_dialog_qss())
        self._build_ui()
        if self._args.get("remove_user_data"):
            self.chk_remove_data.setChecked(True)
        if self._args.get("confirmed"):
            QTimer.singleShot(80, self._do_uninstall)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        icon_lbl = QLabel("🗑️")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 26))
        header.addWidget(icon_lbl)

        title_vbox = QVBoxLayout()
        t = QLabel(f"Gỡ Cài Đặt {APP_DISPLAY_NAME}")
        t.setTextFormat(Qt.PlainText)
        t.setFont(QFont("Segoe UI", 13, QFont.Bold))
        t.setStyleSheet(f"color: {_TEXT_WHITE};")
        t.setWordWrap(True)
        sub = QLabel("Xóa bỏ ứng dụng, lối tắt và đăng ký hệ thống")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(f"color: {_TEXT_MUTED};")
        title_vbox.addWidget(t)
        title_vbox.addWidget(sub)
        header.addLayout(title_vbox)
        header.addStretch()
        layout.addLayout(header)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(14, 12, 14, 12)
        c_lay.setSpacing(8)

        msg = QLabel(
            f"Bạn có chắc chắn muốn gỡ bỏ hoàn toàn {APP_DISPLAY_NAME} "
            "khỏi máy tính?\n\n"
            "Sẽ xóa tệp chương trình, lối tắt, đăng ký Windows Settings → Ứng dụng "
            "và mục khởi động cùng Windows."
        )
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.PlainText)
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet(f"color: {_TEXT_WHITE};")
        c_lay.addWidget(msg)

        self.chk_remove_data = QCheckBox("Xóa cả cấu hình / dữ liệu cá nhân")
        self.chk_remove_data.setChecked(False)
        self.chk_remove_data.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        self.chk_remove_data.setToolTip(
            "Bỏ chọn để giữ %APPDATA%\\PCAutoCleaner (cấu hình, lịch sử) khi cài lại sau này."
        )
        c_lay.addWidget(self.chk_remove_data)

        hint = QLabel("Mặc định giữ cấu hình trong %APPDATA%\\PCAutoCleaner.")
        hint.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")
        hint.setWordWrap(True)
        c_lay.addWidget(hint)

        layout.addWidget(card)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_PANEL_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: {_DANGER};
                border-radius: 3px;
            }}
        """)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Hủy Bỏ")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_TEXT_WHITE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 16px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #21262d; }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_uninstall = QPushButton("Gỡ Cài Đặt")
        self.btn_uninstall.setCursor(Qt.PointingHandCursor)
        self.btn_uninstall.setFixedHeight(32)
        self.btn_uninstall.setStyleSheet(f"""
            QPushButton {{
                background: {_DANGER};
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #da3633; }}
        """)
        self.btn_uninstall.clicked.connect(self._do_uninstall)
        btn_layout.addWidget(self.btn_uninstall)

        layout.addLayout(btn_layout)

    def _do_uninstall(self):
        self.btn_cancel.setEnabled(False)
        self.btn_uninstall.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(20)
        self.lbl_status.setText("⏳ Đang dọn dẹp biểu tượng lối tắt (Shortcuts)...")
        QApplication.processEvents()

        remove_data = bool(self.chk_remove_data.isChecked())

        def _on_schedule(path: str) -> bool:
            self.progress_bar.setValue(95)
            self.lbl_status.setText("⏳ Đang lên lịch xóa thư mục chương trình...")
            QApplication.processEvents()
            return schedule_install_dir_removal(path)

        self.progress_bar.setValue(50)
        self.lbl_status.setText("⏳ Đang xóa đăng ký Windows Registry...")
        QApplication.processEvents()

        self.progress_bar.setValue(80)
        if remove_data:
            self.lbl_status.setText("⏳ Đang xóa cấu hình / dữ liệu cá nhân...")
        else:
            self.lbl_status.setText("⏳ Đang giữ cấu hình trong %APPDATA%\\PCAutoCleaner...")
        QApplication.processEvents()

        perform_uninstall(
            remove_user_data=remove_data,
            schedule_dir=_on_schedule,
        )

        self.progress_bar.setValue(100)
        self.lbl_status.setText("✅ Đã gỡ bỏ hoàn tất!")
        QApplication.processEvents()

        QMessageBox.information(
            self,
            "Hoàn Tất",
            f"{qt_literal_ampersand(APP_DISPLAY_NAME)} đã được gỡ cài đặt thành công khỏi máy tính."
            + (
                "\n\nĐã xóa cả cấu hình cá nhân."
                if remove_data
                else "\n\nCấu hình trong %APPDATA%\\PCAutoCleaner vẫn được giữ lại."
            ),
        )
        self.accept()


def run_quiet_uninstall(argv: Optional[Sequence[str]] = None) -> UninstallReport:
    args = parse_uninstall_args(argv)
    return perform_uninstall(remove_user_data=bool(args.get("remove_user_data")))


def main():
    args = parse_uninstall_args()
    if args.get("quiet"):
        # Im lặng: vẫn cần QApplication? Không — chỉ thao tác file/registry.
        run_quiet_uninstall()
        return 0
    app = QApplication(sys.argv)
    dlg = UninstallerDialog(sys.argv[1:])
    dlg.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
