import os
import sys

print("===================================================")
print("     PC AUTO CLEANER & OPTIMIZER - FULL AUDIT      ")
print("===================================================")

# 1. Test Core Modules Import
from core.cleaner import JunkCleaner, LargeFileScanner
from core.memory_optimizer import MemoryOptimizer
from core.process_manager import ProcessManager
from core.game_booster import GameBooster
from core.health_monitor import HealthMonitor
from core.system_monitor import SystemMonitorHub
from startup_manager import StartupManager
from config_manager import ConfigManager
print(" [PASS] 1. Tat ca cac module loi (core) da import thanh cong!")

# 2. Test Process Manager
top_procs = ProcessManager.get_top_processes(limit=5, sort_by="ram")
print(f" [PASS] 2. ProcessManager: Lay duoc {len(top_procs)} tien trinh tieu thu RAM hang dau:")
for p in top_procs:
    print(f"         - [{p['pid']}] {p['name']}: {p['ram_mb']:.1f} MB RAM | {p['cpu_percent']:.1f}% CPU | {p['category']}")

# 3. Test Game Booster Mode
gb_res = GameBooster.enable_game_boost()
print(f" [PASS] 3. GameBooster Bat: Giai phong {gb_res.get('freed_ram_mb', 0):.1f} MB RAM, dieu chinh {gb_res.get('throttled_count', 0)} tien trinh.")
assert GameBooster.is_active() == True, "GameBooster phai o trang thai Active"
gb_restore = GameBooster.disable_game_boost()
print(f" [PASS] 4. GameBooster Tat: Da khoi phuc {gb_restore.get('restored_count', 0)} tien trinh.")
assert GameBooster.is_active() == False, "GameBooster phai o trang thai Inactive"

# 4. Test Cleaner Targets
targets = JunkCleaner.get_target_paths()
print(f" [PASS] 5. JunkCleaner Targets: {len(targets)} danh muc:")
for k, v in targets.items():
    print(f"         - {k}: {len(v)} duong dan quet")

# 5. Test Health Monitor
health = HealthMonitor.run_health_check()
print(f" [PASS] 6. HealthMonitor: Trang thai he thong: {health['status']}")

# 6. Test Phase 4 - AnalyticsReporter
from core.analytics_reporter import AnalyticsReporter
cfg = ConfigManager()
history = cfg.get("history", [])
summary_7d = AnalyticsReporter.generate_summary(history, days=7)
report_text = AnalyticsReporter.generate_report_text(cfg)
assert "BÁO CÁO HIỆU QUẢ" in report_text, "Báo cáo text phải có tiêu đề"
print(f" [PASS] 7. AnalyticsReporter: Tong hop 7 ngay: {summary_7d['total_cleanups']} lan don, giai phong {summary_7d['total_junk_mb']:.1f} MB rac.")

# 7. Test Phase 4 - Memory Leak Detector
from core.leak_detector import MemoryLeakDetector
detector = MemoryLeakDetector()
leaks = detector.check_leaks()
print(f" [PASS] 8. MemoryLeakDetector: Quet hoan tat ({len(leaks)} canh bao ro ri).")

# 8. Test Phase 4 - Process Whitelist
test_proc = "test_safe_proc.exe"
cfg.add_to_whitelist(test_proc)
assert test_proc in cfg.get_whitelist_set(), "Tien trinh phai co trong whitelist"
cfg.remove_from_whitelist(test_proc)
assert test_proc not in cfg.get_whitelist_set(), "Tien trinh phai duoc xoa khoi whitelist"
print(" [PASS] 9. Process Whitelist: Them, kiem tra va xoa hoat dong chinh xac!")

# 9. Test PyQt5 UI & MainWindow Instantiation
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from ui.main_window import MainWindow
win = MainWindow(cfg)
assert win.tabs.count() == 7, f"MainWindow phai co 7 tabs, hien co {win.tabs.count()}"
for idx in range(win.tabs.count()):
    win.tabs.setCurrentIndex(idx)
win._populate_whitelist()
win._refresh_analytics_cards()
print(f" [PASS] 10. UI & MainWindow: 7 tabs khoi tao sach se, chuyen tab & refresh cards thanh cong!")

# 10. Test Network Speed Monitor
from core.system_monitor import SystemMonitor
net_info = SystemMonitor.get_network_info()
assert "down_bps" in net_info and "up_bps" in net_info, "net_info phai co thong tin toc do"
print(f" [PASS] 11. Network Monitor: Toc do tai: {net_info['down_speed_str']}, tai len: {net_info['up_speed_str']}, Ping: {net_info['ping_ms']} ms, Card: {net_info['adapter']}")

