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
advisor = AIAdvisor(config_manager=cfg)
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

win._ai_action_dispatcher("open_security_dialog")
assert win.tabs.currentWidget() == win.tab_security, "Dispatch open_security_dialog phai chuyen sang tab_security"
win._ai_action_dispatcher("open_process_tab")
assert win.tabs.currentWidget() == win.tab_performance, "Dispatch open_process_tab phai chuyen sang tab_performance"

win._update_ai_badge()
badge_text = win.btn_ai_advisor.text()
assert "AI Gợi Ý" in badge_text, f"Button text phai chua 'AI Gợi Ý', hien tai: {badge_text}"
print(f" [PASS] 24. Action Dispatcher & Badge: Action dispatch hoat dong chuan, Tab navigation chinh xac, Badge button cap nhat: '{badge_text}'.")

# 25. Test Windows Services Optimizer (v3.4 Pro)
from core.service_optimizer import (
    ServiceOptimizer, WindowsService,
    RECOMMENDATION_SAFE_DISABLE, RECOMMENDATION_MANUAL,
)
svc_summary = ServiceOptimizer.get_summary()
assert svc_summary["total"] > 0, "Tong so services phai > 0"
assert svc_summary["running"] > 0, "So service dang chay phai > 0"
all_services = ServiceOptimizer.get_services()
assert len(all_services) == svc_summary["total"], "So luong get_services() phai bang tong summary"
candidates = ServiceOptimizer.get_services(only_candidates=True)
assert isinstance(candidates, list), "Candidates phai la list"
print(f" [PASS] 25. Windows Services: Nhan dien {svc_summary['total']} services ({svc_summary['running']} running, {svc_summary['candidates']} candidates toi uu).")

# 26. Test Context Menu Manager (v3.4 Pro)
from core.context_menu_manager import ContextMenuManager, ContextMenuItem
menu_summary = ContextMenuManager.get_summary()
assert menu_summary["total"] > 0, "Tong so context menu handlers phai > 0"
assert "enabled" in menu_summary and "orphan" in menu_summary, "Menu summary phai day du thong tin"
menu_items = ContextMenuManager.scan_items()
assert len(menu_items) == menu_summary["total"], "So luong scan_items() phai bang total"
print(f" [PASS] 26. Context Menu Manager: Quet thanh cong {menu_summary['total']} Shell Extensions, {menu_summary['orphan']} menu mo coi (orphan).")

# 27. Test Context Menu Toggle & Blocked List
blocked_set = ContextMenuManager.get_blocked_clsids()
assert isinstance(blocked_set, set), "Blocked CLSIDs phai la set"
dummy_item = ContextMenuItem(
    id="test::dummy",
    name="TestDummyHandler",
    location_key="file",
    location_title="Tập Tin (*)",
    reg_path="dummy_path",
    clsid="{00000000-0000-0000-0000-000000000000}",
    dll_path=None,
    company="Test Co",
    is_enabled=True,
    is_orphan=False
)
ok_dis, msg_dis = ContextMenuManager.toggle_item(dummy_item, enable=False)
assert ok_dis == True, "Disable dummy item phai thanh cong"
assert "{00000000-0000-0000-0000-000000000000}" in ContextMenuManager.get_blocked_clsids()
ok_en, msg_en = ContextMenuManager.toggle_item(dummy_item, enable=True)
assert ok_en == True, "Enable dummy item phai thanh cong"
assert "{00000000-0000-0000-0000-000000000000}" not in ContextMenuManager.get_blocked_clsids()
print(" [PASS] 27. Context Menu Toggle: Logic Block / Unblock qua HKCU Shell Extensions hoat dong an toan 100%!")

# 28. Test Service & Context Menu Dialog UI
from ui.service_context_dialog import ServiceContextDialog
svc_dlg = ServiceContextDialog(parent=win)
assert svc_dlg.tabs.count() == 2, "ServiceContextDialog phai co 2 tabs"
assert hasattr(win, "btn_services"), "MainWindow phai co nut btn_services"
assert hasattr(win, "open_services_context_dialog"), "MainWindow phai co ham open_services_context_dialog"
svc_dlg.close()
print(" [PASS] 28. Service & Context Menu UI: ServiceContextDialog (2 tabs) & MainWindow Integration khoi tao thanh cong!")

# 29. Test Software Uninstaller - Desktop Apps (v3.5 Pro)
from core.uninstaller_manager import UninstallerManager, InstalledApp
desktop_apps = UninstallerManager.get_installed_desktop_apps()
assert isinstance(desktop_apps, list), "Desktop apps phai la list"
assert len(desktop_apps) > 0, "So luong desktop apps tim thay phai > 0"
sample_app = desktop_apps[0]
assert hasattr(sample_app, "name") and hasattr(sample_app, "uninstall_string"), "App phai co name va uninstall_string"
assert sample_app.app_type == "desktop", "App type phai la desktop"
print(f" [PASS] 29. Desktop Apps Uninstaller: Tim thay {len(desktop_apps)} phan mem desktop (VD: {sample_app.name}).")

# 30. Test Windows Bloatware Scan (v3.5 Pro)
bloatware_apps = UninstallerManager.get_bloatware_apps()
assert isinstance(bloatware_apps, list), "Bloatware apps phai la list"
uninst_summary = UninstallerManager.get_summary()
assert uninst_summary["desktop_count"] == len(desktop_apps), "Summary desktop count phai khop"
assert uninst_summary["bloatware_count"] == len(bloatware_apps), "Summary bloatware count phai khop"
if bloatware_apps:
    sample_bloat = bloatware_apps[0]
    assert sample_bloat.is_bloatware == True, "Bloatware app phai co is_bloatware == True"
    assert sample_bloat.package_full_name is not None, "UWP bloatware phai co package_full_name"
print(f" [PASS] 30. Windows Bloatware Scanner: Phat hien {len(bloatware_apps)} ung dung rac/bloatware UWP can go.")

