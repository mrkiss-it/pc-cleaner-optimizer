"""
Unit tests for GitHub release update checking.
All HTTP is mocked — no live network in CI.
"""
import io
import json
import os
import sys
import types
import urllib.error

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

from core.update_checker import (
    ENV_APP_VERSION,
    ENV_FORCE_NEWER,
    ENV_MOCK_JSON,
    ENV_SKIP_CHECK,
    FetchResult,
    cache_from_config,
    check_for_update,
    compare_versions,
    current_app_version,
    is_newer,
    parse_release_payload,
    parse_version,
    pick_download_asset,
    snippet_release_notes,
)

PASSES = 0


def check(cond, msg):
    global PASSES
    assert cond, msg
    PASSES += 1


def sample_release(**overrides):
    data = {
        "tag_name": "v3.8.0",
        "name": "PC Auto Cleaner 3.8.0",
        "html_url": "https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/tag/v3.8.0",
        "body": "## Mới\n- Kiểm tra cập nhật GitHub Releases\n- Nút Cập nhật trên giao diện",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "PCAutoCleaner_Setup.exe",
                "browser_download_url": "https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/download/v3.8.0/PCAutoCleaner_Setup.exe",
            }
        ],
    }
    data.update(overrides)
    return data


print("===================================================")
print("     UPDATE CHECKER — VERSION / PARSE / MOCK HTTP  ")
print("===================================================")

# --- parse_version ---
check(parse_version("3.7.0") == ((3, 7, 0), ""), "3.7.0")
check(parse_version("v3.7.0") == ((3, 7, 0), ""), "v prefix")
check(parse_version("V3.8") == ((3, 8), ""), "V prefix short")
check(parse_version("3.7.0 Pro") == ((3, 7, 0), ""), "trailing label")
check(parse_version("3.8.0-beta")[0] == (3, 8, 0), "beta numeric")
check(parse_version("3.8.0-beta")[1] == "beta", "beta suffix")
check(parse_version("") == ((0,), ""), "empty")
check(parse_version("not-a-version")[0] == (0,), "garbage numeric")
print(" [PASS] parse_version: tag, v-prefix, Pro label, pre-release, empty")

# --- compare_versions / is_newer ---
check(compare_versions("3.7.0", "3.7.0") == 0, "equal")
check(compare_versions("3.7", "3.7.0") == 0, "pad zeros")
check(compare_versions("v3.8.0", "3.7.0") == 1, "3.8 > 3.7")
check(compare_versions("3.7.0", "3.8.0") == -1, "3.7 < 3.8")
check(compare_versions("3.10.0", "3.9.9") == 1, "10 > 9 not lexicographic")
check(compare_versions("3.8.0", "3.8.0-beta") == 1, "release > pre")
check(compare_versions("3.8.0-beta", "3.8.0") == -1, "pre < release")
check(is_newer("v3.8.0", "3.7.0") is True, "newer true")
check(is_newer("3.7.0", "3.7.0") is False, "same not newer")
check(is_newer("3.6.9", "3.7.0") is False, "older not newer")
check(is_newer("3.7.0-beta", "3.7.0") is False, "beta of same not newer")
print(" [PASS] compare_versions / is_newer: pad, semver-ish, pre-release")

# --- notes snippet ---
snip = snippet_release_notes("## Hello\n\nWorld " + ("x" * 400), limit=40)
check("Hello" in snip and snip.endswith("…"), "snippet trims markdown heading + ellipsis")
check(snippet_release_notes("") == "Xem ghi chú phát hành trên GitHub.", "empty notes fallback")
print(" [PASS] snippet_release_notes")

# --- pick_download_asset ---
setup_url, setup_name = pick_download_asset(
    [
        {"name": "notes.txt", "browser_download_url": "https://ex/notes.txt"},
        {"name": "PCAutoCleaner_Setup.exe", "browser_download_url": "https://ex/PCAutoCleaner_Setup.exe"},
        {"name": "portable.zip", "browser_download_url": "https://ex/portable.zip"},
    ],
    html_url="https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/tag/v1",
)
check(setup_name == "PCAutoCleaner_Setup.exe", "prefer Setup.exe name")
check(setup_url.endswith("PCAutoCleaner_Setup.exe"), "prefer Setup.exe url")

zip_url, zip_name = pick_download_asset(
    [{"name": "PCAutoCleaner_portable.zip", "browser_download_url": "https://ex/p.zip"}],
    html_url="https://github.com/x/y/releases/tag/v1",
)
check(zip_name.endswith(".zip"), "zip when no exe")
check(zip_url == "https://ex/p.zip", "zip url")

page_url, page_name = pick_download_asset(
    [],
    html_url="https://github.com/mrkiss-it/pc-cleaner-optimizer/releases/tag/v9",
)
check(page_name == "", "no asset name")
check("releases" in page_url, "fallback to release page")

un_url, un_name = pick_download_asset(
    [
        {"name": "uninstall.exe", "browser_download_url": "https://ex/uninstall.exe"},
        {"name": "app.zip", "browser_download_url": "https://ex/app.zip"},
    ],
    html_url="https://github.com/x/y/releases/tag/v1",
)
check(un_name == "app.zip", "skip uninstall.exe")
print(" [PASS] pick_download_asset: Setup.exe, zip, empty, skip uninstall")

