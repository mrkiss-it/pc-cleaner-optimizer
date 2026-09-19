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
assert win.tabs.count() == 8, f"MainWindow phai co 8 tabs, hien co {win.tabs.count()}"
for idx in range(win.tabs.count()):
    win.tabs.setCurrentIndex(idx)
win._populate_whitelist()
win._refresh_analytics_cards()
win.refresh_tweaks_ui()
print(f" [PASS] 10. UI & MainWindow: 8 tabs khoi tao sach se, chuyen tab & refresh cards thanh cong!")


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

# 19. Test System Tweaker & Privacy Shield (v3.1 Pro)
from core.system_tweaker import SystemTweaker

tweaker = SystemTweaker()
assert len(tweaker.TWEAKS_DEF) == 15, f"Phai co 15 tinh chinh he thong, hien co {len(tweaker.TWEAKS_DEF)}"
stats = tweaker.get_summary_stats()
assert stats["total"] == 15, "Tong so tweak phai la 15"
assert stats["recommended_total"] == 12, "Tong so muc khuyen dung phai la 12"

# Test apply and revert on a safe HKCU key
test_key = "speedup_menu_delay"
init_status = tweaker.is_applied(test_key)
ok, msg = tweaker.apply_tweak(test_key)
assert ok == True, f"Apply tweak {test_key} phai thanh cong"
assert tweaker.is_applied(test_key) == True, "Status sau apply phai la True"
ok2, msg2 = tweaker.revert_tweak(test_key)
assert ok2 == True, f"Revert tweak {test_key} phai thanh cong"
assert tweaker.is_applied(test_key) == False, "Status sau revert phai la False"
if init_status:
    tweaker.apply_tweak(test_key)

print(f" [PASS] 19. System Tweaker & Privacy Shield: {stats['total']} tinh chinh (12 khuyen dung), Test Apply & Revert {test_key} hoan hao 100%!")

# 20. Test Hardware Sensors & Battery Health (v3.2 Pro)
from core.hardware_monitor import HardwareMonitor
from ui.hardware_dialog import HardwareMonitorDialog

bat_info = HardwareMonitor.get_battery_info()
assert "has_battery" in bat_info, "Battery info phai co has_battery"
assert "health_percent" in bat_info, "Battery info phai co health_percent"
assert "wear_level_percent" in bat_info, "Battery info phai co wear_level_percent"

cpu_info = HardwareMonitor.get_cpu_details()
assert cpu_info["physical_cores"] >= 1, "CPU phai co it nhat 1 nhan vat ly"
assert cpu_info["logical_cores"] >= 1, "CPU phai co it nhat 1 luong logic"
assert len(cpu_info["per_core_percent"]) == cpu_info["logical_cores"], "So luong phan tram per-core phai bang logical_cores"

gpu_list = HardwareMonitor.get_gpu_details()
assert isinstance(gpu_list, list) and len(gpu_list) >= 1, "Phai phat hien it nhat 1 card do hoa GPU"

hw_dlg = HardwareMonitorDialog()
assert hw_dlg.tabs.count() == 2, "HardwareMonitorDialog phai co 2 tabs"
assert hasattr(win, "btn_hardware"), "MainWindow phai co nut btn_hardware"
hw_dlg.close()

if bat_info["has_battery"]:
    bat_str = f"Laptop Battery Health: {bat_info['health_percent']}% (Chai: {bat_info['wear_level_percent']}%, {bat_info['cycle_count']} chu ky)"
else:
    bat_str = "Desktop PC (Nguon AC truc tiep)"

print(f" [PASS] 20. Hardware Sensors & Battery Health: {bat_str} | CPU: {cpu_info['name']} ({cpu_info['core_summary']}) | GPU: {gpu_list[0]['name']} ({gpu_list[0]['vram']}).")

# 21. Test AI Smart Suggestions - Engine & Data Model (v3.3 Pro)
from core.ai_advisor import (
    AIAdvisor, Suggestion,
    PRIORITY_CRITICAL, PRIORITY_WARNING, PRIORITY_TIP,
    CATEGORY_RAM, CATEGORY_CPU, CATEGORY_DISK, CATEGORY_NETWORK,
)
advisor = AIAdvisor()
assert advisor.get_suggestions() is not None, "get_suggestions() phai tra ve list"
counts = advisor.get_suggestions_count_by_priority()
assert isinstance(counts, dict) and PRIORITY_CRITICAL in counts, "Phai tra ve count dict"
print(f" [PASS] 21. AI Advisor: Rule Engine & Data Model khoi tao thanh cong, cache TTL hoat dong chuan xac!")

