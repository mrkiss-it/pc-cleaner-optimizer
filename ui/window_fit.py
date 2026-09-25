"""Keep top-level windows inside a typical laptop work area.

1366×768 with a Windows taskbar leaves roughly 1366×720. The client size
also loses a title bar and borders, so preferred geometry stays smaller
than that usable rectangle.
"""
from PyQt5.QtWidgets import QApplication

# Client size that fits 1366×768 after a taskbar (~48px) and a title bar.
MAIN_PREFERRED_W = 1200
MAIN_PREFERRED_H = 640
MAIN_MIN_W = 960
MAIN_MIN_H = 560
FRAME_MARGIN_W = 16
FRAME_MARGIN_H = 48


def clamp_client_size(
    width,
    height,
    minimum_w,
    minimum_h,
    available_w,
    available_h,
    frame_w=FRAME_MARGIN_W,
    frame_h=FRAME_MARGIN_H,
):
    """Return (width, height, min_w, min_h) that fit in the work area."""
    max_w = max(320, int(available_w) - int(frame_w))
    max_h = max(240, int(available_h) - int(frame_h))
    min_w = min(max(0, int(minimum_w)), max_w)
    min_h = min(max(0, int(minimum_h)), max_h)
    fitted_w = max(min_w, min(int(width), max_w))
    fitted_h = max(min_h, min(int(height), max_h))
    return fitted_w, fitted_h, min_w, min_h


def screen_available_size(widget=None):
    screen = None
    app = QApplication.instance()
    if widget is not None:
        handle = widget.windowHandle()
        if handle is not None:
            screen = handle.screen()
    if screen is None and app is not None:
        screen = app.primaryScreen()
    if screen is None:
        return 1366, 720
    geo = screen.availableGeometry()
    return int(geo.width()), int(geo.height())


def apply_client_size(widget, width, height, minimum_w, minimum_h):
    """Resize a widget so its frame can sit in the current work area."""
    avail_w, avail_h = screen_available_size(widget)
    fitted_w, fitted_h, min_w, min_h = clamp_client_size(
        width, height, minimum_w, minimum_h, avail_w, avail_h
    )
    widget.setMinimumSize(min_w, min_h)
    widget.resize(fitted_w, fitted_h)
    return fitted_w, fitted_h


def apply_initial_window_geometry(window, geometry):
    """Restore saved geometry, clamped so a laptop does not open off-screen."""
    geom = geometry if isinstance(geometry, dict) else {}
    try:
        width = int(geom.get("width") or MAIN_PREFERRED_W)
    except (TypeError, ValueError):
        width = MAIN_PREFERRED_W
    try:
        height = int(geom.get("height") or MAIN_PREFERRED_H)
    except (TypeError, ValueError):
        height = MAIN_PREFERRED_H
    apply_client_size(window, width, height, MAIN_MIN_W, MAIN_MIN_H)

    try:
        x = int(geom.get("x", -1))
        y = int(geom.get("y", -1))
    except (TypeError, ValueError):
        x, y = -1, -1
    if x >= 0 and y >= 0:
        avail_w, avail_h = screen_available_size(window)
        x = min(max(0, x), max(0, avail_w - 160))
        y = min(max(0, y), max(0, avail_h - 80))
        window.move(x, y)
    if geom.get("is_maximized"):
        window.showMaximized()
