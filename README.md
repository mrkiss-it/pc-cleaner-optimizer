# ⚡ PC Auto Cleaner & System Optimizer Pro (v3.2)

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PyQt5 Modern GUI](https://img.shields.io/badge/UI-PyQt5%20Fluent%20Dark-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://pypi.org/project/PyQt5/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20x64-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com)
[![Tests Passing](https://img.shields.io/badge/Tests-20%2F20%20Passed%20(100%25)-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](https://github.com)
[![License Proprietary](https://img.shields.io/badge/License-Proprietary%20%7C%20All%20Rights%20Reserved-red?style=for-the-badge)](LICENSE)

**Phần mềm toàn diện tối ưu hóa Windows, tự động dọn dẹp rác, giải phóng RAM, tăng tốc Gaming, đo tốc độ DNS song song, kiểm tra sức khỏe ổ cứng SSD S.M.A.R.T, đo độ chai pin laptop (Battery Health & Cycles), xuất báo cáo pin HTML Windows, giám sát CPU đa nhân thời gian thực, nhận diện GPU, dọn dẹp an toàn Registry, quét bảo mật hệ thống và bảo vệ quyền riêng tư (Windows Tweaks & Privacy Shield).**


---

## 🌟 Tính Năng Toàn Diện (Feature Showcase)

### 1. 🧹 Safe Deep Junk Cleaner (Dọn Rác Chuyên Sâu & An Toàn)
- **File tạm hệ thống & người dùng**: Tự động dọn dẹp `%TEMP%`, `C:\Windows\Temp`.
- **Thùng rác**: Dọn sạch Recycle Bin bằng Windows Native API `SHEmptyRecycleBinW`.
- **Bộ nhớ đệm Trình duyệt**: Hỗ trợ Google Chrome, Microsoft Edge, Brave, Mozilla Firefox (quét tất cả các Profiles).
- **Windows Update Cache**: Làm sạch các gói tải về tồn đọng trong `C:\Windows\SoftwareDistribution\Download`.
- **Bộ nhớ đệm Ứng dụng**: 
  - **Zalo**: Chỉ dọn cache ảnh/video tạm thời, bảo vệ **100%** cơ sở dữ liệu `Database` và thư mục tải về `ZaloDownloads`.
  - **VS Code, Discord, Telegram, Pip cache, Npm cache**.
- **Crash Dumps**: Dọn sạch các tệp kết xuất lỗi `*.dmp`, Windows Error Reporting (WER).

---

### 2. ⚡ RAM Optimizer & Memory Leak Detector (Tối Ưu RAM)
- **Win32 Memory Compaction**: Sử dụng Win32 API `EmptyWorkingSet` thu hồi RAM từ các tiến trình nhàn rỗi.
- **Tự động theo ngưỡng (Auto-threshold)**: Tự động kích hoạt giải phóng bộ nhớ khi dung lượng RAM vượt ngưỡng thiết lập (mặc định 80%).
- **Phát hiện rò rỉ bộ nhớ (Memory Leak Detector)**: Theo dõi tiến trình có dung lượng bộ nhớ tăng liên tục bất thường và cảnh báo người dùng.

---

### 3. 🚀 1-Click Game Booster (Tăng Tốc Gaming)
- **Dồn 100% tài nguyên cho Game**: Quét sâu và thu hồi RAM từ tất cả ứng dụng nền đang chờ.
- **Hạ mức ưu tiên dịch vụ ngốn CPU (Demote Priority)**: Tự động đưa Windows Search Indexer, Telemetry, Windows Update xuống `IDLE_PRIORITY_CLASS`.
- **Đẩy tiến trình Game lên đỉnh**: Tự động nhận diện trò chơi đang chạy và gán `HIGH_PRIORITY_CLASS`.
- **Khôi phục nguyên vẹn khi tắt**: Trả mọi tiến trình về trạng thái bình thường khi người dùng tắt Game Boost.

---

### 4. 🌐 Network Optimizer & Parallel DNS Benchmark (Tối Ưu Mạng & DNS)
- **Đo tốc độ DNS song song (Parallel Benchmark)**: Kiểm tra đồng thời độ trễ (latency ms) của các DNS hàng đầu thế giới:
  - 🚀 Cloudflare DNS (`1.1.1.1`)
  - 🔍 Google Public DNS (`8.8.8.8`)
  - 🛡️ NextDNS & AdGuard DNS (chặn quảng cáo & mã độc)
  - 🔒 Quad9 DNS (`9.9.9.9` - bảo mật cao cấp)
  - ⚡ OpenDNS
- **1-Click Apply DNS**: Áp dụng DNS nhanh nhất trực tiếp vào Network Adapter đang hoạt động mà không cần vào Control Panel.
- **Khôi phục DHCP mặc định**: 1-click đưa DNS về tự động nhận từ Router.
- **Tối ưu hóa TCP/IP Stack**: Tinh chỉnh Windows TCP Window Auto-Tuning, Congestion Provider (CTCP), Chimney Offload, xóa cache DNS Resolver (`ipconfig /flushdns`) và Reset Winsock catalog.

---

### 5. 💽 S.M.A.R.T Disk Health & SSD TRIM Optimizer (Sức Khỏe Ổ Đĩa)
- **Giám sát S.M.A.R.T thời gian thực**:
  - Tự động nhận diện loại ổ đĩa: NVMe SSD, SATA SSD, HDD.
  - Đọc nhiệt độ hoạt động (°C), trạng thái hỏng hóc dự đoán (Predict Failure Status).
  - Tỉ lệ hao mòn (Wear Percentage / Remaining Life).
- **Tối ưu hóa SSD TRIM**: Thực thi lệnh TRIM (`defrag /O`) giúp phục hồi tốc độ ghi ngẫu nhiên cho ổ SSD.
- **Chẩn đoán bad sector**: Kiểm tra mã lỗi đọc/ghi và cảnh báo sớm nguy cơ mất dữ liệu.

---

### 6. 🛡️ Safe Registry Cleaner with 1-Click Rollback (Dọn Registry An Toàn)
- **Quét các khóa hỏng vô hại**:
  - Khóa gỡ cài đặt phần mềm không tồn tại (Uninstaller invalid paths).
  - Khóa MUI Cache mồ côi (Orphaned MUI Entries).
  - Tệp thư viện chia sẻ thiếu (Missing Shared DLLs).
  - Các mục khởi động chết (Dead Startup items).
- **Sao lưu tự động tuyệt đối (.REG Backup)**: Tự động xuất file backup định dạng `.reg` có dấu thời gian trước khi thực hiện dọn dẹp.
- **1-Click Rollback**: Hộp thoại khôi phục trực quan, cho phép hoàn tác bất kỳ phiên dọn Registry nào chỉ với một click.

---

### 7. 🔒 System Security & Vulnerability Scanner (Quét Lỗ Hổng Bảo Mật)
- **Kiểm tra trạng thái bảo mật cốt lõi**:
  - Trạng thái kiểm soát tài khoản người dùng (**UAC** - User Account Control).
  - Trạng thái thời gian thực của **Windows Defender Antivirus**.
  - Tường lửa **Windows Firewall** trên cả 3 profile (Domain, Private, Public).
- **Quét các cổng mạng rủi ro cao (High-risk Ports)**:
  - Port `135` (RPC Endpoint Mapper)
  - Port `445` (SMB Direct / WannaCry vector)
  - Port `137`, `138`, `139` (NetBIOS legacy)
- **Phát hiện SMBv1**: Cảnh báo giao thức SMBv1 lỗi thời dễ bị tấn công khai thác.
- **1-Click Quick Remediation**: Hỗ trợ khắc phục nhanh các rủi ro phát hiện được.

---

### 8. 📁 Large File Scanner & Interactive Disk Analyzer (Phân Tích Dung Lượng)
- **Tìm kiếm tệp lớn siêu tốc**: Quét tệp >100MB (hoặc tùy biến) trên toàn bộ ổ đĩa.
- **Phân loại thông minh**: Video, Bộ cài đặt (Installer/ISO), Tệp nén (Zip/Rar/7z), Ổ đĩa ảo (VM/VHDX).
- **Xóa an toàn vào Thùng rác (Recycle Bin)**: Dùng Win32 API `SHFileOperationW` cho phép phục hồi tệp khi cần, tuyệt đối không xóa cứng gây mất mát ngoài ý muốn.
- **Interactive Disk Visualizer**: Biểu đồ phân bổ dung lượng trực quan theo thư mục.

---

### 9. 🎯 Desktop Floating Widget & Smart Privileges
- **Desktop HUD Widget**:
  - Hiển thị mức sử dụng RAM & CPU phong cách Cyberpunk/Modern Fluent.
  - Kéo thả tự do trên màn hình, tự ghi nhớ vị trí, thanh trượt chỉnh độ trong suốt (Opacity).
  - Chạm 1-click để dồn RAM tức thì với hiệu ứng trực quan.
- **Quyền hạn thông minh (`asInvoker`)**:
  - Khởi chạy bình thường không cần quyền Administrator (không hiện cảnh báo UAC phiền toái).
  - Khi người dùng chạy với Administrator: Các tác vụ cấp cao (TRIM, Registry, DNS, Tweaks) thực thi trực tiếp 100% không hỏi lại.
  - Khi chạy quyền thường: Hướng dẫn thân thiện và chỉ yêu cầu quyền khi thao tác tính năng đặc quyền.

---

### 10. 🛡️ Windows Tweaks & Privacy Shield (15 Tinh Chỉnh Hệ Thống & Quyền Riêng Tư)
- **Quyền Riêng Tư & Chống Theo Dõi (Privacy Shield)**:
  - 🛑 Chặn thu thập dữ liệu chẩn đoán ngầm (Telemetry) gửi về Microsoft.
  - 🚫 Vô hiệu hóa dịch vụ ngốn CPU `DiagTrack` (Connected User Experiences and Telemetry).
  - 🔍 Tắt tìm kiếm Bing trên Start Menu (tăng tốc tìm kiếm app cục bộ gấp 3 lần và bảo mật gõ phím).
  - 🚫 Chặn Advertising ID & theo dõi vị trí nền (Location Tracking).
  - 📢 Tắt quảng cáo ứng dụng được tài trợ (Promoted Apps) và khảo sát định kỳ (Feedback Prompts).
  - ⏳ Tắt lịch sử hoạt động đồng bộ Timeline (Activity History).
- **Tăng Tốc Hiệu Năng & Nguồn Điện (Performance Tweaks)**:
  - ⚡ Kích hoạt chế độ nguồn cực đại ẩn **Ultimate Performance** của Windows 10/11.
  - 🚀 Giảm độ trễ mở Menu chuột phải từ 400ms xuống **50ms** (`MenuShowDelay`), phản hồi tức thì.
  - 💾 Tùy chọn tắt chế độ ngủ đông (`powercfg -h off`) giải phóng **8GB - 32GB** tệp `hiberfil.sys` trên ổ C:.
  - 🎮 Tắt ghi hình nền Game DVR của Xbox Game Bar giúp tăng FPS và giảm giật khung hình.
- **Giao Diện & Explorer (UI & Windows 11 Tweaks)**:
  - 🖱️ Khôi phục **Menu chuột phải cổ điển đầy đủ trên Windows 11** (không còn bị ẩn sau "Show more options").
  - 📄 Luôn hiển thị đuôi tệp tin (`.exe`, `.pdf`, `.bat`...) phòng chống tệp độc hại mạo danh.
  - 💻 Mở File Explorer trực tiếp vào **This PC** thay vì trang Quick Access.
  - 🚀 Nút 1-click **Khởi động lại Windows Explorer** để áp dụng thay đổi giao diện ngay lập tức.
- **An toàn tuyệt đối**: Hỗ trợ nút **Tối ưu khuyên dùng 1-Click** và **Khôi phục mặc định Windows 100%**.

---

### 11. 🔋 Laptop Battery Health & Deep Hardware Sensors (Sức Khỏe Pin & Phần Cứng)
- **Đo lường độ chai pin chuẩn xác 100%**:
  - Trích xuất dữ liệu Telemetry chính thức của Microsoft Windows (`powercfg /batteryreport`).
  - Dung lượng thiết kế chuẩn từ nhà máy (**Design Capacity** mWh).
  - Dung lượng tích điện sạc đầy tối đa hiện tại (**Full Charge Capacity** mWh).
  - Số chu kỳ sạc/xả tích lũy (**Cycle Count**).
  - Tỉ lệ chai pin thực tế (**Wear Level %**) và điểm sức khỏe tổng thể (**Health %**).
  - Đánh giá tình trạng cell pin và đưa ra **lời khuyên bảo dưỡng thông minh** (bật giới hạn sạc 80% trên Asus/Dell/Lenovo, tránh dùng cạn 0%).
- **Xuất Báo Cáo Pin Windows Chuẩn 1-Click**:
  - Tự động tạo tệp báo cáo chuyên sâu `Battery_Health_Report.html` và mở trực tiếp trên trình duyệt web với đồ thị sạc xả đầy đủ của Windows.
- **Tự động nhận diện thiết bị thông minh**:
  - Nhận diện chính xác máy tính để bàn (Desktop PC) dùng nguồn AC trực tiếp và hiển thị thẻ trạng thái nguồn thích hợp.
- **Giám Sát CPU Đa Nhân (Multi-Core Visualizer)**:
  - Nhận diện tên vi xử lý thương mại từ Windows Registry (ví dụ: `12th Gen Intel Core i5-12500H`, 12 nhân 16 luồng).
  - Bảng trực quan mức tải thời gian thực trên từng luồng (Core 0 -> Core 15) với dải màu linh hoạt (xanh lục, cam, đỏ) và xung nhịp hiện tại / Max GHz.
- **Nhận Diện Card Đồ Họa (GPU)**:
  - Quét qua WMI/CIM hiển thị tên GPU (Intel Iris Xe, NVIDIA GeForce, AMD Radeon), phiên bản Driver và dung lượng bộ nhớ VRAM.

---

## 🏗️ Cấu Trúc Mã Nguồn (Architecture)


```text
pc_cleaner_optimizer/
│
├── LICENSE                     # Giấy phép độc quyền (All Rights Reserved) — không MIT
├── main.py                     # Entry point, IPC Single-Instance, CLI & UI switcher
├── config_manager.py           # Quản lý cấu hình JSON, whitelist, EULA (AppData) & thiết lập tự động
├── startup_manager.py          # Quản lý khởi động cùng Windows (Registry Run Key)
├── build_exe.py                # Pipeline đóng gói PyInstaller độc lập (asInvoker mode)
├── build_exe.bat               # Batch script đóng gói nhanh 1-click
├── create_shortcut.ps1         # PowerShell script tạo shortcut Desktop với icon đẹp mắt
├── start_cleaner.bat           # Script khởi chạy nhanh bằng Python
├── start_silent.vbs            # Script chạy ngầm im lặng vào khay hệ thống (System Tray)
├── test_full_system.py         # Bộ kiểm thử tự động toàn diện 20/20 tiêu chí (100% PASS)
├── requirements.txt            # Danh sách thư viện phụ thuộc (PyQt5, psutil, Pillow)
├── config.json                 # Cấu hình mặc định của ứng dụng
│
├── assets/                     # Tài nguyên biểu tượng icon (icon.ico, icon.png)
│
├── backups/                    # Thư mục lưu trữ tự động các bản sao lưu Registry (.reg)
│   └── registry/
│
├── core/                       # Các mô-đun nghiệp vụ nền tảng (Engine Core)
│   ├── cleaner.py              # Dọn dẹp rác chuyên sâu, cache app, Windows Update
│   ├── memory_optimizer.py     # Giải phóng RAM qua Win32 API EmptyWorkingSet
│   ├── process_manager.py      # Giám sát, xếp hạng top RAM/CPU, bảo vệ tiến trình hệ thống
│   ├── game_booster.py         # Chế độ Game Boost (ưu tiên CPU, dồn tài nguyên)
│   ├── system_monitor.py       # Hub giám sát phần cứng RAM, CPU, Ổ đĩa thời gian thực
│   ├── hardware_monitor.py     # Đo độ chai pin laptop, Windows battery report, CPU đa nhân, GPU
│   ├── network_optimizer.py    # Đo tốc độ DNS song song, tối ưu TCP/IP, cấu hình Adapter
│   ├── disk_health_optimizer.py# S.M.A.R.T NVMe/SSD Health, nhiệt độ & TRIM Optimizer
│   ├── registry_cleaner.py     # Quét dọn Registry an toàn, tự động backup & rollback
│   ├── security_scanner.py     # Quét bảo mật UAC, Defender, Firewall, Ports 135/445, SMBv1
│   ├── system_tweaker.py       # Tinh chỉnh Windows Tweaks & Privacy Shield (15 mục hoàn tác)
│   ├── disk_analyzer.py        # Phân tích cây dung lượng ổ đĩa
│   ├── leak_detector.py        # Phát hiện tiến trình rò rỉ bộ nhớ (Memory Leaks)
│   ├── analytics_reporter.py   # Báo cáo thống kê hiệu năng hệ thống
│   ├── health_monitor.py       # Tự chẩn đoán và phát hiện sự cố hệ thống
│   ├── scheduler.py            # Lập lịch tự động dọn dẹp định kỳ và theo dõi ngưỡng RAM
│   └── logger.py               # Hệ thống ghi log an toàn SafeStreamHandler
│
└── ui/                         # Giao diện người dùng đồ họa (PyQt5 Fluent Dark UI)
    ├── main_window.py          # Cửa sổ trung tâm điều khiển 8 tab tích hợp
    ├── floating_widget.py      # Widget nổi Desktop kéo thả & điều chỉnh độ mờ
    ├── tray_icon.py            # Biểu tượng khay hệ thống với menu điều khiển nhanh
    ├── eula_dialog.py          # Điều khoản sử dụng (EULA) lần đầu + xem lại
    ├── hardware_dialog.py      # Hộp thoại Sức khỏe Pin Laptop & Cảm biến phần cứng CPU/GPU
    ├── network_dialog.py       # Hộp thoại đo tốc độ DNS & Tối ưu mạng
    ├── disk_registry_dialog.py # Hộp thoại Sức khỏe ổ đĩa & Dọn dẹp Registry
    ├── large_files_dialog.py   # Hộp thoại quét và quản lý tệp dung lượng lớn
    ├── disk_analyzer_dialog.py # Hộp thoại phân tích cấu trúc dung lượng trực quan
    ├── widgets.py              # Các đồng hồ đo CircularGauge, thẻ thống kê StatCard
    └── styles.py               # Bộ phong cách thiết kế Dark Theme Fluent UI
```


---

## 🚀 Hướng Dẫn Cài Đặt & Sử Dụng

### Yêu Cầu Hệ Thống
- Hệ điều hành: Windows 10 hoặc Windows 11 (64-bit).
- Python: Phiên bản `3.8` trở lên (nếu chạy từ mã nguồn).

### 1. Chạy từ Mã Nguồn (Development Mode)
Mã nguồn trên GitHub là độc quyền — clone để chạy/xem **không** cấp quyền sửa đổi hay tái phân phối. Xem [LICENSE](LICENSE).

1. **Clone repository về máy**:
   ```bash
   git clone https://github.com/mrkiss-it/pc-cleaner-optimizer.git
   cd pc-cleaner-optimizer
   ```

2. **Cài đặt các thư viện phụ thuộc**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Khởi chạy ứng dụng**:
   ```bash
   python main.py
   ```
   *Hoặc click đúp vào file `start_cleaner.bat`*.

4. **Khởi chạy ngầm vào khay hệ thống (Silent Tray Mode)**:
   ```bash
   wscript start_silent.vbs
   ```

---

### 2. Đóng Gói Thành Tệp Thực Thi Độc Lập (.EXE)
Ứng dụng đi kèm script đóng gói thông minh với PyInstaller, tích hợp icon và manifest `asInvoker`:

```bash
python build_exe.py
```
*Hoặc click đúp vào file `build_exe.bat`*.

Sau khi hoàn tất, tệp thực thi sẽ sẵn sàng tại:
```text
dist/PCAutoCleaner/PCAutoCleaner.exe
```
Bạn có thể mang thư mục này sang bất kỳ máy tính Windows nào khác để sử dụng ngay mà không cần cài đặt Python.

---

## 🧪 Kiểm Thử & Đảm Bảo Chất Lượng (Quality Assurance)

Dự án đi kèm bộ kiểm thử tự động toàn diện `test_full_system.py` xác thực 19 tiêu chí hoạt động:
```bash
python test_full_system.py
```

### Kết Quả Kiểm Thử Thực Tế:
```text
[PASS]  1. Import all Core modules
[PASS]  2. ProcessManager (Top CPU/RAM, Protected system whitelist)
[PASS]  3. GameBooster Bat (Thu hồi RAM, điều chỉnh tiến trình)
[PASS]  4. GameBooster Tat (Khôi phục tiến trình bình thường)
[PASS]  5. JunkCleaner Targets (Quét 6 danh mục rác)
[PASS]  6. HealthMonitor (Chẩn đoán trạng thái HEALTHY)
[PASS]  7. AnalyticsReporter (Báo cáo hiệu năng hệ thống)
[PASS]  8. MemoryLeakDetector (Quét phát hiện rò rỉ RAM)
[PASS]  9. Process Whitelist (Quản lý danh sách loại trừ an toàn)
[PASS] 10. UI & MainWindow (8 tabs khởi tạo sạch sẽ, chuyển tab mượt mà)
[PASS] 11. Network Monitor (Đo tốc độ mạng, Ping, Card mạng)
[PASS] 12. Network Optimizer (Flush DNS, tối ưu TCP stack, benchmark DNS)
[PASS] 13. Network UI (Hộp thoại tối ưu mạng & Widget nổi)
[PASS] 14. Auto Network Optimizer (Tự động kích hoạt khi Ping vượt ngưỡng)
[PASS] 15. Security Scanner (Quét UAC, Defender, Firewall, Ports 135/445, SMBv1)
[PASS] 16. Safe Registry Cleaner (Quét khóa hỏng, sao lưu .reg & rollback)
[PASS] 17. Disk Health & SSD TRIM (S.M.A.R.T NVMe, Wear level, Lệnh TRIM)
[PASS] 18. Standalone Executable (File .exe độc lập sẵn sàng)
[PASS] 19. System Tweaker & Privacy Shield (15 tinh chỉnh, 12 khuyên dùng, Apply & Revert 100%)

============================================================
All 19 tests passed successfully! (100% PASS RATE)
============================================================
```


---

## 🔒 Cam Kết An Toàn & Bảo Mật (Safety Principles)

- **Không xóa vĩnh viễn tệp lớn**: Mọi thao tác dọn tệp lớn đều đưa vào Windows Recycle Bin.
- **Bảo vệ dữ liệu Zalo & App Chat**: Tuyệt đối không xóa tin nhắn hoặc dữ liệu tải về, chỉ dọn dẹp các tệp ảnh/video cache tạm.
- **Bảo vệ Registry**: Luôn tự động sao lưu khóa trước khi xử lý, có nút khôi phục 1-click.
- **Bảo vệ tiến trình lõi**: Chặn tuyệt đối việc dừng nhầm các tiến trình trọng yếu của hệ thống (`csrss.exe`, `explorer.exe`, `dwm.exe`, `lsass.exe`).
- **Quyền hạn tối thiểu**: Không ép buộc người dùng phải cấp quyền Administrator khi chỉ cần các tính năng thông thường.

---

## 📄 Bản Quyền (License)

Phần mềm này là **độc quyền (proprietary) — All Rights Reserved**, không phải MIT hay giấy phép mã nguồn mở.

- Chủ sở hữu bản quyền: **[mrkiss-it](https://github.com/mrkiss-it)**.
- **Không** được sao chép, sửa đổi, phân phối lại, hoặc sử dụng thương mại khi chưa có sự cho phép **bằng văn bản** từ chủ sở hữu bản quyền.
- Người dùng cuối được phép chạy bản phát hành chính thức trên máy của mình sau khi đồng ý Điều khoản sử dụng (EULA) trong ứng dụng (lần đầu; trạng thái đồng ý được lưu tại `%APPDATA%\PCAutoCleaner`).
- Chi tiết đầy đủ (tiếng Việt + English): xem tệp [LICENSE](LICENSE).

Kho GitHub công khai **không** đồng nghĩa với quyền tái sử dụng mã nguồn.

---

*Phát triển với ❤️ và sự tỉ mỉ bởi [mrkiss-it](https://github.com/mrkiss-it).*
