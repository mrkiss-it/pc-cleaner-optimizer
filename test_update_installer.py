"""
Unit tests for GitHub release asset download + installer launch.
All HTTP is mocked — no live network in CI.
"""
import errno
import hashlib
import io
import os
import sys
import tempfile
import types
import urllib.error
import zipfile

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

from core.update_checker import is_downloadable_asset, pick_download_asset_info
from core.update_installer import (
    DOWNLOAD_CONNECT_TIMEOUT_SEC,
    DOWNLOAD_TIMEOUT_SEC,
    download_release_asset,
    extract_zip_safely,
    find_setup_in_dir,
    format_bytes,
    installer_command,
    launch_downloaded_update,
    parse_asset_digest,
    resolve_download_path,
    uses_quiet_install_flags,
    verify_downloaded_file,
    vietnamese_download_error,
)

PASSES = 0


def check(cond, msg):
    global PASSES
    assert cond, msg
    PASSES += 1


class FakeHttpResp:
    def __init__(self, data=b"", status=200, headers=None):
        self._buf = io.BytesIO(data)
        self.status = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._buf.read() if n is None or n < 0 else self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def mock_urlopen(data, status=200, headers=None):
    def _open(req, timeout=None):
        ua = ""
        if hasattr(req, "headers"):
            ua = req.headers.get("User-agent") or req.headers.get("User-Agent") or ""
        _open.calls.append({"url": getattr(req, "full_url", ""), "timeout": timeout, "ua": ua})
        return FakeHttpResp(data=data, status=status, headers=headers)
    _open.calls = []
    return _open


print("===================================================")
print("     UPDATE INSTALLER — DOWNLOAD / VERIFY / LAUNCH ")
print("===================================================")

# --- format / digest ---
check(format_bytes(512) == "512 B", "bytes")
check("KB" in format_bytes(2048), "kb")
check("MB" in format_bytes(3 * 1024 * 1024), "mb")
algo, hx = parse_asset_digest("sha256:" + ("ab" * 32))
check(algo == "sha256" and len(hx) == 64, "sha256 prefix")
check(parse_asset_digest("not-a-hash") == ("", ""), "unknown digest skipped")
check(parse_asset_digest("ab" * 32)[0] == "sha256", "bare hex sha256")
print(" [PASS] format_bytes / parse_asset_digest")

# --- Vietnamese errors ---
check("mạng" in vietnamese_download_error("offline"), "offline VN")
check("404" in vietnamese_download_error("http_404"), "404 VN")
check("đĩa" in vietnamese_download_error("disk_full"), "disk VN")
print(" [PASS] Vietnamese download error strings")

# --- installer command: no silent flags ---
setup_cmd = installer_command(r"C:\cache\PCAutoCleaner_Setup.exe")
check(setup_cmd == [r"C:\cache\PCAutoCleaner_Setup.exe"], "setup exe as-is")
check(all("/SILENT" not in p.upper() and "/VERYSILENT" not in p.upper() for p in setup_cmd), "no inno silent")
check(uses_quiet_install_flags("PCAutoCleaner_Setup.exe") is False, "custom wizard has no silent")
check(uses_quiet_install_flags("PCAutoCleaner_InnoSetup.exe") is False, "inno silent unsafe while running")
msi_cmd = installer_command("/tmp/app.msi")
check(msi_cmd[:2] == ["msiexec", "/i"], "msi uses msiexec UI")
check("/quiet" not in " ".join(msi_cmd).lower(), "msi not quiet")
print(" [PASS] installer_command launches UI, no silent flags")

payload = b"PCAutoCleaner-setup-bytes"
digest = "sha256:" + hashlib.sha256(payload).hexdigest()
tmpdir = tempfile.mkdtemp(prefix="pca_upd_")
dest = os.path.join(tmpdir, "PCAutoCleaner_Setup.exe")

# --- happy path download + size + sha ---
progress = []
ok_open = mock_urlopen(payload, headers={"Content-Length": str(len(payload))})
result = download_release_asset(
    url="https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/download/v9.9.9/PCAutoCleaner_Setup.exe",
    dest_path=dest,
    expected_size=len(payload),
    expected_digest=digest,
    urlopen=ok_open,
    progress_cb=lambda d, t: progress.append((d, t)),
)
check(result.ok is True, "download ok")
check(os.path.isfile(dest) and open(dest, "rb").read() == payload, "file contents")
check(result.bytes_written == len(payload), "bytes_written")
check(len(ok_open.calls) == 1, "one urlopen")
check(DOWNLOAD_TIMEOUT_SEC >= 15 * 60, "default timeout >= 15 minutes for ~116MB Setup")
check(10 <= DOWNLOAD_CONNECT_TIMEOUT_SEC <= 60, "connect timeout stays reasonable")
check(ok_open.calls[0]["timeout"] == DOWNLOAD_TIMEOUT_SEC, "urlopen uses long default timeout")
check("PCAutoCleaner" in (ok_open.calls[0]["ua"] or ""), "User-Agent sent")
check(progress and progress[-1][0] == len(payload), "progress reached total")
v_ok, v_err = verify_downloaded_file(dest, len(payload), digest)
check(v_ok is True and v_err == "", "verify after download")
print(" [PASS] download_release_asset 200 + size + sha256")