# --- parse_release_payload ---
info = parse_release_payload(sample_release(), "3.7.0")
check(info is not None, "payload parsed")
check(info.tag == "v3.8.0", "tag")
check(info.asset_name == "PCAutoCleaner_Setup.exe", "asset")
check("Kiểm tra cập nhật" in info.notes_snippet or "GitHub" in info.notes_snippet, "notes")
check(parse_release_payload({"draft": True, "tag_name": "v9"}, "3.7.0") is None, "skip draft")
check(parse_release_payload({"tag_name": ""}, "3.7.0") is None, "skip empty tag")
print(" [PASS] parse_release_payload")

# --- current_app_version env override ---
old_ver = os.environ.get(ENV_APP_VERSION)
os.environ[ENV_APP_VERSION] = "0.0.1"
check(current_app_version() == "0.0.1", "env version override")
if old_ver is None:
    os.environ.pop(ENV_APP_VERSION, None)
else:
    os.environ[ENV_APP_VERSION] = old_ver
print(" [PASS] current_app_version env override")

# --- HTTP mocks ---
CALLS = []


def mock_get_factory(status, body="", headers=None, error=""):
    def _get(url, hdrs, timeout=8.0):
        CALLS.append({"url": url, "headers": dict(hdrs), "timeout": timeout})
        return FetchResult(status=status, body=body, headers=headers or {}, error=error)
    return _get


CALLS.clear()
payload = sample_release()
result = check_for_update(
    current_version="3.7.0",
    cache={},
    http_get=mock_get_factory(200, json.dumps(payload), {"etag": '"abc123"'}),
    now_ts=1_000.0,
    ttl_sec=3600,
    force=True,
)
check(result.ok is True, "200 ok")
check(result.update_available is True, "3.8 newer than 3.7")
check(result.latest is not None and result.latest.tag == "v3.8.0", "latest tag")
check(result.from_cache is False, "not from cache")
check(len(CALLS) == 1, "one http call")
check("api.github.com/repos/mrkiss-it/pc-cleaner-optimizer/releases/latest" in CALLS[0]["url"], "latest endpoint")
check("User-Agent" in CALLS[0]["headers"], "user-agent required by GitHub")
print(" [PASS] check_for_update 200 newer release")

# same version → no update button
same = check_for_update(
    current_version="3.8.0",
    cache={},
    http_get=mock_get_factory(200, json.dumps(payload)),
    now_ts=2_000.0,
    force=True,
)
check(same.ok is True and same.update_available is False, "same version not an update")
check("mới nhất" in same.message, "up to date Vietnamese")
print(" [PASS] check_for_update same version")

# cache TTL: second call without force must not hit network
store = {}
first_get = mock_get_factory(200, json.dumps(payload), {"etag": '"e1"'})
r1 = check_for_update(current_version="3.7.0", cache=store, http_get=first_get, now_ts=10_000.0, ttl_sec=3600, force=False)
check(r1.update_available is True, "first fetch newer")
check(store.get("etag") == '"e1"', "etag stored")

CALLS.clear()
r2 = check_for_update(
    current_version="3.7.0",
    cache=store,
    http_get=mock_get_factory(200, json.dumps(sample_release(tag_name="v9.9.9"))),
    now_ts=10_000.0 + 60,
    ttl_sec=3600,
    force=False,
)
check(r2.from_cache is True, "within TTL uses cache")
check(r2.latest.tag == "v3.8.0", "cached tag not 9.9.9")
check(len(CALLS) == 0, "no HTTP within TTL")
print(" [PASS] cache TTL skips network")

# force bypasses TTL
CALLS.clear()
r3 = check_for_update(
    current_version="3.7.0",
    cache=store,
    http_get=mock_get_factory(200, json.dumps(sample_release(tag_name="v3.9.0")), {"etag": '"e2"'}),
    now_ts=10_000.0 + 70,
    ttl_sec=3600,
    force=True,
)
check(r3.latest.tag == "v3.9.0", "force refresh")
check(len(CALLS) == 1, "force hits network")
print(" [PASS] force=True bypasses TTL")

# 304 Not Modified + If-None-Match
store304 = {
    "last_check_ts": 1.0,
    "etag": '"old"',
    "payload": sample_release(),
}
CALLS.clear()
r304 = check_for_update(
    current_version="3.7.0",
    cache=store304,
    http_get=mock_get_factory(304, "", {}),
    now_ts=10_000_000.0,
    ttl_sec=1.0,
    force=True,
)
check(r304.ok is True and r304.from_cache is True, "304 uses cached payload")
check(r304.latest.tag == "v3.8.0", "304 tag")
check(CALLS[0]["headers"].get("If-None-Match") == '"old"', "sends etag")
print(" [PASS] 304 + If-None-Match")

