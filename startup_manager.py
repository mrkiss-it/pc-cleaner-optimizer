import sys
import os
import winreg

APP_NAME = "PCAutoCleaner"
OLD_APP_NAME = "PCAuxAutoCleaner"

class StartupManager:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    @staticmethod
    def is_startup_enabled() -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, StartupManager.REG_PATH, 0, winreg.KEY_READ) as key:
                try:
                    val, _ = winreg.QueryValueEx(key, APP_NAME)
                    return bool(val)
                except FileNotFoundError:
                    val, _ = winreg.QueryValueEx(key, OLD_APP_NAME)
                    return bool(val)
        except (FileNotFoundError, OSError):
            return False

    @staticmethod
    def set_startup(enable: bool, target_path: str = None) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, StartupManager.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    if not target_path:
                        if getattr(sys, 'frozen', False):
                            target_path = f'"{sys.executable}" --minimized'
                        else:
                            current_dir = os.path.dirname(os.path.abspath(__file__))
                            dist_exe = os.path.join(current_dir, "dist", "PCAutoCleaner", "PCAutoCleaner.exe")
                            if os.path.exists(dist_exe):
                                target_path = f'"{dist_exe}" --minimized'
                            else:
                                python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                                main_py = os.path.join(current_dir, "main.py")
                                target_path = f'"{python_exe}" "{main_py}" --minimized'

                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, target_path)
                    try:
                        winreg.DeleteValue(key, OLD_APP_NAME)
                    except FileNotFoundError:
                        pass
                    print(f"[StartupManager] Enabled startup with command: {target_path}")
                else:
                    for name in (APP_NAME, OLD_APP_NAME):
                        try:
                            winreg.DeleteValue(key, name)
                        except FileNotFoundError:
                            pass
                    print("[StartupManager] Disabled startup.")
            return True
        except Exception as e:
            print(f"[StartupManager] Error configuring startup: {e}")
            return False
