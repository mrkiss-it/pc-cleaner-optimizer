"""
Hộp thoại Điều khoản sử dụng (EULA) — Fluent Dark, tiếng Việt.
Lần chạy đầu: bắt buộc đồng ý trước khi dùng app.
Sau đó: mở lại từ header / tab Tự Động / khay hệ thống (chỉ xem).

Liên kết trong điều khoản:
- Giấy phép đầy đủ → tệp LICENSE cạnh exe / bộ cài (nếu có), không thì GitHub blob.
- Xin phép thương mại → trang GitHub của chủ sở hữu bản quyền.
"""
from __future__ import annotations

import os
import sys
import webbrowser
from typing import Iterable, Optional

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QVBoxLayout, QWidget,
)

from config_manager import ConfigManager, EULA_VERSION

try:
    from app_meta import GITHUB_OWNER, GITHUB_REPO
except ImportError:
    GITHUB_OWNER = "mrkiss-it"
    GITHUB_REPO = "pc-cleaner-optimizer"

COPYRIGHT_HOLDER = "mrkiss-it"

# Custom schemes handled by the EULA viewer (not navigated inside QTextBrowser).
LICENSE_LINK_HREF = "pccleaner://full-license"
COMMERCIAL_LINK_HREF = "pccleaner://commercial"

LICENSE_GITHUB_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/blob/main/LICENSE"
)
COMMERCIAL_PERMISSION_URL = f"https://github.com/{GITHUB_OWNER}"

EULA_HTML = """
<h2 style="color:#38bdf8; margin-top:0;">Điều khoản sử dụng (EULA)</h2>
<p style="color:#94a3b8;"><b>PC Auto Cleaner &amp; System Optimizer Pro</b><br/>
Bản quyền © 2026 {holder}. Mọi quyền được bảo lưu.<br/>
Phiên bản điều khoản: {version}</p>

<h3 style="color:#e2e8f0;">1. Phần mềm độc quyền</h3>
<p>Đây là phần mềm <b>độc quyền (proprietary)</b>, không phải MIT hay mã nguồn mở.
Việc có mã nguồn trên GitHub không cấp quyền sao chép, sửa đổi, phân phối lại
hoặc dùng thương mại.</p>

<h3 style="color:#e2e8f0;">2. Bạn được phép</h3>
<ul>
<li>Sử dụng bản phát hành chính thức trên máy tính của bạn sau khi đồng ý điều khoản này.</li>
<li>Nhận cập nhật từ kênh phát hành chính thức của chủ sở hữu bản quyền.</li>
</ul>

<h3 style="color:#e2e8f0;">3. Bạn KHÔNG được phép (trừ khi có văn bản cho phép từ {holder})</h3>
<ul>
<li>Sao chép, nhân bản, xuất bản phần mềm hoặc mã nguồn.</li>
<li>Sửa đổi, dịch ngược, tách rời, hoặc tạo sản phẩm phái sinh.</li>
<li>Phân phối lại, bán, cho thuê, cấp phép lại cho bên thứ ba.</li>
<li>Sử dụng thương mại: bán lại, OEM, white-label, tích hợp vào sản phẩm/dịch vụ trả phí.</li>
</ul>

<h3 style="color:#e2e8f0;">4. Không bảo đảm</h3>
<p>Phần mềm được cung cấp <b>nguyên trạng</b>. Chủ sở hữu không chịu trách nhiệm
đối với thiệt hại phát sinh từ việc sử dụng, trong phạm vi pháp luật cho phép.</p>

<h3 style="color:#e2e8f0;">5. English (short form)</h3>
<p>All Rights Reserved. No permission to copy, modify, redistribute, or use
commercially without written permission from the copyright holder ({holder}).
The Software is provided “AS IS”, without warranty of any kind.</p>

<p style="color:#64748b;">
<a href="{license_href}" style="color:#38bdf8; text-decoration: underline;">Giấy phép đầy đủ</a>
 — tệp LICENSE trong bộ cài / kho mã nguồn.<br/>
<a href="{commercial_href}" style="color:#38bdf8; text-decoration: underline;">Xin phép thương mại</a>
 — {commercial_url}</p>
""".format(
    holder=COPYRIGHT_HOLDER,
    version=EULA_VERSION,
    license_href=LICENSE_LINK_HREF,
    commercial_href=COMMERCIAL_LINK_HREF,
    commercial_url=COMMERCIAL_PERMISSION_URL,
)

_LINK_BUTTON_STYLE = """
QPushButton {
    background-color: #0b1220;
    color: #38bdf8;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #1e293b;
    border-color: #38bdf8;
}
QPushButton:pressed {
    background-color: #0f172a;
}
"""


