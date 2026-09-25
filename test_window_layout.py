"""
Layout fit: main window stays inside a 1366×768 laptop work area.

No horizontal scrollbar on the primary tabs. Vertical scroll inside panels
is allowed. Runnable on Linux CI with QT_QPA_PLATFORM=offscreen.
"""
import os
import sys
import tempfile
import types

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "winreg" not in sys.modules:
        winreg = types.ModuleType("winreg")
        winreg.HKEY_CURRENT_USER = 1
        winreg.HKEY_LOCAL_MACHINE = 2
        winreg.HKEY_CLASSES_ROOT = 3
        winreg.KEY_READ = 0
        winreg.KEY_WRITE = 0
        winreg.KEY_SET_VALUE = 0
        winreg.KEY_ALL_ACCESS = 0
        winreg.REG_DWORD = 4
        winreg.REG_SZ = 1
        winreg.REG_EXPAND_SZ = 2
        winreg.KEY_WOW64_64KEY = 0x0100

        def _missing(*_a, **_k):
            raise FileNotFoundError("winreg stub")

        winreg.OpenKey = _missing
        winreg.OpenKeyEx = _missing
        winreg.CreateKey = _missing
        winreg.CreateKeyEx = _missing
        winreg.ConnectRegistry = _missing
        winreg.CloseKey = lambda *_a, **_k: None
        winreg.QueryValueEx = _missing
        winreg.SetValueEx = _missing
        winreg.DeleteValue = _missing
        winreg.DeleteKey = _missing
        winreg.EnumKey = _missing
        winreg.EnumValue = _missing
        winreg.QueryInfoKey = lambda *_a, **_k: (0, 0, 0)
        winreg.error = OSError
        sys.modules["winreg"] = winreg
    import ctypes
    if not hasattr(ctypes, "windll"):
        class _P:
            def __getattr__(self, _n):
                return _P()

            def __call__(self, *_a, **_k):
                return 0

        ctypes.windll = _P()

from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QPushButton,
    QScrollArea,
    QWidget,
)

from app_meta import APP_VERSION
from config_manager import DEFAULT_CONFIG, ConfigManager
from ui.c_drive_preview_dialog import CDrivePreviewDialog
from ui.companion_card import CompanionDialog
from ui.flow_layout import FlowLayout
from ui.main_window import MainWindow
from ui.window_fit import (
    MAIN_MIN_H,
    MAIN_MIN_W,
    MAIN_PREFERRED_H,
    MAIN_PREFERRED_W,
    clamp_client_size,
)


def test_clamp_fits_1366_laptop():
    # availableGeometry on 1366×768 is the screen minus the taskbar.
    width, height, min_w, min_h = clamp_client_size(
        MAIN_PREFERRED_W, MAIN_PREFERRED_H, MAIN_MIN_W, MAIN_MIN_H, 1366, 720
    )
    assert width == 1200, width
    assert height == 640, height
    assert min_w == 960 and min_h == 560
    assert width <= 1366 - 16
    assert height <= 720 - 48

    huge_w, huge_h, _, _ = clamp_client_size(1920, 1080, 960, 560, 1366, 720)
    assert huge_w <= 1366 - 16
    assert huge_h <= 720 - 48

    # A smaller panel must not be given a minimum larger than the work area.
    small_w, small_h, small_min_w, small_min_h = clamp_client_size(
        1200, 640, 960, 560, 800, 600
    )
    assert small_min_w <= 800 - 16
    assert small_min_h <= 600 - 48
    assert small_w <= 800 - 16 and small_h <= 600 - 48


def test_default_geometry_matches_preferred_size():
    geom = DEFAULT_CONFIG["window_geometry"]
    assert geom["width"] == MAIN_PREFERRED_W
    assert geom["height"] == MAIN_PREFERRED_H
    assert APP_VERSION == "3.8.7"


