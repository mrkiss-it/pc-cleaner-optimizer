"""
Module Rà Soát Bảo Mật Hệ Thống (Security Scanner)
Kiểm tra tự động 10+ hạng mục bảo mật phổ biến trên Windows:
1. Trạng thái Windows Firewall (tất cả profiles)
2. Trạng thái Windows Defender / Antivirus
3. Bảo vệ thời gian thực (Real-time Protection)
4. Cài đặt UAC (User Account Control)
5. Windows Update - phiên bản hệ điều hành
6. Tài khoản Guest có bật không
7. Tự động đăng nhập (AutoLogon) không mật khẩu
8. Remote Desktop Protocol (RDP) có bật không
9. Các cổng mạng đang lắng nghe bất thường
10. Thư mục chia sẻ mạng (Network Shares)
11. Chương trình autorun đáng ngờ trong Registry
12. Windows SmartScreen có bật không
"""

import os
import sys
import re
import time
import winreg
import socket
import psutil
import subprocess
from typing import Dict, Any, List
from datetime import datetime
from core.logger import logger


# ──────────────────────────────────────────────────────────────────────────────
# Mức độ nghiêm trọng
# ──────────────────────────────────────────────────────────────────────────────
LEVEL_CRITICAL = "CRITICAL"   # Lỗ hổng nghiêm trọng, cần xử lý ngay
LEVEL_WARNING  = "WARNING"    # Cảnh báo, nên xem xét
LEVEL_INFO     = "INFO"       # Thông tin tham khảo
LEVEL_OK       = "OK"         # An toàn

# Các cổng nguy hiểm phổ biến cần cảnh báo nếu đang mở
DANGEROUS_PORTS = {
    21:   "FTP (Truyền file không mã hóa)",
    23:   "Telnet (Remote shell không mã hóa)",
    135:  "RPC Endpoint Mapper",
    137:  "NetBIOS Name Service",
    138:  "NetBIOS Datagram Service",
    139:  "NetBIOS Session Service",
    445:  "SMB (EternalBlue / WannaCry target)",
    1433: "Microsoft SQL Server",
    1434: "SQL Server Browser",
    3306: "MySQL",
    3389: "Remote Desktop (RDP)",
    4444: "Metasploit default reverse shell",
    5900: "VNC",
    8080: "HTTP Proxy",
}

# Các chương trình autorun đáng ngờ theo tên
SUSPICIOUS_AUTORUN_PATTERNS = [
    r"cmd\.exe", r"powershell", r"wscript", r"cscript",
    r"regsvr32", r"mshta", r"rundll32.*temp",
    r"\.vbs$", r"\.bat$", r"\.ps1$", r"temp\\", r"tmp\\",
    r"appdata\\roaming\\[^\\]+\.(exe|vbs|bat|ps1)$",
]


