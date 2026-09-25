"""
Module Quản Lý & Tối Ưu Hóa Mạng (Network Optimizer)
Hỗ trợ:
1. Xóa sạch bộ nhớ đệm DNS Resolver (Flush DNS).
2. Xóa bảng định danh NetBIOS và ARP cache.
3. Tinh chỉnh cấu hình TCP/IP stack (Heuristics, Auto-tuning, RSS).
4. Đo độ trễ phản hồi DNS Benchmark (Google, Cloudflare, Quad9, OpenDNS).
5. Quét và phân loại các tiến trình đang chiếm kết nối mạng.
"""

import os
import sys
import time
import socket
import psutil
import subprocess
import threading
from typing import Dict, Any, List, Optional
from core.logger import logger

DNS_PROVIDERS = [
    {"name": "Cloudflare DNS",        "primary": "1.1.1.1",        "secondary": "1.0.0.1",        "description": "Tốc độ nhanh nhất & bảo mật cao"},
    {"name": "Google Public DNS",     "primary": "8.8.8.8",        "secondary": "8.8.4.4",        "description": "Độ ổn định tối đa & phổ biến toàn cầu"},
    {"name": "Quad9 DNS",             "primary": "9.9.9.9",        "secondary": "149.112.112.112", "description": "Chặn mã độc & tên miền độc hại"},
    {"name": "OpenDNS (Cisco)",       "primary": "208.67.222.222", "secondary": "208.67.220.220", "description": "Lọc nội dung & phân giải ổn định"},
    {"name": "NextDNS",               "primary": "45.90.28.0",     "secondary": "45.90.30.0",     "description": "DNS hiện đại với tính năng lọc tùy chỉnh"},
    {"name": "AdGuard DNS",           "primary": "94.140.14.14",   "secondary": "94.140.15.15",   "description": "Chặn quảng cáo & mã độc toàn cầu"},
    {"name": "Cloudflare DNS (bảo mật)","primary": "1.1.1.2",     "secondary": "1.0.0.2",        "description": "Cloudflare chặn malware (Tầng 2)"},
]

# Các tiến trình hệ thống không được phép tắt
PROTECTED_NET_PROCESSES = {
    "system", "svchost.exe", "lsass.exe", "services.exe", "csrss.exe", 
    "wininit.exe", "explorer.exe", "spoolsv.exe"
}