def test_flow_layout_wraps_without_overflow():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    flow = FlowLayout(host, h_spacing=8, v_spacing=8, expand=False)
    for label in ("Một", "Hai", "Ba", "Bốn nút dài hơn"):
        flow.addWidget(QPushButton(label))
    host.resize(160, 400)
    app.processEvents()
    flow.setGeometry(host.rect())
    buttons = host.findChildren(QPushButton)
    assert len(buttons) == 4
    rows = {button.geometry().y() for button in buttons}
    assert len(rows) >= 2, rows
    for button in buttons:
        assert button.geometry().right() <= host.width() + 1


def _horizontal_overflow(page):
    problems = []
    if page.minimumSizeHint().width() > page.width() + 4:
        problems.append(f"page min {page.minimumSizeHint().width()} > {page.width()}")
    for area in page.findChildren(QAbstractScrollArea):
        if not area.isVisible():
            continue
        bar = area.horizontalScrollBar()
        if bar.maximum() > 0:
            kind = "scroll" if isinstance(area, QScrollArea) else type(area).__name__
            problems.append(f"{kind} hmax={bar.maximum()}")
    return problems


def test_main_tabs_have_no_horizontal_scroll():
    app = QApplication.instance() or QApplication([])
    cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
    win = MainWindow(cfg)
    assert win.minimumSizeHint().width() <= 1366
    assert win.minimumSizeHint().height() <= 768
    assert win.minimumWidth() <= MAIN_MIN_W
    assert not win.tabs.tabBar().isVisible()
    win.show()
    try:
        for width, height in ((1366, 700), (1200, 640), (960, 600)):
            win.resize(width, height)
            app.processEvents()
            strip = win.tab_strip
            labels = " ".join(button.text() for button in strip._buttons)
            assert "Bảng Điều Khiển" in labels
            assert "Game Boost" in labels
            assert strip.width() <= win.width()
            for button in strip._buttons:
                geom = button.geometry()
                assert geom.right() <= strip.width() + 1, button.text()
                assert geom.bottom() <= strip.height() + 1, button.text()
            for index in range(win.tabs.count()):
                win.tabs.setCurrentIndex(index)
                app.processEvents()
                problems = _horizontal_overflow(win.tabs.widget(index))
                assert not problems, (width, index, win.tabs.tabText(index), problems)
    finally:
        win.close()


def test_preview_and_companion_fit_without_horizontal_scroll():
    app = QApplication.instance() or QApplication([])
    preview = {
        "total_label_vi": "1.2 GB",
        "total_files": 8,
        "downloads_min_age_days": 30,
        "targets": [
            {
                "key": "browser_cache",
                "name": "Cache trình duyệt và WebView2 của hồ sơ người dùng này",
                "group_vi": "Cache ứng dụng",
                "reclaimable_bytes": 1_200_000_000,
                "reclaimable_files": 400,
                "status": "ok",
            },
            {
                "key": "downloads_old",
                "name": "Tệp cũ trong Downloads",
                "group_vi": "Tệp người dùng",
                "reclaimable_bytes": 50_000_000,
                "reclaimable_files": 12,
                "status": "ok",
                "min_age_days": 30,
            },
        ],
    }
    dialog = CDrivePreviewDialog(preview, min_clean_mb=10)
    dialog.resize(700, 560)
    dialog.show()
    app.processEvents()
    assert dialog.minimumWidth() <= 1366
    assert dialog.minimumHeight() <= 720
    for area in dialog.findChildren(QScrollArea):
        assert area.horizontalScrollBar().maximum() == 0
    dialog.close()

    cfg = ConfigManager(os.path.join(tempfile.mkdtemp(), "config.json"))
    companion = CompanionDialog(cfg)
    companion.show()
    app.processEvents()
    assert companion.minimumWidth() <= 1366
    assert companion.minimumHeight() <= 720
    areas = companion.findChildren(QScrollArea)
    assert areas, "AI đồng hành dialog should scroll vertically"
    for area in areas:
        assert area.horizontalScrollBar().maximum() == 0
    companion.close()


if __name__ == "__main__":
    test_clamp_fits_1366_laptop()
    test_default_geometry_matches_preferred_size()
    test_flow_layout_wraps_without_overflow()
    test_main_tabs_have_no_horizontal_scroll()
    test_preview_and_companion_fit_without_horizontal_scroll()
    print(" [PASS] window layout fits a 1366×768 laptop without horizontal scroll")
