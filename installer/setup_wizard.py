"""
installer/setup_wizard.py – Trình Cài Đặt Thông Minh (Smart Setup Wizard) cho PC Auto Cleaner & Optimizer.
Giao diện Fluent Dark 4-bước:
- Bước 0: Chào Mừng (Welcome & Overview).
- Bước 1: Tùy Chọn Cài Đặt (Thư mục đích, Desktop Shortcut, Start Menu, Khởi động cùng Windows).
- Bước 2: Tiến Trình Giải Nén & Cài Đặt (Trích xuất bundle, tạo Shortcut, đăng ký Windows Uninstall).
- Bước 3: Hoàn Tất (Khởi chạy ứng dụng ngay).

Phiên bản hiển thị luôn lấy từ APP_VERSION trong app_meta (cùng nguồn với ứng dụng).
"""

import os
import sys
import shutil
import zipfile
import winreg
import subprocess
import json

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QLineEdit, QFileDialog, QStackedWidget,
    QWidget, QFrame, QProgressBar, QMessageBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QIcon, QPixmap

# Tokens
_BG_DARK     = "#0d1117"
_PANEL_BG    = "#161b22"
_CARD_BG     = "#1b212c"
_CARD_BORDER = "#30363d"
_TEXT_WHITE  = "#f0f6fc"
_TEXT_MUTED  = "#8b949e"
_ACCENT_BLUE = "#58a6ff"
_SUCCESS     = "#3fb950"
_WARNING     = "#d29922"
_DANGER      = "#f85149"

def _ensure_app_meta_import_path():
    """Đặt repo root / PyInstaller _MEIPASS lên sys.path để import app_meta."""
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
from app_meta import APP_NAME, APP_VERSION, APP_PUBLISHER


def qt_literal_ampersand(text: str) -> str:
    """Escape '&' so QCheckBox/QPushButton show a literal ampersand, not a mnemonic underline."""
    return (text or "").replace("&", "&&")


# ---------------------------------------------------------------------------
# Helper Utilities
# ---------------------------------------------------------------------------

def get_default_install_dir() -> str:
    """Trả về thư mục cài đặt tiêu chuẩn (User-level, không cần quyền Admin/UAC)."""
    local_app_data = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.join(local_app_data, "Programs", "PCAutoCleaner")