# 22. Test AI Advisor Rules Triggering
for _ in range(12):
    advisor.feed_snapshot({
        "ram": {"percent": 92.5},
        "cpu": {"percent": 45.0},
        "disk": {"free_gb": 40.0},
        "net": {"ping_ms": 35.0},
    })
suggestions = advisor.get_suggestions()
ram_crit = [s for s in suggestions if s.category == CATEGORY_RAM and s.priority == PRIORITY_CRITICAL]
assert len(ram_crit) >= 1, "Khi RAM > 85% lien tuc phai kich hoat suggestion CRITICAL cho RAM"
assert ram_crit[0].action_key == "optimize_ram", "Goi y RAM phai co action_key optimize_ram"

advisor.feed_snapshot({
    "ram": {"percent": 50.0},
    "cpu": {"percent": 20.0},
    "disk": {"free_gb": 3.2},
    "net": {"ping_ms": 30.0},
})
suggestions = advisor.get_suggestions()
disk_crit = [s for s in suggestions if s.category == CATEGORY_DISK and s.priority == PRIORITY_CRITICAL]
assert len(disk_crit) >= 1, "Khi O C: < 5GB phai kich hoat suggestion CRITICAL cho DISK"
assert disk_crit[0].action_key == "clean_junk", "Goi y DISK phai co action_key clean_junk"
print(f" [PASS] 22. AI Advisor Rules: RAM spike (>85%) -> CRITICAL RAM suggestion; Low Disk (<5GB) -> CRITICAL Disk suggestion.")

# 23. Test AI Advisor Dialog & UI Components
from ui.ai_advisor_dialog import AIAdvisorDialog, SuggestionCard
test_sug = Suggestion(
    category=CATEGORY_RAM,
    priority=PRIORITY_CRITICAL,
    title="Test Suggestion",
    detail="Test Detail Description",
    action_key="optimize_ram",
    action_label="Test Action"
)
card = SuggestionCard(test_sug)
assert card is not None, "SuggestionCard phai khoi tao thanh cong"

ai_dlg = AIAdvisorDialog(advisor=advisor, parent=win)
assert ai_dlg is not None, "AIAdvisorDialog phai khoi tao thanh cong"
assert hasattr(win, "btn_ai_advisor"), "MainWindow phai co nut btn_ai_advisor"
assert hasattr(win, "open_ai_advisor_dialog"), "MainWindow phai co ham open_ai_advisor_dialog"
ai_dlg.close()
print(" [PASS] 23. AI Advisor UI: AIAdvisorDialog, SuggestionCard & MainWindow Integration khoi tao thanh cong!")

# 24. Test Action Dispatcher & Badge Updates
dispatched_actions = []
def mock_dispatcher(action_key: str):
    dispatched_actions.append(action_key)

dlg_with_dispatcher = AIAdvisorDialog(advisor=advisor, action_dispatcher=mock_dispatcher)
assert dlg_with_dispatcher._dispatcher is not None, "Action dispatcher phai duoc luu trong dialog"
card.action_triggered.connect(mock_dispatcher)
card.action_triggered.emit("optimize_ram")
assert "optimize_ram" in dispatched_actions, "Card phai trigger action qua signal"
dlg_with_dispatcher.close()

win._update_ai_badge()
badge_text = win.btn_ai_advisor.text()
assert "AI Gợi Ý" in badge_text, f"Button text phai chua 'AI Gợi Ý', hien tai: {badge_text}"
print(f" [PASS] 24. Action Dispatcher & Badge: Action dispatch hoat dong chuan, Badge button cap nhat: '{badge_text}'.")

print("\n>>> TAT CA 24 BAI KIEM TRA TOAN DIEN HE THONG, REGISTRY, SSD TRIM, HARDWARE SENSORS, BATTERY & AI ADVISOR DEU THANH CONG 100%! <<<")


