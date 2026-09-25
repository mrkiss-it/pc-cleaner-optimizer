import sys
import os
import time
import ctypes
from PyQt5.QtCore import Qt, QSharedMemory
from PyQt5.QtWidgets import QApplication

from config_manager import ConfigManager
from ui.tray_icon import SystemTrayManager
from ui.main_window import MainWindow
from ui.floating_widget import FloatingWidget
from core.scheduler import BackgroundScheduler
from core.logger import logger

from PyQt5.QtNetwork import QLocalServer, QLocalSocket

# Set Windows Application ID for proper taskbar grouping and notification styling
try:
    myappid = "Antigravity.PCAux.AutoCleaner.Optimizer.1.0"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

def force_activate_window(widget):
    """
    Kích hoạt và đưa cửa sổ lên trên cùng trên Windows, xử lý được cả trường hợp ForegroundLockTimeout.
    """
    try:
        widget.setWindowState(widget.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        widget.show()
        widget.showNormal()
        widget.raise_()
        widget.activateWindow()

        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE = 9
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)

        foreground_hwnd = user32.GetForegroundWindow()
        if foreground_hwnd != hwnd:
            foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            if foreground_thread != current_thread:
                user32.AttachThreadInput(foreground_thread, current_thread, True)
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                user32.AttachThreadInput(foreground_thread, current_thread, False)
    except Exception:
        pass