# skip re-download when file already valid
ok_open.calls.clear()
again = download_release_asset(
    url="https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/download/v9.9.9/PCAutoCleaner_Setup.exe",
    dest_path=dest,
    expected_size=len(payload),
    expected_digest=digest,
    urlopen=ok_open,
)
check(again.ok is True and again.skipped_existing is True, "reuse cached file")
check(len(ok_open.calls) == 0, "no HTTP when cached valid")
print(" [PASS] skip download when size/sha already match")

# --- size mismatch ---
bad_size_path = os.path.join(tmpdir, "size_bad.exe")
bad_size = download_release_asset(
    url="https://example.invalid/PCAutoCleaner_Setup.exe",
    dest_path=bad_size_path,
    expected_size=len(payload) + 50,
    urlopen=mock_urlopen(payload),
)
check(bad_size.ok is False and bad_size.error == "size_mismatch", "size mismatch")
check("kích thước" in bad_size.message, "size VN")
check(not os.path.isfile(bad_size_path), "mismatch file discarded")
print(" [PASS] size mismatch discarded")

# --- sha mismatch ---
bad_sha_path = os.path.join(tmpdir, "sha_bad.exe")
bad_sha = download_release_asset(
    url="https://example.invalid/PCAutoCleaner_Setup.exe",
    dest_path=bad_sha_path,
    expected_size=len(payload),
    expected_digest="sha256:" + ("ff" * 32),
    urlopen=mock_urlopen(payload),
)
check(bad_sha.ok is False and bad_sha.error == "sha_mismatch", "sha mismatch")
check("SHA" in bad_sha.message, "sha VN")
print(" [PASS] sha mismatch discarded")

# --- HTTP 404 ---
def raise_404(req, timeout=None):
    raise urllib.error.HTTPError(
        "https://github.com/x/y/releases/download/v1/PCAutoCleaner_Setup.exe",
        404, "Not Found", hdrs=None, fp=io.BytesIO(b"missing"),
    )

r404 = download_release_asset(
    url="https://github.com/x/y/releases/download/v1/PCAutoCleaner_Setup.exe",
    dest_path=os.path.join(tmpdir, "missing.exe"),
    urlopen=raise_404,
)
check(r404.ok is False and r404.error == "http_404", "404 code")
check(r404.http_status == 404, "404 status")
check("404" in r404.message, "404 message")
print(" [PASS] HTTP 404 Vietnamese, no crash")

# --- offline ---
def raise_off(req, timeout=None):
    raise urllib.error.URLError("network down")

roff = download_release_asset(
    url="https://github.com/x/y/releases/download/v1/PCAutoCleaner_Setup.exe",
    dest_path=os.path.join(tmpdir, "off.exe"),
    urlopen=raise_off,
)
check(roff.ok is False and roff.error == "offline", "offline code")
check("mạng" in roff.message, "offline VN")
print(" [PASS] network fail Vietnamese, no crash")

# --- disk full ---
class FullWriter:
    def write(self, _b):
        err = OSError(errno.ENOSPC, "No space left on device")
        raise err
    def __enter__(self):
        return self
    def __exit__(self, *_a):
        return False

import builtins
_real_open = builtins.open

def _full_open(path, mode="r", *a, **k):
    if "w" in str(mode) and str(path).endswith(".part"):
        return FullWriter()
    return _real_open(path, mode, *a, **k)

disk_path = os.path.join(tmpdir, "full.exe")
builtins.open = _full_open
try:
    rdisk = download_release_asset(
        url="https://example.invalid/PCAutoCleaner_Setup.exe",
        dest_path=disk_path,
        expected_size=len(payload),
        urlopen=mock_urlopen(payload),
    )
finally:
    builtins.open = _real_open
check(rdisk.ok is False and rdisk.error == "disk_full", "disk full code")
check("đĩa" in rdisk.message, "disk full VN")
print(" [PASS] disk full Vietnamese, no crash")

# --- cancel ---
rcancel = download_release_asset(
    url="https://example.invalid/PCAutoCleaner_Setup.exe",
    dest_path=os.path.join(tmpdir, "cancel.exe"),
    urlopen=mock_urlopen(payload),
    cancel_check=lambda: True,
)
check(rcancel.ok is False and rcancel.error == "cancelled", "cancelled")
print(" [PASS] cancel_check stops download")

