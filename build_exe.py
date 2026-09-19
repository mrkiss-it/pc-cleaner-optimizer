import os
import sys
import shutil
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def build():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(base_dir, "main.py")
    ico_path = os.path.join(base_dir, "assets", "icon.ico")
    assets_dir = os.path.join(base_dir, "assets")
    dist_dir = os.path.join(base_dir, "dist", "PCAutoCleaner")
    build_dir = os.path.join(base_dir, "build")

    print("===================================================")
    print("      PC AUTO CLEANER - BUILD STANDALONE EXE       ")
    print("===================================================")
    print("Source directory:", base_dir)
    print("Target script:", main_script)

    # 1. Đảm bảo tắt mọi tiến trình PCAutoCleaner.exe đang chạy
    print("[1/5] Kiểm tra và tắt mọi tiến trình PCAutoCleaner.exe đang chạy...")
    try:
        subprocess.run(["taskkill", "/F", "/IM", "PCAutoCleaner.exe"], capture_output=True)
        subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Process PCAutoCleaner -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }"], capture_output=True)
    except Exception:
        pass

    # 2. Dọn sạch thư mục build cũ để tránh lưu file trung gian lỗi
    print("[2/5] Dọn dẹp thư mục build tạm thời...")
    if os.path.exists(build_dir):
        try:
            shutil.rmtree(build_dir, ignore_errors=True)
        except Exception:
            pass

    # 3. Chạy PyInstaller build
    print("[3/5] Thực thi PyInstaller đóng gói độc lập (windowed, onedir)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name=PCAutoCleaner",
        f"--icon={ico_path}",
        f"--add-data={assets_dir};assets",
        "--hidden-import=PyQt5.QtNetwork",
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=PyQt5.QtGui",
        "--hidden-import=psutil",
        "--hidden-import=winreg",
        "--hidden-import=core.security_scanner",
        "--hidden-import=core.hardware_monitor",
        "--hidden-import=core.ai_advisor",
        "--hidden-import=core.service_optimizer",
        "--hidden-import=core.context_menu_manager",
        "--hidden-import=ui.hardware_dialog",
        "--hidden-import=ui.ai_advisor_dialog",
        "--hidden-import=ui.service_context_dialog",
        main_script
    ]

    res = subprocess.run(cmd, cwd=base_dir)
    if res.returncode != 0:
        print(f"\n[ERROR] Build thất bại với mã lỗi: {res.returncode}")
        return False

    # 4. Sao chép assets và config.json vào thư mục phân phối
    print("[4/5] Đồng bộ hóa assets và config.json vào dist/PCAutoCleaner...")
    try:
        dest_assets = os.path.join(dist_dir, "assets")
        shutil.copytree(assets_dir, dest_assets, dirs_exist_ok=True)
        src_config = os.path.join(base_dir, "config.json")
        dest_config = os.path.join(dist_dir, "config.json")
        if os.path.exists(src_config):
            shutil.copy2(src_config, dest_config)
    except Exception as e:
        print(f"Cảnh báo khi sao chép tài nguyên: {e}")

    # Xóa lại thư mục build trung gian để giải phóng dung lượng và tránh xung đột
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)

    # 5. Cập nhật Shortcut Desktop
    print("[5/5] Cập nhật Desktop shortcut...")
    try:
        ps_script = os.path.join(base_dir, "create_shortcut.ps1")
        if os.path.exists(ps_script):
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", ps_script], capture_output=True)
    except Exception as e:
        print(f"Cảnh báo cập nhật shortcut: {e}")

    dist_exe = os.path.join(dist_dir, "PCAutoCleaner.exe")
    print("\n[SUCCESS] Build hoàn tất thành công!")
    print(f"File thực thi độc lập: {dist_exe}")
    return True

if __name__ == "__main__":
    build()
