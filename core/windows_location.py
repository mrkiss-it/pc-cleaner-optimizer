"""
Phát hiện khóa Location bởi Group Policy và gỡ khóa một lần qua UAC.

HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\LocationAndSensors\\DisableLocation = 1
làm Settings → Privacy → Location bị xám, và `netsh wlan show interfaces`
thất bại vì thiếu quyền Location — reconnect SSID trong wifi_recovery sẽ hỏng.

ConsentStore vẫn có thể là Allow; GPO mới là khóa thật.
Không tự gỡ khi Wi-Fi rớt — chỉ khi người dùng bấm «Gỡ khóa Location».
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.logger import logger

POLICY_KEY_PATH = r"SOFTWARE\Policies\Microsoft\Windows\LocationAndSensors"
POLICY_VALUE_NAMES = (
    "DisableLocation",
    "DisableLocationScripting",
    "DisableSensors",
    "DisableWindowsLocationProvider",
)
CONSENT_KEY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location"
CONSENT_VALUE_NAME = "Value"
LFSVC_NAME = "lfsvc"

LOCATION_ERROR_MARKERS = (
    "location permission",
    "location services",
    "location is turned off",
    "location is disabled",
    "enable location",
    "turn on location",
    "access to your location",
    "disablelocation",
    "quyền vị trí",
    "quyen vi tri",
    "dịch vụ vị trí",
    "dich vu vi tri",
    "bật vị trí",
    "bat vi tri",
)

UNLOCK_OK_MARKER = "LOCATION_UNLOCK_OK"
ERROR_CANCELLED = 1223  # ERROR_CANCELLED — user clicked No on UAC
_CACHE_TTL_SEC = 5.0

# Test hooks (offline / Linux CI)
_query_value_fn: Optional[Callable[[Any, str, str], Any]] = None
_elevate_runner: Optional[Callable[..., Dict[str, Any]]] = None
_admin_fn: Optional[Callable[[], bool]] = None
_clock_fn: Optional[Callable[[], float]] = None

_cache: Dict[str, Any] = {"ts": 0.0, "status": None}
_last_logged_locked: Optional[bool] = None


def reset_state() -> None:
    """Xóa cache + hook — dùng cho unit test."""
    global _query_value_fn, _elevate_runner, _admin_fn, _clock_fn, _last_logged_locked
    _query_value_fn = None
    _elevate_runner = None
    _admin_fn = None
    _clock_fn = None
    _last_logged_locked = None
    invalidate_cache()


def invalidate_cache() -> None:
    _cache["ts"] = 0.0
    _cache["status"] = None


def _now() -> float:
    if _clock_fn is not None:
        return float(_clock_fn())
    return time.time()


def _winreg_module():
    import winreg
    return winreg


def _access_masks() -> List[int]:
    winreg = _winreg_module()
    masks = [int(getattr(winreg, "KEY_READ", 0))]
    wow64 = int(getattr(winreg, "KEY_WOW64_64KEY", 0x0100) or 0)
    if wow64:
        masks.append(masks[0] | wow64)
    return masks


def _query_value(hive: Any, path: str, name: str) -> Tuple[bool, Any]:
    """Đọc một giá trị registry. Không cần Admin. Hook được cho unit test."""
    if _query_value_fn is not None:
        try:
            return True, _query_value_fn(hive, path, name)
        except FileNotFoundError:
            return False, None
        except Exception:
            return False, None
    if sys.platform != "win32":
        return False, None
    try:
        winreg = _winreg_module()
    except Exception:
        return False, None
    for access in _access_masks():
        try:
            with winreg.OpenKey(hive, path, 0, access) as key:
                val, _typ = winreg.QueryValueEx(key, name)
                return True, val
        except FileNotFoundError:
            continue
        except OSError:
            continue
        except Exception:
            continue
    return False, None


def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return int(value) if isinstance(value, bool) else None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 0) if text.lower().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return None


def _policy_values() -> Dict[str, Optional[int]]:
    try:
        winreg = _winreg_module()
        hive = winreg.HKEY_LOCAL_MACHINE
    except Exception:
        hive = 2  # winreg stub HKEY_LOCAL_MACHINE
        if _query_value_fn is None:
            return {name: None for name in POLICY_VALUE_NAMES}
    found: Dict[str, Optional[int]] = {}
    for name in POLICY_VALUE_NAMES:
        ok, raw = _query_value(hive, POLICY_KEY_PATH, name)
        found[name] = _as_int(raw) if ok else None
    return found


def _consent_value(hive_name: str) -> Optional[str]:
    try:
        winreg = _winreg_module()
        hive = winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM" else winreg.HKEY_CURRENT_USER
    except Exception:
        hive = 2 if hive_name == "HKLM" else 1
        if _query_value_fn is None:
            return None
    ok, raw = _query_value(hive, CONSENT_KEY_PATH, CONSENT_VALUE_NAME)
    if not ok or raw is None:
        return None
    text = str(raw).strip()
    return text or None


def looks_like_location_permission_error(text: str) -> bool:
    """True nếu stdout/stderr của netsh wlan giống lỗi thiếu quyền Location."""
    blob = str(text or "").strip().lower()
    if not blob:
        return False
    return any(marker in blob for marker in LOCATION_ERROR_MARKERS)


def get_location_lock_status(force: bool = False) -> Dict[str, Any]:
    """
    Ảnh chụp khóa Location. Không cần Admin, không sửa hệ thống.
    locked=True khi bất kỳ DWORD policy (DisableLocation / ...) = 1.
    """
    now = _now()
    cached = _cache.get("status")
    if (
        not force
        and cached is not None
        and (now - float(_cache.get("ts") or 0)) < _CACHE_TTL_SEC
    ):
        return dict(cached)

    policies = _policy_values()
    locked_names = [name for name, val in policies.items() if val == 1]
    locked = bool(locked_names)
    consent_hklm = _consent_value("HKLM")
    consent_hkcu = _consent_value("HKCU")
    consent_denied = any(
        str(v).strip().lower() == "deny" for v in (consent_hklm, consent_hkcu) if v
    )
    status: Dict[str, Any] = {
        "locked": locked,
        "locked_values": locked_names,
        "policies": policies,
        "disable_location": policies.get("DisableLocation"),
        "consent_hklm": consent_hklm,
        "consent_hkcu": consent_hkcu,
        "consent_denied": consent_denied,
        "policy_path": POLICY_KEY_PATH,
        "message": (
            "Location bị khóa bởi Group Policy (DisableLocation=1). "
            "Settings → Privacy → Location bị xám; reconnect SSID có thể thất bại."
            if locked else
            "Location không bị khóa bởi Group Policy."
        ),
    }
    _cache["ts"] = now
    _cache["status"] = dict(status)

    global _last_logged_locked
    if locked != _last_logged_locked:
        logger.info(
            f"[LocationUnlock] Detection locked={locked} "
            f"values={locked_names or '-'} "
            f"DisableLocation={policies.get('DisableLocation')} "
            f"ConsentStore HKLM={consent_hklm or '-'} HKCU={consent_hkcu or '-'}"
        )
        _last_logged_locked = locked
    return status


def is_location_gpo_locked(force: bool = False) -> bool:
    return bool(get_location_lock_status(force=force).get("locked"))


def build_unlock_powershell() -> str:
    """Script một lần: xóa DWORD policy, ConsentStore=Allow, khởi động lfsvc nếu dừng."""
    policy_ps = POLICY_KEY_PATH.replace("\\", "\\")
    names = ", ".join(f"'{n}'" for n in POLICY_VALUE_NAMES)
    return f"""$ErrorActionPreference = 'SilentlyContinue'