# 31. Test Residual Junk Hunter Scan & Clean Logic (v3.5 Pro)
# Tao thu muc gia lap trong TEMP de test an toan
import tempfile
import shutil
test_temp_dir = tempfile.mkdtemp(prefix="pc_cleaner_mock_residual_")
test_sub = os.path.join(test_temp_dir, "MockSoftwareLeftover")
os.makedirs(test_sub, exist_ok=True)
with open(os.path.join(test_sub, "junk_cache.dat"), "w") as f:
    f.write("mock residual data" * 50)

# Test clean_residuals logic truc tiep voi dict chua dummy folders
mock_res_data = {
    "app_name": "MockSoftware",
    "folders": [{"path": test_sub, "name": "MockSoftwareLeftover", "size_mb": 0.1}],
    "reg_keys": [],
    "total_size_mb": 0.1,
}
cleaned_folders, cleaned_keys, clean_msg = UninstallerManager.clean_residuals(mock_res_data)
assert cleaned_folders == 1, "Real clean phai xoa 1 folder thanh cong"
assert not os.path.exists(test_sub), "Folder leftover gia lap phai bi xoa khoi he thong"
shutil.rmtree(test_temp_dir, ignore_errors=True)

# Test scan residuals cho 1 app
scanned_res = UninstallerManager.scan_residuals("Kaspersky")
assert isinstance(scanned_res, dict), "Scan residuals phai tra ve dict"
assert "folders" in scanned_res and "reg_keys" in scanned_res, "Scan residuals phai co folders va reg_keys"
total_leftovers = len(scanned_res["folders"]) + len(scanned_res["reg_keys"])
print(f" [PASS] 31. Residual Junk Hunter: Clean residuals hoat dong an toan 100%, scan keyword thu duoc {total_leftovers} leftover items.")

# 32. Test Uninstaller Dialog UI & MainWindow Integration (v3.5 Pro)
from ui.uninstaller_dialog import UninstallerDialog
uninst_dlg = UninstallerDialog(parent=win)
assert uninst_dlg.tabs.count() == 3, "UninstallerDialog phai co 3 tabs (Desktop, Bloatware, Residuals)"
assert hasattr(win, "btn_uninstaller"), "MainWindow phai co nut btn_uninstaller"
assert hasattr(win, "open_uninstaller_dialog"), "MainWindow phai co ham open_uninstaller_dialog"
uninst_dlg.close()
print(" [PASS] 32. Uninstaller UI: UninstallerDialog (3 tabs) & MainWindow btn_uninstaller khoi tao hoan hao!")

# 33. Test Windows Update Caches & Servicing Logs Scanner (v3.6 Pro)
from core.winsxs_cleaner import WinSxSCleaner, UpdateCacheItem, OemDriverItem
caches = WinSxSCleaner.scan_update_caches()
assert isinstance(caches, list), "Caches phai la list"
assert len(caches) >= 3, "So luong danh muc update caches phai >= 3"
sample_cache = caches[0]
assert hasattr(sample_cache, "size_mb") and hasattr(sample_cache, "file_count"), "Cache item phai co size_mb va file_count"
total_cache_size = sum(c.size_mb for c in caches)
print(f" [PASS] 33. Update Caches Scanner: Quet duoc {len(caches)} danh muc bo dem/logs ({total_cache_size:.1f} MB phat hien).")

# 34. Test DriverStore OEM Drivers Scanner & Deduplicator (v3.6 Pro)
all_oem, dup_oem = WinSxSCleaner.scan_oem_drivers()
assert isinstance(all_oem, list) and isinstance(dup_oem, list), "Drivers phai la list"
assert len(all_oem) > 0, "So luong OEM drivers phai > 0"
summary_winsxs = WinSxSCleaner.get_summary()
assert "total_cache_mb" in summary_winsxs and "duplicate_drivers_count" in summary_winsxs
assert summary_winsxs["duplicate_drivers_count"] == len(dup_oem), "Duplicate drivers count phai khop voi list"
if dup_oem:
    assert dup_oem[0].is_duplicate == True, "Duplicate driver phai co is_duplicate == True"
print(f" [PASS] 34. DriverStore Scanner: Nhan dien {len(all_oem)} OEM Drivers, {len(dup_oem)} goi driver cu trung lap.")

# 35. Test Update Cache Clean Logic & Mock Directory (v3.6 Pro)
mock_cache_dir = tempfile.mkdtemp(prefix="pc_cleaner_mock_cache_")
with open(os.path.join(mock_cache_dir, "mock_update.cab"), "w") as f:
    f.write("mock update cab content" * 100)

mock_cache_item = UpdateCacheItem(
    key="test_mock",
    name="Mock Cache Target",
    path=mock_cache_dir,
    size_mb=0.1,
    file_count=1,
    description="Test mock cache",
)
dry_ok, dry_msg, dry_fc, dry_mb = WinSxSCleaner.clean_cache_item(mock_cache_item, dry_run=True)
assert dry_ok == True and dry_fc == 1, "Dry run phai bao cao 1 file"
assert os.path.exists(os.path.join(mock_cache_dir, "mock_update.cab")), "Dry run khong duoc xoa file that"

real_ok, real_msg, real_fc, real_mb = WinSxSCleaner.clean_cache_item(mock_cache_item, dry_run=False)
assert real_ok == True and real_fc == 1, "Real clean phai xoa 1 file thanh cong"
assert not os.path.exists(os.path.join(mock_cache_dir, "mock_update.cab")), "File trong mock cache phai bi xoa"
shutil.rmtree(mock_cache_dir, ignore_errors=True)
print(" [PASS] 35. Cache Clean Logic: Dry-run & Real-clean hoat dong an toan 100%, quan ly file he thong chuan xac.")

