import os
import psutil
import ctypes
from typing import List, Dict, Any, Optional
from core.logger import logger

# Protected Windows system processes that must NEVER be terminated
PROTECTED_PROCESSES = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", 
    "wininit.exe", "services.exe", "lsass.exe", "svchost.exe", "fontdrvhost.exe",
    "winlogon.exe", "dwm.exe", "sihost.exe", "taskhostw.exe", "explorer.exe"
}

# Win32 Process Rights
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001

class ProcessManager:
    """
    Quản lý và giám sát các tiến trình tiêu thụ nhiều tài nguyên (RAM/CPU) nhất hệ thống.
    Hỗ trợ thu hồi RAM theo từng tiến trình riêng biệt và kết thúc tác vụ an toàn.
    """

    @staticmethod
    def get_top_processes(limit: int = 8, sort_by: str = "ram") -> List[Dict[str, Any]]:
        """
        Lấy danh sách các tiến trình chiếm nhiều RAM/CPU nhất.
        """
        processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
            try:
                p_info = proc.info
                pid = p_info['pid']
                name = p_info['name'] or f"Process-{pid}"
                mem_info = p_info.get('memory_info')
                
                if not mem_info:
                    continue

                rss_bytes = mem_info.rss
                rss_mb = round(rss_bytes / (1024 ** 2), 1)
                
                # Bỏ qua các tiến trình quá nhỏ (< 5 MB)
                if rss_mb < 5.0 and pid != 0:
                    continue

                cpu_pct = round(p_info.get('cpu_percent', 0.0) or 0.0, 1)
                is_protected = name.lower() in PROTECTED_PROCESSES or pid in (0, 4)

                # Phân loại tiến trình
                category = "Ứng dụng"
                name_lower = name.lower()
                if any(b in name_lower for b in ["chrome", "edge", "firefox", "brave", "opera"]):
                    category = "Trình duyệt"
                elif any(d in name_lower for d in ["code", "pycharm", "visualstudio", "devenv", "git"]):
                    category = "Lập trình"
                elif any(g in name_lower for g in ["steam", "game", "riot", "valorant", "league", "epic"]):
                    category = "Trò chơi"
                elif is_protected:
                    category = "Hệ thống"

                processes.append({
                    "pid": pid,
                    "name": name,
                    "ram_mb": rss_mb,
                    "cpu_percent": cpu_pct,
                    "is_protected": is_protected,
                    "category": category
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Sắp xếp theo tiêu chí
        if sort_by == "cpu":
            processes.sort(key=lambda x: x["cpu_percent"], reverse=True)
        else:
            processes.sort(key=lambda x: x["ram_mb"], reverse=True)

        return processes[:limit]

    @staticmethod
    def optimize_process_ram(pid: int) -> Dict[str, Any]:
        """
        Thu hồi bộ nhớ RAM cho riêng một tiến trình cụ thể qua Win32 EmptyWorkingSet
        """
        try:
            p = psutil.Process(pid)
            name = p.name()
            mem_before = p.memory_info().rss / (1024 ** 2)

            h_process = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid
            )
            if not h_process:
                return {"success": False, "error": "Không có quyền truy cập tiến trình"}

            try:
                ctypes.windll.psapi.EmptyWorkingSet(h_process)
            finally:
                ctypes.windll.kernel32.CloseHandle(h_process)

            # Đo lại sau tối ưu
            try:
                mem_after = p.memory_info().rss / (1024 ** 2)
                freed_mb = max(0.0, round(mem_before - mem_after, 1))
            except Exception:
                freed_mb = 0.0

            logger.info(f"[ProcessManager] Đã tối ưu RAM cho {name} (PID {pid}): Thu hồi {freed_mb} MB")
            return {
                "success": True,
                "name": name,
                "pid": pid,
                "freed_mb": freed_mb
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def terminate_process(pid: int) -> Dict[str, Any]:
        """
        Đóng tiến trình an toàn nếu không thuộc danh sách tiến trình hệ điều hành được bảo vệ
        """
        try:
            p = psutil.Process(pid)
            name = p.name()

            if name.lower() in PROTECTED_PROCESSES or pid in (0, 4):
                return {
                    "success": False,
                    "error": f"Không thể đóng tiến trình hệ thống được bảo vệ ({name})"
                }

            p.terminate()
            try:
                p.wait(timeout=2)
            except psutil.TimeoutExpired:
                p.kill()

            logger.info(f"[ProcessManager] Đã kết thúc tiến trình {name} (PID {pid})")
            return {"success": True, "name": name, "pid": pid}
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}