$policyPath = 'HKLM:\\{policy_ps}'
$names = @({names})
if (Test-Path -LiteralPath $policyPath) {{
  foreach ($n in $names) {{
    Remove-ItemProperty -LiteralPath $policyPath -Name $n -Force -ErrorAction SilentlyContinue
  }}
}}
$allowPaths = @(
  'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\location',
  'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\location'
)
foreach ($p in $allowPaths) {{
  if (-not (Test-Path -LiteralPath $p)) {{
    New-Item -Path $p -Force | Out-Null
  }}
  Set-ItemProperty -LiteralPath $p -Name 'Value' -Value 'Allow' -Force
}}
$svc = Get-Service -Name '{LFSVC_NAME}' -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -ne 'Running') {{
  Start-Service -Name '{LFSVC_NAME}' -ErrorAction SilentlyContinue
}}
Write-Output '{UNLOCK_OK_MARKER}'
exit 0
"""


def is_admin() -> bool:
    if _admin_fn is not None:
        return bool(_admin_fn())
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _run_powershell_direct(script_path: str, timeout_sec: int = 30) -> Dict[str, Any]:
    import subprocess

    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", script_path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            creationflags=flags,
        )
        stdout = (res.stdout or "").strip()
        stderr = (res.stderr or "").strip()
        return {
            "success": res.returncode == 0 and UNLOCK_OK_MARKER in stdout,
            "cancelled": False,
            "returncode": res.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    except Exception as exc:
        return {
            "success": False,
            "cancelled": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def _run_powershell_elevated(script_path: str, timeout_sec: int = 30) -> Dict[str, Any]:
    """UAC RunAs một lần (ShellExecuteExW). Không lặp, không im lặng."""
    if sys.platform != "win32":
        return {
            "success": False,
            "cancelled": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "not-windows",
        }
    import ctypes
    from ctypes import wintypes

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
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    WAIT_TIMEOUT = 258

    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.hwnd = None
    sei.lpVerb = "runas"
    sei.lpFile = "powershell.exe"
    sei.lpParameters = f'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"'
    sei.lpDirectory = None
    sei.nShow = SW_HIDE

    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
    if not ok:
        err_code = int(ctypes.GetLastError() or 0)
        cancelled = err_code == ERROR_CANCELLED
        return {
            "success": False,
            "cancelled": cancelled,
            "returncode": err_code,
            "stdout": "",
            "stderr": "UAC cancelled" if cancelled else f"ShellExecuteExW error {err_code}",
        }

    if sei.hProcess:
        wait_ms = max(1000, int(timeout_sec * 1000))
        wait = ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, wait_ms)
        exit_code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(sei.hProcess)
        timed_out = int(wait) == WAIT_TIMEOUT
        return {
            "success": (not timed_out) and exit_code.value == 0,
            "cancelled": False,
            "returncode": int(exit_code.value),
            "stdout": "",
            "stderr": "timeout" if timed_out else "",
        }
    return {
        "success": True,
        "cancelled": False,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
    }


def unlock_location_via_uac(timeout_sec: int = 30) -> Dict[str, Any]:
    """
    Gỡ khóa Location một lần qua UAC (hoặc chạy thẳng nếu đã Admin).
    Không gọi từ vòng tự sửa Wi-Fi.
    """
    logger.info("[LocationUnlock] User requested one-shot Location unlock via UAC")
    script = build_unlock_powershell()
    if _elevate_runner is not None:
        raw = _elevate_runner(script, timeout_sec=timeout_sec) or {}
        invalidate_cache()
        after = get_location_lock_status(force=True)
        cancelled = bool(raw.get("cancelled"))
        success = bool(raw.get("success")) and not after.get("locked")
        if cancelled:
            msg = "Bạn đã hủy cửa sổ UAC — Location vẫn bị khóa. Bấm lại «Gỡ khóa Location» khi sẵn sàng."
            logger.warning("[LocationUnlock] UAC cancelled by user")
        elif success:
            msg = "Đã gỡ khóa Location (Group Policy). netsh wlan / reconnect SSID sẽ hoạt động trở lại."
            logger.info("[LocationUnlock] Unlock succeeded; re-check locked=False")
        else:
            msg = str(raw.get("message") or raw.get("stderr") or "Không gỡ được khóa Location.")
            if after.get("locked"):
                msg = (
                    "Đã chạy lệnh gỡ khóa nhưng Group Policy vẫn còn DisableLocation=1. "
                    "Máy domain/MDM có thể ghi lại policy — thử lại hoặc hỏi IT."
                )
            logger.warning(f"[LocationUnlock] Unlock incomplete: {msg}")
        return {
            "success": success,
            "cancelled": cancelled,
            "locked_after": bool(after.get("locked")),
            "status_after": after,
            "message": msg,
            "elevated": True,
        }

    if sys.platform != "win32":
        return {
            "success": False,
            "cancelled": False,
            "locked_after": False,
            "status_after": get_location_lock_status(force=True),
            "message": "Gỡ khóa Location chỉ hỗ trợ trên Windows.",
            "elevated": False,
        }

    already_admin = False
    fd, script_path = tempfile.mkstemp(suffix=".ps1", prefix="pccleaner_locunlock_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(script)
        already_admin = is_admin()
        if already_admin:
            logger.info("[LocationUnlock] Already elevated — running unlock script directly")
            run_res = _run_powershell_direct(script_path, timeout_sec=timeout_sec)
        else:
            logger.info("[LocationUnlock] Launching elevated PowerShell (UAC RunAs)")
            run_res = _run_powershell_elevated(script_path, timeout_sec=timeout_sec)
    finally:
        try:
            os.remove(script_path)
        except Exception:
            pass

    invalidate_cache()
    after = get_location_lock_status(force=True)
    cancelled = bool(run_res.get("cancelled"))
    success = (not cancelled) and (not after.get("locked"))
    if cancelled:
        msg = "Bạn đã hủy cửa sổ UAC — Location vẫn bị khóa. Bấm lại «Gỡ khóa Location» khi sẵn sàng."
        logger.warning("[LocationUnlock] UAC cancelled by user")
    elif success:
        msg = "Đã gỡ khóa Location (Group Policy). netsh wlan / reconnect SSID sẽ hoạt động trở lại."
        logger.info("[LocationUnlock] Unlock succeeded; re-check locked=False")
    elif after.get("locked"):
        err = str(run_res.get("stderr") or "").strip()
        msg = (
            "Không gỡ được khóa Location. Group Policy DisableLocation vẫn = 1."
            + (f" ({err})" if err else "")
            + " Máy domain/MDM có thể ghi lại policy."
        )
        logger.warning(f"[LocationUnlock] Unlock failed, still locked: {run_res}")
    else:
        msg = "Đã gỡ khóa Location."
        success = True
        logger.info("[LocationUnlock] Unlock completed (policy values gone)")
    return {
        "success": success,
        "cancelled": cancelled,
        "locked_after": bool(after.get("locked")),
        "status_after": after,
        "message": msg,
        "elevated": not already_admin,
        "run": run_res,
    }
