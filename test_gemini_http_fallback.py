"""
Unit tests for Cloud Gemini HTTP fallback (404 / 429 / 503).
Stubs Windows-only bits so this file can run offscreen on Linux CI.
"""
import io
import json
import os
import sys
import types
import urllib.error
from unittest.mock import patch

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

from core.ai_copilot import (
    CloudAIBrain,
    format_gemini_http_error,
    gemini_http_should_fallback,
)

_TELEMETRY = {
    "ram": {"percent": 70.0, "used_gb": 5.0, "total_gb": 8.0},
    "cpu": {"percent": 20.0, "count": 4},
    "disk": {"free_gb": 40.0, "total_gb": 256.0},
}

_RAW_503 = (
    '{"error":{"code":503,"message":"This model is currently experiencing high demand. '
    'Please try again later or switch to another model.","status":"UNAVAILABLE"}}'
)
_RAW_404 = (
    '{"error":{"code":404,"message":"models/gemini-2.5-flash is not found for API version v1beta, '
    'or is not supported for generateContent.","status":"NOT_FOUND"}}'
)


def _http_error(url, code, body):
    return urllib.error.HTTPError(url, code, "error", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


class _OkResp:
    status = 200

    def __init__(self, text):
        self._payload = json.dumps({
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]
        }).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_fallback_codes():
    assert gemini_http_should_fallback(404)
    assert gemini_http_should_fallback(429)
    assert gemini_http_should_fallback(503)
    assert not gemini_http_should_fallback(401)
    assert not gemini_http_should_fallback(403)
    assert not gemini_http_should_fallback(500)


def test_format_503_vietnamese():
    msg = format_gemini_http_error(503, _RAW_503)
    assert msg.startswith("HTTP 503:")
    assert "quá tải" in msg
    assert "{" not in msg


def test_503_then_next_model_success_and_persist():
    urls = []
    saved = {}

    def urlopen(req, timeout=8.0):
        url = getattr(req, "full_url", str(req))
        urls.append(url)
        if "gemini-flash-latest" in url:
            raise _http_error(url, 503, _RAW_503)
        if "gemini-3.1-flash-lite" in url:
            return _OkResp("RAM đang cao, hãy thu hồi bộ nhớ standby.")
        raise _http_error(url, 503, _RAW_503)

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = CloudAIBrain.query_gemini(
            api_key="AIzaSyTESTKEY",
            user_prompt="May ngong RAM",
            telemetry=_TELEMETRY,
            model="gemini-flash-latest",
            persist_model=lambda m: saved.update(model=m),
        )
    assert reply and "RAM" in reply
    assert CloudAIBrain.last_working_model == "gemini-3.1-flash-lite"
    assert saved.get("model") == "gemini-3.1-flash-lite"
    assert not CloudAIBrain.last_error
    assert "gemini-flash-latest" in urls[0]
    assert "gemini-3.1-flash-lite" in urls[1]


def test_all_503_vietnamese_status():
    urls = []
    saved = {}

    def urlopen(req, timeout=8.0):
        url = getattr(req, "full_url", str(req))
        urls.append(url)
        raise _http_error(url, 503, _RAW_503)

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = CloudAIBrain.query_gemini(
            api_key="AIzaSyTESTKEY",
            user_prompt="hi",
            telemetry=_TELEMETRY,
            model="gemini-flash-latest",
            persist_model=lambda m: saved.update(model=m),
        )
    assert reply is None
    assert "Google Gemini đang quá tải trên mọi model đã thử" in CloudAIBrain.last_error
    assert CloudAIBrain.last_error_short == (
        "Google Gemini đang quá tải trên mọi model đã thử — thử lại sau."
    )
    assert len(urls) >= 2
    assert "{" not in CloudAIBrain.last_error
    assert "model" not in saved, "failed/overloaded model must not be persisted as default"


def test_429_then_success():
    urls = []

    def urlopen(req, timeout=8.0):
        url = getattr(req, "full_url", str(req))
        urls.append(url)
        if "gemini-flash-latest" in url:
            raise _http_error(
                url, 429,
                '{"error":{"message":"Resource exhausted","status":"RESOURCE_EXHAUSTED"}}',
            )
        return _OkResp("Mạng ổn định.")

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = CloudAIBrain.query_gemini(
            api_key="AIzaSyTESTKEY",
            user_prompt="ping",
            telemetry=_TELEMETRY,
            model="gemini-flash-latest",
        )
    assert reply and "Mạng" in reply
    assert len(urls) >= 2
    assert CloudAIBrain.last_working_model != "gemini-flash-latest"


def test_401_still_stops():
    urls = []

    def urlopen(req, timeout=8.0):
        url = getattr(req, "full_url", str(req))
        urls.append(url)
        raise _http_error(url, 401, '{"error":{"message":"API key not valid"}}')

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = CloudAIBrain.query_gemini(
            api_key="AIzaSyBAD",
            user_prompt="hi",
            telemetry=_TELEMETRY,
            model="gemini-flash-latest",
        )
    assert reply is None
    assert len(urls) == 1
    assert "API key not valid" in CloudAIBrain.last_error
    assert "quá tải trên mọi model" not in CloudAIBrain.last_error


def test_404_still_falls_back():
    urls = []

    def urlopen(req, timeout=8.0):
        url = getattr(req, "full_url", str(req))
        urls.append(url)
        if "gemini-2.5-flash" in url:
            raise _http_error(url, 404, _RAW_404)
        if "gemini-flash-latest" in url:
            return _OkResp("OK")
        raise _http_error(url, 404, '{"error":{"message":"model not found"}}')

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = CloudAIBrain.query_gemini(
            api_key="AIzaSyTESTKEY",
            user_prompt="hi",
            telemetry=_TELEMETRY,
            model="gemini-2.5-flash",
        )
    assert reply == "OK"
    assert CloudAIBrain.last_working_model == "gemini-flash-latest"
    assert any("gemini-2.5-flash" in u for u in urls)


if __name__ == "__main__":
    tests = [
        test_fallback_codes,
        test_format_503_vietnamese,
        test_503_then_next_model_success_and_persist,
        test_all_503_vietnamese_status,
        test_429_then_success,
        test_401_still_stops,
        test_404_still_falls_back,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] gemini HTTP fallback suite")
