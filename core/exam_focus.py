"""
Chế độ Trước thi / họp (Exam / Meeting Focus).

Một nút bật/tắt: chuẩn bị máy cho buổi tập trung yên tĩnh, rồi khôi phục
đúng những gì chế độ này đã đổi (cùng kiểu hoàn tác như Game Boost).

An toàn theo thiết kế:
- Dọn rác NHẸ: chỉ temp/crash dump mà JunkCleaner đã dọn an toàn.
  Không dọn Recycle Bin, cache trình duyệt, Windows Update, WinSxS, registry.
- Giảm nhiễu: tạm tắt thông báo của CHÍNH ứng dụng; tùy chọn chặn khảo sát
  Feedback Hub nếu SystemTweaker chưa áp dụng. Không đụng Focus Assist
  (Quiet Hours / CloudStore) — không khôi phục được tin cậy.
- Ưu tiên tài nguyên: RAM trim + hạ BACKGROUND_HOGS giống Game Boost.
  Bảo vệ Zoom/Teams/trình duyệt họp. Không boost game, không đụng DNS/Wi-Fi.
"""

from typing import Any, Callable, Dict, List, Optional, Set

from core.logger import logger
from core.game_booster import BACKGROUND_HOGS, GameBooster
from core.memory_optimizer import MemoryOptimizer
from core.cleaner import JunkCleaner

# Temp/crash only — never WinSxS, registry, recycle bin, browser, Windows Update.
LIGHT_CLEAN_TARGETS: Dict[str, bool] = {
    "user_temp": True,
    "system_temp": True,
    "crash_dumps": True,
    "recycle_bin": False,
    "browser_cache": False,
    "windows_update": False,
    "app_caches": False,
    "ram_optimize": False,
}

# Do not EmptyWorkingSet / demote processes that a meeting or exam session needs.
MEETING_PROTECT: Set[str] = {
    "zoom.exe",
    "teams.exe",
    "ms-teams.exe",
    "msteams.exe",
    "skype.exe",
    "skypeapp.exe",
    "webex.exe",
    "ciscowebexstart.exe",
    "slack.exe",
    "discord.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "outlook.exe",
    "olk.exe",
    "powerpnt.exe",
    "winword.exe",
    "excel.exe",
    "obs64.exe",
    "obs32.exe",
}

NETWORK_TIP = "Mạng: không đổi DNS hay Wi-Fi — giữ kết nối họp ổn định."

# Feedback Hub survey popups — reversible via SystemTweaker, not Focus Assist.
_FEEDBACK_TWEAK_ID = "disable_feedback_prompts"


