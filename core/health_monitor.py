import os
import sys
import json
import ctypes
import psutil
from typing import Dict, Any, List
from core.logger import logger, LOG_FILE
from core.system_monitor import SystemMonitor

class HealthMonitor:
    @staticmethod
    def run_health_check() -> Dict[str, Any]:
        """
        Tự động chẩn đoán toàn diện hệ thống, file cấu hình, log và các API dọn dẹp
        """
        results = {
            "timestamp": SystemMonitor.get_ram_info(),
            "status": "HEALTHY",
            "issues": [],
            "fixes_applied": [],
            "details": {}
        }

        # 1. Kiểm tra RAM
        ram = SystemMonitor.get_ram_info()
        results["details"]["ram"] = ram
        if ram["percent"] >= 90:
            results["issues"].append(f"Cảnh báo: Bộ nhớ RAM đang quá tải nghiêm trọng ({ram['percent']}%)")
            results["status"] = "WARNING"

        # 2. Kiểm tra Ổ Đĩa C:
        disk = SystemMonitor.get_disk_info("C:\\")
        results["details"]["disk"] = disk
        if disk["free_gb"] < 10:
            results["issues"].append(f"Cảnh báo: Ổ C: chỉ còn {disk['free_gb']} GB trống. Cần dọn rác khẩn cấp!")
            results["status"] = "WARNING"

        # 3. Kiểm tra file config.json
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_path = os.path.join(base_dir, "config.json")
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    json.load(f)
                results["details"]["config"] = "OK (Hợp lệ)"
            else:
                results["issues"].append("File config.json chưa tồn tại (sẽ dùng cấu hình mặc định)")
        except json.JSONDecodeError:
            results["issues"].append("File config.json bị lỗi định dạng. Đang tự động khôi phục...")
            try:
                from config_manager import DEFAULT_CONFIG
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=4)
                results["fixes_applied"].append("Đã khôi phục file config.json về trạng thái mặc định an toàn")
            except Exception as e:
                results["issues"].append(f"Không thể khôi phục config.json: {e}")
                results["status"] = "ERROR"

        # 4. Kiểm tra Log File
        if os.path.exists(LOG_FILE):
            log_size_kb = round(os.path.getsize(LOG_FILE) / 1024, 1)
            results["details"]["log_file"] = f"{LOG_FILE} ({log_size_kb} KB)"
            
            # Quét tìm lỗi gần đây trong app.log
            try:
                error_count = 0
                critical_count = 0
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "[ERROR]" in line:
                            error_count += 1
                        elif "[CRITICAL]" in line:
                            critical_count += 1
                
                results["details"]["errors_in_log"] = error_count
                results["details"]["criticals_in_log"] = critical_count
                if critical_count > 0:
                    results["issues"].append(f"Phát hiện {critical_count} lỗi nghiêm trọng trong app.log")
                    results["status"] = "WARNING"
            except Exception as e:
                results["details"]["log_read_error"] = str(e)
        else:
            results["details"]["log_file"] = "Chưa phát sinh file log."

        # 5. Kiểm tra Win32 API
        try:
            h_proc = ctypes.windll.kernel32.GetCurrentProcess()
            res_ws = ctypes.windll.psapi.EmptyWorkingSet(h_proc)
            results["details"]["win32_empty_working_set"] = "OK" if res_ws != 0 else "WARM"
        except Exception as e:
            results["issues"].append(f"Win32 EmptyWorkingSet API gặp sự cố: {e}")
            results["status"] = "ERROR"

        # 6. Kiểm tra các thư mục Dọn dẹp Chuyên sâu (Windows Update & App Caches)
        try:
            from core.cleaner import JunkCleaner
            target_paths = JunkCleaner.get_target_paths()
            wu_paths = target_paths.get("windows_update", [])
            app_paths = target_paths.get("app_caches", [])

            results["details"]["windows_update_targets"] = len(wu_paths)
            results["details"]["app_cache_targets"] = len(app_paths)
        except Exception as e:
            results["issues"].append(f"Lỗi truy vấn thư mục dọn dẹp chuyên sâu: {e}")

        logger.info(f"[HealthMonitor] Chẩn đoán hoàn tất: Trạng thái {results['status']}, {len(results['issues'])} vấn đề phát hiện.")
        return results