def iter_license_candidates() -> Iterable[str]:
    """Các vị trí LICENSE: cạnh exe đã đóng gói, _MEIPASS, rồi thư mục mã nguồn."""
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
        meipass = getattr(sys, "_MEIPASS", "") or ""
        if meipass:
            dirs.append(meipass)
    # ui/eula_dialog.py → repo root khi chạy từ mã nguồn
    dirs.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dirs.append(os.getcwd())
    if sys.argv and sys.argv[0]:
        dirs.append(os.path.dirname(os.path.abspath(sys.argv[0])))

    seen = set()
    for folder in dirs:
        if not folder:
            continue
        path = os.path.normpath(os.path.join(folder, "LICENSE"))
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        yield path


def resolve_license_path() -> Optional[str]:
    """Đường dẫn tệp LICENSE local nếu có; None khi cần mở GitHub."""
    for path in iter_license_candidates():
        if os.path.isfile(path):
            return path
    return None


def open_external_target(path_or_url: str) -> bool:
    """Mở tệp local hoặc URL trong ứng dụng mặc định của hệ thống."""
    target = (path_or_url or "").strip()
    if not target:
        return False
    if os.path.isfile(target):
        url = QUrl.fromLocalFile(os.path.abspath(target))
    else:
        url = QUrl(target)
    try:
        if QDesktopServices.openUrl(url):
            return True
    except Exception:
        pass
    try:
        return bool(webbrowser.open(url.toString() if isinstance(url, QUrl) else target))
    except Exception:
        return False


def open_full_license() -> bool:
    """Mở LICENSE cạnh exe/bộ cài nếu có; không thì blob GitHub trên nhánh main."""
    local = resolve_license_path()
    if local:
        return open_external_target(local)
    return open_external_target(LICENSE_GITHUB_URL)


def open_commercial_permission() -> bool:
    """Mở trang GitHub của chủ sở hữu bản quyền để xin phép thương mại."""
    return open_external_target(COMMERCIAL_PERMISSION_URL)


def _url_matches(url: QUrl, href: str) -> bool:
    raw = (url.toString() or "").rstrip("/")
    want = (href or "").rstrip("/")
    if raw == want:
        return True
    # pccleaner://full-license → host "full-license"
    host = (url.host() or "").lower()
    want_host = QUrl(href).host().lower()
    return bool(host) and host == want_host