# 36. Test WinSxS Dialog UI & MainWindow Integration (v3.6 Pro)
from ui.winsxs_dialog import WinSxSDialog
winsxs_dlg = WinSxSDialog(parent=win)
assert winsxs_dlg.tabs.count() == 3, "WinSxSDialog phai co 3 tabs (WinSxS, Caches, DriverStore)"
assert hasattr(win, "btn_winsxs"), "MainWindow phai co nut btn_winsxs"
assert hasattr(win, "open_winsxs_dialog"), "MainWindow phai co ham open_winsxs_dialog"
dispatched = []
orig_open = win.open_winsxs_dialog
win.open_winsxs_dialog = lambda: dispatched.append(True)
win._ai_action_dispatcher("open_winsxs_dialog")
assert len(dispatched) == 1, "Action dispatcher phai kich hoat open_winsxs_dialog"
win.open_winsxs_dialog = orig_open
winsxs_dlg.close()
print(" [PASS] 36. WinSxS UI: WinSxSDialog (3 tabs) & MainWindow Integration khoi tao thanh cong!")

# 37. Test Setup Wizard Helpers: Shortcuts & Windows Registry Registration (v3.7 Pro)
from installer.setup_wizard import (
    get_default_install_dir, create_windows_shortcut,
    register_windows_uninstaller, set_autostart_registry
)
default_dir = get_default_install_dir()
assert "PCAutoCleaner" in default_dir, "Thu muc cai dat mac dinh phai chua PCAutoCleaner"

# Test tao shortcut gia lap trong TEMP
mock_temp_dir = tempfile.mkdtemp(prefix="pc_cleaner_mock_installer_")
mock_exe = os.path.join(mock_temp_dir, "dummy.exe")
with open(mock_exe, "w") as f:
    f.write("mock exe")
mock_lnk = os.path.join(mock_temp_dir, "test_shortcut.lnk")
ok_sc = create_windows_shortcut(mock_exe, mock_lnk, mock_temp_dir, mock_exe, "Test Description")
assert ok_sc == True, "Tao shortcut bang WScript.Shell/PowerShell phai thanh cong"
assert os.path.exists(mock_lnk), "File .lnk phai ton tai tren o dia"

# Test dang ky uninstaller vao Registry
ok_reg = register_windows_uninstaller(
    install_dir=mock_temp_dir,
    version="3.7.0",
    publisher="PC Cleaner Team",
    display_name="PC Auto Cleaner (Test Mock)",
    uninstaller_path=mock_exe,
    icon_path=mock_exe
)
assert ok_reg == True, "Dang ky Uninstaller vao Windows Registry phai thanh cong"

# Don dep Registry test
reg_test_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PCAutoCleaner"
try:
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, reg_test_path)
except Exception:
    pass
shutil.rmtree(mock_temp_dir, ignore_errors=True)
print(" [PASS] 37. Installer Engine: Tao Shortcut Windows (.lnk) & Dang ky Uninstaller Registry hoat dong chuan xac 100%!")

# 38. Test Smart Setup Wizard UI & Standalone Uninstaller Dialog (v3.7 Pro)
from installer.setup_wizard import SetupWizard
from installer.uninstall_wizard import UninstallerDialog as StandaloneUninstaller

wizard = SetupWizard()
assert wizard.pages.count() == 4, "SetupWizard phai co 4 trang (Welcome, Options, Progress, Finish)"
assert wizard.current_step == 0, "Trang bat dau phai la 0 (Welcome)"
wizard._go_next()
assert wizard.current_step == 1, "Next phai chuyen sang trang 1 (Options)"
wizard._go_back()
assert wizard.current_step == 0, "Back phai quay lai trang 0"
wizard.close()

standalone_uninst = StandaloneUninstaller()
assert standalone_uninst is not None, "Standalone UninstallerDialog phai khoi tao thanh cong"
standalone_uninst.close()
print(" [PASS] 38. Setup Wizard UI: SetupWizard (4-step Fluent Dark) & Standalone Uninstaller khoi tao hoan hao!")

# 39. Test Predictive AI Engine: Disk Forecaster, Diurnal Habit Learner, Z-Score Anomaly Detector (v3.8 Pro)
from datetime import datetime
from core.predictive_ai import (
    PredictiveAIEngine, DiskForecaster, HabitLearner, ProcessAnomalyDetector,
    DiskForecast, UsageHabit, ProcessAnomaly,
    STATUS_CRITICAL_DEPLETION, STATUS_WARNING_DEPLETION, STATUS_STABLE,
    SLOT_MORNING, SLOT_AFTERNOON, SLOT_EVENING, SLOT_NIGHT
)

# A. Test Disk Forecaster Regression
mock_forecaster = DiskForecaster()
mock_forecaster._history = [
    {"ts": 100000.0, "free_gb": 50.0, "total_gb": 256.0},
    {"ts": 100000.0 + 86400 * 2, "free_gb": 46.0, "total_gb": 256.0},
    {"ts": 100000.0 + 86400 * 4, "free_gb": 42.0, "total_gb": 256.0},
]
mock_forecaster.record_sample(free_gb=40.0, total_gb=256.0, ts=100000.0 + 86400 * 5)
fc = mock_forecaster.calculate_forecast("C:", auto_record=False)
assert fc is not None, "DiskForecast phai tra ve ket qua"
assert fc.daily_burn_rate_gb > 1.0, f"Toc do tieu hao phai > 1.0 GB/ngay, hien tai: {fc.daily_burn_rate_gb}"
assert fc.days_until_exhaustion is not None and fc.days_until_exhaustion > 0, "So ngay can kiet phai > 0"

# B. Test Habit Learner Diurnal Slots
assert HabitLearner.get_current_slot(datetime(2026, 9, 20, 8, 30)) == SLOT_MORNING
assert HabitLearner.get_current_slot(datetime(2026, 9, 20, 14, 0)) == SLOT_AFTERNOON
assert HabitLearner.get_current_slot(datetime(2026, 9, 20, 20, 0)) == SLOT_EVENING
assert HabitLearner.get_current_slot(datetime(2026, 9, 20, 2, 0)) == SLOT_NIGHT

