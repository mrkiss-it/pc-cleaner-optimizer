"""
installer/build_installer.py – Kịch bản tự động đóng gói Smart Setup Wizard Installer.
1. Biên dịch uninstall_wizard.py thành dist/PCAutoCleaner/uninstall.exe.
2. Nén toàn bộ thư mục dist/PCAutoCleaner thành installer/app_bundle.zip.
3. Biên dịch setup_wizard.py thành dist/PCAutoCleaner_Setup.exe (Single-file Setup Wizard).

Phiên bản Setup Wizard lấy từ APP_VERSION (app_meta) nhờ --hidden-import=app_meta.
"""

import os
import re
import sys
import shutil
import zipfile
import subprocess

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from app_meta import APP_NAME, APP_VERSION

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

def make_zip(source_dir: str, output_zip: str):
    """Nén thư mục thành file zip với tỉ lệ nén tối ưu."""
    print(f"[*] Đang nén '{source_dir}' thành '{output_zip}'...")
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, source_dir)
                zf.write(full_path, rel_path)
    sz_mb = os.path.getsize(output_zip) / (1024 * 1024)
    print(f"[+] Hoàn tất nén bundle: {sz_mb:.1f} MB.")


def build():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    installer_dir = os.path.join(base_dir, "installer")
    dist_dir = os.path.join(base_dir, "dist")
    app_dist = os.path.join(dist_dir, "PCAutoCleaner")
    ico_path = os.path.join(base_dir, "assets", "icon.ico")
    bundle_zip = os.path.join(installer_dir, "app_bundle.zip")

    print("=" * 60)
    print("      PC AUTO CLEANER - BUILD SMART SETUP WIZARD       ")
    print(f"      {APP_NAME} v{APP_VERSION}")
    print("=" * 60)

    iss_path = os.path.join(installer_dir, "inno_setup.iss")
    if os.path.exists(iss_path):
        iss_text = open(iss_path, encoding="utf-8").read()
        m = re.search(r'#define\s+MyAppVersion\s+"([^"]*)"', iss_text)
        iss_ver = m.group(1) if m else ""
        if iss_ver != APP_VERSION:
            print(
                f"[!] Cảnh báo: inno_setup.iss MyAppVersion={iss_ver!r} "
                f"khác APP_VERSION={APP_VERSION!r}. Hãy đồng bộ trước khi compile Inno."
            )

    # 1. Kiểm tra dist/PCAutoCleaner
    if not os.path.exists(app_dist) or not os.path.exists(os.path.join(app_dist, "PCAutoCleaner.exe")):
        print("[!] Không tìm thấy dist/PCAutoCleaner. Đang chạy build_exe.py trước...")
        res = subprocess.run([sys.executable, os.path.join(base_dir, "build_exe.py")], cwd=base_dir)
        if res.returncode != 0:
            print("[ERROR] Không thể build PCAutoCleaner!")
            return False

    # 2. Biên dịch Uninstaller: uninstall_wizard.py -> dist/PCAutoCleaner/uninstall.exe
    print("\n[1/3] Biên dịch Trình Gỡ Cài Đặt (uninstall.exe)...")
    uninst_script = os.path.join(installer_dir, "uninstall_wizard.py")
    cmd_uninst = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        f"--icon={ico_path}",
        f"--distpath={app_dist}",
        f"--workpath={os.path.join(base_dir, 'build', 'uninstaller')}",
        "--name=uninstall",
        uninst_script
    ]
    res = subprocess.run(cmd_uninst, cwd=base_dir)
    if res.returncode != 0:
        print("[!] Cảnh báo: PyInstaller uninstaller thất bại, sao chép script dự phòng.")

    # 3. Nén dist/PCAutoCleaner thành app_bundle.zip
    print("\n[2/3] Đóng gói toàn bộ ứng dụng thành app_bundle.zip...")
    make_zip(app_dist, bundle_zip)

    # 4. Biên dịch Setup Wizard: setup_wizard.py -> dist/PCAutoCleaner_Setup.exe
    print("\n[3/3] Đóng gói Trình Cài Đặt Thông Minh (PCAutoCleaner_Setup.exe)...")
    setup_script = os.path.join(installer_dir, "setup_wizard.py")
    app_meta_py = os.path.join(base_dir, "app_meta.py")
    cmd_setup = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        f"--icon={ico_path}",
        f"--paths={base_dir}",
        "--hidden-import=app_meta",
        f"--add-data={bundle_zip};.",
        f"--add-data={os.path.join(base_dir, 'assets')};assets",
        f"--add-data={app_meta_py};.",
        f"--distpath={dist_dir}",
        f"--workpath={os.path.join(base_dir, 'build', 'setup_wizard')}",
        "--name=PCAutoCleaner_Setup",
        setup_script
    ]
    res = subprocess.run(cmd_setup, cwd=base_dir)
    if res.returncode != 0:
        print(f"[ERROR] Build Setup Wizard thất bại với mã {res.returncode}")
        return False

    setup_exe = os.path.join(dist_dir, "PCAutoCleaner_Setup.exe")
    if os.path.exists(setup_exe):
        sz_mb = os.path.getsize(setup_exe) / (1024 * 1024)
        print("\n" + "=" * 60)
        print("[SUCCESS] ĐÃ TẠO THÀNH CÔNG BỘ CÀI ĐẶT THÔNG MINH!")
        print(f"Sản phẩm: {APP_NAME} v{APP_VERSION}")
        print(f"File cài đặt: {setup_exe} ({sz_mb:.1f} MB)")
        print("=" * 60)
        return True
    else:
        print("[ERROR] Không tìm thấy file PCAutoCleaner_Setup.exe sau khi đóng gói!")
        return False


if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