def create_windows_shortcut(target_exe: str, lnk_path: str, working_dir: str, icon_path: str, description: str = ""):
    """Tạo biểu tượng lối tắt Windows (.lnk) bằng WScript.Shell hoặc PowerShell."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)
        shortcut.TargetPath = target_exe
        shortcut.WorkingDirectory = working_dir
        shortcut.IconLocation = f"{icon_path},0" if icon_path and os.path.exists(icon_path) else f"{target_exe},0"
        shortcut.Description = description
        shortcut.Save()
        return True
    except Exception:
        # Fallback qua PowerShell nếu win32com gặp lỗi
        ps_cmd = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{lnk_path}"); '
            f'$s.TargetPath = "{target_exe}"; '
            f'$s.WorkingDirectory = "{working_dir}"; '
            f'$s.IconLocation = "{icon_path},0"; '
            f'$s.Description = "{description}"; '
            f'$s.Save()'
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, shell=True)
            return True
        except Exception:
            return False


def register_windows_uninstaller(install_dir: str, version: str, publisher: str, display_name: str, uninstaller_path: str, icon_path: str):
    """Đăng ký thông tin vào Windows Registry để hiển thị chuẩn trong Settings > Apps > Installed apps."""
    reg_key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PCAutoCleaner"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_key_path) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, display_name)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, publisher)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, icon_path or os.path.join(install_dir, "PCAutoCleaner.exe"))
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_path}"')
            winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ, f'"{uninstaller_path}"')
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            # Ước tính dung lượng KB
            total_kb = 150000
            try:
                total_b = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(install_dir) for f in fs)
                total_kb = total_b // 1024
            except Exception:
                pass
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, total_kb)
        return True
    except Exception as e:
        print(f"Lỗi đăng ký Registry Uninstaller: {e}")
        return False


def set_autostart_registry(exe_path: str, enable: bool = True):
    """Bật/tắt tự động khởi động cùng Windows qua HKCU Run."""
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as k:
            if enable:
                winreg.SetValueEx(k, "PCAutoCleaner", 0, winreg.REG_SZ, f'"{exe_path}" --minimized')
            else:
                try: winreg.DeleteValue(k, "PCAutoCleaner")
                except Exception: pass
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Background Installation Worker Thread
# ---------------------------------------------------------------------------

class InstallWorker(QThread):
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, target_dir: str, create_desktop: bool, create_start_menu: bool, autostart: bool):
        super().__init__()
        self.target_dir = target_dir
        self.create_desktop = create_desktop
        self.create_start_menu = create_start_menu
        self.autostart = autostart

    def run(self):
        try:
            self.progress_signal.emit(5, "Chuẩn bị thư mục cài đặt...")
            os.makedirs(self.target_dir, exist_ok=True)

            # Sao lưu cấu hình người dùng trước khi giải nén đè
            old_config = {}
            appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "PCAutoCleaner")
            appdata_cfg = os.path.join(appdata_dir, "config.json")
            target_cfg = os.path.join(self.target_dir, "config.json")

            def _merge_dict(target, src):
                for k, v in src.items():
                    if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                        _merge_dict(target[k], v)
                    else:
                        target[k] = v
                return target

            for cfg_path in [target_cfg, appdata_cfg]:
                if os.path.exists(cfg_path):
                    try:
                        with open(cfg_path, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                            if isinstance(loaded, dict):
                                _merge_dict(old_config, loaded)
                    except Exception:
                        pass

            # Tìm file bundle.zip (đóng gói kèm theo installer hoặc lấy từ thư mục gốc)
            bundle_path = None
            if getattr(sys, 'frozen', False):
                base_p = sys._MEIPASS
                candidate = os.path.join(base_p, "app_bundle.zip")
                if os.path.exists(candidate):
                    bundle_path = candidate
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                c1 = os.path.join(base_dir, "installer", "app_bundle.zip")
                if os.path.exists(c1):
                    bundle_path = c1

            if bundle_path and os.path.exists(bundle_path):
                self.progress_signal.emit(15, "Đang giải nén các tệp chương trình...")
                with zipfile.ZipFile(bundle_path, 'r') as zf:
                    members = zf.infolist()
                    total_members = len(members)
                    for i, m in enumerate(members):
                        zf.extract(m, self.target_dir)
                        pct = 15 + int((i / total_members) * 60)
                        if i % 10 == 0:
                            self.progress_signal.emit(pct, f"Đang sao chép: {m.filename}...")
            else:
                # Nếu chạy từ source code chưa nén bundle, sao chép trực tiếp từ dist/PCAutoCleaner
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                src_dist = os.path.join(base_dir, "dist", "PCAutoCleaner")
                if os.path.exists(src_dist):
                    self.progress_signal.emit(25, "Đang sao chép tệp chương trình từ dist/...")
                    shutil.copytree(src_dist, self.target_dir, dirs_exist_ok=True)
                else:
                    self.finished_signal.emit(False, f"Không tìm thấy gói cài đặt tại {src_dist}!")
                    return

            # Nếu có cấu hình cũ, thực hiện deep-merge và lưu lại cả target_dir lẫn AppData
            if old_config:
                self.progress_signal.emit(78, "Đang bảo lưu và đồng bộ cài đặt trước đó...")
                new_template = {}
                if os.path.exists(target_cfg):
                    try:
                        with open(target_cfg, "r", encoding="utf-8") as f:
                            new_template = json.load(f)
                    except Exception:
                        pass
                final_merged = _merge_dict(new_template, old_config)
                try:
                    with open(target_cfg, "w", encoding="utf-8") as f:
                        json.dump(final_merged, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass
                try:
                    os.makedirs(appdata_dir, exist_ok=True)
                    with open(appdata_cfg, "w", encoding="utf-8") as f:
                        json.dump(final_merged, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass

            self.progress_signal.emit(80, "Đang tạo biểu tượng lối tắt (Shortcuts)...")
            exe_path = os.path.join(self.target_dir, "PCAutoCleaner.exe")
            ico_path = os.path.join(self.target_dir, "assets", "icon.ico")
            if not os.path.exists(ico_path):
                ico_path = os.path.join(self.target_dir, "assets", "app_icon.ico")
            if not os.path.exists(ico_path):
                ico_path = exe_path

            # Desktop Shortcut
            if self.create_desktop:
                desk_dir = os.path.join(os.path.expanduser("~"), "Desktop")
                lnk = os.path.join(desk_dir, "PC Auto Cleaner.lnk")
                create_windows_shortcut(exe_path, lnk, self.target_dir, ico_path, APP_NAME)

            # Start Menu Shortcut
            if self.create_start_menu:
                sm_dir = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")
                lnk = os.path.join(sm_dir, "PC Auto Cleaner.lnk")
                create_windows_shortcut(exe_path, lnk, self.target_dir, ico_path, APP_NAME)

            # Autostart
            if self.autostart:
                set_autostart_registry(exe_path, enable=True)

            self.progress_signal.emit(90, "Đang đăng ký vào Windows Settings & Control Panel...")
            # Kiểm tra uninstaller
            uninstaller_path = os.path.join(self.target_dir, "uninstall.exe")
            if not os.path.exists(uninstaller_path):
                # Sao chép uninstall_wizard.py nếu có
                uninstaller_path = exe_path

            register_windows_uninstaller(
                install_dir=self.target_dir,
                version=APP_VERSION,
                publisher=APP_PUBLISHER,
                display_name=APP_NAME,
                uninstaller_path=uninstaller_path,
                icon_path=ico_path,
            )

            self.progress_signal.emit(100, "Cài đặt hoàn tất thành công!")
            self.finished_signal.emit(True, "Cài đặt thành công!")
        except Exception as e:
            self.finished_signal.emit(False, f"Lỗi trong quá trình cài đặt: {str(e)}")


# ---------------------------------------------------------------------------
# Setup Wizard Dialog
# ---------------------------------------------------------------------------

class SetupWizard(QDialog):
    """
    Giao diện Trình Cài Đặt Fluent Dark 4-bước cho PC Auto Cleaner & Optimizer.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Cài Đặt – {APP_NAME} v{APP_VERSION}")
        self.resize(680, 480)
        self.setFixedSize(680, 480)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_BG_DARK};
                color: {_TEXT_WHITE};
            }}
        """)

        self.current_step = 0
        self.installed_exe_path = ""
        self._worker = None

        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header Banner
        self.header_frame = QFrame()
        self.header_frame.setFixedHeight(75)
        self.header_frame.setStyleSheet(f"""
            QFrame {{
                background: {_PANEL_BG};
                border-bottom: 1px solid {_CARD_BORDER};
            }}
        """)
        h_lay = QHBoxLayout(self.header_frame)
        h_lay.setContentsMargins(24, 10, 24, 10)

        self.lbl_header_icon = QLabel("🚀")
        self.lbl_header_icon.setFont(QFont("Segoe UI Emoji", 26))
        h_lay.addWidget(self.lbl_header_icon)

        h_vbox = QVBoxLayout()
        h_vbox.setSpacing(2)
        self.lbl_header_title = QLabel(f"Cài Đặt {APP_NAME}")
        self.lbl_header_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.lbl_header_title.setStyleSheet(f"color: {_TEXT_WHITE};")

        self.lbl_header_sub = QLabel(f"Phiên bản v{APP_VERSION} – Giải pháp tối ưu máy tính toàn diện")
        self.lbl_header_sub.setFont(QFont("Segoe UI", 9))
        self.lbl_header_sub.setStyleSheet(f"color: {_TEXT_MUTED};")
        h_vbox.addWidget(self.lbl_header_title)
        h_vbox.addWidget(self.lbl_header_sub)
        h_lay.addLayout(h_vbox)
        h_lay.addStretch()

        root_layout.addWidget(self.header_frame)

        # Central Stacked Pages
        self.pages = QStackedWidget()
        self.page_welcome = self._build_page_welcome()
        self.page_options = self._build_page_options()
        self.page_progress = self._build_page_progress()
        self.page_finish = self._build_page_finish()

        self.pages.addWidget(self.page_welcome)
        self.pages.addWidget(self.page_options)
        self.pages.addWidget(self.page_progress)
        self.pages.addWidget(self.page_finish)

        root_layout.addWidget(self.pages, stretch=1)

        # Bottom Controls Bar
        self.footer_frame = QFrame()
        self.footer_frame.setFixedHeight(60)
        self.footer_frame.setStyleSheet(f"""
            QFrame {{
                background: {_PANEL_BG};
                border-top: 1px solid {_CARD_BORDER};
            }}
        """)
        f_lay = QHBoxLayout(self.footer_frame)
        f_lay.setContentsMargins(24, 12, 24, 12)

        self.btn_cancel = QPushButton("Hủy Bỏ")
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background: {_CARD_BG};
                color: {_TEXT_MUTED};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 16px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #21262d; color: {_TEXT_WHITE}; }}
        """)
        self.btn_cancel.clicked.connect(self.reject)
        f_lay.addWidget(self.btn_cancel)

        f_lay.addStretch()

        self.btn_back = QPushButton("← Quay Lại")
        self.btn_back.setFixedHeight(32)
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setStyleSheet(f"""
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
        self.btn_back.clicked.connect(self._go_back)
        self.btn_back.setVisible(False)
        f_lay.addWidget(self.btn_back)

        self.btn_next = QPushButton("Tiếp Tục →")
        self.btn_next.setFixedHeight(32)
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #388bfd);
                color: #ffffff;
                font-weight: bold;
                font-size: 11px;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
            }}
            QPushButton:hover {{ background: #388bfd; }}
            QPushButton:disabled {{ background: #21262d; color: {_TEXT_MUTED}; }}
        """)
        self.btn_next.clicked.connect(self._go_next)
        f_lay.addWidget(self.btn_next)

        root_layout.addWidget(self.footer_frame)

    # ------------------------------------------------------------------
    # Step 0: Welcome Page
    # ------------------------------------------------------------------

    def _build_page_welcome(self) -> QWidget:
        p = QWidget()
        layout = QVBoxLayout(p)
        layout.setContentsMargins(32, 24, 32, 20)
        layout.setSpacing(14)

        lbl_greet = QLabel(f"Chào mừng bạn đến với trình cài đặt {APP_NAME}!")
        lbl_greet.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl_greet.setStyleSheet(f"color: {_TEXT_WHITE};")
        layout.addWidget(lbl_greet)

        # Overview Card
        card = QFrame()
        card.setObjectName("summaryCard")
        card.setStyleSheet(f"""
            QFrame#summaryCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(16, 12, 16, 12)
        c_lay.setSpacing(8)

        bullets = [
            "⚡ Thu hồi RAM & Chế độ Tăng Tốc Gaming (Game Boost)",
            "🗑️ Dọn dẹp rác hệ thống, bộ đệm trình duyệt & Crash Dumps",
            "🌐 Tối ưu hóa ngăn xếp mạng TCP/IP & Benchmark DNS siêu tốc",
            "🛡️ Tinh chỉnh bảo mật riêng tư (Privacy Shield) & Rà soát an ninh",
            "🔋 Quản lý độ chai Pin Laptop & Cảm biến phần cứng CPU/GPU",
            "🤖 AI Smart Advisor – Phân tích và đưa ra khuyến nghị thông minh",
            "📦 Gỡ cài đặt ứng dụng tận gốc, xóa Bloatware & Dọn kho WinSxS",
        ]
        for b in bullets:
            lb = QLabel(b)
            lb.setFont(QFont("Segoe UI", 9))
            lb.setStyleSheet(f"color: {_TEXT_WHITE}; line-height: 1.4;")
            c_lay.addWidget(lb)

        layout.addWidget(card)

        self.chk_agree = QCheckBox("Tôi đồng ý với các điều khoản sử dụng và giấy phép phần mềm mở")
        self.chk_agree.setChecked(True)
        self.chk_agree.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        self.chk_agree.stateChanged.connect(lambda s: self.btn_next.setEnabled(s == Qt.Checked))
        layout.addWidget(self.chk_agree)

        layout.addStretch()
        return p

    # ------------------------------------------------------------------
    # Step 1: Options Page
    # ------------------------------------------------------------------

    def _build_page_options(self) -> QWidget:
        p = QWidget()
        layout = QVBoxLayout(p)
        layout.setContentsMargins(32, 20, 32, 20)
        layout.setSpacing(14)

        lbl_choose = QLabel("Chọn vị trí và tùy chọn cài đặt trên máy tính:")
        lbl_choose.setFont(QFont("Segoe UI", 11, QFont.Bold))
        lbl_choose.setStyleSheet(f"color: {_TEXT_WHITE};")
        layout.addWidget(lbl_choose)

        # Directory Selector Card
        dir_card = QFrame()
        dir_card.setObjectName("dirCard")
        dir_card.setStyleSheet(f"""
            QFrame#dirCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        d_lay = QVBoxLayout(dir_card)
        d_lay.setContentsMargins(14, 12, 14, 12)
        d_lay.setSpacing(8)

        lbl_dt = QLabel("Thư mục cài đặt (Mặc định cho tài khoản người dùng, không cần Admin):")
        lbl_dt.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        d_lay.addWidget(lbl_dt)

        dir_h = QHBoxLayout()
        self.txt_install_dir = QLineEdit(get_default_install_dir())
        self.txt_install_dir.setFixedHeight(30)
        self.txt_install_dir.setStyleSheet(f"""
            QLineEdit {{
                background: #090d13;
                color: {_TEXT_WHITE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 10px;
                font-size: 11px;
            }}
        """)
        dir_h.addWidget(self.txt_install_dir, stretch=1)

        btn_browse = QPushButton("Duyệt...")
        btn_browse.setFixedHeight(30)
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background: #21262d;
                color: {_TEXT_WHITE};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 0 14px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background: #30363d; }}
        """)
        btn_browse.clicked.connect(self._on_browse_dir)
        dir_h.addWidget(btn_browse)
        d_lay.addLayout(dir_h)

        self.lbl_preserve_badge = QLabel("🛡️ Đã phát hiện cấu hình cũ: Toàn bộ tùy chọn, lịch trình và danh sách Whitelist sẽ được tự động bảo lưu.")
        self.lbl_preserve_badge.setWordWrap(True)
        self.lbl_preserve_badge.setStyleSheet(f"""
            QLabel {{
                background: #161b22;
                color: #58a6ff;
                border: 1px solid #1f6feb;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 11px;
                font-weight: 500;
            }}
        """)
        d_lay.addWidget(self.lbl_preserve_badge)
        self.txt_install_dir.textChanged.connect(self._check_preserve_badge)
        self._check_preserve_badge()

        layout.addWidget(dir_card)

        # Shortcuts Options Card
        sc_card = QFrame()
        sc_card.setObjectName("scCard")
        sc_card.setStyleSheet(f"""
            QFrame#scCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        s_lay = QVBoxLayout(sc_card)
        s_lay.setContentsMargins(14, 12, 14, 12)
        s_lay.setSpacing(10)

        lbl_st = QLabel("Tùy chọn lối tắt & Tự động chạy:")
        lbl_st.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        s_lay.addWidget(lbl_st)

        self.chk_desktop_shortcut = QCheckBox("📌 Tạo biểu tượng lối tắt ngoài màn hình Desktop")
        self.chk_desktop_shortcut.setChecked(True)
        self.chk_desktop_shortcut.setStyleSheet(f"color: {_TEXT_WHITE}; font-size: 11px;")
        s_lay.addWidget(self.chk_desktop_shortcut)

        self.chk_start_menu = QCheckBox("📂 Thêm vào danh mục Start Menu của Windows")
        self.chk_start_menu.setChecked(True)
        self.chk_start_menu.setStyleSheet(f"color: {_TEXT_WHITE}; font-size: 11px;")
        s_lay.addWidget(self.chk_start_menu)

        self.chk_autostart = QCheckBox("⚡ Tự động khởi động cùng Windows (Thu nhỏ xuống Khay hệ thống)")
        self.chk_autostart.setChecked(False)
        self.chk_autostart.setStyleSheet(f"color: {_TEXT_WHITE}; font-size: 11px;")
        s_lay.addWidget(self.chk_autostart)

        layout.addWidget(sc_card)
        layout.addStretch()
        return p

    def _check_preserve_badge(self):
        target = self.txt_install_dir.text().strip()
        target_cfg = os.path.join(target, "config.json")
        appdata_cfg = os.path.join(os.environ.get("APPDATA", ""), "PCAutoCleaner", "config.json")
        if os.path.exists(target_cfg) or os.path.exists(appdata_cfg):
            self.lbl_preserve_badge.setVisible(True)
        else:
            self.lbl_preserve_badge.setVisible(False)

    def _on_browse_dir(self):
        curr = self.txt_install_dir.text().strip()
        chosen = QFileDialog.getExistingDirectory(self, "Chọn Thư Mục Cài Đặt", curr)
        if chosen:
            self.txt_install_dir.setText(os.path.join(chosen, "PCAutoCleaner"))

    # ------------------------------------------------------------------
    # Step 2: Progress Page
    # ------------------------------------------------------------------

    def _build_page_progress(self) -> QWidget:
        p = QWidget()
        layout = QVBoxLayout(p)
        layout.setContentsMargins(32, 30, 32, 20)
        layout.setSpacing(16)

        self.lbl_installing_title = QLabel(f"Đang tiến hành cài đặt {APP_NAME}...")
        self.lbl_installing_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.lbl_installing_title.setStyleSheet(f"color: {_TEXT_WHITE};")
        layout.addWidget(self.lbl_installing_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_PANEL_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1f6feb, stop:1 #388bfd);
                border-radius: 5px;
            }}
        """)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_progress_status = QLabel("Đang khởi tạo gói cài đặt...")
        self.lbl_progress_status.setFont(QFont("Segoe UI", 9))
        self.lbl_progress_status.setStyleSheet(f"color: {_TEXT_MUTED};")
        layout.addWidget(self.lbl_progress_status)

        layout.addStretch()
        return p

    # ------------------------------------------------------------------
    # Step 3: Finish Page
    # ------------------------------------------------------------------

    def _build_page_finish(self) -> QWidget:
        p = QWidget()
        layout = QVBoxLayout(p)
        layout.setContentsMargins(32, 24, 32, 20)
        layout.setSpacing(16)

        top_h = QHBoxLayout()
        ic = QLabel("✅")
        ic.setFont(QFont("Segoe UI Emoji", 32))
        top_h.addWidget(ic)

        tv = QVBoxLayout()
        tv.setSpacing(4)
        t = QLabel("Cài Đặt Hoàn Tất Thành Công!")
        t.setFont(QFont("Segoe UI", 14, QFont.Bold))
        t.setStyleSheet(f"color: {_SUCCESS};")

        self.lbl_finish_sub = QLabel(f"{APP_NAME} v{APP_VERSION} đã sẵn sàng phục vụ bạn.")
        self.lbl_finish_sub.setFont(QFont("Segoe UI", 10))
        self.lbl_finish_sub.setStyleSheet(f"color: {_TEXT_WHITE};")
        tv.addWidget(t)
        tv.addWidget(self.lbl_finish_sub)
        top_h.addLayout(tv)
        top_h.addStretch()
        layout.addLayout(top_h)

        # Finish Card
        card = QFrame()
        card.setObjectName("finishCard")
        card.setStyleSheet(f"""
            QFrame#finishCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(16, 14, 16, 14)
        c_lay.setSpacing(8)

        msg1 = QLabel("• Ứng dụng đã được cài đặt vào thư mục đích.")
        msg2 = QLabel("• Biểu tượng lối tắt đã sẵn sàng trên màn hình Desktop và Start Menu.")
        msg3 = QLabel("• Bạn có thể gỡ cài đặt bất kỳ lúc nào từ Windows Settings > Apps.")
        for m in [msg1, msg2, msg3]:
            m.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; line-height: 1.4;")
            c_lay.addWidget(m)

        layout.addWidget(card)

        self.chk_launch_now = QCheckBox(
            f"🚀 Khởi chạy {qt_literal_ampersand(APP_NAME)} ngay bây giờ"
        )
        self.chk_launch_now.setChecked(True)
        self.chk_launch_now.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.chk_launch_now.setStyleSheet(f"color: {_ACCENT_BLUE};")
        layout.addWidget(self.chk_launch_now)

        layout.addStretch()
        return p

    # ------------------------------------------------------------------
    # Navigation Logic
    # ------------------------------------------------------------------

    def _go_next(self):
        if self.current_step == 0:
            self.current_step = 1
            self.pages.setCurrentIndex(1)
            self.btn_back.setVisible(True)
            self.btn_next.setText("Cài Đặt Ngay →")
            self.lbl_header_title.setText("Tùy Chọn Cài Đặt")
            self.lbl_header_sub.setText("Chọn thư mục và các biểu tượng lối tắt mong muốn")
        elif self.current_step == 1:
            # Bắt đầu cài đặt
            self.current_step = 2
            self.pages.setCurrentIndex(2)
            self.btn_back.setVisible(False)
            self.btn_next.setVisible(False)
            self.btn_cancel.setEnabled(False)
            self.lbl_header_title.setText("Đang Cài Đặt...")
            self.lbl_header_sub.setText("Vui lòng đợi trong giây lát khi hệ thống thiết lập tệp tin")

            target_dir = self.txt_install_dir.text().strip() or get_default_install_dir()
            self.installed_exe_path = os.path.join(target_dir, "PCAutoCleaner.exe")

            self._worker = InstallWorker(
                target_dir=target_dir,
                create_desktop=self.chk_desktop_shortcut.isChecked(),
                create_start_menu=self.chk_start_menu.isChecked(),
                autostart=self.chk_autostart.isChecked(),
            )
            self._worker.progress_signal.connect(self._on_install_progress)
            self._worker.finished_signal.connect(self._on_install_finished)
            self._worker.start()
        elif self.current_step == 3:
            # Hoàn tất
            if self.chk_launch_now.isChecked() and os.path.exists(self.installed_exe_path):
                try:
                    subprocess.Popen([self.installed_exe_path], cwd=os.path.dirname(self.installed_exe_path))
                except Exception as e:
                    print(f"Không thể khởi động ứng dụng: {e}")
            self.accept()

    def _go_back(self):
        if self.current_step == 1:
            self.current_step = 0
            self.pages.setCurrentIndex(0)
            self.btn_back.setVisible(False)
            self.btn_next.setText("Tiếp Tục →")
            self.lbl_header_title.setText(f"Cài Đặt {APP_NAME}")
            self.lbl_header_sub.setText(f"Phiên bản v{APP_VERSION} – Giải pháp tối ưu máy tính toàn diện")

    def _on_install_progress(self, percent: int, text: str):
        self.progress_bar.setValue(percent)
        self.lbl_progress_status.setText(text)

    def _on_install_finished(self, success: bool, message: str):
        if success:
            self.current_step = 3
            self.pages.setCurrentIndex(3)
            self.btn_cancel.setVisible(False)
            self.btn_next.setVisible(True)
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Hoàn Tất")
            self.lbl_header_title.setText("Cài Đặt Thành Công!")
            self.lbl_header_sub.setText(f"Cảm ơn bạn đã lựa chọn {APP_NAME}")
        else:
            QMessageBox.critical(self, "Lỗi Cài Đặt", message)
            self.reject()


def main():
    app = QApplication(sys.argv)
    wizard = SetupWizard()
    wizard.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