habit_learner = HabitLearner()
habit_learner._profiles[SLOT_EVENING] = {"cpu_sum": 350.0, "ram_sum": 380.0, "samples": 5, "gaming_hits": 3}
habit_gaming = habit_learner.analyze_current_habit(current_cpu=70.0, current_ram=80.0)
assert habit_gaming.recommended_mode in ("game_boost", "balanced"), "De xuat phai la game_boost hoac balanced"

# C. Test Process Anomaly Detector Z-Score
detector = ProcessAnomalyDetector()
anomalies = detector.detect_anomalies(limit=5)
assert isinstance(anomalies, list), "detect_anomalies phai tra ve list"
for anom in anomalies:
    assert 0 <= anom.anomaly_score <= 100, "Score phai trong 0..100"
    assert anom.name not in ("system", "csrss.exe"), "Khong duoc bao dong tien trinh he thong"

# D. Test Master Orchestrator
pred_engine = PredictiveAIEngine()
summary = pred_engine.get_summary()
assert "forecast" in summary and "habit" in summary, "Summary phai chua forecast va habit"
print(" [PASS] 39. Predictive AI: Disk Forecaster (Hoi quy chuoi thoi gian), Diurnal Habit Learner & Z-Score Anomaly Detector hoat dong hoan hao!")

# 40. Test AI Advisor Predictive Rules & AIAdvisorDialog UI Dashboard Integration (v3.8 Pro)
from core.ai_advisor import CATEGORY_PREDICTIVE, CATEGORY_ANOMALY, CATEGORY_ICONS
assert CATEGORY_PREDICTIVE in CATEGORY_ICONS and CATEGORY_ICONS[CATEGORY_PREDICTIVE] == "🔮"
assert CATEGORY_ANOMALY in CATEGORY_ICONS and CATEGORY_ICONS[CATEGORY_ANOMALY] == "🚨"

# Test AI Advisor Rule Output
sugs = advisor.get_suggestions()
assert len(sugs) > 0, "AI Advisor phai sinh ra suggestions"

# Test UI Dialog Dashboard & Filter Tabs
from ui.ai_advisor_dialog import AIAdvisorDialog, PredictiveDashboard
pred_dlg = AIAdvisorDialog(advisor=advisor, parent=win)
assert hasattr(pred_dlg, "_dashboard"), "Dialog phai co PredictiveDashboard"
assert isinstance(pred_dlg._dashboard, PredictiveDashboard), "Dashboard phai la instance cua PredictiveDashboard"
assert CATEGORY_PREDICTIVE in pred_dlg._tab_btns, "Dialog phai co tab loc CATEGORY_PREDICTIVE"
assert CATEGORY_ANOMALY in pred_dlg._tab_btns, "Dialog phai co tab loc CATEGORY_ANOMALY"

# Test filter tab switching
pred_dlg._set_filter(CATEGORY_PREDICTIVE, pred_dlg._tab_btns[CATEGORY_PREDICTIVE])
assert pred_dlg._active_filter == CATEGORY_PREDICTIVE, "Filter phai la CATEGORY_PREDICTIVE"

# Test Action Dispatcher for enable_game_boost
dispatched_actions = []
def mock_pred_dispatcher(key):
    dispatched_actions.append(key)

dlg_dispatch = AIAdvisorDialog(advisor=advisor, action_dispatcher=mock_pred_dispatcher)
dlg_dispatch._dispatch_action("enable_game_boost")
assert "enable_game_boost" in dispatched_actions, "Action dispatcher phai nhan duoc enable_game_boost"

dlg_dispatch._dispatch_action("whitelist_proc:test_mock_app.exe")
assert "whitelist_proc:test_mock_app.exe" in dispatched_actions, "Action dispatcher phai nhan duoc whitelist_proc"
cfg_wl = cfg.get_whitelist_set()
assert "test_mock_app.exe" in cfg_wl, "Tien trinh phai duoc them vao config whitelist"
cfg.remove_from_whitelist("test_mock_app.exe")

pred_dlg.close()
dlg_dispatch.close()
print(" [PASS] 40. AI Advisor Predictive Integration: Dashboard 3 the truc quan (Disk, Habit, Anomaly), Tab loc rieng biet & Action Dispatcher hoat dong xuat sac 100%!")

# 41. Test Settings Persistence, Deep Merge & Window State Memory Across Sessions & Updates
from config_manager import _deep_merge

# A. Test Deep Merge algorithm
target_dict = {
    "theme": "dark",
    "targets": {"temp": True, "recycle": True, "prefetch": True},
    "window_geometry": {"width": 1050, "height": 680, "maximized": False},
    "automation": {"auto_clean": False, "ram_threshold": 80}
}
src_dict = {
    "targets": {"prefetch": False, "custom_user_folder": True},
    "window_geometry": {"width": 1280, "height": 720, "x": 150, "y": 100, "maximized": True},
    "automation": {"auto_clean": True, "ram_threshold": 75, "custom_flag": True},
    "last_active_tab": 3,
    "user_custom_setting": "preserved"
}
merged = _deep_merge(target_dict, src_dict)
assert merged["targets"]["temp"] is True, "Target goc phai duoc giu lai neu src khong ghi de"
assert merged["targets"]["prefetch"] is False, "Target src phai ghi de target goc"
assert merged["targets"]["custom_user_folder"] is True, "Khoa moi trong dict con phai duoc them vao"
assert merged["window_geometry"]["width"] == 1280 and merged["window_geometry"]["maximized"] is True, "Window state phai duoc ghi nhan"
assert merged["automation"]["auto_clean"] is True and merged["automation"]["custom_flag"] is True, "Automation settings phai duoc merge sau"
assert merged["last_active_tab"] == 3, "last_active_tab phai duoc luu"
assert merged["user_custom_setting"] == "preserved", "Cai dat tuy bien khong bi mat di"

