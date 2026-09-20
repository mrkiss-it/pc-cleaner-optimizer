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
from installer.setup_wizard import qt_literal_ampersand, SetupWizard, format_uninstall_command, resolve_uninstaller_path
import installer.setup_wizard as setup_wizard_mod

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
check(" Pro" not in wizard.lbl_header_sub.text(), "header subtitle has no Pro edition")

finish = wizard.lbl_finish_sub.text()
check(APP_NAME in finish, "finish line uses APP_NAME")
check(f"v{APP_VERSION}" in finish, "finish line uses APP_VERSION")
check("3.7.0" not in finish, "finish line is not stale 3.7.0")
check(not re.search(r"\bv\d+\.\d+(\.\d+)?\s+Pro\b", finish), "finish line has no fake Pro edition")
check(" Pro" not in finish, "finish line has no Pro suffix")

launch = wizard.chk_launch_now.text()
check(" _Optimizer" not in launch, "checkbox text has no _Optimizer")
check(qt_literal_ampersand(APP_NAME) in launch, "checkbox escapes APP_NAME for Qt mnemonic")
check("&&" in launch, "checkbox stores && so UI shows & Optimizer")
check(APP_NAME in launch.replace("&&", "&"), "displayed checkbox uses the product name")

wizard.close()

# Simulate the Windows-tree bug: local APP_VERSION = "3.7.0" after import must not win.
setup_wizard_mod.APP_NAME = "PC Auto Cleaner & Optimizer"
setup_wizard_mod.APP_VERSION = "3.7.0"
setup_wizard_mod.APP_PUBLISHER = "ignored"
shadowed = SetupWizard()
check(f"v{APP_VERSION}" in shadowed.lbl_finish_sub.text(), "shadowed APP_VERSION still reads app_meta")
check("3.7.0" not in shadowed.lbl_finish_sub.text(), "local APP_VERSION=3.7.0 override is ignored")
check("3.7.0" not in shadowed.lbl_header_sub.text(), "header ignores local 3.7.0 override")
check(qt_literal_ampersand(APP_NAME) in shadowed.chk_launch_now.text(), "shadowed checkbox still escapes &")
shadowed.close()
del setup_wizard_mod.APP_NAME, setup_wizard_mod.APP_VERSION, setup_wizard_mod.APP_PUBLISHER

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
code_only = "\n".join(
    ln for ln in wizard_src.splitlines()
    if not ln.lstrip().startswith("#") and not ln.lstrip().startswith('"""')
)
check(not re.search(r'APP_VERSION\s*=\s*"3\.7\.0"', code_only),
      "wizard has no hard-coded APP_VERSION = 3.7.0")
check(not re.search(r"^(APP_NAME|APP_VERSION|APP_PUBLISHER)\s*=", wizard_src, re.M),
      "wizard does not reassign APP_* after import")
check("v{APP_VERSION} Pro" not in wizard_src and "APP_VERSION} Pro" not in wizard_src,
      "wizard UI strings do not append Pro")
check("app_meta.APP_VERSION" in wizard_src, "wizard reads version via app_meta.APP_VERSION")
check("_Optimizer" not in code_only.replace("qt_literal_ampersand", ""),
      "wizard executable code has no _Optimizer typo")
check("qt_literal_ampersand(app_meta.APP_NAME)" in wizard_src,
      "launch checkbox escapes APP_NAME with &&")

build_src = open(os.path.join(ROOT, "installer", "build_installer.py"), encoding="utf-8").read()
check("--hidden-import=app_meta" in build_src, "Setup PyInstaller bundles app_meta")
check("--paths=" in build_src, "Setup PyInstaller adds repo root to pathex")
check("uninstall.exe" in build_src, "build_installer compiles uninstall.exe")
check(format_uninstall_command("/tmp/uninstall.exe", quiet=False).startswith('"'), "UninstallString quoted")
check("--quiet" in format_uninstall_command("/tmp/uninstall.exe", quiet=True), "QuietUninstallString uses --quiet")
check(resolve_uninstaller_path("/no/such/dir") == "", "missing uninstall.exe is empty path")
check("uninstaller_path = exe_path" not in wizard_src, "wizard does not fall back UninstallString to main exe")

print("===================================================")
if _failed:
    print(f"FAILED: {_failed} check(s)")
    sys.exit(1)
print("ALL CHECKS PASSED")