class EulaDialog(QDialog):
    """Màn hình Điều khoản sử dụng — bắt buộc chấp nhận lần đầu, sau đó chỉ xem."""

    def __init__(
        self,
        config_manager: ConfigManager,
        parent: Optional[QWidget] = None,
        require_accept: bool = True,
    ):
        super().__init__(parent)
        self.config_manager = config_manager
        self.require_accept = bool(require_accept)
        self.setWindowTitle("Điều khoản sử dụng — PC Auto Cleaner")
        self.setModal(True)
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(640, 560)
        self.setMinimumSize(520, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f1f5f9;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel { color: #f1f5f9; background: transparent; }
            QTextBrowser {
                background-color: #0b1220;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 12px 16px;
                font-size: 13px;
            }
            QCheckBox {
                color: #e2e8f0;
                font-size: 13px;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #475569;
                background: #0f172a;
            }
            QCheckBox::indicator:checked {
                background-color: #0284c7;
                border-color: #38bdf8;
            }
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("📜 Điều khoản sử dụng &amp; Bản quyền")
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet("font-size: 18px; font-weight: 800; color: #f8fafc;")
        subtitle = QLabel(
            "Phần mềm độc quyền của <b>mrkiss-it</b> — vui lòng đọc trước khi sử dụng."
        )
        subtitle.setTextFormat(Qt.RichText)
        subtitle.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(subtitle)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setOpenLinks(False)
        browser.anchorClicked.connect(self._on_eula_link)
        browser.setHtml(EULA_HTML)
        browser.setReadOnly(True)
        self.txt_eula = browser
        root.addWidget(browser, stretch=1)

        link_row = QHBoxLayout()
        link_row.setSpacing(10)
        self.btn_full_license = QPushButton("Giấy phép đầy đủ")
        self.btn_full_license.setCursor(Qt.PointingHandCursor)
        self.btn_full_license.setToolTip(
            "Mở tệp LICENSE trong bộ cài. Nếu không có, mở bản trên GitHub."
        )
        self.btn_full_license.setStyleSheet(_LINK_BUTTON_STYLE)
        self.btn_full_license.clicked.connect(self._open_full_license)

        self.btn_commercial = QPushButton("Xin phép thương mại")
        self.btn_commercial.setCursor(Qt.PointingHandCursor)
        self.btn_commercial.setToolTip(COMMERCIAL_PERMISSION_URL)
        self.btn_commercial.setStyleSheet(_LINK_BUTTON_STYLE)
        self.btn_commercial.clicked.connect(self._open_commercial)

        link_row.addWidget(self.btn_full_license)
        link_row.addWidget(self.btn_commercial)
        link_row.addStretch()
        root.addLayout(link_row)

        self.chk_agree = QCheckBox(
            "Tôi đã đọc và đồng ý với Điều khoản sử dụng (EULA) và giấy phép độc quyền."
        )
        self.chk_agree.setCursor(Qt.PointingHandCursor)
        self.chk_agree.toggled.connect(self._sync_accept_enabled)
        if self.require_accept:
            root.addWidget(self.chk_agree)
        else:
            self.chk_agree.setVisible(False)

        buttons = QHBoxLayout()
        buttons.addStretch()

        if self.require_accept:
            self.btn_decline = QPushButton("Từ chối &amp; thoát")
            self.btn_decline.setText("Từ chối & thoát")
            self.btn_decline.setProperty("class", "btn-secondary")
            self.btn_decline.setCursor(Qt.PointingHandCursor)
            self.btn_decline.setStyleSheet(
                "background-color: #334155; color: #e2e8f0; padding: 10px 18px; "
                "border-radius: 8px; font-weight: 600; border: 1px solid #475569;"
            )
            self.btn_decline.clicked.connect(self.reject)

            self.btn_accept = QPushButton("Đồng ý và tiếp tục")
            self.btn_accept.setProperty("class", "btn-success")
            self.btn_accept.setCursor(Qt.PointingHandCursor)
            self.btn_accept.setEnabled(False)
            self.btn_accept.setStyleSheet(
                "background-color: #059669; color: #ffffff; padding: 10px 22px; "
                "border-radius: 8px; font-weight: 700; border: none;"
            )
            self.btn_accept.clicked.connect(self._on_accept)
            buttons.addWidget(self.btn_decline)
            buttons.addWidget(self.btn_accept)
        else:
            self.btn_decline = None
            self.btn_accept = None
            self.btn_close = QPushButton("Đóng")
            self.btn_close.setCursor(Qt.PointingHandCursor)
            self.btn_close.setStyleSheet(
                "background-color: #2563eb; color: #ffffff; padding: 10px 22px; "
                "border-radius: 8px; font-weight: 700; border: none;"
            )
            self.btn_close.clicked.connect(self.accept)
            buttons.addWidget(self.btn_close)

        root.addLayout(buttons)

    def _on_eula_link(self, url: QUrl) -> None:
        if _url_matches(url, LICENSE_LINK_HREF):
            self._open_full_license()
            return
        if _url_matches(url, COMMERCIAL_LINK_HREF):
            self._open_commercial()
            return
        scheme = (url.scheme() or "").lower()
        if scheme in ("http", "https", "file"):
            open_external_target(url.toString())

    def _open_full_license(self) -> None:
        open_full_license()

    def _open_commercial(self) -> None:
        open_commercial_permission()

    def _sync_accept_enabled(self, checked: bool = False) -> None:
        if self.btn_accept is not None:
            self.btn_accept.setEnabled(bool(self.chk_agree.isChecked()))

    def _on_accept(self) -> None:
        if not self.chk_agree.isChecked():
            return
        if not self.config_manager.accept_eula():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Không lưu được điều khoản",
                "Không ghi được trạng thái đồng ý vào cấu hình / AppData. "
                "Hãy kiểm tra quyền ghi rồi thử lại.",
            )
            return
        self.accept()

    def closeEvent(self, event) -> None:
        if self.require_accept and not self.config_manager.is_eula_accepted():
            event.accept()
            self.reject()
            return
        super().closeEvent(event)


def ensure_eula_accepted(config_manager: ConfigManager, parent: Optional[QWidget] = None) -> bool:
    """
    Nếu người dùng đã đồng ý phiên bản EULA hiện tại thì trả về True ngay.
    Nếu chưa: hiện hộp thoại modal; True khi đồng ý và đã lưu, False khi từ chối.
    """
    if config_manager.is_eula_accepted():
        return True
    dlg = EulaDialog(config_manager, parent=parent, require_accept=True)
    result = dlg.exec_()
    return result == QDialog.Accepted and config_manager.is_eula_accepted()