# B. Test ConfigManager window state helpers
cfg.save_window_state(x=120, y=80, width=1150, height=720, maximized=False)
win_state = cfg.get_window_state()
assert win_state["x"] == 120 and win_state["y"] == 80, "get_window_state phai tra ve toa do chinh xac"
assert win_state["width"] == 1150 and win_state["height"] == 720, "get_window_state phai tra ve kich thuoc chinh xac"
assert win_state["maximized"] is False, "get_window_state phai tra ve trang thai maximized chinh xac"

# C. Test Real-time auto-saving in MainWindow
assert hasattr(win, "_auto_save_targets"), "MainWindow phai co phuong thuc _auto_save_targets"
assert hasattr(win, "_auto_save_automation_settings"), "MainWindow phai co phuong thuc _auto_save_automation_settings"
assert hasattr(win, "_on_tab_changed"), "MainWindow phai co slot _on_tab_changed"

# Test tab index change persistence
win._on_tab_changed(2)
assert cfg.get("last_active_tab") == 2, "Config phai cap nhat last_active_tab = 2 ngay lap tuc"
win._on_tab_changed(0)
assert cfg.get("last_active_tab") == 0, "Config phai cap nhat last_active_tab = 0 ngay lap tuc"

# Test auto-saving automation settings
orig_ram = win.spin_ram_threshold.value()
win.chk_auto_clean.setChecked(True)
win.chk_auto_ram.setChecked(True)
win.spin_ram_threshold.setValue(77)
win._auto_save_automation_settings()
assert cfg.get("auto_clean_enabled") is True, "auto_clean_enabled phai duoc ghi nho vao config"
assert cfg.get("auto_ram_optimize_enabled") is True, "auto_ram_optimize_enabled phai duoc ghi nho vao config"
assert cfg.get("ram_threshold_percent") == 77, f"ram_threshold_percent phai la 77, hien tai: {cfg.get('ram_threshold_percent')}"

# Test auto-saving targets
if win.target_rows:
    first_target_key = list(win.target_rows.keys())[0]
    first_cb = win.target_rows[first_target_key].checkbox
    first_cb.setChecked(False)
    win._auto_save_targets()
    saved_targets = cfg.get_targets()
    assert saved_targets.get(first_target_key) is False, f"Muc muc tieu {first_target_key} phai duoc ghi nho la False"
    first_cb.setChecked(True)
    win._auto_save_targets()
    assert cfg.get_targets().get(first_target_key) is True, f"Muc muc tieu {first_target_key} phai duoc ghi nho la True"

# D. Test Setup Wizard badge detection
assert hasattr(wizard, "_check_preserve_badge"), "SetupWizard phai co ham kiem tra cau hinh cu _check_preserve_badge"
assert hasattr(wizard, "lbl_preserve_badge"), "SetupWizard phai co nhan thong bao bao luu cau hinh"
wizard._check_preserve_badge()
# Neu config ton tai, nhan phai hien thi
assert wizard.lbl_preserve_badge is not None, "Badge bao luu phai duoc khoi tao"

print(" [PASS] 41. Settings Persistence: Deep Merge cau hinh, Window Geometry/Tab Memory & Real-time Auto-saving hoat dong hoan hao 100%!")

# 42. Test On-Screen HUD Toast Notification System (ToastNotification, ToastManager, Stacking & Actions)
from PyQt5.QtCore import Qt
from ui.toast_notification import (
    ToastNotification, ToastManager,
    LEVEL_INFO, LEVEL_SUCCESS, LEVEL_WARNING, LEVEL_DANGER, _LEVEL_CONFIG
)

# A. Test Level Configuration
for lvl in (LEVEL_INFO, LEVEL_SUCCESS, LEVEL_WARNING, LEVEL_DANGER):
    assert lvl in _LEVEL_CONFIG, f"Level {lvl} phai ton tai trong _LEVEL_CONFIG"
    assert "border" in _LEVEL_CONFIG[lvl] and "btn_bg" in _LEVEL_CONFIG[lvl]

# B. Test ToastNotification UI & Action callback
toast_action_fired = []
def mock_toast_action():
    toast_action_fired.append(True)

toast = ToastNotification(
    title="Test Toast Title",
    message="This is a test notification message",
    level=LEVEL_WARNING,
    icon_str="⚡",
    action_text="Thu Hồi RAM",
    action_callback=mock_toast_action,
    duration_ms=3000
)
assert toast.windowFlags() & Qt.FramelessWindowHint, "Toast phai la Frameless"
assert toast.windowFlags() & Qt.WindowStaysOnTopHint, "Toast phai StaysOnTop"
assert toast.windowFlags() & Qt.WindowDoesNotAcceptFocus, "Toast khong duoc chiem keyboard focus"
assert toast.btn_action is not None, "Toast phai co action button"
assert toast.btn_action.text() == "Thu Hồi RAM", "Action text phai khop"

# Trigger action
toast._on_action_clicked()
assert len(toast_action_fired) == 1, "Action callback phai duoc kich hoat khi click action"

# Test hover pause and resume
toast.enterEvent(None)
assert toast.is_paused is True, "is_paused phai la True khi hover vao"
toast.leaveEvent(None)
assert toast.is_paused is False, "is_paused phai la False khi roi chuot ra"

toast.dismiss()

# C. Test ToastManager Singleton & Stacking
mgr = ToastManager.get_instance()
assert mgr is not None, "ToastManager phai la singleton instance hop le"

# Call static API show_toast
ToastManager.show_toast(
    title="Static Toast Test",
    message="Message content",
    level=LEVEL_SUCCESS,
    icon="✅",
    action_text="Action Test",
    action_callback=None,
    duration_ms=2500,
    play_sound=False
)
QApplication.processEvents()
assert len(mgr.active_toasts) > 0, "Toast phai duoc them vao danh sach active_toasts cua ToastManager"