class SecurityScanner:
    """
    Bộ công cụ rà soát lỗi bảo mật tự động cho Windows.
    """

    @staticmethod
    def _run_cmd(cmd: str, timeout: int = 8) -> Dict[str, Any]:
        """Thực thi lệnh shell an toàn."""
        try:
            res = subprocess.run(
                cmd, shell=True, capture_output=True,
                text=True, timeout=timeout,
                encoding="utf-8", errors="ignore",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return {
                "returncode": res.returncode,
                "stdout": res.stdout.strip(),
                "stderr": res.stderr.strip(),
                "success": res.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": "Timeout", "success": False}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}

    @staticmethod
    def _read_reg(hive, path: str, key: str, default=None):
        """Đọc giá trị Registry an toàn."""
        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as reg:
                val, _ = winreg.QueryValueEx(reg, key)
                return val
        except Exception:
            return default

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Windows Firewall
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_firewall(cls) -> Dict[str, Any]:
        """Kiểm tra Windows Firewall trên cả 3 profiles: Domain, Private, Public."""
        result = cls._run_cmd("netsh advfirewall show allprofiles state")
        stdout = result["stdout"].lower()

        profiles_off = []
        if "domain profile" in stdout:
            lines = stdout.split("\n")
            current_profile = ""
            for line in lines:
                if "profile" in line and "settings" in line:
                    current_profile = line.strip()
                if "state" in line and "off" in line:
                    profiles_off.append(current_profile or "Unknown Profile")

        if not result["success"]:
            return {
                "check": "Windows Firewall",
                "status": "⚠️ Không thể kiểm tra",
                "level": LEVEL_WARNING,
                "detail": "Không đủ quyền đọc cấu hình Firewall.",
                "fix": None
            }

        if "off" in stdout:
            return {
                "check": "Windows Firewall",
                "status": "❌ Đang TẮT",
                "level": LEVEL_CRITICAL,
                "detail": "Windows Firewall đang bị vô hiệu hóa trên ít nhất một profile. Hệ thống của bạn không có tường lửa bảo vệ!",
                "fix": "enable_firewall"
            }

        return {
            "check": "Windows Firewall",
            "status": "✅ Đang BẬT",
            "level": LEVEL_OK,
            "detail": "Windows Firewall đang hoạt động bình thường trên tất cả profiles.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Windows Defender / Antivirus
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_antivirus(cls) -> Dict[str, Any]:
        """Kiểm tra Windows Defender và các phần mềm diệt virus đã đăng ký."""
        result = cls._run_cmd(
            'powershell -NoProfile -Command "Get-MpComputerStatus | Select-Object -Property AntivirusEnabled,RealTimeProtectionEnabled | ConvertTo-Json"',
            timeout=10
        )

        if result["success"] and result["stdout"]:
            try:
                import json
                data = json.loads(result["stdout"])
                av_enabled = data.get("AntivirusEnabled", False)
                rt_enabled = data.get("RealTimeProtectionEnabled", False)

                if not av_enabled:
                    return {
                        "check": "Windows Defender",
                        "status": "❌ Đang TẮT",
                        "level": LEVEL_CRITICAL,
                        "detail": "Windows Defender Antivirus bị vô hiệu hóa. Máy tính không được bảo vệ khỏi phần mềm độc hại!",
                        "fix": "enable_defender"
                    }
                elif not rt_enabled:
                    return {
                        "check": "Windows Defender",
                        "status": "⚠️ Bảo vệ thời gian thực TẮT",
                        "level": LEVEL_WARNING,
                        "detail": "Windows Defender bật nhưng tính năng bảo vệ thời gian thực đang tắt. Tệp độc hại sẽ không bị chặn khi mở.",
                        "fix": "enable_realtime_protection"
                    }
                else:
                    return {
                        "check": "Windows Defender",
                        "status": "✅ Đang BẬT & Bảo vệ thời gian thực HOẠT ĐỘNG",
                        "level": LEVEL_OK,
                        "detail": "Windows Defender đang hoạt động đầy đủ với bảo vệ thời gian thực.",
                        "fix": None
                    }
            except Exception:
                pass

        # Fallback: kiểm tra service
        svc = cls._run_cmd("sc query WinDefend")
        if svc["success"] and "RUNNING" in svc["stdout"]:
            return {
                "check": "Windows Defender",
                "status": "✅ Service đang chạy",
                "level": LEVEL_OK,
                "detail": "Windows Defender service đang hoạt động.",
                "fix": None
            }

        return {
            "check": "Windows Defender",
            "status": "⚠️ Không xác định",
            "level": LEVEL_WARNING,
            "detail": "Không thể xác minh trạng thái Antivirus. Có thể đã có phần mềm AV thứ ba thay thế.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 3. UAC (User Account Control)
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_uac(cls) -> Dict[str, Any]:
        """Kiểm tra mức độ cài đặt UAC."""
        val = cls._read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
            "EnableLUA", default=1
        )
        consent_val = cls._read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
            "ConsentPromptBehaviorAdmin", default=5
        )

        if val == 0:
            return {
                "check": "UAC (User Account Control)",
                "status": "❌ Đang TẮT",
                "level": LEVEL_CRITICAL,
                "detail": "UAC bị tắt hoàn toàn. Mọi chương trình đều chạy với quyền Administrator mà không cần xác nhận — rất nguy hiểm!",
                "fix": "enable_uac"
            }
        elif consent_val == 0:
            return {
                "check": "UAC (User Account Control)",
                "status": "⚠️ Mức thấp nhất (Không hỏi)",
                "level": LEVEL_WARNING,
                "detail": "UAC bật nhưng ở mức thấp nhất — không hiện hộp thoại xác nhận cho Admin. Phần mềm độc hại dễ leo thang quyền.",
                "fix": "set_uac_recommended"
            }
        else:
            return {
                "check": "UAC (User Account Control)",
                "status": "✅ Đang BẬT (Mức an toàn)",
                "level": LEVEL_OK,
                "detail": f"UAC hoạt động ở mức an toàn (ConsentPromptBehaviorAdmin={consent_val}).",
                "fix": None
            }

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Remote Desktop (RDP)
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_rdp(cls) -> Dict[str, Any]:
        """Kiểm tra Remote Desktop Protocol có đang bật không."""
        val = cls._read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Terminal Server",
            "fDenyTSConnections", default=1
        )
        if val == 0:
            return {
                "check": "Remote Desktop (RDP)",
                "status": "⚠️ Đang BẬT",
                "level": LEVEL_WARNING,
                "detail": "Remote Desktop đang bật. Nếu không cần thiết, đây là một vector tấn công từ xa thường bị khai thác (CVE-2019-0708 BlueKeep, v.v.).",
                "fix": "disable_rdp"
            }
        return {
            "check": "Remote Desktop (RDP)",
            "status": "✅ Đang TẮT",
            "level": LEVEL_OK,
            "detail": "Remote Desktop bị vô hiệu hóa — ít nguy cơ bị tấn công từ xa.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Tài khoản Guest
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_guest_account(cls) -> Dict[str, Any]:
        """Kiểm tra tài khoản Guest có bị bật không."""
        result = cls._run_cmd("net user Guest")
        stdout = result["stdout"].lower()
        if "account active" in stdout or "account is active" in stdout:
            if "yes" in stdout.split("account active")[-1][:20].lower() if "account active" in stdout else False:
                return {
                    "check": "Tài Khoản Guest",
                    "status": "⚠️ Guest Account BẬT",
                    "level": LEVEL_WARNING,
                    "detail": "Tài khoản Guest đang được bật. Người dùng không xác thực có thể truy cập hệ thống ở mức giới hạn.",
                    "fix": "disable_guest"
                }
        return {
            "check": "Tài Khoản Guest",
            "status": "✅ Guest Account TẮT",
            "level": LEVEL_OK,
            "detail": "Tài khoản Guest không được kích hoạt.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 6. AutoLogon (Tự động đăng nhập không cần mật khẩu)
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_autologon(cls) -> Dict[str, Any]:
        """Phát hiện cấu hình AutoLogon lưu mật khẩu trong Registry."""
        auto_logon = cls._read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
            "AutoAdminLogon", default="0"
        )
        default_pass = cls._read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
            "DefaultPassword", default=""
        )

        if str(auto_logon) == "1":
            has_pass = bool(default_pass)
            return {
                "check": "Tự Động Đăng Nhập (AutoLogon)",
                "status": "🔴 AutoLogon BẬT" + (" (mật khẩu lưu dạng plaintext!)" if has_pass else ""),
                "level": LEVEL_CRITICAL if has_pass else LEVEL_WARNING,
                "detail": (
                    "Windows được cấu hình tự động đăng nhập. "
                    + ("Mật khẩu được lưu dạng văn bản thuần (plaintext) trong Registry — cực kỳ nguy hiểm!" if has_pass
                       else "Có thể đăng nhập không cần mật khẩu.")
                ),
                "fix": "disable_autologon"
            }
        return {
            "check": "Tự Động Đăng Nhập (AutoLogon)",
            "status": "✅ Không có AutoLogon",
            "level": LEVEL_OK,
            "detail": "Hệ thống yêu cầu mật khẩu khi khởi động — an toàn.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 7. Cổng mạng đang lắng nghe
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_open_ports(cls) -> Dict[str, Any]:
        """Phát hiện các cổng nguy hiểm đang lắng nghe kết nối từ bên ngoài."""
        dangerous_found = []
        seen_ports = set()
        try:
            conns = psutil.net_connections(kind="inet")
            for c in conns:
                if c.status == "LISTEN" and c.laddr:
                    port = c.laddr.port
                    if port in DANGEROUS_PORTS:
                        # Bỏ qua cổng chỉ nghe trên localhost
                        if c.laddr.ip not in ("127.0.0.1", "::1"):
                            pid_info = ""
                            if c.pid:
                                try:
                                    pid_info = f" [{psutil.Process(c.pid).name()}]"
                                except Exception:
                                    pass
                            key = (port, pid_info)
                            if key not in seen_ports:
                                seen_ports.add(key)
                                dangerous_found.append(
                                    f"Port {port} — {DANGEROUS_PORTS[port]}{pid_info}"
                                )
        except Exception as e:
            return {
                "check": "Cổng Mạng Nguy Hiểm",
                "status": "⚠️ Không thể kiểm tra",
                "level": LEVEL_WARNING,
                "detail": f"Lỗi khi quét cổng: {e}",
                "fix": None
            }

        # Kiểm tra xem đã có rule Windows Firewall chặn các cổng này trên Public profile chưa
        fw_check = cls._run_cmd('netsh advfirewall firewall show rule name="PCAutoCleaner_Block_SMB_RPC_Public"')
        has_block_rule = fw_check.get("success") and "PCAutoCleaner_Block_SMB_RPC_Public" in fw_check.get("stdout", "")

        if dangerous_found:
            if has_block_rule:
                return {
                    "check": "Cổng Mạng Nguy Hiểm",
                    "status": "✅ Đã được bảo vệ bằng Tường Lửa",
                    "level": LEVEL_OK,
                    "detail": (
                        f"Phát hiện {len(dangerous_found)} cổng hệ thống Windows mặc định (RPC, NetBIOS, SMB):\n" +
                        "\n".join(f"  • {p}" for p in dangerous_found) +
                        "\n\n🛡️ Đã có quy tắc Tường Lửa (PCAutoCleaner_Block_SMB_RPC_Public) chặn mọi kết nối bên ngoài vào các cổng này trên mạng Public (WiFi công cộng)."
                    ),
                    "fix": None
                }

            return {
                "check": "Cổng Mạng Nguy Hiểm",
                "status": f"⚠️ Phát hiện {len(dangerous_found)} cổng hệ thống đang mở",
                "level": LEVEL_WARNING,
                "detail": (
                    "Các cổng sau đang mở (đây là dịch vụ cốt lõi Windows RPC / File Sharing):\n" +
                    "\n".join(f"  • {p}" for p in dangerous_found) +
                    "\n\nKhuyến nghị: Khóa các cổng này trên mạng Public (WiFi công cộng) bằng Tường Lửa để tránh bị quét hoặc tấn công qua mạng LAN."
                ),
                "fix": "block_dangerous_ports_public"
            }
        return {
            "check": "Cổng Mạng Nguy Hiểm",
            "status": "✅ Không phát hiện cổng nguy hiểm",
            "level": LEVEL_OK,
            "detail": "Không tìm thấy cổng nguy hiểm nào đang mở công khai.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 8. Thư mục chia sẻ mạng
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_shared_folders(cls) -> Dict[str, Any]:
        """Liệt kê các thư mục đang được chia sẻ qua mạng."""
        shares = []
        # Thử lấy danh sách share qua PowerShell Get-SmbShare (chỉ lấy các share người dùng tạo, bỏ qua Special/Admin shares)
        ps_res = cls._run_cmd('powershell -NoProfile -Command "Get-SmbShare | Where-Object { -not $_.Special } | Select-Object -Property Name,Path | ConvertTo-Json"')
        if ps_res.get("success") and ps_res.get("stdout"):
            try:
                import json
                data = json.loads(ps_res["stdout"])
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = item.get("Name", "")
                    path = item.get("Path", "")
                    if name and path:
                        shares.append(f"{name} ({path})")
            except Exception:
                pass
        else:
            # Fallback qua net share (chỉ phân tích các dòng có đường dẫn hợp lệ)
            result = cls._run_cmd("net share")
            lines = result.get("stdout", "").splitlines()
            system_shares = {"ipc$", "admin$", "c$", "d$", "e$", "f$", "print$"}
            for line in lines[3:]:
                line_str = line.strip()
                if not line_str:
                    continue
                # Bỏ qua các câu thông báo kết thúc lệnh của Windows
                if line_str.lower().startswith("the command") or line_str.lower().startswith("lệnh"):
                    continue
                parts = line_str.split()
                if len(parts) >= 2:
                    share_name = parts[0]
                    # Thư mục chia sẻ phải chứa ký tự đường dẫn ổ đĩa (: hoặc \)
                    has_path = any(":" in p or "\\" in p for p in parts[1:])
                    if has_path and share_name.lower() not in system_shares and share_name.lower() != "share":
                        shares.append(f"{share_name} ({parts[1]})")

        if shares:
            return {
                "check": "Thư Mục Chia Sẻ Mạng",
                "status": f"⚠️ Có {len(shares)} thư mục chia sẻ",
                "level": LEVEL_INFO,
                "detail": "Các thư mục đang được chia sẻ qua mạng nội bộ:\n" + "\n".join(f"  • {s}" for s in shares) + "\nHãy đảm bảo chỉ chia sẻ những gì thực sự cần thiết.",
                "fix": None
            }
        return {
            "check": "Thư Mục Chia Sẻ Mạng",
            "status": "✅ Không có thư mục chia sẻ",
            "level": LEVEL_OK,
            "detail": "Không tìm thấy thư mục chia sẻ mạng người dùng nào.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 9. Windows SmartScreen
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_smartscreen(cls) -> Dict[str, Any]:
        """Kiểm tra SmartScreen có bật để chặn file/website độc hại không."""
        val = cls._read_reg(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer",
            "SmartScreenEnabled", default="On"
        )
        if str(val).lower() in ("off", "0", ""):
            return {
                "check": "Windows SmartScreen",
                "status": "❌ Đang TẮT",
                "level": LEVEL_WARNING,
                "detail": "SmartScreen bị tắt. Tính năng kiểm tra uy tín file tải về và trang web sẽ không hoạt động.",
                "fix": "enable_smartscreen"
            }
        return {
            "check": "Windows SmartScreen",
            "status": "✅ Đang BẬT",
            "level": LEVEL_OK,
            "detail": f"Windows SmartScreen đang hoạt động (giá trị: {val}).",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 10. Autorun entries đáng ngờ trong Registry
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_suspicious_autoruns(cls) -> Dict[str, Any]:
        """Quét các khóa Registry autorun tìm chương trình khởi động đáng ngờ."""
        autorun_keys = [
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
        ]
        suspicious = []
        for hive, path in autorun_keys:
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as reg:
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(reg, i)
                            val_lower = value.lower()
                            name_lower = name.lower()
                            # Bỏ qua chính ứng dụng PCAutoCleaner
                            if "pcautocleaner" in name_lower or "pcauxautocleaner" in name_lower:
                                i += 1
                                continue
                            if "pc_cleaner_optimizer" in val_lower or "pcautocleaner" in val_lower:
                                i += 1
                                continue
                            for pattern in SUSPICIOUS_AUTORUN_PATTERNS:
                                if re.search(pattern, val_lower):
                                    suspicious.append(f"{name}: {value[:80]}...")
                                    break
                            i += 1
                        except OSError:
                            break
            except Exception:
                continue

        if suspicious:
            return {
                "check": "Autorun Đáng Ngờ",
                "status": f"⚠️ Phát hiện {len(suspicious)} mục đáng ngờ",
                "level": LEVEL_WARNING,
                "detail": "Các chương trình khởi động đáng ngờ trong Registry:\n" + "\n".join(f"  • {s}" for s in suspicious),
                "fix": None
            }
        return {
            "check": "Autorun Đáng Ngờ",
            "status": "✅ Không phát hiện autorun đáng ngờ",
            "level": LEVEL_OK,
            "detail": "Các mục khởi động tự động trong Registry an toàn và hợp lệ.",
            "fix": None
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 11. Phiên bản Windows (Windows Update status)
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def check_windows_version(cls) -> Dict[str, Any]:
        """Kiểm tra phiên bản Windows đang dùng."""
        try:
            import platform
            ver = platform.version()
            win_ver = platform.win32_ver()
            build = int(ver.split(".")[-1]) if ver.count(".") >= 2 else 0

            # Windows 10 EOL builds (trước 19041), Windows 11 < 22000
            is_old = False
            detail_str = f"Windows {win_ver[0]} Build {build}"

            if build < 19041 and build > 0:
                is_old = True

            if is_old:
                return {
                    "check": "Phiên Bản Windows",
                    "status": f"⚠️ Phiên bản cũ: {detail_str}",
                    "level": LEVEL_WARNING,
                    "detail": f"Build {build} đang dùng có thể đã hết vòng đời hỗ trợ bảo mật. Hãy cập nhật Windows.",
                    "fix": None
                }
            return {
                "check": "Phiên Bản Windows",
                "status": f"✅ {detail_str}",
                "level": LEVEL_OK,
                "detail": f"Windows phiên bản {detail_str} đang trong vòng đời hỗ trợ.",
                "fix": None
            }
        except Exception as e:
            return {
                "check": "Phiên Bản Windows",
                "status": "⚠️ Không xác định",
                "level": LEVEL_INFO,
                "detail": str(e),
                "fix": None
            }

    # ──────────────────────────────────────────────────────────────────────────
    # Auto-Fix Actions & UAC Elevation
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def is_admin() -> bool:
        """Kiểm tra xem tiến trình hiện tại có quyền Administrator không (dual check)."""
        try:
            import ctypes
            if ctypes.windll.shell32.IsUserAnAdmin() != 0:
                return True
        except Exception:
            pass
        try:
            r = subprocess.run("net session", shell=True, capture_output=True, timeout=2)
            return r.returncode == 0
        except Exception:
            return False

    @classmethod
    def _run_elevated_cmd(cls, cmd: str, timeout_sec: int = 30) -> Dict[str, Any]:
        """
        Thực thi lệnh với quyền Administrator.
        Nếu tiến trình đã có quyền Admin -> chạy trực tiếp.
        Nếu chưa có quyền Admin -> kích hoạt hộp thoại UAC của Windows (ShellExecuteExW runas) để xin quyền.
        """
        if cls.is_admin():
            logger.info(f"[SecurityScanner] Đang chạy với quyền Admin hiện tại: {cmd}")
            return cls._run_cmd(cmd, timeout=timeout_sec)

        # Thử chạy trực tiếp trước (nếu lệnh không bắt buộc quyền Admin cao nhất)
        direct_res = cls._run_cmd(cmd, timeout=timeout_sec)
        stdout_low = direct_res.get("stdout", "").lower()
        stderr_low = direct_res.get("stderr", "").lower()
        if direct_res.get("success") and "access is denied" not in stdout_low and "access is denied" not in stderr_low:
            return direct_res

        # Khi bị từ chối quyền (Access is denied), yêu cầu UAC Elevation qua ShellExecuteExW(runas)
        logger.info(f"[SecurityScanner] Kích hoạt hộp thoại UAC Elevation để thực thi lệnh sửa: {cmd}")
        import tempfile
        import ctypes
        from ctypes import wintypes

        bat_path = None
        try:
            # Ghi lệnh vào file .bat tạm thời để tránh lỗi trích xuất dấu ngoặc kép trên command line
            fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="pccleaner_uac_fix_")
            with os.fdopen(fd, "w", encoding="cp1252", errors="replace") as f:
                f.write("@echo off\r\n")
                f.write(f"{cmd}\r\n")
                f.write("exit /b %ERRORLEVEL%\r\n")

            SEE_MASK_NOCLOSEPROCESS = 0x00000040

            class SHELLEXECUTEINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", wintypes.ULONG),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", wintypes.LPVOID),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE)
                ]

            sei = SHELLEXECUTEINFO()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
            sei.fMask = SEE_MASK_NOCLOSEPROCESS
            sei.hwnd = None
            sei.lpVerb = "runas"
            sei.lpFile = "cmd.exe"
            sei.lpParameters = f'/c "{bat_path}"'
            sei.lpDirectory = None
            sei.nShow = 0  # SW_HIDE

            ret = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
            if not ret:
                err = ctypes.GetLastError()
                if err == 1223:  # ERROR_CANCELLED: Người dùng bấm "No" hoặc đóng hộp thoại UAC
                    return {
                        "returncode": 1223,
                        "stdout": "",
                        "stderr": "Bạn đã từ chối cấp quyền Administrator (hộp thoại UAC). Thao tác sửa đã bị hủy.",
                        "success": False
                    }
                return {
                    "returncode": err,
                    "stdout": "",
                    "stderr": f"Lỗi gọi quyền Administrator (Mã lỗi: {err}).",
                    "success": False
                }

            # Chờ tiến trình chạy xong và lấy mã thoát
            h_proc = sei.hProcess
            if h_proc:
                wait_ms = timeout_sec * 1000
                ctypes.windll.kernel32.WaitForSingleObject(h_proc, wait_ms)
                exit_code = wintypes.DWORD()
                ctypes.windll.kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code))
                ctypes.windll.kernel32.CloseHandle(h_proc)

                code = exit_code.value
                if code == 0:
                    return {
                        "returncode": 0,
                        "stdout": "Executed successfully with Administrator privileges.",
                        "stderr": "",
                        "success": True
                    }
                else:
                    return {
                        "returncode": code,
                        "stdout": "",
                        "stderr": f"Thoát với mã lỗi {code}.",
                        "success": False
                    }

            return {"returncode": 0, "stdout": "", "stderr": "", "success": True}

        except Exception as e:
            logger.error(f"[SecurityScanner] Lỗi thực thi elevated cmd: {e}")
            return {"returncode": -1, "stdout": "", "stderr": str(e), "success": False}
        finally:
            if bat_path and os.path.exists(bat_path):
                try:
                    os.remove(bat_path)
                except Exception:
                    pass

    @classmethod
    def apply_fix(cls, fix_key: str) -> Dict[str, Any]:
        """
        Tự động sửa một vấn đề bảo mật cụ thể.
        Tự động yêu cầu quyền Administrator qua UAC nếu cần thiết.
        """
        fixes = {
            "enable_firewall": (
                "netsh advfirewall set allprofiles state on",
                "Đã bật Windows Firewall cho tất cả profiles."
            ),
            "enable_uac": (
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" /v EnableLUA /t REG_DWORD /d 1 /f',
                "Đã bật UAC. Cần khởi động lại máy tính để có hiệu lực."
            ),
            "set_uac_recommended": (
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System" /v ConsentPromptBehaviorAdmin /t REG_DWORD /d 5 /f',
                "Đã đặt UAC về mức khuyến nghị."
            ),
            "disable_rdp": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Terminal Server" /v fDenyTSConnections /t REG_DWORD /d 1 /f',
                "Đã tắt Remote Desktop Protocol."
            ),
            "disable_autologon": (
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon" /v AutoAdminLogon /t REG_SZ /d 0 /f',
                "Đã tắt AutoLogon. Hệ thống sẽ yêu cầu mật khẩu khi khởi động."
            ),
            "enable_smartscreen": (
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer" /v SmartScreenEnabled /t REG_SZ /d On /f',
                "Đã bật Windows SmartScreen."
            ),
            "disable_guest": (
                "net user Guest /active:no",
                "Đã tắt tài khoản Guest."
            ),
            "enable_realtime_protection": (
                'powershell -NoProfile -Command "Set-MpPreference -DisableRealtimeMonitoring $false"',
                "Đã bật bảo vệ thời gian thực của Windows Defender."
            ),
            "block_dangerous_ports_public": (
                'netsh advfirewall firewall delete rule name="PCAutoCleaner_Block_SMB_RPC_Public" & netsh advfirewall firewall add rule name="PCAutoCleaner_Block_SMB_RPC_Public" dir=in action=block protocol=TCP localport=135,137,138,139,445 profile=public',
                "Đã tạo quy tắc Windows Firewall khóa toàn bộ cổng 135, 137, 138, 139, 445 trên mạng WiFi công cộng (Public Network)."
            ),
        }

        if fix_key not in fixes:
            return {"success": False, "message": f"Không tìm thấy fix cho: {fix_key}"}

        cmd, success_msg = fixes[fix_key]
        logger.info(f"[SecurityScanner] Áp dụng fix: {fix_key}")
        result = cls._run_elevated_cmd(cmd, timeout_sec=25)

        if result.get("success") or result.get("returncode") == 0:
            logger.info(f"[SecurityScanner] Fix thành công: {fix_key}")
            return {"success": True, "message": success_msg}
        else:
            err = result.get("stderr") or result.get("stdout") or "Lỗi không xác định"
            logger.warning(f"[SecurityScanner] Fix thất bại ({fix_key}): {err}")
            return {"success": False, "message": f"Thất bại: {err[:200]}"}

    # ──────────────────────────────────────────────────────────────────────────
    # Full Scan
    # ──────────────────────────────────────────────────────────────────────────
    @classmethod
    def run_full_scan(cls, progress_callback=None) -> Dict[str, Any]:
        """
        Thực hiện toàn bộ quy trình rà soát bảo mật và tổng hợp kết quả.
        Hỗ trợ progress_callback(event_type: str, data: dict) để UI thể hiện hệ thống đang làm gì thời gian thực.
        """
        logger.info("[SecurityScanner] Bắt đầu rà soát bảo mật toàn diện...")
        t0 = time.time()

        checks = [
            ("Windows Firewall", cls.check_firewall),
            ("Antivirus & Defender", cls.check_antivirus),
            ("User Account Control (UAC)", cls.check_uac),
            ("Remote Desktop (RDP)", cls.check_rdp),
            ("Tự động đăng nhập (AutoLogon)", cls.check_autologon),
            ("Tài khoản Guest", cls.check_guest_account),
            ("Cổng mạng đang mở (Open Ports)", cls.check_open_ports),
            ("Thư mục chia sẻ mạng (Network Shares)", cls.check_shared_folders),
            ("Windows SmartScreen", cls.check_smartscreen),
            ("Chương trình Autorun đáng ngờ", cls.check_suspicious_autoruns),
            ("Phiên bản hệ điều hành Windows", cls.check_windows_version),
        ]

        total = len(checks)
        results = []
        critical_count = 0
        warning_count  = 0

        for idx, (check_name, check_fn) in enumerate(checks, 1):
            if progress_callback:
                try:
                    progress_callback("start_check", {
                        "step": idx,
                        "total": total,
                        "name": check_name,
                        "percent": int((idx - 1) / total * 100)
                    })
                except Exception:
                    pass

            try:
                r = check_fn()
                results.append(r)
                if r["level"] == LEVEL_CRITICAL:
                    critical_count += 1
                elif r["level"] == LEVEL_WARNING:
                    warning_count += 1
            except Exception as e:
                logger.error(f"[SecurityScanner] Lỗi khi chạy {check_fn.__name__}: {e}")
                r = {
                    "check": check_name,
                    "status": f"❌ Lỗi: {e}",
                    "level": LEVEL_WARNING,
                    "detail": str(e),
                    "fix": None
                }
                results.append(r)

            if progress_callback:
                try:
                    progress_callback("check_done", {
                        "step": idx,
                        "total": total,
                        "name": check_name,
                        "percent": int(idx / total * 100),
                        "result": r
                    })
                except Exception:
                    pass

        duration_s = round(time.time() - t0, 1)

        if critical_count > 0:
            overall = "CRITICAL"
            overall_icon = "🔴"
        elif warning_count > 0:
            overall = "WARNING"
            overall_icon = "🟡"
        else:
            overall = "SAFE"
            overall_icon = "🟢"

        summary = {
            "overall": overall,
            "overall_icon": overall_icon,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "ok_count": len(results) - critical_count - warning_count,
            "total_checks": len(results),
            "duration_s": duration_s,
            "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "results": results
        }

        logger.info(
            f"[SecurityScanner] Hoàn tất: {overall} — "
            f"{critical_count} CRITICAL, {warning_count} WARNING, "
            f"{summary['ok_count']} OK — ({duration_s}s)"
        )
        return summary