# --- empty / invalid url ---
rinv = download_release_asset(url="", dest_path=dest)
check(rinv.ok is False and rinv.error == "invalid", "invalid empty url")
print(" [PASS] invalid url")

# --- launch installer (mocked popen, no real process) ---
launched = []

def fake_popen(cmd, **_k):
    launched.append(list(cmd))
    class _P:
        pid = 1
    return _P()

launch = launch_downloaded_update(dest, popen=fake_popen, open_folder=lambda _p: True)
check(launch.ok is True and launch.should_close is True, "launch installer should close app")
check(launch.action == "installer", "installer action")
check(launched and launched[0][0] == dest, "popen got setup path")
check(all("/SILENT" not in str(p).upper() for p in launched[0]), "launched without silent")
check("Đang mở trình cài đặt" in launch.message, "auto-close message")
check("thoát" in launch.message.lower() or "ghi đè" in launch.message, "will quit so installer can overwrite")
print(" [PASS] launch Setup.exe via mocked popen, auto-close (no prompt)")

# --- zip portable: extract + find Setup.exe ---
zip_path = os.path.join(tmpdir, "PCAutoCleaner_portable.zip")
inner_dir = os.path.join(tmpdir, "zipsrc")
os.makedirs(inner_dir, exist_ok=True)
inner_setup = os.path.join(inner_dir, "PCAutoCleaner_Setup.exe")
with open(inner_setup, "wb") as handle:
    handle.write(b"setup-inside-zip")
with zipfile.ZipFile(zip_path, "w") as zf:
    zf.write(inner_setup, "PCAutoCleaner_Setup.exe")
    zf.writestr("../evil.exe", b"nope")

extracted = os.path.join(tmpdir, "zip_out")
ok_zip, out_dir = extract_zip_safely(zip_path, extracted)
check(ok_zip is True, "zip extract")
check(find_setup_in_dir(extracted).endswith("PCAutoCleaner_Setup.exe"), "find setup in zip")
check(not os.path.isfile(os.path.join(tmpdir, "evil.exe")), "zip-slip skipped")

launched.clear()
zip_launch = launch_downloaded_update(zip_path, popen=fake_popen, open_folder=lambda _p: False)
check(zip_launch.ok is True and zip_launch.action == "installer", "zip with setup launches installer")
check(launched and launched[0][0].endswith("PCAutoCleaner_Setup.exe"), "zip inner setup")
print(" [PASS] portable zip extract + Setup.exe + zip-slip blocked")

# --- zip portable folder only (no Setup) — open folder, do not quit ---
portable_only = os.path.join(tmpdir, "PCAutoCleaner_3.8.1_portable.zip")
with zipfile.ZipFile(portable_only, "w") as zf:
    zf.writestr("PCAutoCleaner/PCAutoCleaner.exe", b"portable-app")
opened_folders = []
launched.clear()
folder_launch = launch_downloaded_update(
    portable_only, popen=fake_popen, open_folder=lambda p: opened_folders.append(p) or True
)
check(folder_launch.ok is True and folder_launch.action == "folder", "portable folder action")
check(folder_launch.should_close is False, "portable cannot overwrite running files")
check(not launched, "no installer popen for portable-only zip")
check(opened_folders, "opened extracted folder")
check("ghi đè" in folder_launch.message, "VN cannot overwrite running files")
print(" [PASS] portable zip without Setup opens folder, no auto-quit")

# --- cache path uses LOCALAPPDATA ---
os.environ["LOCALAPPDATA"] = tmpdir
cached = resolve_download_path("PCAutoCleaner_Setup.exe", "v3.8.1")
check("updates" in cached.replace("\\", "/"), "cache subdir")
check("v3.8.1" in cached, "tag folder")
check(cached.endswith("PCAutoCleaner_Setup.exe"), "safe filename")
print(" [PASS] resolve_download_path cache folder")

# --- pick + downloadable URL handling (no network) ---
picked = pick_download_asset_info(
    [
        {
            "name": "PCAutoCleaner_Setup.exe",
            "browser_download_url": "https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/download/v3.8.1/PCAutoCleaner_Setup.exe",
            "size": 12,
        }
    ],
    html_url="https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/tag/v3.8.1",
)
check(is_downloadable_asset(picked.name, picked.url) is True, "release asset downloadable")
check("/releases/download/" in picked.url, "browser_download_url")
page_pick = pick_download_asset_info(
    [],
    html_url="https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/tag/v3.8.1",
)
check(page_pick.name == "", "no asset")
check(is_downloadable_asset(page_pick.name, page_pick.url) is False, "page not downloadable")
print(" [PASS] asset pick + download URL handling")

print(f"\n>>> {PASSES} assertions — update installer unit tests OK <<<")