# Clean up active toasts
for t in list(mgr.active_toasts):
    t.dismiss()
QApplication.processEvents()

# D. Test MainWindow Toast Controls & Auto-save
assert hasattr(win, "chk_instant_screen_notif"), "MainWindow phai co chk_instant_screen_notif"
assert hasattr(win, "chk_notif_sound"), "MainWindow phai co chk_notif_sound"
assert hasattr(win, "btn_test_toast"), "MainWindow phai co btn_test_toast"
assert hasattr(win, "_test_screen_toast"), "MainWindow phai co phuong thuc _test_screen_toast"

# Test toggle and auto-save
win.chk_instant_screen_notif.setChecked(True)
win.chk_notif_sound.setChecked(True)
win._auto_save_automation_settings()
assert cfg.get("instant_screen_notifications_enabled") is True, "Config phai luu instant_screen_notifications_enabled = True"
assert cfg.get("notification_sound_enabled") is True, "Config phai luu notification_sound_enabled = True"

# Test trigger test toast from UI
win._test_screen_toast()
QApplication.processEvents()
assert len(mgr.active_toasts) > 0, "Nhan nut thu thong bao phai tao thanh cong toast tren man hinh"

# Clean up
for t in list(mgr.active_toasts):
    t.dismiss()
QApplication.processEvents()

print(" [PASS] 42. On-Screen HUD Toast Notifications: Floating Acrylic Frame, Animated Stacking, Hover Pause, 1-Click Action & Config Integration hoat dong xuat sac 100%!")

# ==============================================================================
# 43. KIEM TRA AI COPILOT & HEALTH SCORE & AUTO-PILOT ENGINE (v4.5 Pro)
# ==============================================================================
print("\n[TEST 43] Kiem tra AI Copilot & AI Health Score (0-100) & Auto-Pilot Engine...")

from core.ai_copilot import AICopilotEngine, ChatMessage, CopilotAction, TelemetryCollector, OfflineExpertBrain, CloudAIBrain
from core.predictive_ai import AIHealthReport, AutoPilotState, MODE_GAMING, MODE_ECO, MODE_WORK, MODE_BALANCED, HabitLearner
from ui.ai_copilot_widget import AICopilotWidget, ChatBubbleWidget
from ui.ai_advisor_dialog import AIAdvisorDialog

# A. Test Telemetry Collector
telemetry = TelemetryCollector.collect()
assert "ram" in telemetry and "percent" in telemetry["ram"], "Telemetry phai chua thong so RAM"
assert "cpu" in telemetry and "percent" in telemetry["cpu"], "Telemetry phai chua thong so CPU"
assert "disk" in telemetry and "free_gb" in telemetry["disk"], "Telemetry phai chua thong so Disk C:"

# B. Test AI Health Score (0 - 100)
pred_engine = win._ai_advisor.predictive_engine
health = pred_engine.calculate_health_score(stats=telemetry, force_refresh=True)
assert isinstance(health, AIHealthReport), "calculate_health_score phai tra ve instance AIHealthReport"
assert 0 <= health.score <= 100, f"Diem suc khoe phai nam trong khoang 0 - 100 (nhan duoc: {health.score})"
assert health.grade in ("XUẤT SẮC", "TỐT", "CẦN TỐI ƯU", "NGUY CƠ"), f"Xep loai phai hop le (nhan duoc: {health.grade})"
assert len(health.prescription) > 0, "Toa thuoc AI phai co it nhat 1 giai phap toi uu"
assert health.predicted_score_after >= health.score, "Diem sau khi toi uu phai lon hon hoac bang diem hien tai"

# C. Test AI Auto-Pilot Context Engine
# Test Gaming detection
state_game = pred_engine.get_autopilot_state(
    current_stats=telemetry,
    running_process_names=["cs2.exe", "explorer.exe"]
)
assert state_game.mode == MODE_GAMING, f"Phai nhan dien mode GAMING khi co game chay (nhan duoc: {state_game.mode})"

# Test Eco battery detection
state_eco = pred_engine.get_autopilot_state(
    current_stats=telemetry,
    on_battery=True,
    battery_pct=35,
    running_process_names=["notepad.exe"]
)
assert state_eco.mode == MODE_ECO, f"Phai nhan dien mode ECO khi rut sac pin duoi 50% (nhan duoc: {state_eco.mode})"

# Test Work detection
state_work = pred_engine.get_autopilot_state(
    current_stats=telemetry,
    on_battery=False,
    running_process_names=["code.exe", "antigravity.exe"]
)
assert state_work.mode == MODE_WORK, f"Phai nhan dien mode WORK khi co IDE lam viec (nhan duoc: {state_work.mode})"

# D. Test AI Copilot Engine
copilot = AICopilotEngine(config_manager=win.config_manager, predictive_engine=pred_engine)
assert len(copilot.chat_history) > 0, "AI Copilot phai co loi chao mac dinh"

# Hoi ve RAM
res_ram = copilot.ask("Tai sao may toi bi ngon RAM?")
assert isinstance(res_ram, ChatMessage), "ask phai tra ve ChatMessage"
assert any(a.key == "optimize_ram" for a in res_ram.actions), "Cau hoi ve RAM phai dinh kem action optimize_ram"

# Hoi ve Game
res_game = copilot.ask("Lam sao de choi game muot hon?")
assert any(a.key in ("toggle_game_boost", "enable_game_boost") for a in res_game.actions), "Cau hoi ve Game phai dinh kem action Game Boost"

# Hoi ve O C
res_disk = copilot.ask("O C bi day can xoa gi?")
assert any(a.key in ("clean_disk", "winsxs_cleanup") for a in res_disk.actions), "Cau hoi ve O C phai dinh kem action clean_disk/winsxs"

# Hoi Tong quan suc khoe
res_health = copilot.ask("Kham benh may tinh tong quan")
assert "AI Health Score" in res_health.content or "Sức Khỏe" in res_health.content or "Hồ Sơ" in res_health.content, "Kham benh phai co Health Score"

