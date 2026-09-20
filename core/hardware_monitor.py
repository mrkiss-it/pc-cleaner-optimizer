import os
import sys
import time
import winreg
import tempfile
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
import psutil

class HardwareMonitor:
    """
    Engine chuyên sâu giám sát cảm biến phần cứng & sức khỏe Pin laptop (Battery Health).
    - Đo độ chai pin (Wear Level), chu kỳ sạc (Cycle Count), dung lượng thiết kế (Design Capacity).
    - Xuất báo cáo pin HTML chuẩn Windows Powercfg.
    - Giám sát CPU đa nhân (Per-core load), xung nhịp, tên vi xử lý.
    - Nhận diện card đồ họa GPU (Intel, NVIDIA, AMD), VRAM và Driver version.
    - Ủy quyền giám sát nhiệt laptop (thermal_monitor) — không bịa số khi Windows trống cảm biến.
    """
    _battery_cache = {}
    _battery_cache_time = 0.0
    _gpu_cache = []
    _gpu_cache_time = 0.0
    _cpu_name_cached = None

    @classmethod
    def get_cpu_name(cls) -> str:
        """Lấy tên thương mại chuẩn xác của CPU từ Windows Registry."""
        if cls._cpu_name_cached:
            return cls._cpu_name_cached
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            cls._cpu_name_cached = val.strip()
            return cls._cpu_name_cached
        except Exception:
            import platform
            cls._cpu_name_cached = platform.processor() or "Bộ vi xử lý Windows"
            return cls._cpu_name_cached

    @classmethod
    def get_cpu_details(cls) -> Dict[str, Any]:
        """
        Lấy thông tin chi tiết vi xử lý CPU: Tên, số nhân/luồng, xung nhịp, mức tải từng nhân.
        """
        name = cls.get_cpu_name()
        physical = psutil.cpu_count(logical=False) or 1
        logical = psutil.cpu_count(logical=True) or physical

        # Freq
        freq_info = psutil.cpu_freq()
        current_mhz = round(freq_info.current, 0) if freq_info else 0.0
        max_mhz = round(freq_info.max, 0) if freq_info and freq_info.max > 0 else current_mhz

        # Load
        overall_pct = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(percpu=True, interval=None)
        if not per_core:
            per_core = [overall_pct] * logical

        return {
            "name": name,
            "physical_cores": physical,
            "logical_cores": logical,
            "current_freq_ghz": round(current_mhz / 1000, 2) if current_mhz else 0.0,
            "max_freq_ghz": round(max_mhz / 1000, 2) if max_mhz else 0.0,
            "overall_percent": overall_pct,
            "per_core_percent": per_core,
            "core_summary": f"{physical} Nhân (Cores) / {logical} Luồng (Threads)"
        }

    @classmethod
    def get_battery_info(cls, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Lấy thông tin sức khỏe pin laptop chi tiết.
        Tự động nhận diện thiết bị Desktop (không có pin) hoặc Laptop.
        """
        b_psutil = psutil.sensors_battery()
        if b_psutil is None:
            return {
                "has_battery": False,
                "percent": 100,
                "power_plugged": True,
                "is_charging": False,
                "status_text": "Máy tính để bàn (Nguồn điện AC trực tiếp)",
                "design_capacity_mwh": 0,
                "full_charge_capacity_mwh": 0,
                "cycle_count": 0,
                "wear_level_percent": 0.0,
                "health_percent": 100.0,
                "health_status": "Không có pin (Desktop PC)",
                "battery_name": "N/A",
                "manufacturer": "N/A",
                "chemistry": "N/A",
                "system_product_name": "Máy tính để bàn (Desktop PC)",
                "system_manufacturer": "Standard PC",
                "secs_left_str": "Nguồn AC liên tục",
                "advice": "Thiết bị đang sử dụng nguồn điện trực tiếp AC. Không cần quản lý chu kỳ sạc pin."
            }

        now = time.time()
        # Cache battery XML report for 60s to avoid repeated powercfg calls
        if not force_refresh and cls._battery_cache and (now - cls._battery_cache_time < 60.0):
            result = dict(cls._battery_cache)
            # Update live psutil stats
            result["percent"] = b_psutil.percent
            result["power_plugged"] = b_psutil.power_plugged
            result["is_charging"] = b_psutil.power_plugged and (b_psutil.percent < 100)
            return result

        # Extract deep battery telemetry via powercfg XML
        design_cap = 0
        full_cap = 0
        cycle_count = 0
        bat_name = "Pin Laptop tiêu chuẩn"
        manufacturer = "OEM"
        chemistry = "LIon"
        system_model = "Laptop Windows"
        system_vendor = "OEM"

        temp_xml = os.path.join(tempfile.gettempdir(), f"bat_rep_{os.getpid()}.xml")
        try:
            subprocess.run(
                ["powercfg", "/batteryreport", "/xml", "/output", temp_xml],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                timeout=10
            )
            if os.path.exists(temp_xml):
                tree = ET.parse(temp_xml)
                root = tree.getroot()
                ns = {"b": "http://schemas.microsoft.com/battery/2012"}

                # System info
                sys_elem = root.find(".//b:SystemInformation", ns)
                if sys_elem is not None:
                    prod = sys_elem.find("b:SystemProductName", ns)
                    if prod is not None and prod.text:
                        system_model = prod.text.strip()
                    mfg = sys_elem.find("b:SystemManufacturer", ns)
                    if mfg is not None and mfg.text:
                        system_vendor = mfg.text.strip()

                # Batteries info
                bat_elem = root.find(".//b:Batteries", ns)
                if bat_elem is not None:
                    # Find first battery with valid capacities
                    for b_entry in bat_elem.findall("b:Battery", ns):
                        d_elem = b_entry.find("b:DesignCapacity", ns)
                        f_elem = b_entry.find("b:FullChargeCapacity", ns)
                        c_elem = b_entry.find("b:CycleCount", ns)
                        id_elem = b_entry.find("b:Id", ns)
                        m_elem = b_entry.find("b:Manufacturer", ns)
                        ch_elem = b_entry.find("b:Chemistry", ns)

                        if d_elem is not None and d_elem.text and d_elem.text.strip().isdigit():
                            d_val = int(d_elem.text.strip())
                            if d_val > 0:
                                design_cap = d_val
                        if f_elem is not None and f_elem.text and f_elem.text.strip().isdigit():
                            f_val = int(f_elem.text.strip())
                            if f_val > 0:
                                full_cap = f_val
                        if c_elem is not None and c_elem.text and c_elem.text.strip().isdigit():
                            cycle_count = int(c_elem.text.strip())
                        if id_elem is not None and id_elem.text:
                            bat_name = id_elem.text.strip()
                        if m_elem is not None and m_elem.text:
                            manufacturer = m_elem.text.strip()
                        if ch_elem is not None and ch_elem.text:
                            chemistry = ch_elem.text.strip()
                        
                        if design_cap > 0:
                            break

                try:
                    os.remove(temp_xml)
                except Exception:
                    pass
        except Exception:
            pass

        # Fallback if XML failed
        if design_cap == 0 and full_cap == 0:
            # Approximate from standard values
            design_cap = 50000
            full_cap = 50000

        # Calculations
        if design_cap > 0 and full_cap > 0:
            wear_level = round(max(0.0, (1.0 - (full_cap / design_cap)) * 100), 1)
            health_pct = round(max(0.0, min(100.0, 100.0 - wear_level)), 1)
        else:
            wear_level = 0.0
            health_pct = 100.0

        # Health assessment
        if health_pct >= 90.0:
            health_status = "Xuất Sắc (Pin Rất Tốt)"
            health_color = "#10b981"
        elif health_pct >= 80.0:
            health_status = "Tốt (Hoạt Động Ổn Định)"
            health_color = "#34d399"
        elif health_pct >= 70.0:
            health_status = "Khá (Hao Mòn Bình Thường)"
            health_color = "#f59e0b"
        elif health_pct >= 55.0:
            health_status = "Trung Bình (Đã Chai Đáng Kể)"
            health_color = "#fb923c"
        else:
            health_status = "Kém (Khuyến Nghị Bảo Dưỡng)"
            health_color = "#ef4444"

        # Time remaining
        if b_psutil.power_plugged:
            secs_str = "Đang cắm nguồn sạc AC" if b_psutil.percent < 100 else "Đã sạc đầy (Nguồn AC)"
        else:
            secs = b_psutil.secsleft
            if secs is not None and secs > 0:
                hrs = secs // 3600
                mins = (secs % 3600) // 60
                secs_str = f"Còn lại khoảng {hrs} giờ {mins} phút"
            else:
                secs_str = "Đang ước tính thời lượng..."

        # Smart advice
        advice_list = []
        if wear_level > 20.0:
            advice_list.append("Pin đã chai hơn 20%. Bạn có thể bật tính năng giới hạn sạc 80% (Battery Care / Conservation Mode) để kéo dài tuổi thọ cell pin.")
        if cycle_count > 500:
            advice_list.append(f"Pin đã trải qua {cycle_count} chu kỳ sạc xả. Tránh dùng cạn kiệt về 0% thường xuyên.")
        if b_psutil.power_plugged and b_psutil.percent == 100:
            advice_list.append("Máy đang cắm nguồn AC 100%. Nếu thường xuyên cắm sạc cố định, hãy dùng chế độ giới hạn sạc để bảo vệ pin.")
        if not advice_list:
            advice_list.append("Tình trạng pin đang rất hoàn hảo. Duy trì cắm sạc khi làm việc nặng và không để máy quá nhiệt.")

        res = {
            "has_battery": True,
            "percent": b_psutil.percent,
            "power_plugged": b_psutil.power_plugged,
            "is_charging": b_psutil.power_plugged and (b_psutil.percent < 100),
            "status_text": "Đang cắm sạc" if b_psutil.power_plugged else "Đang dùng pin",
            "design_capacity_mwh": design_cap,
            "full_charge_capacity_mwh": full_cap,
            "cycle_count": cycle_count,
            "wear_level_percent": wear_level,
            "health_percent": health_pct,
            "health_status": health_status,
            "health_color": health_color,
            "battery_name": bat_name,
            "manufacturer": manufacturer,
            "chemistry": chemistry,
            "system_product_name": system_model,
            "system_manufacturer": system_vendor,
            "secs_left_str": secs_str,
            "advice": " ".join(advice_list)
        }

        cls._battery_cache = res
        cls._battery_cache_time = now
        return res

    @classmethod
    def export_battery_report_html(cls, target_path: Optional[str] = None) -> Optional[str]:
        """
        Tạo tệp HTML báo cáo sức khỏe và lịch sử chu kỳ pin chính thức của Microsoft Windows.
        Mở trực tiếp trên trình duyệt mặc định của hệ điều hành.
        """
        if not target_path:
            target_path = os.path.join(tempfile.gettempdir(), "Battery_Health_Report.html")
        
        try:
            subprocess.run(
                ["powercfg", "/batteryreport", "/output", target_path],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                timeout=12
            )
            if os.path.exists(target_path):
                os.startfile(target_path)
                return target_path
        except Exception:
            pass
        return None

    @classmethod
    def get_gpu_details(cls, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Lấy thông tin danh sách card màn hình GPU (Intel, NVIDIA, AMD).
        Bao gồm tên card, dung lượng VRAM, phiên bản Driver điều khiển.
        """
        now = time.time()
        if not force_refresh and cls._gpu_cache and (now - cls._gpu_cache_time < 120.0):
            return cls._gpu_cache

        gpus = []
        try:
            # Query WMI via PowerShell CIM
            cmd = (
                'Get-CimInstance Win32_VideoController | '
                'Select-Object Name, DriverVersion, AdapterRAM, VideoProcessor | '
                'ConvertTo-Json'
            )
            p = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                timeout=6
            )
            if p.returncode == 0 and p.stdout.strip():
                import json
                data = json.loads(p.stdout.strip())
                if isinstance(data, dict):
                    raw_list = [data]
                elif isinstance(data, list):
                    raw_list = data
                else:
                    raw_list = []

                for item in raw_list:
                    name = item.get("Name") or "Đồ họa tích hợp"
                    driver = item.get("DriverVersion") or "Mặc định Windows"
                    ram_bytes = item.get("AdapterRAM") or 0
                    if isinstance(ram_bytes, (int, float)) and ram_bytes > 0:
                        vram_gb = round(ram_bytes / (1024 ** 3), 1)
                        if vram_gb >= 1.0:
                            vram_str = f"{vram_gb} GB VRAM"
                        else:
                            vram_str = f"{int(ram_bytes / (1024 ** 2))} MB VRAM"
                    else:
                        vram_str = "Bộ nhớ chia sẻ hệ thống (Shared RAM)"

                    # Detect brand
                    lower_name = name.lower()
                    if "nvidia" in lower_name:
                        brand = "NVIDIA"
                        brand_color = "#76b900"
                    elif "amd" in lower_name or "radeon" in lower_name:
                        brand = "AMD Radeon"
                        brand_color = "#ed1c24"
                    elif "intel" in lower_name:
                        brand = "Intel Iris / UHD"
                        brand_color = "#0071c5"
                    else:
                        brand = "Hiển thị đồ họa"
                        brand_color = "#38bdf8"

                    gpus.append({
                        "name": name,
                        "brand": brand,
                        "brand_color": brand_color,
                        "driver_version": driver,
                        "vram": vram_str,
                        "status": "Đang hoạt động ổn định"
                    })
        except Exception:
            pass

        if not gpus:
            # Fallback
            gpus.append({
                "name": "Bộ điều hợp đồ họa tiêu chuẩn",
                "brand": "GPU",
                "brand_color": "#38bdf8",
                "driver_version": "Chuẩn WDDM",
                "vram": "Bộ nhớ chia sẻ hệ thống",
                "status": "Đang hoạt động"
            })

        cls._gpu_cache = gpus
        cls._gpu_cache_time = now
        return gpus

    @classmethod
    def get_thermal_snapshot(cls, force_refresh: bool = False, warn_celsius: float = 90.0) -> Dict[str, Any]:
        """Nhiệt CPU/GPU khi cảm biến đọc được; empty-state nếu Windows không lộ sensor."""
        from core.thermal_monitor import collect_thermal_snapshot
        return collect_thermal_snapshot(force_refresh=force_refresh, warn_celsius=warn_celsius)