# quiet failures: 403, 404, 429, offline, bad json
for status, err in ((403, "http"), (404, "http"), (429, "http"), (500, "http")):
    quiet = check_for_update(
        current_version="3.7.0",
        cache={},
        http_get=mock_get_factory(status, "rate limit", error=err),
        now_ts=1.0,
        force=True,
    )
    check(quiet.ok is False and quiet.quiet_failure is True, f"{status} quiet")
    check(quiet.update_available is False, f"{status} no update flag")
    if status == 404:
        check("phát hành" in quiet.message, "404 explains no releases")
    else:
        check(quiet.message == "", f"{status} no nag message")

offline = check_for_update(
    current_version="3.7.0",
    cache={},
    http_get=mock_get_factory(0, error="offline"),
    force=True,
)
check(offline.quiet_failure is True and offline.update_available is False, "offline quiet")

bad_json = check_for_update(
    current_version="3.7.0",
    cache={},
    http_get=mock_get_factory(200, body="not-json{"),
    force=True,
)
check(bad_json.quiet_failure is True, "malformed JSON quiet")
print(" [PASS] 403/404/429/500/offline/bad-json fail quietly")

# no assets → open releases page
no_asset = check_for_update(
    current_version="3.7.0",
    cache={},
    http_get=mock_get_factory(200, json.dumps(sample_release(assets=[]))),
    force=True,
)
check(no_asset.update_available is True, "still an update")
check(no_asset.latest.asset_name == "", "no asset")
check("releases" in no_asset.latest.download_url, "download url is releases page")
print(" [PASS] no assets opens Releases page")

# cache_from_config round-trip shape
cfg = {
    "last_update_check_ts": 42.5,
    "last_update_check_etag": '"x"',
    "cached_release_payload": sample_release(),
    "last_update_check_status": 200,
}
c = cache_from_config(cfg)
check(c["etag"] == '"x"' and c["payload"]["tag_name"] == "v3.8.0", "cache_from_config")
print(" [PASS] cache_from_config")

# SKIP env
os.environ[ENV_SKIP_CHECK] = "1"
skipped = check_for_update(current_version="3.7.0", cache={}, http_get=mock_get_factory(200, json.dumps(payload)), force=True)
check(skipped.quiet_failure is True, "skip env")
os.environ.pop(ENV_SKIP_CHECK, None)
print(" [PASS] PCAUTOCLEANER_SKIP_UPDATE_CHECK")

# mock JSON file (manual verify without network)
import tempfile
fd, mock_path = tempfile.mkstemp(suffix=".json")
os.close(fd)
with open(mock_path, "w", encoding="utf-8") as f:
    json.dump(sample_release(tag_name="v9.0.0"), f)
os.environ[ENV_MOCK_JSON] = mock_path
CALLS.clear()
mocked = check_for_update(
    current_version="3.7.0",
    cache={},
    http_get=mock_get_factory(200, json.dumps(sample_release(tag_name="v1.0.0"))),
    force=True,
)
check(mocked.latest.tag == "v9.0.0", "mock json file wins")
check(len(CALLS) == 0, "mock json does not call http_get")
os.environ.pop(ENV_MOCK_JSON, None)
os.remove(mock_path)
print(" [PASS] PCAUTOCLEANER_UPDATE_MOCK_JSON")

# FORCE_NEWER treats same tag as update (local verify)
os.environ[ENV_FORCE_NEWER] = "1"
forced = check_for_update(
    current_version="3.8.0",
    cache={},
    http_get=mock_get_factory(200, json.dumps(payload)),
    force=True,
)
check(forced.update_available is True, "force newer flag")
os.environ.pop(ENV_FORCE_NEWER, None)
print(" [PASS] PCAUTOCLEANER_UPDATE_FORCE_NEWER")

# default_http_get uses urllib — patch urlopen, still no live network
from unittest.mock import patch

class _OkResp:
    status = 200
    headers = {"ETag": '"net"'}
    def read(self):
        return json.dumps(sample_release()).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_a):
        return False

with patch("urllib.request.urlopen", return_value=_OkResp()):
    via_urllib = check_for_update(current_version="3.7.0", cache={}, force=True, ttl_sec=0)
check(via_urllib.update_available is True, "urlopen mock")

def _raise_offline(req, timeout=8.0):
    raise urllib.error.URLError("offline")

with patch("urllib.request.urlopen", side_effect=_raise_offline):
    via_off = check_for_update(current_version="3.7.0", cache={}, force=True, ttl_sec=0)
check(via_off.quiet_failure is True, "URLError quiet")

def _http_403(req, timeout=8.0):
    raise urllib.error.HTTPError(
        "https://api.github.com/repos/mrkiss-it/pc-cleaner-optimizer/releases/latest",
        403, "rate limit", hdrs=None, fp=io.BytesIO(b"nope"),
    )

with patch("urllib.request.urlopen", side_effect=_http_403):
    via_403 = check_for_update(current_version="3.7.0", cache={}, force=True, ttl_sec=0)
check(via_403.quiet_failure is True and via_403.http_status == 403, "HTTPError 403")
print(" [PASS] urllib.request.urlopen patched (200 / URLError / 403)")

print(f"\n>>> {PASSES} assertions — update checker unit tests OK <<<")