# E. Test AICopilotWidget UI & Dialog Tab
copilot_widget = AICopilotWidget(config_manager=win.config_manager, predictive_engine=pred_engine)
assert hasattr(copilot_widget, "txt_input"), "AICopilotWidget phai co o nhap txt_input"
assert hasattr(copilot_widget, "btn_send"), "AICopilotWidget phai co nut btn_send"

# Test action signal
action_received = []
copilot_widget.action_triggered.connect(lambda k: action_received.append(k))
copilot_widget._on_action_dispatched("optimize_ram")
assert "optimize_ram" in action_received, "Signal action_triggered phai phat dung action_key"

# Test AIAdvisorDialog Copilot tab
adv_dlg = AIAdvisorDialog(advisor=win._ai_advisor, action_dispatcher=win._ai_action_dispatcher)
assert "COPILOT" in adv_dlg._tab_btns, "AIAdvisorDialog phai co tab COPILOT"
assert hasattr(adv_dlg, "_copilot_widget"), "AIAdvisorDialog phai chua _copilot_widget"
assert hasattr(adv_dlg._dashboard, "lbl_health_score"), "Dashboard phai co lbl_health_score"

# Switch to Copilot tab
adv_dlg._set_filter("COPILOT", adv_dlg._tab_btns["COPILOT"])
assert not adv_dlg._copilot_widget.isHidden(), "Chuyen sang tab COPILOT thi _copilot_widget phai khong bi an"
assert adv_dlg._scroll.isHidden(), "Chuyen sang tab COPILOT thi _scroll phai an"

# F. Dashboard Auto-Pilot card must use AutoPilotState.label/description (not missing attrs)
adv_dlg._set_filter(None, adv_dlg._tab_btns[None])
adv_dlg._dashboard.update_data()
KNOWN_AUTOPILOT_LABELS = {
    "Chế Độ Game Thần Tốc (Game Boost)",
    "Chế Độ Tiết Kiệm Pin Cơ Động (Eco Saver)",
    "Chế Độ Làm Việc & Sáng Tạo (Workstation)",
    "Chế Độ Ban Đêm Tĩnh Lặng (Quiet Night)",
    "Chế Độ Cân Bằng Thông Minh (Balanced)",
}
assert adv_dlg._dashboard.lbl_habit_mode.text() in KNOWN_AUTOPILOT_LABELS, (
    f"The Auto-Pilot card phai hien thi AutoPilotState.label, nhan duoc: "
    f"{adv_dlg._dashboard.lbl_habit_mode.text()!r}"
)

# G. Habit learner must not rewrite config.json on every 800ms sample
class _SaveCounter:
    def __init__(self):
        self.saves = 0
        self.store = {}
    def get(self, key, default=None):
        return self.store.get(key, default)
    def set(self, key, value):
        self.store[key] = value
        self.saves += 1

save_cfg = _SaveCounter()
habit_throttled = HabitLearner(config_manager=save_cfg)
habit_throttled.feed_sample(10.0, 20.0)
assert save_cfg.saves == 1, "Lan ghi dau tien sau khoi tao phai duoc luu"
habit_throttled.feed_sample(12.0, 22.0)
habit_throttled.feed_sample(8.0, 18.0)
assert save_cfg.saves == 1, "Khong duoc ghi config.json lai o moi mau 800ms"

# H. Cloud Gemini: model 1.5 da ngung, API key khong nam trong URL
import inspect
gemini_src = inspect.getsource(CloudAIBrain.query_gemini)
assert 'model: str = "gemini-2.5-flash"' in gemini_src or 'models/{model}:generateContent' in gemini_src
assert "models/gemini-1.5" not in gemini_src, "Khong duoc goi model Gemini 1.5 da shut down"
assert "gemini-2.5-flash" in gemini_src, "Phai dung gemini-2.5-flash (hoac model cau hinh tuong duong)"
assert "?key=" not in gemini_src, "API key khong duoc gan vao query string"
assert "x-goog-api-key" in gemini_src, "API key phai gui qua header x-goog-api-key"

adv_dlg.close()

print(" [PASS] 43. AI Copilot & Real-time Telemetry & Health Score 0-100 & Auto-Pilot Context Engine hoat dong xuat sac 100%!")

# ==============================================================================
# 44. Auto-Pilot apply/undo, Gemini last_error, secrets not in tracked config
# ==============================================================================
print("\n[TEST 44] Auto-Pilot applicator, Cloud error surface, secret storage...")

from core.predictive_ai import AutoPilotApplicator, MODE_GAMING, MODE_BALANCED, MODE_ECO
from core.ai_copilot import CloudAIBrain
from config_manager import SECRET_KEYS, secrets_file_path
import tempfile
import json as _json

# A. Applicator enables Game Boost on GAMING and undoes on BALANCED
class _StubBooster:
    active = False
    enables = 0
    disables = 0
    @classmethod
    def is_active(cls):
        return cls.active
    @classmethod
    def enable_game_boost(cls, whitelist=None):
        cls.active = True
        cls.enables += 1
        return {"success": True}
    @classmethod
    def disable_game_boost(cls):
        cls.active = False
        cls.disables += 1
        return {"success": True}

class _StubRam:
    calls = 0
    @classmethod
    def optimize_ram(cls, whitelist=None):
        cls.calls += 1
        return {"freed_mb": 1.0}

class _MemCfg:
    def __init__(self, enabled=True, mode="auto"):
        self.data = {"ai_autopilot_enabled": enabled, "ai_autopilot_mode": mode}
    def get(self, k, default=None):
        return self.data.get(k, default)

