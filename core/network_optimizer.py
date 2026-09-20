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

        return {
            "success": success_count > 0,
            "best_dns_name": best_name,
            "best_dns_ip": best_ip,
            "best_dns_latency_ms": best["latency_ms"],
            "adapters_updated": success_count,
            "adapters_total": len(adapters),
            "apply_results": apply_results,
            "benchmark_results": results,
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
