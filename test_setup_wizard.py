"""
Setup wizard success-page copy: version from APP_VERSION, Qt ampersand mnemonic.
"""
import os
import re
import sys
import types

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "winreg" not in sys.modules:
        winreg = types.ModuleType("winreg")
        winreg.HKEY_CURRENT_USER = 1
        winreg.HKEY_LOCAL_MACHINE = 2
        winreg.KEY_READ = 0
        winreg.KEY_WRITE = 0
        winreg.KEY_SET_VALUE = 0
        winreg.KEY_ALL_ACCESS = 0
        winreg.REG_DWORD = 4
        winreg.REG_SZ = 1

        def _missing(*_a, **_k):
            raise FileNotFoundError("winreg stub")

        winreg.OpenKey = _missing
        winreg.CreateKey = _missing
        winreg.CloseKey = lambda *_a, **_k: None
        winreg.QueryValueEx = _missing
        winreg.SetValueEx = _missing
        winreg.DeleteValue = _missing
        winreg.EnumKey = _missing
        winreg.error = OSError
        sys.modules["winreg"] = winreg
    import ctypes
    if not hasattr(ctypes, "windll"):
        class _P:
            def __getattr__(self, _n):
                return _P()
            def __call__(self, *_a, **_k):
                return 0
        ctypes.windll = _P()  # type: ignore

from PyQt5.QtWidgets import QApplication

from app_meta import APP_NAME, APP_VERSION, APP_PUBLISHER
from installer.setup_wizard import qt_literal_ampersand, SetupWizard

ROOT = os.path.dirname(os.path.abspath(__file__))
_failed = 0


def check(cond, msg):
    global _failed
    if cond:
        print(f" [PASS] {msg}")
    else:
        _failed += 1
        print(f" [FAIL] {msg}")


print("===================================================")
print("     SETUP WIZARD SUCCESS COPY / VERSION           ")
print("===================================================")

check(qt_literal_ampersand("PC Auto Cleaner & Optimizer") == "PC Auto Cleaner && Optimizer", "escape &")
check("& Optimizer" not in qt_literal_ampersand(APP_NAME).replace("&&", ""), "no raw mnemonic after escape")
check(" _Optimizer" not in qt_literal_ampersand(APP_NAME), "no _Optimizer typo")

app = QApplication.instance() or QApplication(sys.argv)
wizard = SetupWizard()

check(f"v{APP_VERSION}" in wizard.windowTitle(), "window title uses APP_VERSION")
check("3.7.0" not in wizard.windowTitle(), "window title is not stale 3.7.0")
check(f"v{APP_VERSION}" in wizard.lbl_header_sub.text(), "header subtitle uses APP_VERSION")
check("3.7.0" not in wizard.lbl_header_sub.text(), "header subtitle is not stale 3.7.0")

finish = wizard.lbl_finish_sub.text()
check(APP_NAME in finish, "finish line uses APP_NAME")
check(f"v{APP_VERSION}" in finish, "finish line uses APP_VERSION")
check("3.7.0" not in finish, "finish line is not stale 3.7.0")
check(not re.search(r"\bv\d+\.\d+(\.\d+)?\s+Pro\b", finish), "finish line has no fake Pro edition")

launch = wizard.chk_launch_now.text()
check(" _Optimizer" not in launch, "checkbox text has no _Optimizer")
check(qt_literal_ampersand(APP_NAME) in launch, "checkbox escapes APP_NAME for Qt mnemonic")
check("&&" in launch, "checkbox stores && so UI shows & Optimizer")
check(APP_NAME in launch.replace("&&", "&"), "displayed checkbox uses the product name")

wizard.close()

iss_path = os.path.join(ROOT, "installer", "inno_setup.iss")
iss_text = open(iss_path, encoding="utf-8").read()
iss_ver = re.search(r'#define\s+MyAppVersion\s+"([^"]*)"', iss_text)
iss_name = re.search(r'#define\s+MyAppName\s+"([^"]*)"', iss_text)
iss_pub = re.search(r'#define\s+MyAppPublisher\s+"([^"]*)"', iss_text)
check(iss_ver is not None and iss_ver.group(1) == APP_VERSION, "inno MyAppVersion == APP_VERSION")
check(iss_name is not None and iss_name.group(1) == APP_NAME, "inno MyAppName == APP_NAME")
check(iss_pub is not None and iss_pub.group(1) == APP_PUBLISHER, "inno MyAppPublisher == APP_PUBLISHER")
check("3.7.0" not in iss_text, "inno script has no hardcoded 3.7.0")

wizard_src = open(os.path.join(ROOT, "installer", "setup_wizard.py"), encoding="utf-8").read()
check('APP_VERSION = "3.7.0"' not in wizard_src, "wizard has no ImportError fallback to 3.7.0")
check("_Optimizer" not in wizard_src, "wizard source has no _Optimizer typo")

build_src = open(os.path.join(ROOT, "installer", "build_installer.py"), encoding="utf-8").read()
check("--hidden-import=app_meta" in build_src, "Setup PyInstaller bundles app_meta")
check("--paths=" in build_src, "Setup PyInstaller adds repo root to pathex")

print("===================================================")
if _failed:
    print(f"FAILED: {_failed} check(s)")
    sys.exit(1)
print("ALL CHECKS PASSED")