class NetworkOptimizer:
    """
    Bộ công cụ tối ưu hóa kết nối mạng và chẩn đoán độ trễ trên Windows.
    """

    @staticmethod
    def _run_cmd(cmd: str, timeout: int = 5) -> Dict[str, Any]:
        """Thực thi lệnh shell Windows an toàn với timeout."""
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return {
                "returncode": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "success": res.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "Lệnh bị quá thời gian (timeout)", "success": False}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}

    @classmethod
    def flush_dns(cls) -> Dict[str, Any]:
        """
        Xóa sạch bộ nhớ đệm DNS Resolver của Windows (ipconfig /flushdns).
        Giúp sửa lỗi kết nối trang web, tải chậm hoặc tên miền cũ bị lưu đệm.
        """
        logger.info("[NetworkOptimizer] Đang thực hiện ipconfig /flushdns...")
        res = cls._run_cmd("ipconfig /flushdns")
        success = res["success"] or "Successfully flushed" in res["stdout"] or "thành công" in res["stdout"].lower()
        msg = "Đã làm mới và xóa sạch bộ nhớ đệm DNS Resolver." if success else res["stderr"] or res["stdout"]
        if success:
            logger.info("[NetworkOptimizer] Xóa DNS Cache thành công.")
        else:
            logger.warning(f"[NetworkOptimizer] Xóa DNS Cache thất bại: {msg}")
        return {
            "action": "flush_dns",
            "success": success,
            "message": msg
        }

    @classmethod
    def purge_arp_netbios(cls) -> Dict[str, Any]:
        """
        Làm mới bảng ánh xạ địa chỉ ARP và bộ nhớ đệm tên NetBIOS.
        """
        logger.info("[NetworkOptimizer] Đang làm mới NetBIOS và ARP cache...")
        res_nb = cls._run_cmd("nbtstat -R")
        res_arp = cls._run_cmd("netsh interface ip delete arpcache")
        
        # arpcache có thể yêu cầu quyền Admin, nhưng nbtstat -R thường thành công
        success = res_nb["success"] or res_arp["success"]
        return {
            "action": "purge_arp_netbios",
            "success": success,
            "message": "Đã làm mới bảng phân giải địa chỉ ARP và tên NetBIOS nội mạng."
        }

    @classmethod
    def optimize_tcp_stack(cls) -> Dict[str, Any]:
        """
        Tinh chỉnh các thiết lập TCP/IP Global để cải thiện băng thông và độ trễ:
        - Tắt TCP Heuristics (tránh Windows tự động bóp nghẹt kích thước cửa sổ nhận).
        - Bật TCP Autotuning ở mức Normal (đảm bảo tận dụng tối đa băng thông cao).
        - Bật Receive Side Scaling (RSS) để xử lý gói tin đa lõi CPU.
        """
        logger.info("[NetworkOptimizer] Đang tinh chỉnh cấu hình TCP/IP stack...")
        details = []
        
        # 1. Tắt TCP Heuristics
        r1 = cls._run_cmd("netsh interface tcp set heuristics disabled")
        if r1["success"] or "ok" in r1["stdout"].lower():
            details.append("Đã vô hiệu hóa TCP Heuristics (ngăn chặn tự giảm băng thông)")
        
        # 2. Bật TCP Auto-Tuning level normal
        r2 = cls._run_cmd("netsh interface tcp set global autotuninglevel=normal")
        if r2["success"] or "ok" in r2["stdout"].lower():
            details.append("Đã đặt TCP Auto-Tuning = Normal (tối đa hóa tốc độ tải xuống)")
        elif "elevation" in r2["stderr"].lower() or "administrator" in r2["stderr"].lower():
            details.append("TCP Auto-Tuning: Giữ nguyên mức mặc định (Cần quyền Admin để ghi đè)")

        # 3. Bật Receive-Side Scaling (RSS)
        r3 = cls._run_cmd("netsh interface tcp set global rss=enabled")
        if r3["success"] or "ok" in r3["stdout"].lower():
            details.append("Đã kích hoạt Receive-Side Scaling (phân phối tải mạng đa nhân CPU)")

        # 4. Kích hoạt Fast Open
        r4 = cls._run_cmd("netsh interface tcp set global fastopen=enabled")
        if r4["success"] or "ok" in r4["stdout"].lower():
            details.append("Đã bật TCP Fast Open (rút ngắn thời gian thiết lập kết nối)")

        return {
            "action": "optimize_tcp_stack",
            "success": True,
            "details": details,
            "message": "Đã tinh chỉnh cấu hình TCP/IP stack tối ưu cho Windows."
        }

    @classmethod
    def full_optimize(cls) -> Dict[str, Any]:
        """
        Thực hiện toàn diện gói tối ưu hóa mạng 1-Click:
        1. Xóa bộ nhớ đệm DNS.
        2. Làm mới ARP & NetBIOS.
        3. Tinh chỉnh TCP/IP stack.
        """
        t0 = time.time()
        res_dns = cls.flush_dns()
        res_arp = cls.purge_arp_netbios()
        res_tcp = cls.optimize_tcp_stack()
        duration_ms = round((time.time() - t0) * 1000, 1)

        summary_steps = [
            f"✅ {res_dns['message']}",
            f"✅ {res_arp['message']}",
            f"✅ {res_tcp['message']}"
        ]
        for d in res_tcp.get("details", []):
            summary_steps.append(f"   • {d}")

        return {
            "success": True,
            "duration_ms": duration_ms,
            "steps": summary_steps,
            "dns_result": res_dns,
            "arp_result": res_arp,
            "tcp_result": res_tcp,
            "timestamp": datetime_str()
        }

    @classmethod
    def is_admin(cls) -> bool:
        """Kiểm tra xem ứng dụng có đang chạy với quyền Administrator hay không (dual check)."""
        try:
            import ctypes
            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
                return True
        except Exception:
            pass
        try:
            r = subprocess.run(
                "net session", shell=True, capture_output=True, timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return r.returncode == 0
        except Exception:
            return False

    @classmethod
    def get_active_adapters(cls) -> list:
        """
        Lấy danh sách tên các network adapter vật lý đang hoạt động (Connected & Non-virtual).
        Tự động loại bỏ các adapter ảo/tunnel như Teredo, Loopback, vEthernet.
        """
        adapters = []
        # 1. Thử qua PowerShell Get-NetAdapter (chính xác và lọc sạch virtual nhất trên Windows)
        try:
            cmd = "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.Virtual -eq $false } | Select-Object -ExpandProperty Name"
            res = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.splitlines():
                    name = line.strip()
                    if name and name not in adapters:
                        adapters.append(name)
        except Exception:
            pass

        # 2. Fallback: netsh interface show interface
        if not adapters:
            try:
                result = cls._run_cmd('netsh interface show interface', timeout=5)
                for line in result["stdout"].splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and 'connected' in parts[0].lower():
                        adapter_name = ' '.join(parts[3:])
                        lower = adapter_name.lower()
                        if not any(k in lower for k in ['teredo', 'loopback', 'vethernet', 'tunnel', 'pseudo']):
                            if adapter_name not in adapters:
                                adapters.append(adapter_name)
            except Exception:
                pass

        # 3. Fallback: psutil
        if not adapters:
            try:
                import psutil
                stats = psutil.net_if_stats()
                for name, stat in stats.items():
                    lower = name.lower()
                    if stat.isup and not any(k in lower for k in ['teredo', 'loopback', 'vethernet', 'pseudo', 'virtual']):
                        adapters.append(name)
            except Exception:
                pass

        return adapters

    @classmethod
    def apply_dns_to_adapter(cls, adapter_name: str, primary_dns: str, secondary_dns: str, allow_elevation: bool = True) -> Dict[str, Any]:
        """
        Áp dụng cấu hình DNS server vào một network adapter cụ thể.
        Nếu ứng dụng đã chạy bằng Administrator: Thực thi trực tiếp 100%, không hỏi hay xin quyền tiếp.
        Nếu chưa có quyền Administrator: Yêu cầu quyền UAC RunAs để thực thi.
        """
        is_elevated = cls.is_admin()

        if is_elevated:
            # Khi đã có quyền Admin: Áp dụng trực tiếp bằng PowerShell cmdlet hoặc netsh, không hỏi quyền lại
            ps_cmd = f"Set-DnsClientServerAddress -InterfaceAlias '{adapter_name}' -ServerAddresses @('{primary_dns}','{secondary_dns}')"
            r_ps = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if r_ps.returncode == 0:
                logger.info(f"[NetworkOptimizer] Đã áp dụng DNS trực tiếp (Admin Mode) cho adapter '{adapter_name}' qua PowerShell.")
                return {
                    "adapter": adapter_name,
                    "primary": primary_dns,
                    "secondary": secondary_dns,
                    "success": True,
                    "message": f"Đã áp dụng DNS {primary_dns}/{secondary_dns} cho adapter '{adapter_name}' (Admin Mode)"
                }

            # Fallback qua netsh
            r1 = cls._run_cmd(
                f'netsh interface ip set dns name="{adapter_name}" source=static address={primary_dns} validate=no',
                timeout=8
            )
            r2 = cls._run_cmd(
                f'netsh interface ip add dns name="{adapter_name}" addr={secondary_dns} index=2 validate=no',
                timeout=8
            )
            success = r1["success"] or r1["returncode"] == 0
            return {
                "adapter": adapter_name,
                "primary": primary_dns,
                "secondary": secondary_dns,
                "success": success,
                "message": f"Đã áp dụng DNS {primary_dns}/{secondary_dns} cho adapter '{adapter_name}'" if success
                           else f"Thất bại: {r1['stderr'] or r1['stdout']}"
            }
        elif allow_elevation:
            # Chạy qua UAC RunAs có chờ hoàn tất
            try:
                import ctypes
                from ctypes import wintypes

                cmd_params = (
                    f'/c netsh interface ip set dns name="{adapter_name}" source=static address={primary_dns} validate=no && '
                    f'netsh interface ip add dns name="{adapter_name}" addr={secondary_dns} index=2 validate=no && '
                    f'ipconfig /flushdns'
                )

                class SHELLEXECUTEINFO(ctypes.Structure):
                    _fields_ = [
                        ('cbSize', wintypes.DWORD),
                        ('fMask', wintypes.ULONG),
                        ('hwnd', wintypes.HWND),
                        ('lpVerb', wintypes.LPCWSTR),
                        ('lpFile', wintypes.LPCWSTR),
                        ('lpParameters', wintypes.LPCWSTR),
                        ('lpDirectory', wintypes.LPCWSTR),
                        ('nShow', ctypes.c_int),
                        ('hInstApp', wintypes.HINSTANCE),
                        ('lpIDList', wintypes.LPVOID),
                        ('lpClass', wintypes.LPCWSTR),
                        ('hkeyClass', wintypes.HKEY),
                        ('dwHotKey', wintypes.DWORD),
                        ('hIconOrMonitor', wintypes.HANDLE),
                        ('hProcess', wintypes.HANDLE)
                    ]

                SEE_MASK_NOCLOSEPROCESS = 0x00000040
                SW_HIDE = 0

                sei = SHELLEXECUTEINFO()
                sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
                sei.fMask = SEE_MASK_NOCLOSEPROCESS
                sei.hwnd = None
                sei.lpVerb = "runas"
                sei.lpFile = "cmd.exe"
                sei.lpParameters = cmd_params
                sei.lpDirectory = None
                sei.nShow = SW_HIDE

                success = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
                if success:
                    if sei.hProcess:
                        ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 6000)
                        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
                    return {
                        "adapter": adapter_name,
                        "primary": primary_dns,
                        "secondary": secondary_dns,
                        "success": True,
                        "message": f"Đã cập nhật DNS có quyền Administrator cho '{adapter_name}'."
                    }
                else:
                    err_code = ctypes.GetLastError()
                    if err_code == 1223:
                        msg = "Người dùng đã từ chối cấp quyền Administrator (UAC)."
                    else:
                        msg = f"Không thể cấp quyền Administrator (Mã lỗi: {err_code})."
                    return {
                        "adapter": adapter_name,
                        "primary": primary_dns,
                        "secondary": secondary_dns,
                        "success": False,
                        "message": msg
                    }
            except Exception as e:
                # Fallback qua ShellExecuteW
                try:
                    import ctypes
                    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", cmd_params, None, 0)
                    if ret > 32:
                        return {
                            "adapter": adapter_name,
                            "primary": primary_dns,
                            "secondary": secondary_dns,
                            "success": True,
                            "message": f"Đã thực thi cập nhật DNS có quyền Administrator cho '{adapter_name}'."
                        }
                except Exception:
                    pass
                return {
                    "adapter": adapter_name,
                    "primary": primary_dns,
                    "secondary": secondary_dns,
                    "success": False,
                    "message": f"Lỗi yêu cầu quyền UAC: {e}"
                }
        else:
            return {
                "adapter": adapter_name,
                "primary": primary_dns,
                "secondary": secondary_dns,
                "success": False,
                "message": "Yêu cầu quyền Administrator để thay đổi cấu hình DNS."
            }

    @classmethod
    def apply_best_dns(cls, allow_elevation: bool = True) -> Dict[str, Any]:
        """
        Tự động benchmark tất cả DNS servers, tìm DNS có độ trễ thấp nhất
        và áp dụng vào toàn bộ network adapters đang hoạt động.
        Trả về thông tin DNS được chọn và kết quả áp dụng.
        """
        logger.info("[NetworkOptimizer] Đang tự động benchmark để tìm DNS tốt nhất...")
        results = cls.benchmark_dns()

        # Lọc các DNS phản hồi được (latency > 0)
        available = [r for r in results if r["latency_ms"] > 0]
        if not available:
            return {"success": False, "message": "Không thể kết nối tới bất kỳ DNS nào. Hãy kiểm tra kết nối mạng."}

        # DNS tốt nhất = latency thấp nhất
        best = available[0]
        best_name = best["name"]
        best_ip   = best["primary"]
        second_ip = best["secondary"]

        logger.info(f"[NetworkOptimizer] DNS tốt nhất: {best_name} ({best_ip}) - {best['latency_ms']} ms. Đang áp dụng...")

        adapters = cls.get_active_adapters()
        if not adapters:
            return {"success": False, "message": "Không tìm thấy network adapter vật lý nào đang hoạt động."}

        apply_results = []
        success_count = 0
        for adapter in adapters:
            res = cls.apply_dns_to_adapter(adapter, best_ip, second_ip, allow_elevation=allow_elevation)
            apply_results.append(res)
            if res["success"]:
                success_count += 1
                logger.info(f"[NetworkOptimizer] ✅ {adapter}: DNS đặt thành {best_ip}")
            else:
                logger.warning(f"[NetworkOptimizer] ⚠️ {adapter}: {res['message']}")

        # Sau khi đổi DNS, flush cache để áp dụng ngay
        cls.flush_dns()

        if success_count > 0:
            msg = (
                f"Đã chuyển sang {best_name} ({best_ip}) – "
                f"Độ trễ {best['latency_ms']:.0f} ms – "
                f"Cập nhật thành công {success_count}/{len(adapters)} adapter ({', '.join(adapters[:2])})!"
            )
        else:
            msg = (
                f"Không thể áp dụng DNS {best_name} ({best_ip}): "
                f"Yêu cầu quyền Administrator (Run as administrator) để thay đổi cấu hình mạng Windows."
            )

        needs_admin = success_count == 0 and not cls.is_admin()
        return {
            "success": success_count > 0,
            "best_dns_name": best_name,
            "best_dns_ip": best_ip,
            "best_dns_latency_ms": best["latency_ms"],
            "adapters_updated": success_count,
            "adapters_total": len(adapters),
            "apply_results": apply_results,
            "benchmark_results": results,
            "needs_admin": needs_admin,
            "message": msg
        }

    @staticmethod
    def measure_dns_latency(ip: str, port: int = 53, timeout: float = 1.0) -> float:
        """
        Đo độ trễ phản hồi (ms) tới một máy chủ DNS thông qua kết nối socket TCP.
        Trả về độ trễ trung bình sau 2 lượt kiểm tra, hoặc -1 nếu timeout.
        """
        latencies = []
        for _ in range(2):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            t_start = time.time()
            try:
                s.connect((ip, port))
                latencies.append((time.time() - t_start) * 1000)
            except Exception:
                pass
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        if not latencies:
            return -1.0
        return round(sum(latencies) / len(latencies), 1)

    @classmethod
    def benchmark_dns(cls) -> List[Dict[str, Any]]:
        """
        Đo độ trễ của các dịch vụ DNS phổ biến để tìm ra máy chủ có phản hồi nhanh nhất.
        Thực hiện đo song song (parallel) bằng ThreadPoolExecutor cho tốc độ phản hồi cực nhanh (<0.5s).
        """
        import concurrent.futures

        def _measure_provider(provider):
            ip = provider["primary"]
            latency = cls.measure_dns_latency(ip, timeout=0.8)
            status = "Cực nhanh 🟢" if 0 < latency < 40 else ("Tốt 🟡" if latency < 80 else ("Chậm 🔴" if latency > 0 else "Không phản hồi ❌"))
            return {
                "name": provider["name"],
                "ip": provider["primary"],
                "primary": provider["primary"],
                "secondary": provider["secondary"],
                "description": provider["description"],
                "latency_ms": latency,
                "status": status
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(DNS_PROVIDERS)) as executor:
            results = list(executor.map(_measure_provider, DNS_PROVIDERS))

        # Sắp xếp các DNS khả dụng có ping thấp nhất lên đầu
        results.sort(key=lambda x: (x["latency_ms"] if x["latency_ms"] > 0 else 9999))
        return results

    @classmethod
    def get_network_processes(cls, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Quét và lấy danh sách các tiến trình đang mở kết nối mạng Internet.
        """
        try:
            conns = psutil.net_connections(kind='inet')
        except Exception as e:
            logger.warning(f"[NetworkOptimizer] Lỗi khi lấy net_connections: {e}")
            return []

        # Nhóm các kết nối theo PID
        pid_conns: Dict[int, Dict[str, Any]] = {}
        for c in conns:
            pid = c.pid
            if not pid:
                continue
            if pid not in pid_conns:
                pid_conns[pid] = {
                    "total": 0,
                    "established": 0,
                    "listen": 0,
                    "remote_endpoints": set()
                }
            pid_conns[pid]["total"] += 1
            if c.status == 'ESTABLISHED':
                pid_conns[pid]["established"] += 1
            elif c.status == 'LISTEN':
                pid_conns[pid]["listen"] += 1
            if c.raddr:
                pid_conns[pid]["remote_endpoints"].add(f"{c.raddr.ip}:{c.raddr.port}")

        procs_list = []
        for pid, c_info in pid_conns.items():
            try:
                proc = psutil.Process(pid)
                name = proc.name()
                mem_mb = round(proc.memory_info().rss / (1024 ** 2), 1)
                cpu_pct = round(proc.cpu_percent(interval=None), 1)
                
                # Phân loại tiến trình
                name_lower = name.lower()
                category = "Ứng dụng"
                if any(b in name_lower for b in ["chrome", "edge", "firefox", "brave", "opera"]):
                    category = "Trình duyệt"
                elif any(g in name_lower for g in ["steam", "epic", "riot", "game", "valorant", "league"]):
                    category = "Trò chơi"
                elif any(c in name_lower for c in ["onedrive", "dropbox", "google drive", "cloud"]):
                    category = "Đồng bộ đám mây"
                elif any(t in name_lower for t in ["torrent", "utorrent", "bittorrent", "qbittorrent"]):
                    category = "Chia sẻ tệp P2P"
                elif any(m in name_lower for m in ["zalo", "discord", "telegram", "teams", "zoom", "skype"]):
                    category = "Nhắn tin & Gọi"
                elif name_lower in PROTECTED_NET_PROCESSES or pid in (0, 4):
                    category = "Hệ thống"

                is_protected = name_lower in PROTECTED_NET_PROCESSES or pid in (0, 4)

                procs_list.append({
                    "pid": pid,
                    "name": name,
                    "total_connections": c_info["total"],
                    "established": c_info["established"],
                    "listen": c_info["listen"],
                    "remote_count": len(c_info["remote_endpoints"]),
                    "mem_mb": mem_mb,
                    "cpu_percent": cpu_pct,
                    "category": category,
                    "is_protected": is_protected
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sắp xếp theo số kết nối established và total giảm dần
        procs_list.sort(key=lambda x: (x["established"], x["total_connections"]), reverse=True)
        return procs_list[:limit]

    # ------------------------------------------------------------------
    # Network health check + safe repair (missing / failed ping)
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_tcp(host: str, port: int, timeout: float = 1.0) -> Dict[str, Any]:
        """TCP connect probe. Trả về ok + latency_ms (-1 nếu thất bại)."""
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            t0 = time.time()
            s.connect((host, port))
            latency = round((time.time() - t0) * 1000, 1)
            return {"ok": True, "latency_ms": latency, "error": ""}
        except (socket.timeout, TimeoutError):
            return {"ok": False, "latency_ms": -1.0, "error": "timeout"}
        except OSError as e:
            return {"ok": False, "latency_ms": -1.0, "error": str(e) or "unreachable"}
        except Exception as e:
            return {"ok": False, "latency_ms": -1.0, "error": str(e)}
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    @classmethod
    def get_default_gateway(cls) -> Dict[str, Any]:
        """Đọc default gateway (Windows `route print`, Linux `ip route`)."""
        gateway = ""
        detail = ""
        try:
            if sys.platform == "win32":
                res = cls._run_cmd("route print 0.0.0.0", timeout=4)
                text = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
                for line in text.splitlines():
                    parts = line.split()
                    # Typical: 0.0.0.0  0.0.0.0  192.168.1.1  192.168.1.10  25
                    if len(parts) >= 3 and parts[0] == "0.0.0.0":
                        cand = parts[2]
                        if cand.count(".") == 3 and not cand.startswith("0."):
                            gateway = cand
                            break
            else:
                res = cls._run_cmd("ip route show default", timeout=3)
                text = res.get("stdout") or ""
                parts = text.split()
                if "via" in parts:
                    gateway = parts[parts.index("via") + 1]
        except Exception as e:
            detail = str(e)

        ok = bool(gateway)
        if ok:
            detail = f"Gateway mặc định: {gateway}"
        elif not detail:
            detail = "Không tìm thấy default gateway (máy có thể offline / chưa có DHCP)."
        return {"ok": ok, "gateway": gateway, "detail": detail}

    @classmethod
    def check_dns_resolve(cls, hostname: str = "dns.google", timeout: float = 2.0) -> Dict[str, Any]:
        """Kiểm tra phân giải DNS (không cần ICMP). Có timeout để không kẹt UI."""
        box: Dict[str, Any] = {"ok": False, "addresses": [], "detail": "DNS quá thời gian chờ."}

        def _resolve():
            try:
                infos = socket.getaddrinfo(hostname, 443, socket.AF_INET, socket.SOCK_STREAM)
                addrs = sorted({item[4][0] for item in infos if item and item[4]})
                if addrs:
                    box.update({
                        "ok": True,
                        "addresses": addrs[:3],
                        "detail": f"DNS OK — {hostname} → {', '.join(addrs[:3])}",
                    })
                else:
                    box["detail"] = f"DNS không trả về địa chỉ cho {hostname}."
            except socket.gaierror as e:
                box["detail"] = f"DNS lỗi: {e}"
            except Exception as e:
                box["detail"] = f"DNS không phản hồi: {e}"

        t = threading.Thread(target=_resolve, daemon=True)
        t.start()
        t.join(timeout)
        return box

    @classmethod
    def get_adapter_state(cls) -> Dict[str, Any]:
        """Trạng thái card mạng vật lý đang Up."""
        names = []
        try:
            stats = psutil.net_if_stats()
            for name, st in stats.items():
                lower = name.lower()
                if st.isup and not any(k in lower for k in ("loopback", "teredo", "tunnel", "pseudo")):
                    names.append(name)
        except Exception:
            pass
        if not names:
            # Fallback to the existing adapter enumerator (Windows netsh / PowerShell)
            try:
                names = list(cls.get_active_adapters() or [])
            except Exception:
                names = []
        ok = len(names) > 0
        detail = (
            f"Card đang hoạt động: {', '.join(names[:3])}"
            if ok else
            "Không có card mạng nào đang Up (Wi-Fi/Ethernet có thể bị tắt)."
        )
        return {"ok": ok, "adapters": names, "name": names[0] if names else "", "detail": detail}

    @classmethod
    def run_health_check(cls, measure_ping: bool = True) -> Dict[str, Any]:
        """
        Chẩn đoán mạng tập trung: adapter, gateway, DNS, TCP connectivity, ping.
        Không thay đổi hệ thống.
        """
        from core.system_monitor import SystemMonitor

        adapter = cls.get_adapter_state()
        gateway = cls.get_default_gateway()
        dns = cls.check_dns_resolve()

        conn_cloudflare = cls._probe_tcp("1.1.1.1", 443, timeout=1.5)
        conn_google_dns = cls._probe_tcp("8.8.8.8", 53, timeout=1.5)
        conn_google_https = cls._probe_tcp("8.8.8.8", 443, timeout=1.5)
        connectivity_ok = bool(
            conn_cloudflare["ok"] or conn_google_dns["ok"] or conn_google_https["ok"]
        )
        conn_latency = -1.0
        for probe in (conn_cloudflare, conn_google_https, conn_google_dns):
            if probe["ok"]:
                conn_latency = probe["latency_ms"]
                break
        connectivity = {
            "ok": connectivity_ok,
            "latency_ms": conn_latency,
            "cloudflare": conn_cloudflare,
            "google_dns": conn_google_dns,
            "google_https": conn_google_https,
            "detail": (
                f"Kết nối TCP OK ({conn_latency:.0f} ms)"
                if connectivity_ok else
                "Không kết nối được tới Cloudflare/Google DNS (53) lẫn HTTPS (443)."
            ),
        }

        if measure_ping:
            ping_ms = SystemMonitor.measure_ping_now()
        else:
            ping_ms = float(SystemMonitor.get_network_info().get("ping_ms", -1))
        ping_ok = ping_ms > 0
        ping = {
            "ok": ping_ok,
            "ping_ms": ping_ms,
            "status": SystemMonitor._ping_status,
            "fail_streak": SystemMonitor._ping_fail_streak,
            "detail": (
                f"Ping {ping_ms:.0f} ms"
                if ping_ok else
                f"Ping không đo được ({SystemMonitor._ping_status or 'timeout'})."
            ),
        }

        # Wi-Fi snapshot without wevtutil on the ping path (scheduler gathers events).
        wifi = {"ok": True, "is_wifi": False, "unstable": False, "cause": "ok", "detail": "Không phải Wi-Fi."}
        try:
            from core.wifi_recovery import WifiRecovery
            wifi = WifiRecovery.detect_wifi_instability(
                include_events=False, event_text="", ping_ok=ping_ok,
            )
            wifi.setdefault("detail", wifi.get("cause_label") or "")
            wifi["ok"] = not bool(wifi.get("unstable"))
        except Exception:
            wifi = {"ok": True, "is_wifi": False, "unstable": False, "cause": "ok", "detail": ""}

        issues = []
        if not adapter["ok"]:
            issues.append("adapter_down")
        if not gateway["ok"]:
            issues.append("no_gateway")
        if not dns["ok"]:
            issues.append("dns_fail")
        if not connectivity["ok"]:
            issues.append("no_connectivity")
        if not ping["ok"]:
            issues.append("ping_missing")
        if wifi.get("unstable"):
            issues.append("wifi_unstable")

        cause, cause_label = cls.classify_missing_ping_cause(
            {"issues": issues, "checks": {
                "adapter": adapter, "gateway": gateway, "dns": dns,
                "connectivity": connectivity, "ping": ping, "wifi": wifi,
            }}
        ) if (not ping_ok or wifi.get("unstable")) else ("ok", "mạng ổn định")

        overall_ok = ping_ok and connectivity_ok
        if not issues:
            summary = "Mạng ổn định, Ping đo được."
        elif ping_ok:
            summary = "Ping đo được nhưng một số kiểm tra phụ chưa đạt."
        else:
            summary = f"Nguyên nhân: {cause_label}."

        return {
            "ok": overall_ok,
            "summary": summary,
            "issues": issues,
            "cause": cause,
            "cause_label": cause_label,
            "checks": {
                "adapter": adapter,
                "gateway": gateway,
                "dns": dns,
                "connectivity": connectivity,
                "ping": ping,
                "wifi": wifi,
            },
        }

    CAUSE_LABELS = {
        "adapter_down": "card mạng tắt / không có adapter",
        "no_gateway": "không có default gateway",
        "dns_fail": "DNS không phân giải được tên miền",
        "tcp_fail": "TCP tới DNS/HTTPS công cộng thất bại",
        "firewall_or_no_route": "firewall / không có tuyến mạng (no route)",
        "meter_timeout": "đồng hồ Ping quá thời gian (probe chậm hoặc bị chặn)",
        "ping_missing": "không đo được Ping",
        "reconnect_loop": "Wi-Fi rớt liên tục / vòng reconnect (WLAN flap)",
        "weak_link": "Wi-Fi tín hiệu yếu / tốc độ liên kết thấp",
        "link_loss": "mất liên kết Wi-Fi (không còn SSID / link)",
        "ok": "mạng ổn định",
    }

    last_missing_ping_report: Dict[str, Any] = {}
    last_wifi_drop_report: Dict[str, Any] = {}

    @classmethod
    def classify_missing_ping_cause(
        cls,
        health: Dict[str, Any],
        ping_status: str = "",
        down_bps: float = 0.0,
    ) -> tuple:
        """
        Chọn nguyên nhân chính (tiếng Việt) từ health check.
        Ưu tiên: adapter → gateway → firewall/no-route → TCP fail → DNS → meter timeout.
        """
        issues = list(health.get("issues") or [])
        checks = health.get("checks") or {}
        conn = checks.get("connectivity") or {}
        ping = checks.get("ping") or {}
        status = str(ping_status or ping.get("status") or "").lower()
        conn_err = " ".join(
            str((conn.get(key) or {}).get("error") or "")
            for key in ("cloudflare", "google_dns", "google_https")
        ).lower()
        firewall_markers = (
            "no route", "network is unreachable", "host is unreachable",
            "10051", "10065", "forbidden", "firewall", "permission denied",
        )
        looks_firewall = any(m in conn_err for m in firewall_markers)
        wifi = checks.get("wifi") or {}

        if wifi.get("unstable") and wifi.get("cause") in (
            "reconnect_loop", "weak_link", "link_loss",
        ):
            cause = str(wifi.get("cause") or "reconnect_loop")
        elif "wifi_unstable" in issues and wifi.get("cause") in (
            "reconnect_loop", "weak_link", "link_loss", "adapter_down",
        ):
            cause = str(wifi.get("cause") or "reconnect_loop")
        elif "adapter_down" in issues:
            cause = "adapter_down"
        elif "no_gateway" in issues:
            cause = "no_gateway"
        elif looks_firewall or (not conn.get("ok") and status == "unreachable"):
            cause = "firewall_or_no_route"
        elif "no_connectivity" in issues:
            cause = "tcp_fail"
        elif "dns_fail" in issues:
            cause = "dns_fail"
        elif (
            status in ("timeout", "meter_timeout")
            or (not ping.get("ok") and (conn.get("ok") or float(down_bps or 0) > 0))
        ):
            cause = "meter_timeout"
        else:
            cause = "ping_missing"
        return cause, cls.CAUSE_LABELS.get(cause, cls.CAUSE_LABELS["ping_missing"])

    @staticmethod
    def format_applied_fixes(steps: List[Dict[str, Any]]) -> str:
        """Tóm tắt 'đã sửa gì' cho toast / Advisor / widget."""
        labels = {
            "remeasure_long_timeout": "đo lại với timeout dài hơn",
            "flush_dns": "flush DNS",
            "purge_arp_netbios": "làm mới ARP/NetBIOS",
            "apply_best_dns": "đổi DNS siêu tốc",
            "optimize_tcp_stack": "tinh chỉnh TCP stack",
            "renew_dhcp": "renew DHCP",
            "reconnect_ssid": "ngắt rồi kết nối lại SSID",
            "disable_wifi_power_saving": "tắt tiết kiệm pin Wi-Fi",
            "wait_stable_link": "cửa sổ ổn định Wi-Fi",
        }
        parts = []
        for step in steps or []:
            action = step.get("action")
            label = labels.get(action, action or "")
            if not label:
                continue
            if step.get("success"):
                parts.append(label)
            else:
                parts.append(f"{label} (chưa xong)")
        return ", ".join(parts) if parts else "chưa áp dụng bước sửa"

    @classmethod
    def diagnose_and_repair_missing_ping(
        cls,
        apply_dns: bool = False,
        escalate_dns: bool = True,
    ) -> Dict[str, Any]:
        """
        Khi Ping không đo được: chẩn đoán nguyên nhân rồi sửa theo bậc, dừng khi Ping về:
          0. Đo lại với timeout dài hơn (2s)
          1. Flush DNS resolver cache
          2. Làm mới ARP / NetBIOS
          3. Áp dụng DNS tốt nhất (không UAC ẩn; UAC chỉ khi apply_dns=True)
          4. Tinh chỉnh TCP stack nhẹ (đã có sẵn)
        Không reset Winsock, không restart adapter trừ khi người dùng xác nhận riêng.
        Nếu Wi-Fi đang flap / yếu / mất link: chuyển sang lộ trình WifiRecovery
        (DHCP, reconnect SSID, tắt tiết kiệm pin, cửa sổ ổn định).
        """
        from core.system_monitor import SystemMonitor, PING_REPAIR_TIMEOUT
        from core.wifi_recovery import WifiRecovery

        t0 = time.time()
        health = cls.run_health_check(measure_ping=True)
        wifi_snap = (health.get("checks") or {}).get("wifi") or {}
        if not wifi_snap.get("is_wifi"):
            try:
                wifi_snap = WifiRecovery.detect_wifi_instability(
                    include_events=True,
                    health=health,
                )
            except Exception:
                wifi_snap = {}
        if wifi_snap.get("unstable"):
            report = WifiRecovery.diagnose_and_repair_wifi_drop(
                apply_dns=apply_dns,
                snapshot=wifi_snap,
                health=health,
            )
            cls.last_wifi_drop_report = report
            cls.last_missing_ping_report = report
            return report
        ping_before = float(health["checks"]["ping"]["ping_ms"])
        down_bps = 0.0
        try:
            down_bps = float(SystemMonitor.get_network_info().get("down_bps", 0) or 0)
        except Exception:
            down_bps = 0.0
        cause, cause_label = cls.classify_missing_ping_cause(
            health,
            ping_status=str(health["checks"]["ping"].get("status") or ""),
            down_bps=down_bps,
        )
        steps: List[Dict[str, Any]] = []
        skipped: List[str] = []
        needs_dns_confirm = False
        dns_applied = False
        stopped_at = ""
        loc_locked = bool((wifi_snap or {}).get("location_gpo_locked"))
        if not loc_locked:
            try:
                from core.windows_location import is_location_gpo_locked
                loc_locked = is_location_gpo_locked()
            except Exception:
                loc_locked = False
        needs_location_unlock = loc_locked

        def _pack(ping_after: float, recovered: bool, repaired: bool, reason: str, msg: str) -> Dict[str, Any]:
            applied = cls.format_applied_fixes(steps)
            report = {
                "success": repaired or recovered or any(s.get("success") for s in steps),
                "repaired": repaired,
                "recovered": recovered,
                "reason": reason,
                "cause": cause,
                "cause_label": cause_label,
                "applied_summary": applied,
                "message": msg,
                "issues": health.get("issues", []),
                "steps": steps,
                "skipped": skipped,
                "health_before": health,
                "ping_before": ping_before,
                "ping_after": ping_after,
                "dns_applied": dns_applied,
                "needs_dns_confirm": needs_dns_confirm,
                "needs_location_unlock": needs_location_unlock,
                "location_gpo_locked": loc_locked,
                "stopped_at": stopped_at,
                "duration_ms": round((time.time() - t0) * 1000, 1),
                "timestamp": datetime_str(),
            }
            cls.last_missing_ping_report = report
            return report

        if ping_before > 0:
            msg = (
                f"Ping đã đo được lại ({ping_before:.0f} ms). "
                "Không cần sửa mạng — đồng hồ Ping hoạt động bình thường."
            )
            logger.info(f"[NetworkOptimizer] {msg}")
            skipped.append("Bỏ qua sửa vì Ping đã đo được.")
            return _pack(ping_before, True, False, "ping_recovered_before_fix", msg)

        def _remeasure() -> float:
            return float(SystemMonitor.measure_ping_now(timeout=PING_REPAIR_TIMEOUT))

        # 0. Re-measure with a longer timeout — common when the live meter is too tight.
        ping_now = _remeasure()
        steps.append({
            "action": "remeasure_long_timeout",
            "success": ping_now > 0,
            "message": (
                f"Đo lại với timeout {PING_REPAIR_TIMEOUT:.1f}s → {ping_now:.0f} ms"
                if ping_now > 0 else
                f"Đo lại với timeout {PING_REPAIR_TIMEOUT:.1f}s vẫn thất bại"
            ),
        })
        if ping_now > 0:
            stopped_at = "remeasure_long_timeout"
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: đo lại với timeout dài hơn. Ping đo được lại: {ping_now:.0f} ms."
            )
            logger.info(f"[NetworkOptimizer] {msg}")
            skipped.append("Không cần flush DNS vì đo lại đã thành công.")
            skipped.append("Không khởi động lại card mạng / không reset Winsock (thao tác nặng).")
            return _pack(ping_now, True, True, "meter_timeout_recovered", msg)

        # 1. Flush DNS — always safe
        dns_res = cls.flush_dns()
        steps.append({
            "action": "flush_dns",
            "success": bool(dns_res.get("success")),
            "message": dns_res.get("message", "Flush DNS"),
        })
        ping_now = _remeasure()
        if ping_now > 0:
            stopped_at = "flush_dns"
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: {cls.format_applied_fixes(steps)}. "
                f"Ping đo được lại: {ping_now:.0f} ms."
            )
            skipped.append("Không khởi động lại card mạng / không reset Winsock (thao tác nặng).")
            logger.info(f"[NetworkOptimizer] Missing-ping repair: recovered=True ping_after={ping_now}")
            return _pack(ping_now, True, True, "ping_missing", msg)

        # 2. ARP / NetBIOS
        arp_res = cls.purge_arp_netbios()
        steps.append({
            "action": "purge_arp_netbios",
            "success": bool(arp_res.get("success")),
            "message": arp_res.get("message", "Làm mới ARP/NetBIOS"),
        })
        ping_now = _remeasure()
        if ping_now > 0:
            stopped_at = "purge_arp_netbios"
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: {cls.format_applied_fixes(steps)}. "
                f"Ping đo được lại: {ping_now:.0f} ms."
            )
            skipped.append("Không khởi động lại card mạng / không reset Winsock (thao tác nặng).")
            logger.info(f"[NetworkOptimizer] Missing-ping repair: recovered=True ping_after={ping_now}")
            return _pack(ping_now, True, True, "ping_missing", msg)

        # 3. Best DNS — auto without silent UAC; elevation only if the user asked (apply_dns).
        if escalate_dns or apply_dns:
            best = cls.apply_best_dns(allow_elevation=bool(apply_dns))
            dns_applied = bool(best.get("success"))
            needs_dns_confirm = (not dns_applied) and (
                bool(best.get("needs_admin"))
                or "Administrator" in str(best.get("message") or "")
                or "quyền" in str(best.get("message") or "").lower()
            )
            steps.append({
                "action": "apply_best_dns",
                "success": dns_applied,
                "message": best.get("message", "Áp dụng DNS tốt nhất"),
            })
            ping_now = _remeasure()
            if ping_now > 0:
                stopped_at = "apply_best_dns"
                msg = (
                    f"Nguyên nhân: {cause_label}. "
                    f"Đã sửa: {cls.format_applied_fixes(steps)}. "
                    f"Ping đo được lại: {ping_now:.0f} ms."
                )
                skipped.append("Không khởi động lại card mạng / không reset Winsock (thao tác nặng).")
                logger.info(f"[NetworkOptimizer] Missing-ping repair: recovered=True ping_after={ping_now}")
                return _pack(ping_now, True, True, "ping_missing", msg)
        else:
            skipped.append(
                "Không đổi DNS tự động. Dùng nút «Đổi DNS Siêu Tốc» nếu DNS vẫn lỗi."
            )

        # 4. Light TCP stack tweak (already in NetworkOptimizer)
        tcp_res = cls.optimize_tcp_stack()
        steps.append({
            "action": "optimize_tcp_stack",
            "success": bool(tcp_res.get("success")),
            "message": tcp_res.get("message", "Tinh chỉnh TCP stack"),
        })

        skipped.append("Không khởi động lại card mạng / không reset Winsock (thao tác nặng).")
        if needs_dns_confirm:
            skipped.append(
                "Đổi DNS cần quyền Administrator — bấm «Đổi DNS Siêu Tốc» để xác nhận UAC."
            )

        ping_after = _remeasure()
        recovered = ping_after > 0
        stopped_at = "optimize_tcp_stack" if recovered else "unrecovered"
        applied = cls.format_applied_fixes(steps)
        if recovered:
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: {applied}. Ping đo được lại: {ping_after:.0f} ms."
            )
        else:
            confirm = (
                " Cần quyền Admin để đổi DNS — bấm «Đổi DNS Siêu Tốc»."
                if needs_dns_confirm else
                " Hãy kiểm tra Wi-Fi/cáp hoặc bấm «Đổi DNS Siêu Tốc»."
            )
            msg = (
                f"Nguyên nhân: {cause_label}. "
                f"Đã sửa: {applied}. Ping vẫn chưa đo được.{confirm}"
            )

        logger.info(f"[NetworkOptimizer] Missing-ping repair: recovered={recovered} ping_after={ping_after}")
        return _pack(ping_after, recovered, True, "ping_missing", msg)

    @staticmethod
    def terminate_process(pid: int) -> Dict[str, Any]:
        """Ngắt an toàn một tiến trình chiếm dụng mạng."""
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            if name.lower() in PROTECTED_NET_PROCESSES or pid in (0, 4):
                return {"success": False, "message": f"Không thể tắt tiến trình hệ thống được bảo vệ: {name}"}
            proc.terminate()
            return {"success": True, "message": f"Đã gửi lệnh kết thúc tiến trình {name} (PID: {pid})."}
        except psutil.NoSuchProcess:
            return {"success": True, "message": "Tiến trình đã kết thúc trước đó."}
        except psutil.AccessDenied:
            return {"success": False, "message": f"Không đủ quyền hạn để tắt PID {pid} (Cần quyền Administrator)."}
        except Exception as e:
            return {"success": False, "message": str(e)}


def datetime_str():
    from datetime import datetime
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
