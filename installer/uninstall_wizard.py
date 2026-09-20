"""
installer/uninstall_wizard.py – Trình Gỡ Cài Đặt Chuẩn Windows (Uninstaller) cho PC Auto Cleaner & Optimizer.
Tự động dọn dẹp Shortcut, khóa Registry gỡ cài đặt và các tệp chương trình.
"""

import os
import sys
import shutil
import winreg
import subprocess

from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QMessageBox, QFrame, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor, QIcon

# Tokens
_BG_DARK     = "#0d1117"
_PANEL_BG    = "#161b22"
_CARD_BG     = "#1b212c"
_CARD_BORDER = "#30363d"
_TEXT_WHITE  = "#f0f6fc"
_TEXT_MUTED  = "#8b949e"
_ACCENT_BLUE = "#58a6ff"
_DANGER      = "#f85149"
_SUCCESS     = "#3fb950"


class UninstallerDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gỡ Cài Đặt – PC Auto Cleaner & Optimizer")
        self.resize(520, 340)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_BG_DARK};
                color: {_TEXT_WHITE};
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        header = QHBoxLayout()
        icon_lbl = QLabel("🗑️")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 26))
        header.addWidget(icon_lbl)

        title_vbox = QVBoxLayout()
        t = QLabel("Gỡ Cài Đặt PC Auto Cleaner & Optimizer")
        t.setFont(QFont("Segoe UI", 13, QFont.Bold))
        t.setStyleSheet(f"color: {_TEXT_WHITE};")
        sub = QLabel("Xóa bỏ ứng dụng, lối tắt và đăng ký hệ thống")
        sub.setFont(QFont("Segoe UI", 9))
        sub.setStyleSheet(f"color: {_TEXT_MUTED};")
        title_vbox.addWidget(t)
        title_vbox.addWidget(sub)
        header.addLayout(title_vbox)
        header.addStretch()
        layout.addLayout(header)

        # Content Card
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        c_lay = QVBoxLayout(card)
        c_lay.setSpacing(8)

        msg = QLabel("Bạn có chắc chắn muốn gỡ bỏ hoàn toàn PC Auto Cleaner & Optimizer khỏi máy tính?")
        msg.setWordWrap(True)
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet(f"color: {_TEXT_WHITE};")
        c_lay.addWidget(msg)

        self.chk_remove_data = QCheckBox("Đồng thời xóa toàn bộ tệp cấu hình và lịch sử dọn dẹp")
        self.chk_remove_data.setChecked(True)
        self.chk_remove_data.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        c_lay.addWidget(self.chk_remove_data)

        layout.addWidget(card)

        # Status & Progress (hidden initially)
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

        # Action Buttons
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

        # 1. Xóa Desktop Shortcut
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        for lnk in ["PC Auto Cleaner.lnk", "PC Auto Cleaner & Optimizer.lnk"]:
            dp = os.path.join(desktop_dir, lnk)
            if os.path.exists(dp):
                try: os.remove(dp)
                except Exception: pass

        # 2. Xóa Start Menu Shortcut
        start_menu_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs"
        )
        for lnk in ["PC Auto Cleaner.lnk", "PC Auto Cleaner & Optimizer.lnk"]:
            sp = os.path.join(start_menu_dir, lnk)
            if os.path.exists(sp):
                try: os.remove(sp)
                except Exception: pass

        self.progress_bar.setValue(50)
        self.lbl_status.setText("⏳ Đang xóa đăng ký Windows Registry...")
        QApplication.processEvents()

        # 3. Xóa Registry Uninstall Key
        reg_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PCAutoCleaner"
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_path)
        except Exception:
            pass

        # 4. Xóa Registry Autostart Run Key nếu có
        run_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_path, 0, winreg.KEY_SET_VALUE) as k:
                try: winreg.DeleteValue(k, "PCAutoCleaner")
                except Exception: pass
        except Exception:
            pass

        self.progress_bar.setValue(80)
        self.lbl_status.setText("⏳ Đang dọn dẹp thư mục chương trình...")
        QApplication.processEvents()

        # 5. Xóa AppData config nếu được chọn
        if self.chk_remove_data.isChecked():
            config_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "PCAutoCleaner")
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir, ignore_errors=True)

        self.progress_bar.setValue(100)
        self.lbl_status.setText("✅ Đã gỡ bỏ hoàn tất!")
        QApplication.processEvents()

        QMessageBox.information(
            self,
            "Hoàn Tất",
            "PC Auto Cleaner & Optimizer đã được gỡ cài đặt thành công khỏi máy tính."
        )

        # 6. Lên lịch xóa chính thư mục cài đặt sau khi process thoát
        install_dir = os.path.dirname(os.path.abspath(__file__))
        if getattr(sys, 'frozen', False):
            # Chạy cmd ngầm chờ uninstaller thoát rồi xóa thư mục cài đặt
            cleanup_cmd = f'cmd.exe /c timeout /t 2 /nobreak > nul & rmdir /s /q "{install_dir}"'
            subprocess.Popen(cleanup_cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

        self.accept()


def main():
    app = QApplication(sys.argv)
    dlg = UninstallerDialog()
    dlg.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