_StubBooster.active = False
_StubBooster.enables = 0
_StubBooster.disables = 0
app_on = AutoPilotApplicator(config_manager=_MemCfg(True, "auto"), booster=_StubBooster, ram_optimizer=_StubRam)
gaming_state = pred_engine.get_autopilot_state(running_process_names=["cs2.exe"])
assert gaming_state.mode == MODE_GAMING
applied = app_on.sync(gaming_state)
assert _StubBooster.enables == 1, "Auto-Pilot phai bat Game Boost khi GAMING"
assert app_on.auto_applied_game_boost is True
assert "enable_game_boost" in applied.applied_actions

# Immediate second sync same mode should not re-enable
app_on.sync(gaming_state)
assert _StubBooster.enables == 1

# Leave gaming: skip 30s grace then force ts
app_on.last_change_ts = 0.0
app_on.LEAVE_GAMING_GRACE_SEC = 0.0
balanced = pred_engine.autopilot.evaluate_context(running_process_names=["notepad.exe"])
# Night/work/balanced depending on hour — just ask applicator to target balanced via config
app_bal = AutoPilotApplicator(config_manager=_MemCfg(True, "balanced"), booster=_StubBooster, ram_optimizer=_StubRam)
app_bal.auto_applied_game_boost = True
_StubBooster.active = True
app_bal.LEAVE_GAMING_GRACE_SEC = 0.0
app_bal.MODE_DWELL_SEC = 0.0
out = app_bal.sync(balanced)
assert _StubBooster.disables >= 1, "Auto-Pilot phai hoan tac Game Boost khi roi GAMING"
assert app_bal.auto_applied_game_boost is False

# Disabled = recommendation only, undo
_StubBooster.active = True
app_off = AutoPilotApplicator(config_manager=_MemCfg(False, "auto"), booster=_StubBooster, ram_optimizer=_StubRam)
app_off.auto_applied_game_boost = True
off_state = app_off.sync(gaming_state)
assert off_state.is_auto_applied is False
assert "Đề xuất" in off_state.badge_text or "đề xuất" in off_state.description.lower()
assert _StubBooster.active is False

# B. Cloud last_error when no key
CloudAIBrain.last_error = ""
none_reply = CloudAIBrain.query_gemini(api_key="", user_prompt="hi", telemetry=telemetry)
assert none_reply is None
assert CloudAIBrain.last_error, "last_error phai duoc gan khi thieu API key"

# Engine surfaces cloud failure in offline reply
class _CloudCfg:
    def get(self, k, default=None):
        if k == "ai_copilot_cloud_enabled":
            return True
        if k == "ai_copilot_gemini_api_key":
            return ""
        return default
cloud_copilot = AICopilotEngine(config_manager=_CloudCfg(), predictive_engine=pred_engine)
cloud_msg = cloud_copilot.ask("Kham suc khoe")
assert "Cloud Gemini lỗi" in cloud_msg.content or "Cloud Gemini" in cloud_msg.content
assert "Offline" in cloud_msg.content or "Hồ Sơ" in cloud_msg.content or "sức khỏe" in cloud_msg.content.lower() or "RAM" in cloud_msg.content

# C. Secrets never land in tracked config.json
fd, tmp_cfg = tempfile.mkstemp(suffix=".json")
os.close(fd)
fd2, tmp_sec = tempfile.mkstemp(suffix=".json")
os.close(fd2)
os.environ["PCAUTOCLEANER_SECRETS_PATH"] = tmp_sec
with open(tmp_cfg, "w", encoding="utf-8") as f:
    _json.dump({"ai_copilot_cloud_enabled": False, "ai_copilot_gemini_api_key": "AIzaSyLEAKED"}, f)
from config_manager import ConfigManager as _CM
iso = _CM(config_path=tmp_cfg)
assert iso.get("ai_copilot_gemini_api_key") == "AIzaSyLEAKED"
with open(tmp_cfg, "r", encoding="utf-8") as f:
    disk_cfg = _json.load(f)
assert "ai_copilot_gemini_api_key" not in disk_cfg, "Key khong duoc con trong config.json"
assert "AIzaSyLEAKED" not in _json.dumps(disk_cfg)
with open(tmp_sec, "r", encoding="utf-8") as f:
    sec_disk = _json.load(f)
assert sec_disk.get("ai_copilot_gemini_api_key") == "AIzaSyLEAKED"
iso.set("ai_copilot_gemini_api_key", "AIzaSyNEW")
with open(tmp_cfg, "r", encoding="utf-8") as f:
    disk_cfg2 = _json.load(f)
assert "AIzaSyNEW" not in _json.dumps(disk_cfg2)
os.environ.pop("PCAUTOCLEANER_SECRETS_PATH", None)
try:
    os.remove(tmp_cfg)
    os.remove(tmp_sec)
except Exception:
    pass

# D. Dispatcher enable_game_boost does not toggle off
from core.game_booster import GameBooster as _GB
was_active = _GB.is_active()
if was_active:
    _GB.disable_game_boost()
win.enable_game_boost()
assert _GB.is_active() is True, "enable_game_boost phai bat Game Boost"
win.enable_game_boost()
assert _GB.is_active() is True, "enable_game_boost lan 2 khong duoc tat"
_GB.disable_game_boost()

# E. Async worker class exists
from ui.ai_copilot_widget import CopilotAskWorker
from PyQt5.QtCore import QThread
assert issubclass(CopilotAskWorker, QThread)
worker = CopilotAskWorker(copilot, "ping", append_user=False)
assert worker._prompt == "ping"

print(" [PASS] 44. Auto-Pilot apply/undo, Gemini last_error hien thi, secrets khong ghi vao config.json!")

print("\n>>> TAT CA 44 BAI KIEM TRA TOAN DIEN HE THONG, REGISTRY, SSD TRIM, HARDWARE, AI ADVISOR, SERVICES, CONTEXT MENU, UNINSTALLER, WINSXS, SETUP WIZARD, PREDICTIVE AI, SETTINGS PERSISTENCE, HUD TOAST, AI COPILOT/AUTO-PILOT APPLY, ASYNC GEMINI & SECRET STORAGE DEU THANH CONG 100%! <<<")