class ExamMeetingFocus:
    """
    Chế độ Trước thi / họp.

    Bật: dọn temp nhẹ, thu hồi RAM, hạ tiến trình nền, giảm thông báo app.
    Tắt: khôi phục độ ưu tiên tiến trình và các tinh chỉnh nhiễu đã áp dụng.
    """

    _is_active: bool = False
    _saved_priorities: Dict[int, int] = {}
    _applied_feedback_tweak: bool = False
    _suppress_app_toasts: bool = False
    _last_result: Dict[str, Any] = {}

    @classmethod
    def is_active(cls) -> bool:
        return cls._is_active

    @classmethod
    def should_suppress_app_toasts(cls) -> bool:
        """True while focus mode is on — PC Cleaner itself stays quiet."""
        return cls._is_active and cls._suppress_app_toasts

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._is_active = False
        cls._saved_priorities = {}
        cls._applied_feedback_tweak = False
        cls._suppress_app_toasts = False
        cls._last_result = {}

    @classmethod
    def enable(
        cls,
        whitelist: Optional[Set[str]] = None,
        *,
        cleaner: Optional[Any] = None,
        ram_optimizer: Optional[Any] = None,
        process_iter: Optional[Callable] = None,
        tweaker: Optional[Any] = None,
        game_booster: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Bật chế độ. Mỗi bước ghi success/error riêng để UI báo thật.
        """
        if cls._is_active:
            return {
                "success": True,
                "already_active": True,
                "is_active": True,
                "message": "Chế độ Trước thi / họp đã đang bật",
                "steps": [],
                "failed_steps": [],
                "network_changed": False,
                "network_tip": NETWORK_TIP,
            }

        logger.info("[ExamMeetingFocus] Đang bật chế độ Trước thi / họp...")
        cls._saved_priorities = {}
        cls._applied_feedback_tweak = False
        cls._suppress_app_toasts = False

        safe_whitelist = set(whitelist or set())
        protect = {n.lower() for n in (safe_whitelist | MEETING_PROTECT)}
        steps: List[Dict[str, Any]] = []

        steps.append(cls._step_light_clean(cleaner))
        steps.append(cls._step_ram_trim(protect, ram_optimizer))
        steps.append(
            cls._step_demote_background(
                protect,
                process_iter=process_iter,
                game_booster=game_booster,
            )
        )
        steps.append(cls._step_reduce_noise(tweaker))

        failed = [s for s in steps if not s.get("success")]
        # Mode is active if we have anything to restore, or all steps at least ran.
        cls._is_active = True
        cls._suppress_app_toasts = True

        result = {
            "success": len(failed) == 0,
            "already_active": False,
            "is_active": True,
            "steps": steps,
            "failed_steps": [s.get("id") for s in failed],
            "freed_junk_mb": _step_value(steps, "light_clean", "freed_mb", 0.0),
            "deleted_files": _step_value(steps, "light_clean", "deleted_files", 0),
            "freed_ram_mb": _step_value(steps, "ram_trim", "freed_mb", 0.0),
            "demoted_count": _step_value(steps, "resource_priority", "demoted_count", 0),
            "skipped_game_boost": _step_value(
                steps, "resource_priority", "skipped_game_boost", False
            ),
            "noise_reduced": _step_value(steps, "reduce_noise", "success", False),
            "network_changed": False,
            "network_tip": NETWORK_TIP,
            "message": format_enable_message(steps, failed),
        }
        cls._last_result = result
        logger.info(f"[ExamMeetingFocus] {result['message']}")
        return result

    @classmethod
    def disable(
        cls,
        *,
        process_ctor: Optional[Callable] = None,
        tweaker: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Tắt chế độ và khôi phục những gì đã đổi."""
        if not cls._is_active:
            return {
                "success": True,
                "already_inactive": True,
                "is_active": False,
                "message": "Chế độ Trước thi / họp chưa được bật",
                "steps": [],
                "failed_steps": [],
                "restored_count": 0,
                "network_changed": False,
            }

        logger.info("[ExamMeetingFocus] Đang tắt chế độ, khôi phục hệ thống...")
        steps: List[Dict[str, Any]] = []
        steps.append(cls._restore_priorities(process_ctor))
        steps.append(cls._restore_noise(tweaker))

        cls._suppress_app_toasts = False
        cls._is_active = False
        cls._saved_priorities = {}
        cls._applied_feedback_tweak = False

        failed = [s for s in steps if not s.get("success")]
        restored_count = int(_step_value(steps, "restore_priority", "restored_count", 0))
        result = {
            "success": len(failed) == 0,
            "already_inactive": False,
            "is_active": False,
            "steps": steps,
            "failed_steps": [s.get("id") for s in failed],
            "restored_count": restored_count,
            "network_changed": False,
            "network_tip": NETWORK_TIP,
            "message": format_disable_message(steps, failed, restored_count),
        }
        cls._last_result = result
        logger.info(f"[ExamMeetingFocus] {result['message']}")
        return result

    # ------------------------------------------------------------------
    # Enable steps
    # ------------------------------------------------------------------
    @classmethod
    def _step_light_clean(cls, cleaner: Optional[Any]) -> Dict[str, Any]:
        engine = cleaner if cleaner is not None else JunkCleaner
        try:
            res = engine.clean(dict(LIGHT_CLEAN_TARGETS))
            freed = float(res.get("total_freed_mb", 0.0) or 0.0)
            deleted = int(res.get("total_deleted_files", 0) or 0)
            return {
                "id": "light_clean",
                "label": "Dọn rác nhẹ (temp / crash dump)",
                "success": True,
                "freed_mb": freed,
                "deleted_files": deleted,
                "detail": f"Đã giải phóng {freed:.1f} MB ({deleted} tệp).",
            }
        except Exception as e:
            logger.warning(f"[ExamMeetingFocus] Light clean failed: {e}")
            return {
                "id": "light_clean",
                "label": "Dọn rác nhẹ (temp / crash dump)",
                "success": False,
                "freed_mb": 0.0,
                "deleted_files": 0,
                "error": str(e),
                "detail": f"Không dọn được rác nhẹ: {e}",
            }

    @classmethod
    def _step_ram_trim(
        cls, protect: Set[str], ram_optimizer: Optional[Any]
    ) -> Dict[str, Any]:
        engine = ram_optimizer if ram_optimizer is not None else MemoryOptimizer
        try:
            res = engine.optimize_ram(whitelist=protect)
            freed = float(res.get("freed_mb", 0.0) or 0.0)
            flushed = int(res.get("processes_flushed", 0) or 0)
            return {
                "id": "ram_trim",
                "label": "Thu hồi RAM nhẹ",
                "success": bool(res.get("success", True)),
                "freed_mb": freed,
                "processes_flushed": flushed,
                "detail": f"Thu hồi {freed:.1f} MB RAM từ {flushed} tiến trình.",
            }
        except Exception as e:
            logger.warning(f"[ExamMeetingFocus] RAM trim failed: {e}")
            return {
                "id": "ram_trim",
                "label": "Thu hồi RAM nhẹ",
                "success": False,
                "freed_mb": 0.0,
                "error": str(e),
                "detail": f"Không thu hồi được RAM: {e}",
            }

    @classmethod
    def _step_demote_background(
        cls,
        protect: Set[str],
        process_iter: Optional[Callable] = None,
        game_booster: Optional[Any] = None,
    ) -> Dict[str, Any]:
        booster = game_booster if game_booster is not None else GameBooster
        if booster.is_active():
            return {
                "id": "resource_priority",
                "label": "Hạ ưu tiên tác vụ nền",
                "success": True,
                "demoted_count": 0,
                "skipped_game_boost": True,
                "detail": "Game Boost đang bật — bỏ qua đổi ưu tiên để không xung đột.",
            }

        import psutil

        iterate = process_iter or psutil.process_iter
        idle = getattr(psutil, "IDLE_PRIORITY_CLASS", None)
        demoted = 0
        errors = 0

        try:
            for proc in iterate(["pid", "name"]):
                try:
                    info = proc.info if hasattr(proc, "info") else {}
                    pid = info.get("pid") if info else proc.pid
                    name = (info.get("name") or getattr(proc, "name", lambda: "")() or "").lower()
                    if pid in (0, 4) or not name:
                        continue
                    if name in protect:
                        continue
                    if name not in BACKGROUND_HOGS:
                        continue
                    old_prio = proc.nice()
                    cls._saved_priorities[int(pid)] = old_prio
                    if idle is not None:
                        proc.nice(idle)
                    else:
                        proc.nice(19)
                    demoted += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception:
                    errors += 1
                    continue
        except Exception as e:
            logger.warning(f"[ExamMeetingFocus] Demote scan failed: {e}")
            return {
                "id": "resource_priority",
                "label": "Hạ ưu tiên tác vụ nền",
                "success": False,
                "demoted_count": demoted,
                "skipped_game_boost": False,
                "error": str(e),
                "detail": f"Không điều chỉnh được tiến trình nền: {e}",
            }

        ok = errors == 0 or demoted > 0
        detail = f"Đã hạ ưu tiên {demoted} tác vụ nền (Search, Update, sync)."
        if errors and demoted == 0:
            detail = "Không hạ được tiến trình nền (thiếu quyền hoặc không có tiến trình phù hợp)."
            ok = True  # empty/no-permission is not a hard failure
        return {
            "id": "resource_priority",
            "label": "Hạ ưu tiên tác vụ nền",
            "success": ok,
            "demoted_count": demoted,
            "skipped_game_boost": False,
            "detail": detail,
        }

    @classmethod
    def _step_reduce_noise(cls, tweaker: Optional[Any]) -> Dict[str, Any]:
        """
        Mute this app's toasts + optionally apply Feedback Hub block.
        Never writes Focus Assist / Quiet Hours keys.
        """
        cls._suppress_app_toasts = True
        applied_feedback = False
        feedback_detail = "Không đổi Feedback Hub (đã tối ưu sẵn hoặc bỏ qua)."

        try:
            from core.system_tweaker import SystemTweaker

            tw = tweaker if tweaker is not None else SystemTweaker()
            if not tw.is_applied(_FEEDBACK_TWEAK_ID):
                ok, msg = tw.apply_tweak(_FEEDBACK_TWEAK_ID)
                if ok:
                    cls._applied_feedback_tweak = True
                    applied_feedback = True
                    feedback_detail = "Đã tạm tắt khảo sát Windows Feedback Hub."
                else:
                    feedback_detail = f"Không tắt được khảo sát Feedback Hub: {msg}"
                    return {
                        "id": "reduce_noise",
                        "label": "Giảm thông báo",
                        "success": True,  # app mute still applied
                        "applied_feedback": False,
                        "app_muted": True,
                        "detail": (
                            "Đã tắt thông báo của ứng dụng này. "
                            f"{feedback_detail}"
                        ),
                        "warning": msg,
                    }
        except Exception as e:
            logger.warning(f"[ExamMeetingFocus] Noise reduction tweak failed: {e}")
            feedback_detail = f"Bỏ qua tinh chỉnh Feedback Hub: {e}"

        return {
            "id": "reduce_noise",
            "label": "Giảm thông báo",
            "success": True,
            "applied_feedback": applied_feedback,
            "app_muted": True,
            "detail": (
                "Đã tắt thông báo của ứng dụng này trong phiên. "
                f"{feedback_detail} Không đụng Focus Assist."
            ),
        }

    # ------------------------------------------------------------------
    # Restore steps
    # ------------------------------------------------------------------
    @classmethod
    def _restore_priorities(cls, process_ctor: Optional[Callable]) -> Dict[str, Any]:
        import psutil

        ctor = process_ctor or psutil.Process
        restored = 0
        for pid, old_prio in list(cls._saved_priorities.items()):
            try:
                proc = ctor(pid)
                proc.nice(old_prio)
                restored += 1
            except Exception:
                continue
        return {
            "id": "restore_priority",
            "label": "Khôi phục ưu tiên tiến trình",
            "success": True,
            "restored_count": restored,
            "detail": f"Đã khôi phục {restored} tiến trình về mức ưu tiên cũ.",
        }

    @classmethod
    def _restore_noise(cls, tweaker: Optional[Any]) -> Dict[str, Any]:
        cls._suppress_app_toasts = False
        if not cls._applied_feedback_tweak:
            return {
                "id": "restore_noise",
                "label": "Khôi phục thông báo",
                "success": True,
                "reverted_feedback": False,
                "detail": "Đã bật lại thông báo của ứng dụng. Không đổi Focus Assist.",
            }
        try:
            from core.system_tweaker import SystemTweaker

            tw = tweaker if tweaker is not None else SystemTweaker()
            ok, msg = tw.revert_tweak(_FEEDBACK_TWEAK_ID)
            return {
                "id": "restore_noise",
                "label": "Khôi phục thông báo",
                "success": bool(ok),
                "reverted_feedback": bool(ok),
                "detail": (
                    "Đã bật lại thông báo của ứng dụng. "
                    + (msg if ok else f"Không hoàn tác được Feedback Hub: {msg}")
                ),
                "error": None if ok else str(msg),
            }
        except Exception as e:
            logger.warning(f"[ExamMeetingFocus] Restore noise failed: {e}")
            return {
                "id": "restore_noise",
                "label": "Khôi phục thông báo",
                "success": False,
                "reverted_feedback": False,
                "error": str(e),
                "detail": f"Đã bật lại thông báo app. Lỗi hoàn tác Feedback Hub: {e}",
            }


def _step_value(steps: List[Dict[str, Any]], step_id: str, key: str, default: Any) -> Any:
    for s in steps:
        if s.get("id") == step_id:
            return s.get(key, default)
    return default


def format_enable_message(steps: List[Dict[str, Any]], failed: List[Dict[str, Any]]) -> str:
    bits = []
    for s in steps:
        bits.append(s.get("detail") or s.get("label", s.get("id")))
    bits.append(NETWORK_TIP)
    if failed:
        names = ", ".join(s.get("label") or s.get("id") for s in failed)
        return f"Đã bật chế độ Trước thi / họp (một số bước lỗi: {names}). " + " ".join(bits)
    return "Đã bật chế độ Trước thi / họp. " + " ".join(bits)


def format_disable_message(
    steps: List[Dict[str, Any]], failed: List[Dict[str, Any]], restored_count: int
) -> str:
    if failed:
        names = ", ".join(s.get("label") or s.get("id") for s in failed)
        return (
            f"Đã tắt chế độ Trước thi / họp. Khôi phục {restored_count} tiến trình "
            f"(một số bước lỗi: {names})."
        )
    return f"Đã tắt chế độ Trước thi / họp. Khôi phục {restored_count} tiến trình về trạng thái cũ."