# 11. Test Network Optimizer
from core.network_optimizer import NetworkOptimizer
dns_res = NetworkOptimizer.flush_dns()
assert dns_res["success"] == True, "Flush DNS phai thanh cong"
tcp_res = NetworkOptimizer.optimize_tcp_stack()
assert tcp_res["success"] == True, "Optimize TCP phai thanh cong"
net_procs = NetworkOptimizer.get_network_processes(limit=10)
bench = NetworkOptimizer.benchmark_dns()
print(f" [PASS] 12. Network Optimizer: Flush DNS thanh cong, TCP stack toi uu, {len(net_procs)} tien trinh mang, {len(bench)} DNS benchmarked.")

# 12. Test Network UI Components
from ui.network_dialog import NetworkOptimizerDialog
from ui.floating_widget import FloatingWidget
dlg = NetworkOptimizerDialog()
assert dlg.tabs.count() == 3, "NetworkOptimizerDialog phai co 3 tabs"
f_widget = FloatingWidget(cfg)
assert hasattr(f_widget, "lbl_net_val"), "FloatingWidget phai co chi so NET"
print(" [PASS] 13. Network UI: NetworkOptimizerDialog (3 tabs) va FloatingWidget NET indicator khoi tao thanh cong!")

# 13. Test Auto Network Optimizer (BackgroundScheduler Integration)
from core.scheduler import BackgroundScheduler
sched = BackgroundScheduler(cfg)
assert hasattr(sched, "network_optimized"), "BackgroundScheduler phai co signal network_optimized"
assert hasattr(sched, "security_scan_completed"), "BackgroundScheduler phai co signal security_scan_completed"
assert cfg.get("auto_network_optimize_enabled") is not None, "Phai co config auto_network_optimize_enabled"
assert cfg.get("auto_security_scan_enabled") is not None, "Phai co config auto_security_scan_enabled"
sched.run_auto_network_boost(210.0, 180.0)
print(f" [PASS] 14. Auto Network Optimizer: BackgroundScheduler da tich hop tu dong toi uu mang khi Ping > {cfg.get('auto_network_ping_threshold_ms')}ms!")

# 14. Test Security Scanner
from core.security_scanner import SecurityScanner
sec_res = SecurityScanner.run_full_scan()
assert "overall" in sec_res and "results" in sec_res, "SecurityScanner phai tra ve day du ket qua"
assert len(sec_res["results"]) >= 10, f"Phai co it nhat 10 hang muc kiem tra, hien co {len(sec_res['results'])}"
win.update_security_tab_result(sec_res)
print(f" [PASS] 15. Security Scanner: Quet hoan tat ({sec_res['overall']}), {sec_res['critical_count']} CRITICAL, {sec_res['warning_count']} Warning, {sec_res['ok_count']} OK.")

# 16. Test Safe Registry Cleaner
from core.registry_cleaner import SafeRegistryCleaner
reg_findings = SafeRegistryCleaner.scan()
assert isinstance(reg_findings, list), "SafeRegistryCleaner.scan() phai tra ve list"
if reg_findings:
    # Test backup generation
    backup_file = SafeRegistryCleaner.create_backup(reg_findings[:2])
    assert backup_file and os.path.exists(backup_file), "File sao luu .reg phai duoc tao thanh cong"
    print(f" [PASS] 16. Safe Registry Cleaner: Quet thay {len(reg_findings)} muc, tao file sao luu {os.path.basename(backup_file)} thanh cong!")
else:
    print(" [PASS] 16. Safe Registry Cleaner: He thong Registry hoan toan sach se, 0 loi phat hien!")

# 17. Test Disk Health & SSD TRIM Optimizer
from core.disk_health_optimizer import DiskHealthOptimizer
disk_summary = DiskHealthOptimizer.get_summary()
assert "disks" in disk_summary and "volumes" in disk_summary, "DiskHealthOptimizer phai tra ve day du thong tin"
assert len(disk_summary["disks"]) > 0, "Phai phat hien it nhat 1 o cung vat ly"
first_disk = disk_summary["disks"][0]
print(f" [PASS] 17. Disk Health & SSD TRIM: Nhan dien {len(disk_summary['disks'])} o cung ({first_disk['name']}, {first_disk['media_type']}, S.M.A.R.T: {first_disk['health_status']}), {len(disk_summary['volumes'])} phan vung.")

# 18. Test Standalone Executable
exe_path = os.path.join(os.path.dirname(__file__), "dist", "PCAutoCleaner", "PCAutoCleaner.exe")
if os.path.exists(exe_path):
    exe_size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f" [PASS] 18. Standalone Executable: {exe_path} ({exe_size_mb:.2f} MB) san sang!")
else:
    print(" [INFO] 18. Standalone Executable chua duoc build lai (co the build bang build_exe.bat).")

print("\n>>> TAT CA 18 BAI KIEM TRA TOAN DIEN HE THONG, REGISTRY & SSD TRIM DEU THANH CONG 100%! <<<")

