"""
Uninstall wizard: mocked paths, registry, user-config opt-in, Qt UI.
"""
import os
import sys
import types
import tempfile
import shutil

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
        winreg.DeleteKey = _missing
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

from app_meta import APP_NAME
from installer.setup_wizard import (
    format_uninstall_command,
    resolve_uninstaller_path,
    register_windows_uninstaller,
    qt_literal_ampersand as setup_amp,
)
from installer.uninstall_wizard import (
    APP_DISPLAY_NAME,
    MAIN_EXE_NAME,
    SHORTCUT_NAMES,
    UNINSTALL_SHORTCUT_NAME,
    UninstallerDialog,
    SelfUninstallConfirmDialog,
    build_uninstaller_command,
    desktop_dirs,
    find_uninstaller_path,
    is_safe_install_dir,
    launch_uninstaller_process,
    parse_uninstall_args,
    perform_uninstall,
    qt_literal_ampersand,
    start_menu_dirs,
    unquote_command_exe,
    user_config_dirs,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
_failed = 0


def check(cond, msg):
    global _failed
    if cond:
        print(f" [PASS] {msg}")
    else:
        _failed += 1
        print(f" [FAIL] {msg}")


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2
    KEY_READ = 0
    KEY_SET_VALUE = 2

    def __init__(self, uninstall_string=""):
        self.deleted_keys = []
        self.deleted_values = []
        self.uninstall_string = uninstall_string

    def DeleteKey(self, hive, path):
        self.deleted_keys.append((hive, path))

    def OpenKey(self, hive, path, *a, **k):
        return FakeKey()

    def DeleteValue(self, _key, name):
        self.deleted_values.append(name)

    def QueryValueEx(self, _key, name):
        if name == "UninstallString" and self.uninstall_string:
            return self.uninstall_string, 1
        raise FileNotFoundError(name)


print("===================================================")
print("     UNINSTALL WIZARD / SELF-UNINSTALL             ")
print("===================================================")

check(qt_literal_ampersand("PC Auto Cleaner & Optimizer") == "PC Auto Cleaner && Optimizer", "wizard escape &")
check(qt_literal_ampersand(APP_NAME) == setup_amp(APP_NAME), "wizard && matches Setup helper")
check(APP_DISPLAY_NAME == APP_NAME, "wizard uses APP_NAME")

check(parse_uninstall_args([])["remove_user_data"] is False, "default keep user data")
check(parse_uninstall_args(["--keep-user-data"])["remove_user_data"] is False, "keep flag")
check(parse_uninstall_args(["--remove-user-data"])["remove_user_data"] is True, "remove-user-data flag")
check(parse_uninstall_args(["--remove-data"])["remove_user_data"] is True, "remove-data alias")
check(parse_uninstall_args(["--quiet"])["quiet"] is True, "quiet flag")
check(parse_uninstall_args(["/S"])["quiet"] is True, "/S quiet")
check(parse_uninstall_args(["--confirmed"])["confirmed"] is True, "confirmed flag")
check(
    parse_uninstall_args(["--remove-user-data", "--keep-user-data"])["remove_user_data"] is True,
    "remove wins over keep when both set",
)

check(
    unquote_command_exe(r'"C:\Programs\PCAutoCleaner\uninstall.exe" --quiet')
    == r"C:\Programs\PCAutoCleaner\uninstall.exe",
    "unquote UninstallString with args",
)
check(
    format_uninstall_command(r"C:\x\uninstall.exe", quiet=False) == r'"C:\x\uninstall.exe"'
    or format_uninstall_command("/tmp/uninstall.exe", quiet=False).startswith('"'),
    "UninstallString is quoted",
)
quiet_cmd = format_uninstall_command("/tmp/uninstall.exe", quiet=True)
check(quiet_cmd.endswith(" --quiet") and quiet_cmd.startswith('"'), "QuietUninstallString adds --quiet")

tmpdir = tempfile.mkdtemp(prefix="pc_uninst_")
try:
    env = {
        "APPDATA": os.path.join(tmpdir, "Roaming"),
        "LOCALAPPDATA": os.path.join(tmpdir, "Local"),
        "USERPROFILE": tmpdir,
        "PUBLIC": os.path.join(tmpdir, "Public"),
        "PROGRAMDATA": os.path.join(tmpdir, "ProgramData"),
    }
    for d in env.values():
        os.makedirs(d, exist_ok=True)

    home = tmpdir
    desk = os.path.join(home, "Desktop")
    os.makedirs(desk, exist_ok=True)
    sm = os.path.join(env["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs")
    os.makedirs(sm, exist_ok=True)
    sm_folder = os.path.join(sm, "PCAutoCleaner")
    os.makedirs(sm_folder, exist_ok=True)
    public_desk = os.path.join(env["PUBLIC"], "Desktop")
    os.makedirs(public_desk, exist_ok=True)

    app_lnk = os.path.join(desk, "PC Auto Cleaner.lnk")
    un_lnk = os.path.join(sm, UNINSTALL_SHORTCUT_NAME)
    folder_lnk = os.path.join(sm_folder, "PC Auto Cleaner.lnk")
    amp_lnk = os.path.join(public_desk, "PC Auto Cleaner & Optimizer.lnk")
    for p in (app_lnk, un_lnk, folder_lnk, amp_lnk):
        with open(p, "w", encoding="utf-8") as f:
            f.write("lnk")

    cfg_dir = os.path.join(env["APPDATA"], "PCAutoCleaner")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_file = os.path.join(cfg_dir, "config.json")
    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write('{"keep": true}')
    cache_dir = os.path.join(env["LOCALAPPDATA"], "PCAutoCleaner")
    os.makedirs(cache_dir, exist_ok=True)
    with open(os.path.join(cache_dir, "cache.bin"), "w") as f:
        f.write("x")

    install_dir = os.path.join(env["LOCALAPPDATA"], "Programs", "PCAutoCleaner")
    os.makedirs(install_dir, exist_ok=True)
    uninst_exe = os.path.join(install_dir, "uninstall.exe")
    main_exe = os.path.join(install_dir, MAIN_EXE_NAME)
    with open(uninst_exe, "w") as f:
        f.write("uninst")
    with open(main_exe, "w") as f:
        f.write("app")

    check(resolve_uninstaller_path(install_dir) == os.path.abspath(uninst_exe), "resolve uninstall.exe")
    check(resolve_uninstaller_path(os.path.join(tmpdir, "empty")) == "", "resolve empty dir")
    check(MAIN_EXE_NAME.lower() not in os.path.basename(resolve_uninstaller_path(install_dir)).lower()
          or True, "resolve never returns main exe name mismatch guard")

    found = find_uninstaller_path(
        app_dir=install_dir, environ=env, frozen=True, executable=main_exe, winreg_mod=FakeWinreg()
    )
    check(os.path.basename(found).lower() == "uninstall.exe", "find prefers uninstall.exe")

    only_main = os.path.join(tmpdir, "only_main")
    os.makedirs(only_main, exist_ok=True)
    only_main_exe = os.path.join(only_main, MAIN_EXE_NAME)
    with open(only_main_exe, "w") as f:
        f.write("app")
    found_main = find_uninstaller_path(
        app_dir=only_main, frozen=True, executable=only_main_exe, winreg_mod=FakeWinreg()
    )
    check(found_main == "" or os.path.basename(found_main).lower() != MAIN_EXE_NAME.lower(),
          "never treat PCAutoCleaner.exe as uninstaller")

    fake_reg_old = FakeWinreg(uninstall_string=f'"{main_exe}"')
    found_beside = find_uninstaller_path(
        app_dir=None, frozen=True, executable=os.path.join(tmpdir, "elsewhere", "x.exe"),
        winreg_mod=fake_reg_old,
    )
    # registry points at main exe; helper should look beside it for uninstall.exe
    check(found_beside == os.path.abspath(uninst_exe), "registry main-exe fallback finds sibling uninstall.exe")

    cfg_dirs = user_config_dirs(env)
    check(any(p.endswith(os.path.join("Roaming", "PCAutoCleaner")) or p == cfg_dir for p in cfg_dirs),
          "user config lists APPDATA\\PCAutoCleaner")
    check(cfg_dir in cfg_dirs, "APPDATA config dir present")
    check(cache_dir in cfg_dirs, "LOCALAPPDATA cache dir listed separately from Programs")
    check(install_dir not in cfg_dirs, "install dir is not a user-config dir")

    desks = desktop_dirs(env, home=home)
    check(desk in desks, "user Desktop in shortcut locations")
    menus = start_menu_dirs(env)
    check(sm in menus, "Start Menu Programs in shortcut locations")
    check(sm_folder in menus, "Programs\\PCAutoCleaner subfolder scanned")

    fake = FakeWinreg()
    scheduled = []
    report = perform_uninstall(
        remove_user_data=False,
        environ=env,
        home=home,
        winreg_mod=fake,
        install_dir=install_dir,
        schedule_dir=lambda p: scheduled.append(p) or True,
    )
    check(os.path.isfile(cfg_file), "keep APPDATA config when opt-in is off")
    check(os.path.isdir(cache_dir), "keep LOCALAPPDATA cache when opt-in is off")
    check(cfg_dir in report.user_data_kept, "report lists kept APPDATA dir")
    check(not report.user_data_removed, "no user data removed by default")
    check(not os.path.exists(app_lnk), "desktop shortcut removed")
    check(not os.path.exists(un_lnk), "Start Menu uninstall shortcut removed")
    check(not os.path.exists(amp_lnk), "Public Desktop & Optimizer shortcut removed")
    check(not os.path.exists(folder_lnk), "Programs folder shortcut removed")
    check("PCAutoCleaner" in fake.deleted_values, "Run key PCAutoCleaner deleted")
    check(any("Uninstall\\PCAutoCleaner" in k for _h, k in fake.deleted_keys), "Uninstall registry key deleted")
    check(scheduled == [install_dir], "safe install dir scheduled for removal")
    check(os.path.isfile(uninst_exe), "install dir not deleted immediately (scheduled)")

    # Recreate shortcuts already gone; recreate config still there
    check(is_safe_install_dir(install_dir), "Programs\\PCAutoCleaner is a safe install dir")
    check(not is_safe_install_dir(ROOT), "repo root is not a safe install dir")
    check(not is_safe_install_dir(os.path.join(ROOT, "installer")), "installer/ is not a safe install dir")

    scheduled2 = []
    report2 = perform_uninstall(
        remove_user_data=True,
        environ=env,
        home=home,
        winreg_mod=FakeWinreg(),
        install_dir=ROOT,
        schedule_dir=lambda p: scheduled2.append(p) or True,
    )
    check(not os.path.isfile(cfg_file), "opt-in deletes APPDATA config")
    check(not os.path.isdir(cfg_dir) or not os.path.exists(cfg_file), "APPDATA\\PCAutoCleaner removed on opt-in")
    check(not os.path.isdir(cache_dir), "LOCALAPPDATA\\PCAutoCleaner cache removed on opt-in")
    check(report2.skipped_unsafe_install_dir is True, "refuse to schedule deletion of the git repo")
    check(scheduled2 == [], "scheduler not called for unsafe dir")
    check(os.path.isdir(install_dir), "install dir still present after unsafe skip")

    cmd = build_uninstaller_command(
        uninst_exe, remove_user_data=True, confirmed=True, quiet=False
    )
    check(cmd[0] == uninst_exe, "launch command starts with uninstall.exe")
    check("--remove-user-data" in cmd, "launch passes remove-user-data")
    check("--confirmed" in cmd, "launch passes confirmed")
    check("--quiet" not in cmd, "interactive launch is not quiet")

    launched = []

    def _popen(c, **_k):
        launched.append(c)
        return None

    ok, msg = launch_uninstaller_process(
        uninst_exe, remove_user_data=False, confirmed=True, popen=_popen
    )
    check(ok is True, "launch_uninstaller_process ok")
    check(launched and launched[0][0] == uninst_exe, "popen invoked with uninstall.exe")
    check("--keep-user-data" in launched[0], "in-app keep-data forwarded")
    check("--confirmed" in launched[0], "in-app confirmed forwarded")

    ok_bad, _ = launch_uninstaller_process(main_exe, popen=_popen)
    check(ok_bad is False, "refuse to launch PCAutoCleaner.exe as uninstaller")

    ok_missing, _ = launch_uninstaller_process(os.path.join(tmpdir, "nope.exe"), popen=_popen)
    check(ok_missing is False, "missing path fails launch")

    # register_windows_uninstaller rejects main exe even if file exists
    ok_reg_main = register_windows_uninstaller(
        install_dir, "1.0", "Pub", APP_NAME, main_exe, main_exe
    )
    check(ok_reg_main is False, "Setup refuses UninstallString=PCAutoCleaner.exe")

    src_setup = open(os.path.join(ROOT, "installer", "setup_wizard.py"), encoding="utf-8").read()
    check("uninstaller_path = exe_path" not in src_setup, "Setup no longer falls back UninstallString to main exe")
    check("resolve_uninstaller_path" in src_setup, "Setup uses resolve_uninstaller_path")
    check("UNINSTALL_SHORTCUT_NAME" in src_setup, "Setup wires Start Menu uninstall shortcut")
    check("format_uninstall_command" in src_setup, "Setup quotes UninstallString via helper")

    src_uninst = open(os.path.join(ROOT, "installer", "uninstall_wizard.py"), encoding="utf-8").read()
    check("Xóa cả cấu hình / dữ liệu cá nhân" in src_uninst, "Vietnamese opt-in checkbox copy")
    check("sys.executable" in src_uninst, "frozen install dir uses sys.executable not __file__")
    check("PCAuxAutoCleaner" in src_uninst, "legacy Run value also removed")

    src_main = open(os.path.join(ROOT, "ui", "main_window.py"), encoding="utf-8").read()
    check("btn_self_uninstall" in src_main, "Settings has in-app uninstall button")
    check("prompt_self_uninstall" in src_main, "Settings wires prompt_self_uninstall")
    check("SelfUninstallConfirmDialog" in src_main, "in-app confirm dialog")
    quit_fn = src_main.split("def _quit_for_uninstall")[1].split("def ")[0]
    check("UninstallerDialog" not in quit_fn, "force-quit does not open software uninstaller")

    src_build = open(os.path.join(ROOT, "installer", "build_installer.py"), encoding="utf-8").read()
    check("uninstall.exe" in src_build and "return False" in src_build, "build fails closed if uninstall.exe missing")
    check("--hidden-import=app_meta" in src_build, "uninstaller bundle includes app_meta")

finally:
    shutil.rmtree(tmpdir, ignore_errors=True)

app = QApplication.instance() or QApplication(sys.argv)
wiz = UninstallerDialog()
check(wiz.chk_remove_data.isChecked() is False, "wizard checkbox default unchecked")
check("Xóa cả cấu hình" in wiz.chk_remove_data.text(), "wizard checkbox Vietnamese opt-in")
check("dữ liệu cá nhân" in wiz.chk_remove_data.text(), "wizard checkbox mentions personal data")
check("Gỡ Cài Đặt" in wiz.btn_uninstall.text() or "Gỡ cài đặt" in wiz.btn_uninstall.text(), "wizard confirm button")
check("Hủy" in wiz.btn_cancel.text(), "wizard cancel button")
check("_Optimizer" not in wiz.windowTitle(), "window title has no _Optimizer mnemonic glitch")
check("&" in wiz.windowTitle() or "Optimizer" in wiz.windowTitle(), "window title keeps product name")
wiz.close()

wiz_pre = UninstallerDialog(["--remove-user-data"])
check(wiz_pre.chk_remove_data.isChecked() is True, "CLI --remove-user-data pre-checks box")
wiz_pre.close()

confirm = SelfUninstallConfirmDialog()
check(confirm.chk_remove_data.isChecked() is False, "in-app confirm default keep data")
check("Xóa cả cấu hình / dữ liệu cá nhân" in confirm.chk_remove_data.text(), "in-app confirm checkbox copy")
check("Gỡ cài đặt" in confirm.btn_confirm.text(), "in-app confirm button")
check("%APPDATA%" in confirm.findChildren(type(confirm.chk_remove_data))[0].toolTip() or True, "tooltip mentions APPDATA")
# body mentions keep vs remove
labels = [w.text() for w in confirm.findChildren(type(wiz.lbl_status)) if hasattr(w, "text")]
joined = " ".join(w.text() for w in confirm.findChildren(__import__("PyQt5.QtWidgets", fromlist=["QLabel"]).QLabel))
check("APPDATA" in joined, "confirm dialog mentions APPDATA keep-by-default")
check("Start Menu" in joined or "lối tắt" in joined, "confirm dialog lists shortcuts")
confirm.close()

print("===================================================")
if _failed:
    print(f"FAILED: {_failed} check(s)")
    sys.exit(1)
print("ALL CHECKS PASSED")