def main():
    # Ẩn hoàn toàn cửa sổ Console (CMD) nếu khởi chạy bằng python.exe hoặc file .bat
    if "--show-console" not in sys.argv and "--debug" not in sys.argv:
        try:
            hwnd_console = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd_console:
                ctypes.windll.user32.ShowWindow(hwnd_console, 0)  # SW_HIDE = 0
        except Exception:
            pass

    logger.info("=== PC Auto Cleaner & RAM Optimizer Đang Khởi Động ===")
    from core.network_optimizer import NetworkOptimizer
    is_admin = NetworkOptimizer.is_admin()
    logger.info(f"Quyền Administrator (Admin Mode): {'BẬT (Full Elevated)' if is_admin else 'TẮT (Standard User)'}")
    logger.info(f"Process PID: {os.getpid()} | Python: {sys.executable} | Args: {sys.argv}")

    # Ensure High DPI scaling is enabled
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Crucial: Keeps running in system tray when window is closed

    # Single Instance Check & Window Wakeup using QLocalServer / QLocalSocket
    server_name = "PCAutoCleaner_SingleInstance_IPC_Server"
    client_socket = QLocalSocket()
    client_socket.connectToServer(server_name)
    if client_socket.waitForConnected(400):
        logger.info("Một phiên bản PC Auto Cleaner đã đang chạy. Đang kích hoạt hiển thị cửa sổ chính...")
        client_socket.write(b"ACTIVATE_WINDOW\n")
        client_socket.waitForBytesWritten(1000)
        client_socket.disconnectFromServer()
        sys.exit(0)

    # We are the primary instance. Clean up any stale pipe/server and listen.
    QLocalServer.removeServer(server_name)
    ipc_server = QLocalServer()
    if not ipc_server.listen(server_name):
        QLocalServer.removeServer(server_name)
        if not ipc_server.listen(server_name):
            logger.warning(f"Không thể khởi tạo IPC Server: {ipc_server.errorString()}")

    # Base directory
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.json")
    config_mgr = ConfigManager(config_path)

    # First-run EULA: must accept once before tray / scheduler / main window.
    from ui.eula_dialog import ensure_eula_accepted
    if not ensure_eula_accepted(config_mgr):
        logger.info("Người dùng từ chối Điều khoản sử dụng. Thoát ứng dụng.")
        try:
            ipc_server.close()
            QLocalServer.removeServer(server_name)
        except Exception:
            pass
        sys.exit(0)

    # Initialize Central System Monitor Hub (Single Source of Truth)
    from core.system_monitor import SystemMonitorHub
    monitor_hub = SystemMonitorHub()
    logger.info("Đã khởi tạo SystemMonitorHub điều phối dữ liệu thời gian thực.")

    # Initialize System Tray
    tray_mgr = SystemTrayManager(config_manager=config_mgr)
    tray_mgr.show()
    logger.info("Đã khởi tạo System Tray Icon.")

    # Initialize Main Window
    main_win = MainWindow(config_mgr, tray_mgr, monitor_hub=monitor_hub)
    logger.info("Đã khởi tạo Giao diện chính (MainWindow).")

    # Initialize Floating Desktop Widget
    floating_widget = FloatingWidget(config_mgr, monitor_hub=monitor_hub)
    if config_mgr.get("floating_widget_enabled", True):
        floating_widget.show()
        logger.info("Đã hiển thị Floating Desktop Widget.")

    # Initialize Background Scheduler
    scheduler = BackgroundScheduler(config_mgr)
    logger.info("Đã khởi chạy BackgroundScheduler.")

    # Connect Tray Actions
    def on_quick_clean():
        targets = config_mgr.get("targets", {})
        from core.cleaner import JunkCleaner
        from core.memory_optimizer import MemoryOptimizer
        
        clean_res = JunkCleaner.clean(
            targets,
            downloads_min_age_days=config_mgr.get("downloads_old_min_days", 30),
        )
        junk_mb = clean_res.get("total_freed_mb", 0.0)
        
        ram_mb = 0.0
        if targets.get("ram_optimize", True):
            whitelist = config_mgr.get_whitelist_set()
            ram_res = MemoryOptimizer.optimize_ram(whitelist=whitelist)
            ram_mb = ram_res.get("freed_mb", 0.0)

        config_mgr.add_history(junk_mb, ram_mb, trigger_type="quick_tray")
        main_win.refresh_history_table()
        monitor_hub.force_refresh()

        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                "PC Auto Cleaner: Đã Dọn Nhanh",
                f"Đã giải phóng {junk_mb:.1f} MB rác và {ram_mb:.1f} MB RAM!",
                level="success",
                icon="🗑️",
                action_text="📊 Xem Nhật Ký",
                action_callback=lambda: (force_activate_window(main_win), main_win.tabs.setCurrentIndex(1))
            )

    def on_optimize_ram():
        from core.memory_optimizer import MemoryOptimizer
        whitelist = config_mgr.get_whitelist_set()
        ram_res = MemoryOptimizer.optimize_ram(whitelist=whitelist)
        freed = ram_res.get("freed_mb", 0.0)
        p_after = ram_res.get("percent_after", 0.0)

        config_mgr.add_history(0.0, freed, trigger_type="quick_tray")
        main_win.refresh_history_table()
        monitor_hub.force_refresh()

        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                "PC Auto Cleaner: Tối Ưu RAM",
                f"Đã giải phóng {freed:.1f} MB RAM. Mức sử dụng hiện tại: {p_after:.1f}%",
                level="success",
                icon="⚡",
                action_text="📈 Xem Tiến Trình",
                action_callback=lambda: (force_activate_window(main_win), main_win.tabs.setCurrentIndex(0))
            )

    def on_toggle_window():
        if main_win.isVisible() and not main_win.isMinimized():
            main_win.hide()
        else:
            force_activate_window(main_win)

    def on_exit_app():
        try:
            ipc_server.close()
            QLocalServer.removeServer(server_name)
        except Exception:
            pass
        app.quit()

    def on_optimize_network():
        from core.network_optimizer import NetworkOptimizer
        res = NetworkOptimizer.full_optimize()
        main_win.lbl_status.setText("🌐 Đã tối ưu hóa mạng: Làm mới DNS & TCP stack")
        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                "Tối Ưu Hóa Mạng Thành Công",
                "Đã xóa sạch bộ nhớ đệm DNS và tối ưu TCP stack!",
                level="success",
                icon="🌐",
                action_text="📶 Thử Nghiệm Mạng",
                action_callback=main_win.open_network_dialog
            )

    tray_mgr.quick_clean_requested.connect(on_quick_clean)
    tray_mgr.optimize_ram_requested.connect(on_optimize_ram)
    tray_mgr.network_optimize_requested.connect(on_optimize_network)
    tray_mgr.game_boost_requested.connect(main_win.toggle_game_boost)
    tray_mgr.exam_focus_requested.connect(main_win.toggle_exam_focus)
    tray_mgr.toggle_window_requested.connect(on_toggle_window)
    tray_mgr.toggle_floating_widget_requested.connect(floating_widget.toggle_widget)
    tray_mgr.check_updates_requested.connect(
        lambda: main_win.check_for_updates(force=True, interactive=True)
    )
    tray_mgr.show_eula_requested.connect(main_win.open_eula_dialog)
    tray_mgr.exit_requested.connect(on_exit_app)

    # Connect Floating Widget Actions
    floating_widget.open_dashboard_requested.connect(on_toggle_window)
    floating_widget.open_network_requested.connect(main_win.open_network_dialog)
    main_win.floating_widget_toggled.connect(lambda enabled: floating_widget.show() if enabled else floating_widget.hide())
    main_win.floating_widget_opacity_changed.connect(lambda _: floating_widget.update_opacity())

    def on_widget_boost_done(freed_mb):
        main_win.refresh_history_table()
        main_win.lbl_status.setText(f"🚀 Widget nổi vừa tối ưu RAM: Thu hồi {freed_mb:.1f} MB")
        monitor_hub.force_refresh()

    floating_widget.boost_completed.connect(on_widget_boost_done)

    # Connect Scheduler Background Notifications
    def on_scheduled_clean_done(info):
        main_win.refresh_history_table()
        monitor_hub.force_refresh()
        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                "Tự Động Dọn Dẹp Định Kỳ",
                f"Hệ thống đã tự động giải phóng {info['junk_freed_mb']:.1f} MB rác và {info['ram_freed_mb']:.1f} MB RAM.",
                level="success",
                icon="🗑️",
                action_text="📊 Xem Nhật Ký",
                action_callback=lambda: (force_activate_window(main_win), main_win.tabs.setCurrentIndex(1))
            )

    def on_ram_threshold_boost_done(info):
        main_win.refresh_history_table()
        monitor_hub.force_refresh()
        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                "⚡ Tự Động Thu Hồi RAM Quá Tải",
                f"Phát hiện RAM cao. Đã tự động thu hồi {info['freed_mb']:.1f} MB RAM để máy chạy mượt hơn.",
                level="warning",
                icon="⚡",
                action_text="📈 Bảng Điều Khiển",
                action_callback=lambda: (force_activate_window(main_win), main_win.tabs.setCurrentIndex(0))
            )

    def on_auto_network_optimized(info):
        kind = info.get("type", "ping_threshold")
        msg = info.get("message", "Đã tự động tối ưu mạng")
        if kind == "wifi_stability_monitor":
            status = info.get("status") if isinstance(info.get("status"), dict) else {}
            if hasattr(main_win, "apply_wifi_stability_status"):
                main_win.apply_wifi_stability_status(status)
            if not info.get("notify"):
                return
        main_win.lbl_status.setText(f"🌐 {msg}")
        if hasattr(main_win, "_ai_advisor"):
            try:
                main_win._ai_advisor.invalidate_cache()
            except Exception:
                pass
        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            open_stability = lambda: main_win.open_network_dialog(focus_wifi_stability=True)
            if kind == "wifi_stability_monitor":
                recovered = bool(info.get("recovered") or info.get("success"))
                title = "Ổn định Wi-Fi"
                level = "success" if recovered else "warning"
                action_text = "📶 Ổn định Wi-Fi"
                action_cb = open_stability
            elif kind == "wifi_stability":
                title = str(info.get("title") or "Ổn định Wi-Fi")
                level = "warning"
                needs_loc = bool(info.get("needs_location_unlock") or info.get("location_gpo_locked"))
                if needs_loc:
                    action_text = "📍 Gỡ khóa Location"
                    action_cb = main_win.unlock_location_now
                else:
                    action_text = "📶 Ổn định Wi-Fi"
                    action_cb = open_stability
                # Gate already consumed in scheduler._maybe_emit_wifi_stability_tip
            elif kind == "wifi_drop":
                recovered = info.get("recovered")
                title = "Wi-Fi đã ổn định" if recovered else "Tự sửa Wi-Fi rớt"
                level = "success" if recovered else "warning"
                needs_loc = bool(info.get("needs_location_unlock") or info.get("location_gpo_locked")) and not recovered
                needs_dns = bool(info.get("needs_dns_confirm")) and not recovered
                needs_guide = bool(info.get("needs_wifi_stability_guidance")) and not recovered
                if needs_loc:
                    action_text = "📍 Gỡ khóa Location"
                    action_cb = main_win.unlock_location_now
                elif needs_dns:
                    action_text = "🌐 Đổi DNS Siêu Tốc"
                    action_cb = main_win.apply_fast_dns
                elif needs_guide:
                    action_text = "📶 Ổn định Wi-Fi"
                    action_cb = open_stability
                    try:
                        scheduler.recovery_toast_gate.allow_stability_tip_from_config(
                            time.time(), config_mgr.config,
                        )
                    except Exception:
                        pass
                else:
                    action_text = "📶 Xem Mạng"
                    action_cb = main_win.open_network_dialog
            elif kind == "ping_missing":
                recovered = info.get("recovered")
                title = "Ping đã đo được lại" if recovered else "Tự kiểm tra & sửa mạng"
                level = "success" if recovered else "warning"
                needs_loc = bool(info.get("needs_location_unlock") or info.get("location_gpo_locked")) and not recovered
                needs_dns = bool(info.get("needs_dns_confirm")) and not recovered
                if needs_loc:
                    action_text = "📍 Gỡ khóa Location"
                    action_cb = main_win.unlock_location_now
                elif needs_dns:
                    action_text = "🌐 Đổi DNS Siêu Tốc"
                    action_cb = main_win.apply_fast_dns
                else:
                    action_text = "📶 Xem Mạng"
                    action_cb = main_win.open_network_dialog
            else:
                title = "Tự Động Tối Ưu Mạng"
                level = "info"
                action_text = "📶 Xem Mạng"
                action_cb = main_win.open_network_dialog
            if kind in ("wifi_drop", "ping_missing"):
                try:
                    if not scheduler.recovery_toast_gate.allow_from_config(
                        info,
                        now_ts=time.time(),
                        config=config_mgr.config,
                    ):
                        return
                except Exception:
                    pass
            tray_mgr.notify(
                title,
                msg,
                level=level,
                icon="🌐",
                action_text=action_text,
                action_callback=action_cb
            )

    scheduler.clean_completed.connect(on_scheduled_clean_done)
    scheduler.ram_optimized.connect(on_ram_threshold_boost_done)
    scheduler.network_optimized.connect(on_auto_network_optimized)

    def on_auto_dns_switched(info):
        msg = info.get("message", "Đã tự động chuyển sang DNS tốt nhất.")
        main_win.lbl_status.setText(f"🌐 {msg}")
        if hasattr(main_win, "lbl_dns_status"):
            if info.get("success"):
                main_win.lbl_dns_status.setText(f"✅ {msg}")
                main_win.lbl_dns_status.setStyleSheet("color: #34d399; font-size: 11px;")
            else:
                main_win.lbl_dns_status.setText(f"⚠️ {msg}")
                main_win.lbl_dns_status.setStyleSheet("color: #f87171; font-size: 11px;")
        if (config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True)) and info.get("success"):
            tray_mgr.notify(
                "🌐 Đã Tự Động Chuyển DNS Tốt Nhất",
                msg,
                level="success",
                icon="🌐"
            )

    scheduler.dns_switched.connect(on_auto_dns_switched)

    def on_auto_security_scan_done(info):
        overall = info.get("overall", "SAFE")
        critical_count = info.get("critical_count", 0)
        warning_count  = info.get("warning_count", 0)
        msg = info.get("message", "Quét bảo mật hoàn tất.")
        main_win.lbl_status.setText(f"🔒 {msg}")
        # Cập nhật tab bảo mật nếu có kết quả đầy đủ
        if info.get("results") and hasattr(main_win, "update_security_tab_result"):
            main_win.update_security_tab_result(info)
        # Chỉ thông báo khi phát hiện vấn đề
        if (config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True)) and (critical_count > 0 or warning_count > 0):
            icon_map = {"CRITICAL": "🔴", "WARNING": "🟡", "SAFE": "🟢"}
            tray_mgr.notify(
                f"{icon_map.get(overall, '🔒')} Cảnh Báo Bảo Mật",
                msg,
                level="danger" if critical_count > 0 else "warning",
                icon="🛡️",
                action_text="🛡️ Xem Rà Soát",
                action_callback=lambda: (force_activate_window(main_win), main_win.tabs.setCurrentIndex(4))
            )

    scheduler.security_scan_completed.connect(on_auto_security_scan_done)

    def on_thermal_snapshot(info):
        if not isinstance(info, dict):
            return
        if hasattr(main_win, "thermal_card"):
            try:
                main_win.thermal_card.set_warn_celsius(
                    float(config_mgr.get("thermal_warn_celsius", 90))
                )
                main_win.thermal_card.apply_snapshot(info)
            except Exception:
                pass

    def on_thermal_warning(info):
        msg = str(info.get("message") or "Laptop đang nóng.")
        title = str(info.get("title") or "Laptop đang nóng")
        try:
            main_win.lbl_status.setText(f"🌡️ {msg}")
        except Exception:
            pass
        if hasattr(main_win, "thermal_card") and isinstance(info.get("snapshot"), dict):
            try:
                main_win.thermal_card.apply_snapshot(info["snapshot"])
            except Exception:
                pass
        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                title,
                msg,
                level="warning",
                icon="🌡️",
                action_text="🔋 Xem nhiệt",
                action_callback=lambda: (
                    force_activate_window(main_win),
                    main_win.open_hardware_dialog(),
                ),
                duration_ms=6500,
            )

    scheduler.thermal_snapshot_ready.connect(on_thermal_snapshot)
    scheduler.thermal_warning.connect(on_thermal_warning)

    def on_low_disk_warning(info):
        if not isinstance(info, dict):
            return
        title = str(info.get("title") or "Ổ C: sắp đầy")
        msg = str(info.get("message") or "Ổ C: sắp hết dung lượng.")
        try:
            main_win.lbl_status.setText(f"💾 {title}")
        except Exception:
            pass
        try:
            from core.system_monitor import SystemMonitor
            disk = SystemMonitor.get_disk_info("C:\\")
            main_win._refresh_low_disk_banner(disk)
        except Exception:
            pass
        if config_mgr.get("show_notifications", True) or config_mgr.get("instant_screen_notifications_enabled", True):
            tray_mgr.notify(
                title,
                msg,
                level="warning",
                icon="💾",
                action_text="Dọn ổ C (không cần Admin)",
                action_callback=lambda: (
                    force_activate_window(main_win),
                    main_win.start_deep_c_clean(),
                ),
                duration_ms=7000,
            )

    scheduler.low_disk_warning.connect(on_low_disk_warning)

    def on_companion_tip(info):
        if not isinstance(info, dict):
            return
        if not config_mgr.get("companion_enabled", True):
            return
        if not config_mgr.get("companion_nudges_enabled", True):
            return
        if not (
            config_mgr.get("show_notifications", True)
            or config_mgr.get("instant_screen_notifications_enabled", True)
        ):
            return
        title = str(info.get("title") or "AI đồng hành")
        message = str(info.get("message") or "").strip()
        if not message:
            return
        # Soft info nudges may offer Đừng nhắc. Thermal warnings and Wi-Fi
        # emergency toasts (warning/danger) never take this button.
        action_text = None
        action_callback = None
        try:
            from core.companion import companion_nudge_snooze_button
            from core.companion_profile import snooze_tip_family
            button = companion_nudge_snooze_button(info)
            if button:
                action_text = button["label_vi"]
                family = button["topic"]

                def _snooze(topic=family):
                    snooze_tip_family(topic, level="info", critical=False)

                action_callback = _snooze
        except Exception:
            action_text = None
            action_callback = None
        tray_mgr.notify(
            title,
            message,
            level=str(info.get("level") or "info"),
            icon="🌱",
            action_text=action_text,
            action_callback=action_callback,
            duration_ms=6500,
        )

    scheduler.companion_tip.connect(on_companion_tip)

    # Kiểm tra GitHub Releases (trễ vài giây, không chặn khởi động)
    try:
        main_win.start_update_checker(delay_ms=4500)
    except Exception:
        pass

    # Kết nối cảnh báo rò rỉ bộ nhớ (Phase 4)
    scheduler.leak_detected.connect(main_win.show_leak_alert)


    # IPC Connection Handler to bring main window to front when another instance tries to launch
    def on_ipc_connection():
        sock = ipc_server.nextPendingConnection()
        if sock:
            sock.waitForReadyRead(400)
            sock.disconnectFromServer()
            force_activate_window(main_win)
            if tray_mgr:
                tray_mgr.notify("PC Auto Cleaner", "Đã mở lại Bảng Điều Khiển!")

    ipc_server.newConnection.connect(on_ipc_connection)

    # Check startup arguments (if started minimized or by Windows boot)
    start_minimized = "--minimized" in sys.argv or "-m" in sys.argv
    if not start_minimized:
        force_activate_window(main_win)
    else:
        if config_mgr.get("show_notifications", True):
            tray_mgr.notify("PC Auto Cleaner", "Ứng dụng đã khởi động chạy ngầm trong khay hệ thống.")

    exit_code = app.exec_()
    try:
        ipc_server.close()
        QLocalServer.removeServer(server_name)
    except Exception:
        pass
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
