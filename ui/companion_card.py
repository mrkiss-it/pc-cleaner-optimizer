"""
Thẻ AI đồng hành — giai đoạn, nhật ký, kỹ năng, sổ tay (tiếng Việt).

Empty-state trung thực khi cài mới. Không nhận là AGI.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_NAME
from core.companion import (
    REFLECT_BUTTON_VI,
    accept_skill_offer,
    clear_diary_memory,
    clear_local_memory,
    clear_reflection_memory,
    clear_skills_memory,
    confirm_clear_prompt,
    current_stage,
    decline_skill_offer,
    delete_diary_entry,
    delete_saved_skill,
    diary_digest,
    active_guidance_text,
    empty_states_vi,
    explain_stage_progress,
    format_event_row,
    format_reflection_feedback,
    format_skill_row,
    is_enabled,
    latest_reflection,
    list_diary_rows,
    list_skill_rows,
    load_reflection_meta,
    maybe_run_reflection,
    note_user_feedback,
    clear_profile_habits,
    pending_skill_offer,
    recent_learning_text,
    stage_legend_vi,
)
from core.companion_profile import (
    current_insight,
    dismiss_insight,
    format_profile_browse,
    goal_status,
    set_goal,
)


_STAGE_COLORS = {
    0: "#94a3b8",
    1: "#38bdf8",
    2: "#a78bfa",
    3: "#34d399",
}

_BTN_STYLE = """
    QPushButton {
        background-color: #334155;
        color: #f8fafc;
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 11px;
        border: 1px solid #475569;
    }
    QPushButton:hover { background-color: #475569; border-color: #38bdf8; }
    QPushButton:disabled { color: #64748b; border-color: #334155; }
"""

_DANGER_BTN_STYLE = """
    QPushButton {
        background-color: #3f1d2e;
        color: #fecdd3;
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 11px;
        border: 1px solid #9f1239;
    }
    QPushButton:hover { background-color: #4c1d32; border-color: #fb7185; }
    QPushButton:disabled { color: #64748b; border-color: #334155; background: #1e293b; }
"""

_LIST_STYLE = """
    QListWidget {
        background: #0f172a;
        color: #e2e8f0;
        border: 1px solid #334155;
        border-radius: 8px;
        font-size: 12px;
        padding: 4px;
    }
    QListWidget::item { padding: 4px 6px; }
    QListWidget::item:selected { background: #334155; color: #f8fafc; }
"""


def _plain_label(text_color: str) -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    label.setStyleSheet(
        f"color: {text_color}; font-size: 12px; background: transparent; border: none;"
    )
    return label


class CompanionInsightBar(QFrame):
    """Calm local lines: stage-up, check-in, follow-up, end of day, and «Hôm nay: …»."""

    dismissed = pyqtSignal()
    action_requested = pyqtSignal(str)
    goal_edit_requested = pyqtSignal()

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self._insight_id = ""
        self._insight_topic = ""
        self._action_key = ""
        self._skill_id = ""
        self._checkin_action = ""
        self._checkin_skill_id = ""
        self._follow_topic = ""
        self.setObjectName("CompanionInsightBar")
        self.setStyleSheet(
            "QFrame#CompanionInsightBar { background-color: #1e1b4b; border: 1px solid #4338ca; "
            "border-radius: 10px; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        self.row_stage = QWidget()
        stage_row = QHBoxLayout(self.row_stage)
        stage_row.setContentsMargins(0, 0, 0, 0)
        stage_row.setSpacing(8)
        self.lbl_stage = _plain_label("#fde68a")
        self.btn_stage_ok = QPushButton("Đã rõ")
        self.btn_stage_ok.setStyleSheet(_BTN_STYLE)
        self.btn_stage_ok.setToolTip("Mình chỉ chúc mừng giai đoạn này một lần.")
        self.btn_stage_ok.clicked.connect(self._dismiss_stage)
        stage_row.addWidget(self.lbl_stage, stretch=1)
        stage_row.addWidget(self.btn_stage_ok)
        self.row_stage.hide()

        self.row_milestone = QWidget()
        mile_row = QHBoxLayout(self.row_milestone)
        mile_row.setContentsMargins(0, 0, 0, 0)
        mile_row.setSpacing(8)
        self.lbl_milestone = _plain_label("#fde68a")
        self.btn_milestone_ok = QPushButton("Đã rõ")
        self.btn_milestone_ok.setStyleSheet(_BTN_STYLE)
        self.btn_milestone_ok.setToolTip("Mình chỉ nhắc cột mốc này một lần.")
        self.btn_milestone_ok.clicked.connect(self._dismiss_milestone)
        mile_row.addWidget(self.lbl_milestone, stretch=1)
        mile_row.addWidget(self.btn_milestone_ok)
        self.row_milestone.hide()

        self.row_week = QWidget()
        week_row = QHBoxLayout(self.row_week)
        week_row.setContentsMargins(0, 0, 0, 0)
        week_row.setSpacing(8)
        self.lbl_week = _plain_label("#ddd6fe")
        self.btn_week_hide = QPushButton("Ẩn")
        self.btn_week_hide.setStyleSheet(_BTN_STYLE)
        self.btn_week_hide.setToolTip("Ẩn tóm tắt tuần này.")
        self.btn_week_hide.clicked.connect(self._dismiss_week)
        week_row.addWidget(self.lbl_week, stretch=1)
        week_row.addWidget(self.btn_week_hide)
        self.row_week.hide()

        self.row_pins = QWidget()
        pins_row = QHBoxLayout(self.row_pins)
        pins_row.setContentsMargins(0, 0, 0, 0)
        pins_row.setSpacing(8)
        self.lbl_pins = _plain_label("#c4b5fd")
        pins_row.addWidget(self.lbl_pins)
        self.pin_action_buttons = []
        self.pin_unpin_buttons = []
        self._pin_keys: list = []
        for index in range(3):
            action = QPushButton("")
            action.setStyleSheet(_BTN_STYLE)
            action.setToolTip("Một việc đã ghim. Mình không tự chạy.")
            action.clicked.connect(lambda _checked=False, i=index: self._activate_pin(i))
            unpin = QPushButton("Bỏ ghim")
            unpin.setStyleSheet(_BTN_STYLE)
            unpin.setToolTip("Bỏ ghim việc này. Mình không tự chạy.")
            unpin.clicked.connect(lambda _checked=False, i=index: self._unpin_at(i))
            action.hide()
            unpin.hide()
            pins_row.addWidget(action)
            pins_row.addWidget(unpin)
            self.pin_action_buttons.append(action)
            self.pin_unpin_buttons.append(unpin)
        pins_row.addStretch(1)
        self.row_pins.hide()

        self.row_checkin = QWidget()
        check_row = QHBoxLayout(self.row_checkin)
        check_row.setContentsMargins(0, 0, 0, 0)
        check_row.setSpacing(8)
        self.lbl_checkin = _plain_label("#c7d2fe")
        self.btn_checkin_action = QPushButton("")
        self.btn_checkin_action.setStyleSheet(_BTN_STYLE)
        self.btn_checkin_action.setToolTip("Một việc an toàn. Mình không tự chạy.")
        self.btn_checkin_action.clicked.connect(self._activate_checkin)
        self.btn_checkin_action.hide()
        self.btn_checkin_hide = QPushButton("Ẩn")
        self.btn_checkin_hide.setStyleSheet(_BTN_STYLE)
        self.btn_checkin_hide.setToolTip("Ẩn lời chào hôm nay.")
        self.btn_checkin_hide.clicked.connect(self._dismiss_checkin)
        check_row.addWidget(self.lbl_checkin, stretch=1)
        check_row.addWidget(self.btn_checkin_action)
        check_row.addWidget(self.btn_checkin_hide)
        self.row_checkin.hide()

        self.row_follow = QWidget()
        follow_row = QHBoxLayout(self.row_follow)
        follow_row.setContentsMargins(0, 0, 0, 0)
        follow_row.setSpacing(8)
        self.lbl_follow = _plain_label("#ddd6fe")
        self.btn_follow_yes = QPushButton("Có ích")
        self.btn_follow_yes.setStyleSheet(_BTN_STYLE)
        self.btn_follow_yes.setToolTip("Ghi lại là việc vừa rồi có giúp máy này.")
        self.btn_follow_yes.clicked.connect(lambda: self._answer_followup(True))
        self.btn_follow_no = QPushButton("Chưa")
        self.btn_follow_no.setStyleSheet(_BTN_STYLE)
        self.btn_follow_no.setToolTip("Ghi lại là việc vừa rồi chưa giúp. Mình sẽ đề xuất ít hơn.")
        self.btn_follow_no.clicked.connect(lambda: self._answer_followup(False))
        self.btn_follow_hide = QPushButton("Ẩn")
        self.btn_follow_hide.setStyleSheet(_BTN_STYLE)
        self.btn_follow_hide.setToolTip("Ẩn câu hỏi này. Không tính là từ chối.")
        self.btn_follow_hide.clicked.connect(self._dismiss_followup)
        self.btn_follow_pin = QPushButton("Ghim")
        self.btn_follow_pin.setStyleSheet(_BTN_STYLE)
        self.btn_follow_pin.setToolTip("Ghim việc vừa rồi (tối đa 3). Mình không tự chạy.")
        self.btn_follow_pin.clicked.connect(self._toggle_pin_follow)
        self.btn_follow_pin.hide()
        follow_row.addWidget(self.lbl_follow, stretch=1)
        follow_row.addWidget(self.btn_follow_yes)
        follow_row.addWidget(self.btn_follow_no)
        follow_row.addWidget(self.btn_follow_pin)
        follow_row.addWidget(self.btn_follow_hide)
        self.row_follow.hide()

        self.row_eod = QWidget()
        eod_row = QHBoxLayout(self.row_eod)
        eod_row.setContentsMargins(0, 0, 0, 0)
        eod_row.setSpacing(8)
        self.lbl_eod = _plain_label("#e9d5ff")
        self.btn_eod_hide = QPushButton("Ẩn")
        self.btn_eod_hide.setStyleSheet(_BTN_STYLE)
        self.btn_eod_hide.setToolTip("Ẩn lời cuối ngày.")
        self.btn_eod_hide.clicked.connect(self._dismiss_eod)
        eod_row.addWidget(self.lbl_eod, stretch=1)
        eod_row.addWidget(self.btn_eod_hide)
        self.row_eod.hide()

        self.row_conflict = QWidget()
        conflict_row = QHBoxLayout(self.row_conflict)
        conflict_row.setContentsMargins(0, 0, 0, 0)
        conflict_row.setSpacing(8)
        self.lbl_conflict = _plain_label("#fde68a")
        self.btn_conflict_unmute = QPushButton("Bỏ im chủ đề")
        self.btn_conflict_unmute.setStyleSheet(_BTN_STYLE)
        self.btn_conflict_unmute.setToolTip("Bỏ im chủ đề của mục tiêu này. Mình không tự bật lại thông báo khác.")
        self.btn_conflict_unmute.clicked.connect(self._unmute_conflict)
        self.btn_conflict_unmute.hide()
        self.btn_conflict_goal = QPushButton("Đổi mục tiêu")
        self.btn_conflict_goal.setStyleSheet(_BTN_STYLE)
        self.btn_conflict_goal.setToolTip("Sửa mục tiêu ở ô bên dưới, hoặc mở bộ nhớ để xem hồ sơ.")
        self.btn_conflict_goal.clicked.connect(self._edit_goal)
        self.btn_conflict_hide = QPushButton("Ẩn")
        self.btn_conflict_hide.setStyleSheet(_BTN_STYLE)
        self.btn_conflict_hide.setToolTip("Ẩn dòng này hôm nay. Mình không nhắc lại cho đến ngày mai.")
        self.btn_conflict_hide.clicked.connect(self._dismiss_conflict)
        conflict_row.addWidget(self.lbl_conflict, stretch=1)
        conflict_row.addWidget(self.btn_conflict_unmute)
        conflict_row.addWidget(self.btn_conflict_goal)
        conflict_row.addWidget(self.btn_conflict_hide)
        self.row_conflict.hide()

        self.row_insight = QWidget()
        row = QHBoxLayout(self.row_insight)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.lbl_insight = _plain_label("#e0e7ff")
        self.btn_action = QPushButton("")
        self.btn_action.setStyleSheet(_BTN_STYLE)
        self.btn_action.setToolTip("Một việc an toàn có sẵn trong app. Không tự dọn ổ đĩa hay sửa registry.")
        self.btn_action.clicked.connect(self._activate)
        self.btn_action.hide()
        self.btn_pin = QPushButton("Ghim")
        self.btn_pin.setStyleSheet(_BTN_STYLE)
        self.btn_pin.setToolTip("Ghim việc này (tối đa 3). Mình không tự chạy.")
        self.btn_pin.clicked.connect(self._toggle_pin_insight)
        self.btn_pin.hide()
        self.btn_snooze = QPushButton("Đừng nhắc")
        self.btn_snooze.setStyleSheet(_BTN_STYLE)
        self.btn_snooze.setToolTip("Ẩn chủ đề này 3 ngày. Cảnh báo nhiệt và Wi-Fi khẩn cấp vẫn hiện.")
        self.btn_snooze.clicked.connect(self._snooze_topic)
        self.btn_snooze.hide()
        self.btn_mute = QPushButton("Đừng nhắc lại")
        self.btn_mute.setStyleSheet(_BTN_STYLE)
        self.btn_mute.setToolTip("Im chủ đề này 7 ngày. Copilot vẫn trả lời nếu bạn hỏi.")
        self.btn_mute.clicked.connect(self._mute_topic)
        self.btn_mute.hide()
        self.btn_dismiss = QPushButton("Ẩn")
        self.btn_dismiss.setStyleSheet(_BTN_STYLE)
        self.btn_dismiss.setToolTip("Ẩn insight này. AI không hiện lại cùng một dòng.")
        self.btn_dismiss.clicked.connect(self._dismiss)
        row.addWidget(self.lbl_insight, stretch=1)
        row.addWidget(self.btn_action)
        row.addWidget(self.btn_pin)
        row.addWidget(self.btn_snooze)
        row.addWidget(self.btn_mute)
        row.addWidget(self.btn_dismiss)
        self.row_insight.hide()

        root.addWidget(self.row_stage)
        root.addWidget(self.row_milestone)
        root.addWidget(self.row_week)
        root.addWidget(self.row_pins)
        root.addWidget(self.row_checkin)
        root.addWidget(self.row_follow)
        root.addWidget(self.row_eod)
        root.addWidget(self.row_conflict)
        root.addWidget(self.row_insight)

        self.lbl_learned_today = QLabel("")
        self.lbl_learned_today.setWordWrap(True)
        self.lbl_learned_today.setStyleSheet(
            "color: #94a3b8; font-size: 11px; background: transparent; border: none;"
        )
        self.lbl_learned_today.hide()
        root.addWidget(self.lbl_learned_today)
        self.lbl_model = QLabel("")
        self.lbl_model.setWordWrap(True)
        self.lbl_model.setTextFormat(Qt.PlainText)
        self.lbl_model.setStyleSheet(
            "color: #94a3b8; font-size: 11px; background: transparent; border: none;"
        )
        self.lbl_model.hide()
        root.addWidget(self.lbl_model)
        self.hide()

    def insight_topic(self) -> str:
        return str(self._insight_topic or "")

    def refresh(self):
        enabled = is_enabled(self.config_manager)
        if enabled:
            try:
                from core.companion_profile import refresh_profile
                refresh_profile()
            except Exception:
                pass
        if enabled:
            try:
                from core.companion_moment import sync_focus_session
                sync_focus_session(config_manager=self.config_manager)
            except Exception:
                pass
        self._show_stage(enabled)
        self._show_milestone(enabled)
        self._show_week(enabled)
        self._show_pins(enabled)
        self._show_checkin(enabled)
        self._show_followup(enabled)
        self._show_eod(enabled)
        self._show_conflict(enabled)
        self._show_insight(enabled)
        self._show_learned_today(enabled)
        self._show_model(enabled)
        # isVisible() is false while this frame is hidden, so decide from the text.
        labels = (
            self.lbl_stage,
            self.lbl_milestone,
            self.lbl_week,
            self.lbl_pins,
            self.lbl_checkin,
            self.lbl_follow,
            self.lbl_eod,
            self.lbl_conflict,
            self.lbl_insight,
            self.lbl_learned_today,
            self.lbl_model,
        )
        if any(label.text().strip() for label in labels):
            self.show()
        else:
            self.hide()

    def _show_stage(self, enabled: bool):
        self.lbl_stage.setText("")
        self.row_stage.hide()
        if not enabled:
            return
        try:
            from core.companion import maybe_note_stage_up, pending_stage_celebration
            maybe_note_stage_up(config_manager=self.config_manager)
            pending = pending_stage_celebration()
        except Exception:
            pending = None
        text = str((pending or {}).get("text") or "").strip()
        if not text:
            return
        self.lbl_stage.setText(text)
        self.row_stage.show()

    def _show_milestone(self, enabled: bool):
        self.lbl_milestone.setText("")
        self.row_milestone.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import sync_milestone
            payload = sync_milestone(config_manager=self.config_manager)
        except Exception:
            payload = None
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return
        self.lbl_milestone.setText(text)
        self.row_milestone.show()

    def _show_checkin(self, enabled: bool):
        self.lbl_checkin.setText("")
        self._checkin_action = ""
        self._checkin_skill_id = ""
        self.btn_checkin_action.hide()
        self.row_checkin.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import sync_daily_checkin
            payload = sync_daily_checkin(config_manager=self.config_manager)
        except Exception:
            payload = None
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return
        self.lbl_checkin.setText(text)
        key = str((payload or {}).get("action_key") or "")
        label = str((payload or {}).get("action_label_vi") or "")
        self._checkin_skill_id = str((payload or {}).get("skill_id") or "")
        if key and label:
            try:
                from core.companion_moment import is_allowed_insight_action
                allowed = is_allowed_insight_action(key)
            except Exception:
                allowed = False
            if allowed:
                self._checkin_action = key
                self.btn_checkin_action.setText(label)
                self.btn_checkin_action.show()
        self.row_checkin.show()

    def _show_followup(self, enabled: bool):
        self.lbl_follow.setText("")
        self._follow_topic = ""
        self._follow_action = ""
        self.btn_follow_pin.hide()
        self.row_follow.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import due_action_followup
            payload = due_action_followup(config_manager=self.config_manager)
        except Exception:
            payload = None
        text = str((payload or {}).get("question_vi") or "").strip()
        if not text:
            return
        self._follow_topic = str((payload or {}).get("topic") or "")
        self._follow_action = str((payload or {}).get("action_key") or "")
        self.lbl_follow.setText(text)
        self._refresh_pin_button(self.btn_follow_pin, self._follow_action)
        self.row_follow.show()

    def _show_eod(self, enabled: bool):
        self.lbl_eod.setText("")
        self.row_eod.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import sync_eod_wrap
            payload = sync_eod_wrap(config_manager=self.config_manager)
        except Exception:
            payload = None
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return
        self.lbl_eod.setText(text)
        self.row_eod.show()

    def _show_conflict(self, enabled: bool):
        self.lbl_conflict.setText("")
        self._conflict_topic = ""
        self.btn_conflict_unmute.hide()
        self.row_conflict.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import sync_goal_conflict
            payload = sync_goal_conflict(config_manager=self.config_manager)
        except Exception:
            payload = None
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return
        self._conflict_topic = str((payload or {}).get("topic") or "")
        self.lbl_conflict.setText(text)
        if payload.get("unmute") and self._conflict_topic:
            self.btn_conflict_unmute.show()
        self.row_conflict.show()

    def _unmute_conflict(self):
        topic = str(getattr(self, "_conflict_topic", "") or "")
        if topic:
            try:
                from core.companion_profile import unmute_topic
                unmute_topic(topic)
            except Exception:
                pass
        try:
            from core.companion_moment import dismiss_goal_conflict
            dismiss_goal_conflict()
        except Exception:
            pass
        self.refresh()

    def _edit_goal(self):
        self.goal_edit_requested.emit()

    def _dismiss_conflict(self):
        try:
            from core.companion_moment import dismiss_goal_conflict
            dismiss_goal_conflict()
        except Exception:
            pass
        self.refresh()

    def _show_learned_today(self, enabled: bool):
        self.lbl_learned_today.setText("")
        self.lbl_learned_today.hide()
        if not enabled:
            return
        try:
            from core.companion_learning import ensure_daily_model, learn_status_vi
            model = ensure_daily_model(config_manager=self.config_manager)
            summary = str((model or {}).get("summary_vi") or "")
            text = "" if "chưa có gì mới" in summary else learn_status_vi(model)
        except Exception:
            text = ""
        if not text:
            return
        self.lbl_learned_today.setText(text)
        self.lbl_learned_today.show()

    def _show_model(self, enabled: bool):
        """Mô hình học: lessons and topic bars. Hidden on a day with nothing learned."""
        self.lbl_model.setText("")
        self.lbl_model.hide()
        if not enabled:
            return
        try:
            from core.companion_learning import current_lessons, ensure_daily_model, format_model_panel_vi
            model = ensure_daily_model(config_manager=self.config_manager)
            summary = str((model or {}).get("summary_vi") or "")
            if not current_lessons(model, limit=1) and "chưa có gì mới" in summary:
                return
            text = format_model_panel_vi(model)
        except Exception:
            text = ""
        if not text or "Chưa có mô hình" in text:
            return
        self.lbl_model.setText(text)
        self.lbl_model.show()

    def _show_insight(self, enabled: bool):
        self._insight_id = ""
        self._insight_topic = ""
        self._action_key = ""
        self._skill_id = ""
        self.lbl_insight.setText("")
        self.btn_action.hide()
        self.btn_pin.hide()
        self.btn_snooze.hide()
        self.btn_mute.hide()
        self.row_insight.hide()
        insight = None
        if enabled:
            try:
                from core.companion_moment import present_exam_season_hint
                insight = present_exam_season_hint(config_manager=self.config_manager)
            except Exception:
                insight = None
        if not insight:
            insight = current_insight(enabled=enabled) if enabled else None
            if insight and enabled:
                try:
                    from core.companion_moment import attach_insight_action
                    insight = attach_insight_action(insight, config_manager=self.config_manager)
                except Exception:
                    pass
        if not insight:
            return
        self._insight_id = str(insight.get("id") or "")
        self._insight_topic = str(insight.get("topic") or "")
        self._action_key = str(insight.get("action_key") or "")
        self._skill_id = str(insight.get("skill_id") or "")
        label = str(insight.get("action_label_vi") or "")
        if self._action_key and label:
            self.btn_action.setText(label)
            self.btn_action.show()
            self._refresh_pin_button(self.btn_pin, self._action_key)
        if self._insight_topic:
            self.btn_snooze.show()
            self.btn_mute.show()
        self.lbl_insight.setText(str(insight.get("text") or ""))
        if insight.get("quiet"):
            self.lbl_insight.setStyleSheet(
                "color: #a5b4fc; font-size: 12px; background: transparent; border: none;"
            )
        else:
            self.lbl_insight.setStyleSheet(
                "color: #e0e7ff; font-size: 12px; background: transparent; border: none;"
            )
        self.row_insight.show()

    def _emit_allowed(self, key: str, skill_id: str):
        if not key:
            return
        try:
            from core.companion_moment import is_allowed_insight_action
            if not is_allowed_insight_action(key):
                return
        except Exception:
            return
        if skill_id:
            try:
                from core.companion_skills import bump_skill_hit
                bump_skill_hit(skill_id=skill_id)
            except Exception:
                pass
        try:
            from core.companion_moment import schedule_action_followup
            schedule_action_followup(key, skill_id=skill_id, config_manager=self.config_manager)
        except Exception:
            pass
        self.action_requested.emit(key)

    def _activate(self):
        self._emit_allowed(self._action_key, self._skill_id)

    def _activate_checkin(self):
        self._emit_allowed(self._checkin_action, self._checkin_skill_id)

    def _show_week(self, enabled: bool):
        self.lbl_week.setText("")
        self.row_week.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import sync_weekly_strip
            payload = sync_weekly_strip(config_manager=self.config_manager)
        except Exception:
            payload = None
        text = str((payload or {}).get("text") or "").strip()
        if not text:
            return
        self.lbl_week.setText(text)
        self.row_week.show()

    def _dismiss_week(self):
        try:
            from core.companion_moment import dismiss_weekly_strip
            dismiss_weekly_strip()
        except Exception:
            pass
        self.refresh()

    def _show_pins(self, enabled: bool):
        self.lbl_pins.setText("")
        self._pin_keys = []
        for button in self.pin_action_buttons:
            button.hide()
            button.setText("")
        for button in self.pin_unpin_buttons:
            button.hide()
        self.row_pins.hide()
        if not enabled:
            return
        try:
            from core.companion_moment import eligible_pinned_actions, list_pinned_actions
            stored = list_pinned_actions()
            eligible = {
                str(item.get("key") or "")
                for item in eligible_pinned_actions(config_manager=self.config_manager)
            }
        except Exception:
            return
        if not stored:
            return
        self.lbl_pins.setText("Đã ghim")
        for index, pin in enumerate(stored[:3]):
            key = str(pin.get("action_key") or "")
            label = str(pin.get("label_vi") or "")
            self._pin_keys.append(key)
            self.pin_unpin_buttons[index].show()
            if key in eligible and label:
                self.pin_action_buttons[index].setText(label)
                self.pin_action_buttons[index].show()
        self.row_pins.show()

    def _activate_pin(self, index: int):
        keys = list(getattr(self, "_pin_keys", []) or [])
        if index < 0 or index >= len(keys):
            return
        key = keys[index]
        try:
            from core.companion_moment import eligible_pinned_actions
            allowed = {
                str(item.get("key") or "")
                for item in eligible_pinned_actions(config_manager=self.config_manager)
            }
        except Exception:
            return
        if key not in allowed:
            return
        self._emit_allowed(key, "")

    def _unpin_at(self, index: int):
        keys = list(getattr(self, "_pin_keys", []) or [])
        if index < 0 or index >= len(keys):
            return
        try:
            from core.companion_moment import unpin_favorite_action
            unpin_favorite_action(keys[index])
        except Exception:
            pass
        self.refresh()

    def _refresh_pin_button(self, button, action_key: str):
        key = str(action_key or "").strip()
        button.hide()
        if not key:
            return
        try:
            from core.companion_moment import MAX_PINNED_ACTIONS, is_allowed_insight_action, list_pinned_actions
            from core.companion_skills import BLOCKED_ACTION_KEYS
            if not is_allowed_insight_action(key) or key in BLOCKED_ACTION_KEYS:
                return
            pinned = {str(item.get("action_key") or "") for item in list_pinned_actions()}
        except Exception:
            return
        if key in pinned:
            button.setText("Bỏ ghim")
            button.show()
            return
        if len(pinned) >= MAX_PINNED_ACTIONS:
            return
        button.setText("Ghim")
        button.show()

    def _toggle_pin_key(self, action_key: str, topic: str = ""):
        key = str(action_key or "").strip()
        if not key:
            return
        try:
            from core.companion_moment import list_pinned_actions, pin_favorite_action, unpin_favorite_action
            pinned = {str(item.get("action_key") or "") for item in list_pinned_actions()}
            if key in pinned:
                unpin_favorite_action(key)
            else:
                pin_favorite_action(key, topic=topic)
        except Exception:
            pass
        self.refresh()

    def _toggle_pin_insight(self):
        self._toggle_pin_key(self._action_key, self._insight_topic)

    def _toggle_pin_follow(self):
        self._toggle_pin_key(getattr(self, "_follow_action", ""), getattr(self, "_follow_topic", ""))

    def _dismiss_milestone(self):
        try:
            from core.companion_moment import dismiss_milestone
            dismiss_milestone()
        except Exception:
            pass
        self.refresh()

    def _snooze_topic(self):
        topic = str(self._insight_topic or "")
        if topic:
            try:
                from core.companion_profile import snooze_tip_family
                snooze_tip_family(topic, level="info", critical=False)
            except Exception:
                pass
        self.refresh()

    def _dismiss_stage(self):
        try:
            from core.companion import dismiss_stage_celebration
            dismiss_stage_celebration()
        except Exception:
            pass
        self.refresh()

    def _dismiss_checkin(self):
        try:
            from core.companion_moment import dismiss_daily_checkin
            dismiss_daily_checkin()
        except Exception:
            pass
        self.refresh()

    def _answer_followup(self, helpful: bool):
        try:
            from core.companion_moment import answer_action_followup
            answer_action_followup(helpful, config_manager=self.config_manager)
        except Exception:
            pass
        self.refresh()

    def _dismiss_followup(self):
        try:
            from core.companion_moment import dismiss_action_followup
            dismiss_action_followup()
        except Exception:
            pass
        self.refresh()

    def _dismiss_eod(self):
        try:
            from core.companion_moment import dismiss_eod_wrap
            dismiss_eod_wrap()
        except Exception:
            pass
        self.refresh()

    def _mute_topic(self):
        topic = str(self._insight_topic or "")
        if topic:
            try:
                from core.companion_profile import MUTE_DAYS, mute_topic
                mute_topic(topic, days=MUTE_DAYS, reason="user")
            except Exception:
                pass
            try:
                from core.companion_moment import note_mute_after_action
                note_mute_after_action(topic)
            except Exception:
                pass
        self.refresh()

    def _dismiss(self):
        if str(self._insight_id or "").startswith("exam_season:"):
            try:
                from core.companion_moment import dismiss_exam_season_hint
                dismiss_exam_season_hint()
            except Exception:
                pass
        if self._insight_id:
            dismiss_insight(self._insight_id)
        self.refresh()
        self.dismissed.emit()


def _confirm(parent, prompt: dict) -> bool:
    reply = QMessageBox.question(
        parent,
        prompt.get("title") or "Xác nhận",
        prompt.get("body") or "",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return reply == QMessageBox.Yes


class CompanionReflectWorker(QThread):
    finished_ok = pyqtSignal(object)

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self._cfg = config_manager

    def run(self):
        try:
            result = maybe_run_reflection(self._cfg, force=True)
        except Exception as exc:
            result = exc
        self.finished_ok.emit(result)


class CompanionWeeklyWorker(QThread):
    finished_ok = pyqtSignal(object)

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self._cfg = config_manager

    def run(self):
        try:
            from core.companion_moment import maybe_weekly_digest
            result = maybe_weekly_digest(force=True, config_manager=self._cfg)
        except Exception as exc:
            result = exc
        self.finished_ok.emit(result)


class CompanionCard(QFrame):
    """Settings / Copilot card for companion stage, diary, skills."""

    stage_changed = pyqtSignal()
    insight_action_requested = pyqtSignal(str)

    def __init__(self, config_manager=None, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.config_manager = config_manager
        self.compact = bool(compact)
        self._reflect_worker: Optional[CompanionReflectWorker] = None
        self._weekly_worker: Optional[CompanionWeeklyWorker] = None
        self.setObjectName("CompanionCard")
        self.setStyleSheet(
            "QFrame#CompanionCard { background-color: #1e293b; border: 1px solid #334155; "
            "border-radius: 12px; }"
            "QCheckBox { color: #cbd5e1; spacing: 8px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; "
            "border: 1px solid #64748b; background: #0f172a; }"
            "QCheckBox::indicator:checked { background: #7c3aed; border-color: #a78bfa; }"
        )
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.lbl_title = QLabel("🌱 AI đồng hành")
        self.lbl_title.setStyleSheet(
            "color: #c4b5fd; font-size: 13px; font-weight: 800; background: transparent; border: none;"
        )
        header.addWidget(self.lbl_title)
        header.addStretch()
        self.lbl_badge = QLabel("Giai đoạn 0 · Mới gặp")
        self.lbl_badge.setStyleSheet(
            "background-color: #334155; color: #e2e8f0; font-size: 11px; font-weight: bold; "
            "padding: 4px 10px; border-radius: 10px;"
        )
        header.addWidget(self.lbl_badge)
        layout.addLayout(header)

        self.insight_bar = CompanionInsightBar(config_manager=self.config_manager, parent=self)
        self.insight_bar.action_requested.connect(self.insight_action_requested.emit)
        self.insight_bar.goal_edit_requested.connect(self._focus_goal)
        layout.addWidget(self.insight_bar)

        self.lbl_blurb = QLabel("")
        self.lbl_blurb.setWordWrap(True)
        self.lbl_blurb.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent; border: none;")
        layout.addWidget(self.lbl_blurb)

        self.lbl_legend = QLabel(stage_legend_vi())
        self.lbl_legend.setWordWrap(True)
        self.lbl_legend.setStyleSheet("color: #64748b; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_legend)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setWordWrap(True)
        self.lbl_progress.setStyleSheet("color: #cbd5e1; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_progress)

        self.lbl_reason = QLabel("")
        self.lbl_reason.setWordWrap(True)
        self.lbl_reason.setStyleSheet("color: #a5b4fc; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_reason)

        self.lbl_learning = QLabel("")
        self.lbl_learning.setWordWrap(True)
        self.lbl_learning.setStyleSheet("color: #e2e8f0; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_learning)

        self.lbl_diary = QLabel("")
        self.lbl_diary.setWordWrap(True)
        self.lbl_diary.setTextFormat(Qt.PlainText)
        self.lbl_diary.setStyleSheet("color: #e2e8f0; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_diary)

        self.lbl_skills = QLabel("")
        self.lbl_skills.setWordWrap(True)
        self.lbl_skills.setStyleSheet("color: #a5b4fc; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_skills)

        self.lbl_note = QLabel("")
        self.lbl_note.setWordWrap(True)
        self.lbl_note.setTextFormat(Qt.PlainText)
        self.lbl_note.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_note)

        self.txt_goal = QLineEdit()
        self.txt_goal.setPlaceholderText("Mục tiêu ngắn, ví dụ: ổn định Wi-Fi trước họp")
        self.txt_goal.setMaxLength(80)
        self.txt_goal.setStyleSheet(
            "QLineEdit { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 8px; font-size: 12px; }"
        )
        layout.addWidget(self.txt_goal)
        goal_btns = QHBoxLayout()
        self.btn_goal_save = QPushButton("Lưu mục tiêu")
        self.btn_goal_save.setStyleSheet(_BTN_STYLE)
        self.btn_goal_save.setToolTip("Một mục tiêu ngắn. Để trống rồi lưu là bỏ mục tiêu.")
        self.btn_goal_save.clicked.connect(self._save_goal)
        self.btn_goal_clear = QPushButton("Xóa mục tiêu")
        self.btn_goal_clear.setStyleSheet(_BTN_STYLE)
        self.btn_goal_clear.clicked.connect(self._clear_goal)
        goal_btns.addWidget(self.btn_goal_save)
        goal_btns.addWidget(self.btn_goal_clear)
        goal_btns.addStretch()
        layout.addLayout(goal_btns)
        self.lbl_goal = QLabel("")
        self.lbl_goal.setWordWrap(True)
        self.lbl_goal.setTextFormat(Qt.PlainText)
        self.lbl_goal.setStyleSheet("color: #fde68a; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_goal)

        self.txt_correction = QLineEdit()
        self.txt_correction.setPlaceholderText("Sửa cho mình — ví dụ: Wi-Fi yếu vì kênh DFS, gọi ngắn gọn")
        self.txt_correction.setMaxLength(120)
        self.txt_correction.setStyleSheet(
            "QLineEdit { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 8px; font-size: 12px; }"
        )
        layout.addWidget(self.txt_correction)
        note_btns = QHBoxLayout()
        self.btn_correction_save = QPushButton("Nhớ giúp mình")
        self.btn_correction_save.setStyleSheet(_BTN_STYLE)
        self.btn_correction_save.setToolTip("Một câu ngắn về máy này hoặc cách bạn muốn được nói chuyện. Không gửi đi đâu.")
        self.btn_correction_save.clicked.connect(self._save_correction)
        note_btns.addWidget(self.btn_correction_save)
        note_btns.addStretch()
        layout.addLayout(note_btns)
        self.lbl_correction = QLabel("")
        self.lbl_correction.setWordWrap(True)
        self.lbl_correction.setTextFormat(Qt.PlainText)
        self.lbl_correction.setStyleSheet("color: #c4b5fd; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_correction)

        if not self.compact:
            self.chk_enabled = QCheckBox("Ghi nhật ký máy (local, không gửi đám mây)")
            self.chk_enabled.setStyleSheet("font-weight: bold; font-size: 13px; color: #c4b5fd;")
            self.chk_reflect = QCheckBox(
                "Phản tỉnh buổi tối / sổ tay (Gemini nếu đã bật; không thì chỉ số liệu)"
            )
            self.chk_reflect.setStyleSheet("font-size: 12px; color: #cbd5e1;")
            self.chk_propose = QCheckBox(
                "Cho phép đề xuất Dọn nhẹ / Trước thi khi đã lớn dần (không tự chạy, không WinSxS)"
            )
            self.chk_propose.setStyleSheet("font-size: 12px; color: #cbd5e1;")
            self.chk_nudges = QCheckBox(
                "Gợi ý nhẹ khi đã học thói quen máy (không liên tục)"
            )
            self.chk_nudges.setStyleSheet("font-size: 12px; color: #cbd5e1;")
            self.chk_quiet = QCheckBox("Giờ yên lặng 23:00–07:00 (không nhắc, không thông báo)")
            self.chk_quiet.setStyleSheet("font-size: 12px; color: #cbd5e1;")
            self.chk_quiet.setToolTip(
                "Mặc định tắt. Bật để mình im từ 23:00 đến 07:00: không thông báo nổi, "
                "không chào buổi sáng giữa đêm. Dòng hôm nay vẫn hiện, nhẹ hơn."
            )
            self.chk_quiet_actions = QCheckBox("Vẫn hiện nút đề xuất trong giờ yên lặng")
            self.chk_quiet_actions.setStyleSheet("font-size: 12px; color: #cbd5e1;")
            self.chk_quiet_actions.setToolTip("Chỉ khi bạn muốn. Mặc định giờ yên lặng không có nút đề xuất.")
            layout.addWidget(self.chk_enabled)
            layout.addWidget(self.chk_reflect)
            layout.addWidget(self.chk_propose)
            layout.addWidget(self.chk_nudges)
            layout.addWidget(self.chk_quiet)
            layout.addWidget(self.chk_quiet_actions)
            self._refresh_quiet_controls()
            if self.config_manager:
                self.chk_enabled.setChecked(bool(self.config_manager.get("companion_enabled", True)))
                self.chk_reflect.setChecked(bool(self.config_manager.get("companion_reflection_enabled", True)))
                self.chk_propose.setChecked(bool(self.config_manager.get("companion_may_propose_actions", True)))
                self.chk_nudges.setChecked(bool(self.config_manager.get("companion_nudges_enabled", True)))
            self.chk_enabled.toggled.connect(self._persist_toggles)
            self.chk_reflect.toggled.connect(self._persist_toggles)
            self.chk_propose.toggled.connect(self._persist_toggles)
            self.chk_nudges.toggled.connect(self._persist_toggles)
            self.chk_quiet.toggled.connect(self._persist_quiet)
            self.chk_quiet_actions.toggled.connect(self._persist_quiet)

        offer_row = QHBoxLayout()
        self.lbl_offer = QLabel("")
        self.lbl_offer.setWordWrap(True)
        self.lbl_offer.setStyleSheet("color: #fde68a; font-size: 11px; background: transparent; border: none;")
        offer_row.addWidget(self.lbl_offer, stretch=1)
        self.btn_save_skill = QPushButton("Lưu kỹ năng")
        self.btn_save_skill.setStyleSheet(_BTN_STYLE)
        self.btn_save_skill.clicked.connect(self._save_skill)
        self.btn_skip_skill = QPushButton("Bỏ qua")
        self.btn_skip_skill.setStyleSheet(_BTN_STYLE)
        self.btn_skip_skill.clicked.connect(self._skip_skill)
        offer_row.addWidget(self.btn_save_skill)
        offer_row.addWidget(self.btn_skip_skill)
        layout.addLayout(offer_row)

        btns = QHBoxLayout()
        self.btn_helpful = QPushButton("Hữu ích")
        self.btn_helpful.setStyleSheet(_BTN_STYLE)
        self.btn_helpful.setToolTip("Phản hồi giúp AI lớn dần — không phải wall-clock.")
        self.btn_helpful.clicked.connect(lambda: self._feedback(True))
        self.btn_meh = QPushButton("Chưa khớp")
        self.btn_meh.setStyleSheet(_BTN_STYLE)
        self.btn_meh.clicked.connect(lambda: self._feedback(False))
        self.btn_reflect = QPushButton(REFLECT_BUTTON_VI)
        self.btn_reflect.setStyleSheet(_BTN_STYLE)
        self.btn_reflect.setToolTip("Tóm tắt nhật ký máy này thành sổ tay. Không bịa kỷ niệm.")
        self.btn_reflect.clicked.connect(self._reflect_now)
        self.btn_weekly = QPushButton("Tóm tắt tuần")
        self.btn_weekly.setStyleSheet(_BTN_STYLE)
        self.btn_weekly.setToolTip(
            "Một lần mỗi tuần, hoặc bấm để viết ngay vào sổ tay. Gemini nếu có key; không thì chỉ số liệu."
        )
        self.btn_weekly.clicked.connect(self._weekly_now)
        self.btn_manage = QPushButton("Xem và xóa bộ nhớ")
        self.btn_manage.setStyleSheet(_BTN_STYLE)
        self.btn_manage.setToolTip("Xem nhật ký, kỹ năng và xóa dữ liệu local (có xác nhận).")
        self.btn_manage.clicked.connect(self._open_manage)
        btns.addWidget(self.btn_helpful)
        btns.addWidget(self.btn_meh)
        btns.addWidget(self.btn_reflect)
        btns.addWidget(self.btn_weekly)
        btns.addWidget(self.btn_manage)
        btns.addStretch()
        layout.addLayout(btns)

        self.lbl_reflect_status = QLabel("")
        self.lbl_reflect_status.setWordWrap(True)
        self.lbl_reflect_status.setStyleSheet(
            "color: #94a3b8; font-size: 11px; background: transparent; border: none;"
        )
        layout.addWidget(self.lbl_reflect_status)

        hint = QLabel(
            f"{APP_NAME} nhớ sự kiện trên máy này (AppData), không huấn luyện lại mô hình, "
            "không tự dọn phá hủy."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 10px; background: transparent; border: none;")
        layout.addWidget(hint)

    def _focus_goal(self):
        if hasattr(self, "txt_goal"):
            self.txt_goal.setFocus()
            self.txt_goal.selectAll()

    def _persist_toggles(self, *_args):
        if not self.config_manager or not hasattr(self, "chk_enabled"):
            return
        self.config_manager.set("companion_enabled", self.chk_enabled.isChecked())
        self.config_manager.set("companion_reflection_enabled", self.chk_reflect.isChecked())
        self.config_manager.set("companion_may_propose_actions", self.chk_propose.isChecked())
        if hasattr(self, "chk_nudges"):
            self.config_manager.set("companion_nudges_enabled", self.chk_nudges.isChecked())
        self.refresh()

    def _persist_quiet(self, *_args):
        if not hasattr(self, "chk_quiet"):
            return
        try:
            from core.companion_profile import set_quiet_hours
            set_quiet_hours(
                self.chk_quiet.isChecked(),
                allow_actions=self.chk_quiet_actions.isChecked(),
            )
        except Exception:
            return
        self.chk_quiet_actions.setEnabled(self.chk_quiet.isChecked())
        if hasattr(self, "insight_bar"):
            self.insight_bar.refresh()

    def _refresh_quiet_controls(self):
        if not hasattr(self, "chk_quiet"):
            return
        try:
            from core.companion_profile import quiet_hours_settings
            settings = quiet_hours_settings()
        except Exception:
            settings = {"enabled": False, "allow_actions": False}
        self.chk_quiet.blockSignals(True)
        self.chk_quiet_actions.blockSignals(True)
        self.chk_quiet.setChecked(bool(settings.get("enabled")))
        self.chk_quiet_actions.setChecked(bool(settings.get("allow_actions")))
        self.chk_quiet_actions.setEnabled(bool(settings.get("enabled")))
        self.chk_quiet.blockSignals(False)
        self.chk_quiet_actions.blockSignals(False)

    def _set_reflect_status(self, text: str, status: str = ""):
        colors = {
            "success": "#34d399",
            "empty": "#fbbf24",
            "error": "#f87171",
        }
        color = colors.get(status, "#94a3b8")
        self.lbl_reflect_status.setText(text or "")
        self.lbl_reflect_status.setStyleSheet(
            f"color: {color}; font-size: 11px; background: transparent; border: none;"
        )

    def refresh(self):
        empty = empty_states_vi()
        enabled = is_enabled(self.config_manager)
        stage = current_stage(config_manager=self.config_manager)
        color = _STAGE_COLORS.get(stage.stage, "#94a3b8")
        self.lbl_badge.setText(stage.badge_vi())
        self.lbl_badge.setStyleSheet(
            f"background-color: #0f172a; color: {color}; font-size: 11px; font-weight: bold; "
            f"padding: 4px 10px; border-radius: 10px; border: 1px solid {color};"
        )
        self.lbl_blurb.setText(stage.blurb_vi if enabled else "AI đồng hành đang tắt — không ghi nhật ký.")
        self.lbl_legend.setText(stage_legend_vi())
        if stage.empty:
            self.lbl_progress.setText(empty["stage"])
        else:
            self.lbl_progress.setText(
                f"{stage.active_days} ngày dùng máy · "
                f"{stage.positive_feedback} phản hồi hữu ích · "
                f"{stage.skills_count} kỹ năng"
            )
        self.lbl_reason.setText(explain_stage_progress(stage) if enabled else "")
        learned = recent_learning_text() if enabled else ""
        guidance = active_guidance_text() if enabled else ""
        daily = ""
        if enabled:
            try:
                from core.companion_learning import ensure_daily_model, learn_status_vi
                daily = learn_status_vi(ensure_daily_model(config_manager=self.config_manager))
            except Exception:
                daily = ""
        model_line = ""
        if enabled:
            try:
                from core.companion_learning import current_lessons, ensure_daily_model
                lessons = current_lessons(ensure_daily_model(config_manager=self.config_manager), limit=2)
                if lessons:
                    model_line = "Bài học: " + "; ".join(lessons)
            except Exception:
                model_line = ""
        learning_bits = [bit for bit in (learned, guidance, daily, model_line) if bit]
        self.lbl_learning.setText("\n".join(learning_bits))
        digest = diary_digest(limit=3, days=14)
        preview_kinds = (
            "high_ram", "ram_optimized", "wifi_weak", "wifi_repaired", "ping_high",
            "clean_freed", "clean_light", "focus_mode", "thermal_warn", "session_day",
            "chat_note", "stage_up",
        )
        interesting = [row for row in list_diary_rows(limit=20, days=14) if row.get("kind") in preview_kinds]
        if interesting:
            digest = "\n".join(f"- {format_event_row(row)}" for row in interesting[:3])
        if stage.empty or "còn trống" in digest or "Chưa có nhật ký" in digest:
            self.lbl_diary.setText(empty["diary"])
        else:
            self.lbl_diary.setText(digest)
        offer = pending_skill_offer()
        if offer:
            self.lbl_offer.setText(
                f"Cùng vấn đề lặp {offer.get('hit_count')} lần: {offer.get('title')}. Lưu thành kỹ năng máy này?"
            )
            self.btn_save_skill.show()
            self.btn_skip_skill.show()
            self.lbl_skills.setText("")
        else:
            self.lbl_offer.setText("")
            self.btn_save_skill.hide()
            self.btn_skip_skill.hide()
            if stage.skills_count <= 0:
                self.lbl_skills.setText(empty["skills"])
            else:
                self.lbl_skills.setText(
                    f"Đã lưu {stage.skills_count} kỹ năng (mẹo máy này, không phải mã chạy)."
                )
        note = latest_reflection()
        meta = load_reflection_meta()
        if not note:
            self.lbl_note.setText(empty["reflection"])
        else:
            src = meta.get("source") or ""
            prefix = "Sổ tay: "
            if src == "template":
                prefix = "Sổ tay (số liệu, không LLM): "
            elif src == "gemini":
                prefix = "Sổ tay (Gemini): "
            elif str(src).startswith("weekly"):
                prefix = "Sổ tay tuần: "
            elif src:
                prefix = "Sổ tay: "
            preview = note.replace("\n", " ")
            if len(preview) > 220:
                preview = preview[:219] + "…"
            self.lbl_note.setText(prefix + preview)
        if hasattr(self, "insight_bar"):
            self.insight_bar.refresh()
        self._refresh_quiet_controls()
        self._refresh_goal()
        self._refresh_correction()
        self.stage_changed.emit()

    def _refresh_goal(self):
        status = goal_status()
        if not self.txt_goal.hasFocus():
            self.txt_goal.setText(status.get("text") if status else "")
        if not status:
            self.lbl_goal.setText(empty_states_vi()["goal"])
            self.btn_goal_clear.hide()
            return
        lines = [status.get("summary_vi") or ""]
        if status.get("next_action_vi"):
            lines.append(status["next_action_vi"])
        self.lbl_goal.setText("\n".join(line for line in lines if line))
        self.btn_goal_clear.show()

    def _save_goal(self):
        try:
            set_goal(self.txt_goal.text())
        except Exception:
            pass
        self.refresh()

    def _clear_goal(self):
        try:
            set_goal("")
        except Exception:
            pass
        self.txt_goal.clear()
        self.refresh()

    def _refresh_correction(self):
        try:
            from core.companion_profile import list_user_notes
            notes = list_user_notes()
        except Exception:
            notes = []
        if not notes:
            self.lbl_correction.setText("Chưa có lời sửa — gõ một câu ngắn nếu mình nhớ nhầm.")
            return
        latest = notes[-1]
        text = str(latest.get("text") or "").strip()
        self.lbl_correction.setText(f"Mình nhớ: {text}" if text else "")

    def _save_correction(self):
        raw = self.txt_correction.text() if hasattr(self, "txt_correction") else ""
        if not str(raw or "").strip():
            return
        try:
            from core.companion_profile import add_user_note
            add_user_note(raw, source="user")
        except Exception:
            pass
        self.txt_correction.clear()
        self.refresh()

    def _feedback(self, helpful: bool):
        topic = ""
        bar = getattr(self, "insight_bar", None)
        if bar is not None:
            try:
                topic = bar.insight_topic()
            except Exception:
                topic = ""
        try:
            note_user_feedback(helpful, config_manager=self.config_manager, topic=topic)
        except Exception:
            pass
        self.refresh()

    def _save_skill(self):
        try:
            accept_skill_offer()
        except Exception:
            pass
        self.refresh()

    def _skip_skill(self):
        try:
            decline_skill_offer()
        except Exception:
            pass
        self.refresh()

    def _open_manage(self):
        dlg = CompanionDialog(config_manager=self.config_manager, parent=self.window())
        dlg.exec_()
        self.refresh()

    def _reflect_now(self):
        if self._reflect_worker and self._reflect_worker.isRunning():
            return
        self.btn_reflect.setEnabled(False)
        self.btn_reflect.setText("Đang phản tỉnh…")
        self._set_reflect_status("Đang viết sổ tay từ nhật ký máy này…")
        worker = CompanionReflectWorker(self.config_manager, parent=self)
        self._reflect_worker = worker
        worker.finished_ok.connect(self._on_reflect_done)
        worker.start()

    def _on_reflect_done(self, result):
        self.btn_reflect.setEnabled(True)
        self.btn_reflect.setText(REFLECT_BUTTON_VI)
        feedback = format_reflection_feedback(result)
        self._set_reflect_status(feedback["body"], feedback["status"])
        self.refresh()
        if feedback["status"] == "error":
            QMessageBox.warning(self, feedback["title"], feedback["body"])

    def _weekly_now(self):
        if self._weekly_worker and self._weekly_worker.isRunning():
            return
        self.btn_weekly.setEnabled(False)
        self.btn_weekly.setText("Đang tóm tắt…")
        self._set_reflect_status("Đang viết tóm tắt tuần từ nhật ký máy này…")
        worker = CompanionWeeklyWorker(self.config_manager, parent=self)
        self._weekly_worker = worker
        worker.finished_ok.connect(self._on_weekly_done)
        worker.start()

    def _on_weekly_done(self, result):
        self.btn_weekly.setEnabled(True)
        self.btn_weekly.setText("Tóm tắt tuần")
        try:
            from core.companion_moment import format_weekly_feedback
            feedback = format_weekly_feedback(result)
        except Exception:
            feedback = {
                "status": "error",
                "title": "Chưa ghi được tóm tắt tuần",
                "body": "Chưa ghi được tóm tắt tuần.",
            }
        self._set_reflect_status(feedback["body"], feedback["status"])
        self.refresh()
        if feedback["status"] == "error":
            QMessageBox.warning(self, feedback["title"], feedback["body"])


class CompanionDialog(QDialog):
    """Xem nhật ký / kỹ năng / sổ tay và xóa bộ nhớ local (có xác nhận)."""

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self._reflect_worker: Optional[CompanionReflectWorker] = None
        self.setWindowTitle(f"AI đồng hành — {APP_NAME}")
        self.resize(560, 920)
        self._growth_dismissed = False
        self.setStyleSheet("QDialog { background: #0f172a; color: #e2e8f0; }")
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.lbl_badge = QLabel("Giai đoạn 0 · Mới gặp")
        self.lbl_badge.setStyleSheet("color: #c4b5fd; font-size: 14px; font-weight: 800;")
        root.addWidget(self.lbl_badge)

        self.lbl_blurb = QLabel("")
        self.lbl_blurb.setWordWrap(True)
        self.lbl_blurb.setStyleSheet("color: #94a3b8; font-size: 12px;")
        root.addWidget(self.lbl_blurb)

        self.lbl_legend = QLabel(stage_legend_vi())
        self.lbl_legend.setWordWrap(True)
        self.lbl_legend.setStyleSheet("color: #64748b; font-size: 11px;")
        root.addWidget(self.lbl_legend)

        root.addWidget(QLabel("Hồ sơ thói quen"))
        self.lbl_profile = QLabel("")
        self.lbl_profile.setWordWrap(True)
        self.lbl_profile.setTextFormat(Qt.PlainText)
        self.lbl_profile.setStyleSheet("color: #e2e8f0; font-size: 12px;")
        root.addWidget(self.lbl_profile)
        profile_btns = QHBoxLayout()
        self.btn_clear_profile = QPushButton("Xóa hồ sơ thói quen…")
        self.btn_clear_profile.setStyleSheet(_DANGER_BTN_STYLE)
        self.btn_clear_profile.clicked.connect(self._clear_profile)
        profile_btns.addWidget(self.btn_clear_profile)
        profile_btns.addStretch()
        root.addLayout(profile_btns)

        root.addWidget(QLabel("Mô hình học"))
        self.lbl_model = QLabel("")
        self.lbl_model.setWordWrap(True)
        self.lbl_model.setTextFormat(Qt.PlainText)
        self.lbl_model.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        root.addWidget(self.lbl_model)

        root.addWidget(QLabel("Lời bạn đã sửa"))
        self.lbl_corrections_empty = QLabel("Chưa có lời sửa. Gõ một câu ngắn nếu mình nhớ nhầm.")
        self.lbl_corrections_empty.setWordWrap(True)
        self.lbl_corrections_empty.setStyleSheet("color: #94a3b8; font-size: 11px;")
        root.addWidget(self.lbl_corrections_empty)
        self.txt_correction = QLineEdit()
        self.txt_correction.setPlaceholderText("Sửa cho mình — ví dụ: đừng đề xuất dọn nặng")
        self.txt_correction.setMaxLength(120)
        self.txt_correction.setStyleSheet(
            "QLineEdit { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 8px; font-size: 12px; }"
        )
        root.addWidget(self.txt_correction)
        self.list_corrections = QListWidget()
        self.list_corrections.setStyleSheet(_LIST_STYLE)
        self.list_corrections.setMaximumHeight(88)
        root.addWidget(self.list_corrections)
        corr_btns = QHBoxLayout()
        self.btn_add_correction = QPushButton("Nhớ giúp mình")
        self.btn_add_correction.setStyleSheet(_BTN_STYLE)
        self.btn_add_correction.clicked.connect(self._add_correction)
        self.btn_delete_correction = QPushButton("Xóa lời đã chọn")
        self.btn_delete_correction.setStyleSheet(_BTN_STYLE)
        self.btn_delete_correction.clicked.connect(self._delete_correction)
        corr_btns.addWidget(self.btn_add_correction)
        corr_btns.addWidget(self.btn_delete_correction)
        corr_btns.addStretch()
        root.addLayout(corr_btns)

        root.addWidget(QLabel("Mình đã lớn thế nào"))
        growth_head = QHBoxLayout()
        self.lbl_growth_empty = QLabel("")
        self.lbl_growth_empty.setWordWrap(True)
        self.lbl_growth_empty.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self.btn_growth_hide = QPushButton("Ẩn")
        self.btn_growth_hide.setStyleSheet(_BTN_STYLE)
        self.btn_growth_hide.setToolTip("Ẩn dòng trống. Mốc lớn sẽ hiện lại khi có.")
        self.btn_growth_hide.clicked.connect(self._hide_growth_empty)
        growth_head.addWidget(self.lbl_growth_empty, stretch=1)
        growth_head.addWidget(self.btn_growth_hide)
        root.addLayout(growth_head)
        self.list_growth = QListWidget()
        self.list_growth.setStyleSheet(_LIST_STYLE)
        self.list_growth.setMaximumHeight(96)
        root.addWidget(self.list_growth)

        root.addWidget(QLabel("Chủ đề đang im"))
        self.lbl_muted = QLabel("")
        self.lbl_muted.setWordWrap(True)
        self.lbl_muted.setStyleSheet("color: #94a3b8; font-size: 11px;")
        root.addWidget(self.lbl_muted)
        self.list_muted = QListWidget()
        self.list_muted.setStyleSheet(_LIST_STYLE)
        self.list_muted.setMaximumHeight(72)
        root.addWidget(self.list_muted)
        mute_btns = QHBoxLayout()
        self.btn_unmute = QPushButton("Bỏ im chủ đề đã chọn")
        self.btn_unmute.setStyleSheet(_BTN_STYLE)
        self.btn_unmute.clicked.connect(self._unmute_selected)
        self.btn_unmute_all = QPushButton("Bỏ hết im lặng")
        self.btn_unmute_all.setStyleSheet(_BTN_STYLE)
        self.btn_unmute_all.clicked.connect(self._unmute_all)
        mute_btns.addWidget(self.btn_unmute)
        mute_btns.addWidget(self.btn_unmute_all)
        mute_btns.addStretch()
        root.addLayout(mute_btns)

        reflect_row = QHBoxLayout()
        self.btn_reflect = QPushButton(REFLECT_BUTTON_VI)
        self.btn_reflect.setStyleSheet(_BTN_STYLE)
        self.btn_reflect.clicked.connect(self._reflect_now)
        reflect_row.addWidget(self.btn_reflect)
        reflect_row.addStretch()
        root.addLayout(reflect_row)

        self.lbl_reflect_status = QLabel("")
        self.lbl_reflect_status.setWordWrap(True)
        self.lbl_reflect_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        root.addWidget(self.lbl_reflect_status)

        self.lbl_diary_empty = QLabel("")
        self.lbl_diary_empty.setWordWrap(True)
        self.lbl_diary_empty.setStyleSheet("color: #94a3b8; font-size: 11px;")
        root.addWidget(QLabel("Nhật ký gần đây"))
        root.addWidget(self.lbl_diary_empty)
        self.list_diary = QListWidget()
        self.list_diary.setStyleSheet(_LIST_STYLE)
        self.list_diary.setMaximumHeight(120)
        root.addWidget(self.list_diary)

        diary_btns = QHBoxLayout()
        self.btn_delete_diary = QPushButton("Xóa mục đã chọn")
        self.btn_delete_diary.setStyleSheet(_BTN_STYLE)
        self.btn_delete_diary.clicked.connect(self._delete_diary_item)
        self.btn_clear_diary = QPushButton("Xóa nhật ký…")
        self.btn_clear_diary.setStyleSheet(_DANGER_BTN_STYLE)
        self.btn_clear_diary.clicked.connect(self._clear_diary)
        diary_btns.addWidget(self.btn_delete_diary)
        diary_btns.addWidget(self.btn_clear_diary)
        diary_btns.addStretch()
        root.addLayout(diary_btns)

        self.lbl_skills_empty = QLabel("")
        self.lbl_skills_empty.setWordWrap(True)
        self.lbl_skills_empty.setStyleSheet("color: #94a3b8; font-size: 11px;")
        root.addWidget(QLabel("Kỹ năng đã lưu"))
        root.addWidget(self.lbl_skills_empty)
        self.list_skills = QListWidget()
        self.list_skills.setStyleSheet(_LIST_STYLE)
        self.list_skills.setMaximumHeight(100)
        root.addWidget(self.list_skills)

        skill_btns = QHBoxLayout()
        self.btn_delete_skill = QPushButton("Xóa kỹ năng đã chọn")
        self.btn_delete_skill.setStyleSheet(_BTN_STYLE)
        self.btn_delete_skill.clicked.connect(self._delete_skill_item)
        self.btn_clear_skills = QPushButton("Xóa hết kỹ năng…")
        self.btn_clear_skills.setStyleSheet(_DANGER_BTN_STYLE)
        self.btn_clear_skills.clicked.connect(self._clear_skills)
        skill_btns.addWidget(self.btn_delete_skill)
        skill_btns.addWidget(self.btn_clear_skills)
        skill_btns.addStretch()
        root.addLayout(skill_btns)

        root.addWidget(QLabel("Sổ tay"))
        self.txt_note = QTextEdit()
        self.txt_note.setReadOnly(True)
        self.txt_note.setStyleSheet(
            "QTextEdit { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 8px; font-size: 12px; }"
        )
        root.addWidget(self.txt_note, stretch=1)

        transfer = QHBoxLayout()
        self.btn_export = QPushButton("Xuất bộ nhớ")
        self.btn_export.setStyleSheet(_BTN_STYLE)
        self.btn_export.setToolTip(
            "Lưu hồ sơ, giai đoạn, kỹ năng, nhật ký và sổ tay ra một file JSON trên máy này. Không gửi đám mây."
        )
        self.btn_export.clicked.connect(self._export_memory)
        self.btn_import = QPushButton("Nhập bộ nhớ")
        self.btn_import.setStyleSheet(_BTN_STYLE)
        self.btn_import.setToolTip(
            "Gộp hoặc thay thế bộ nhớ từ file JSON. Mình không chạy hành động trong file."
        )
        self.btn_import.clicked.connect(self._import_memory)
        transfer.addWidget(self.btn_export)
        transfer.addWidget(self.btn_import)
        transfer.addStretch()
        root.addLayout(transfer)
        self.lbl_transfer = QLabel("")
        self.lbl_transfer.setWordWrap(True)
        self.lbl_transfer.setStyleSheet("color: #94a3b8; font-size: 11px;")
        root.addWidget(self.lbl_transfer)

        foot = QHBoxLayout()
        self.btn_clear_all = QPushButton("Xóa hết bộ nhớ local…")
        self.btn_clear_all.setStyleSheet(_DANGER_BTN_STYLE)
        self.btn_clear_all.clicked.connect(self._clear_all)
        close_btn = QPushButton("Đóng")
        close_btn.setStyleSheet(_BTN_STYLE)
        close_btn.clicked.connect(self.accept)
        foot.addWidget(self.btn_clear_all)
        foot.addStretch()
        foot.addWidget(close_btn)
        root.addLayout(foot)

        self.refresh()

    def _show_transfer(self, result: Any):
        payload = result if isinstance(result, dict) else {}
        text = str(payload.get("message_vi") or "Chưa xong việc với file bộ nhớ.")
        color = "#34d399" if payload.get("ok") else "#f87171"
        self.lbl_transfer.setText(text)
        self.lbl_transfer.setStyleSheet(f"color: {color}; font-size: 11px;")
        if payload.get("ok"):
            QMessageBox.information(self, "Bộ nhớ đồng hành", text)
        else:
            QMessageBox.warning(self, "Bộ nhớ đồng hành", text)

    def _memory_start_dir(self) -> str:
        try:
            from config_manager import companion_dir
            folder = companion_dir()
            os.makedirs(folder, exist_ok=True)
            return folder
        except Exception:
            return ""

    def _export_memory(self):
        folder = self._memory_start_dir()
        suggested = os.path.join(folder, "bo-nho-dong-hanh.json") if folder else "bo-nho-dong-hanh.json"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Xuất bộ nhớ đồng hành",
            suggested,
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            from core.companion import export_companion_memory
            result = export_companion_memory(path)
        except Exception:
            result = {"ok": False, "message_vi": "Chưa xuất được bộ nhớ."}
        self._show_transfer(result)

    def _import_memory(self):
        folder = self._memory_start_dir()
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Nhập bộ nhớ đồng hành",
            folder,
            "JSON (*.json)",
        )
        if not path:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Nhập bộ nhớ đồng hành?")
        box.setText(
            "Gộp thêm vào bộ nhớ máy này, hoặc thay thế toàn bộ.\n\n"
            "Mình không chạy hành động trong file. Đây là bản sao một máy, không phải đồng bộ đám mây."
        )
        btn_merge = box.addButton("Gộp", QMessageBox.AcceptRole)
        btn_replace = box.addButton("Thay thế", QMessageBox.DestructiveRole)
        box.addButton("Hủy", QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is btn_merge:
            mode = "merge"
        elif clicked is btn_replace:
            mode = "replace"
        else:
            return
        try:
            from core.companion import import_companion_memory
            result = import_companion_memory(path, mode=mode)
        except Exception:
            result = {"ok": False, "message_vi": "Chưa nhập được bộ nhớ."}
        self._show_transfer(result)
        if isinstance(result, dict) and result.get("ok"):
            self.refresh()

    def _set_reflect_status(self, text: str, status: str = ""):
        colors = {
            "success": "#34d399",
            "empty": "#fbbf24",
            "error": "#f87171",
        }
        color = colors.get(status, "#94a3b8")
        self.lbl_reflect_status.setText(text or "")
        self.lbl_reflect_status.setStyleSheet(f"color: {color}; font-size: 11px;")

    def refresh(self):
        empty = empty_states_vi()
        stage = current_stage(config_manager=self.config_manager)
        color = _STAGE_COLORS.get(stage.stage, "#94a3b8")
        self.lbl_badge.setText(stage.badge_vi())
        self.lbl_badge.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 800;")
        self.lbl_blurb.setText(stage.blurb_vi)
        self.lbl_legend.setText(stage_legend_vi() + "\n" + explain_stage_progress(stage))
        learned = recent_learning_text()
        if learned:
            self.lbl_legend.setText(self.lbl_legend.text() + "\n" + learned)
        try:
            from core.companion_learning import ensure_daily_model, learn_status_vi
            daily = learn_status_vi(ensure_daily_model(config_manager=self.config_manager))
        except Exception:
            daily = ""
        if daily:
            self.lbl_legend.setText(self.lbl_legend.text() + "\n" + daily)
        try:
            from core.companion_learning import ensure_daily_model, format_model_panel_vi
            self.lbl_model.setText(format_model_panel_vi(ensure_daily_model(config_manager=self.config_manager)))
        except Exception:
            self.lbl_model.setText(
                "Trí nhớ thích nghi local trên máy này, không phải AGI, không train lại mạng nơ-ron."
            )
        self.lbl_profile.setText(format_profile_browse() or empty["profile"])
        self._fill_corrections()
        self._fill_growth()
        self._fill_muted()

        diary_rows = list_diary_rows(limit=20, days=30)
        self.list_diary.clear()
        if not diary_rows:
            self.lbl_diary_empty.setText(empty["diary"])
            self.lbl_diary_empty.show()
        else:
            self.lbl_diary_empty.hide()
            for event in diary_rows:
                item = QListWidgetItem(format_event_row(event))
                item.setData(Qt.UserRole, event)
                self.list_diary.addItem(item)

        skills = list_skill_rows()
        self.list_skills.clear()
        if not skills:
            self.lbl_skills_empty.setText(empty["skills"])
            self.lbl_skills_empty.show()
        else:
            self.lbl_skills_empty.hide()
            for skill in skills:
                item = QListWidgetItem(format_skill_row(skill))
                item.setData(Qt.UserRole, skill.id)
                self.list_skills.addItem(item)

        note = latest_reflection() or empty["reflection"]
        self.txt_note.setPlainText(note)

    def _reflect_now(self):
        if self._reflect_worker and self._reflect_worker.isRunning():
            return
        self.btn_reflect.setEnabled(False)
        self.btn_reflect.setText("Đang phản tỉnh…")
        self._set_reflect_status("Đang viết sổ tay từ nhật ký máy này…")
        worker = CompanionReflectWorker(self.config_manager, parent=self)
        self._reflect_worker = worker
        worker.finished_ok.connect(self._on_reflect_done)
        worker.start()

    def _on_reflect_done(self, result):
        self.btn_reflect.setEnabled(True)
        self.btn_reflect.setText(REFLECT_BUTTON_VI)
        feedback = format_reflection_feedback(result)
        self._set_reflect_status(feedback["body"], feedback["status"])
        self.refresh()
        if feedback["status"] == "error":
            QMessageBox.warning(self, feedback["title"], feedback["body"])

    def _delete_diary_item(self):
        item = self.list_diary.currentItem()
        if item is None:
            QMessageBox.information(self, "Nhật ký", "Chọn một mục nhật ký để xóa.")
            return
        if not _confirm(self, confirm_clear_prompt("diary_item")):
            return
        event = item.data(Qt.UserRole)
        if isinstance(event, dict):
            delete_diary_entry(event)
        self.refresh()

    def _clear_diary(self):
        if not _confirm(self, confirm_clear_prompt("diary")):
            return
        clear_diary_memory()
        self.refresh()

    def _delete_skill_item(self):
        item = self.list_skills.currentItem()
        if item is None:
            QMessageBox.information(self, "Kỹ năng", "Chọn một kỹ năng để xóa.")
            return
        if not _confirm(self, confirm_clear_prompt("skill_item")):
            return
        skill_id = item.data(Qt.UserRole)
        if skill_id:
            delete_saved_skill(str(skill_id))
        self.refresh()

    def _clear_skills(self):
        if not _confirm(self, confirm_clear_prompt("skills")):
            return
        clear_skills_memory()
        self.refresh()

    def _add_correction(self):
        raw = self.txt_correction.text() if hasattr(self, "txt_correction") else ""
        if not str(raw or "").strip():
            return
        try:
            from core.companion_profile import add_user_note
            add_user_note(raw, source="user")
        except Exception:
            pass
        self.txt_correction.clear()
        self.refresh()

    def _delete_correction(self):
        item = self.list_corrections.currentItem()
        if item is None:
            QMessageBox.information(self, "Lời đã sửa", "Chọn một câu để xóa.")
            return
        note_id = item.data(Qt.UserRole)
        if not note_id:
            return
        if not _confirm(self, confirm_clear_prompt("correction")):
            return
        try:
            from core.companion_profile import delete_user_note
            delete_user_note(str(note_id))
        except Exception:
            pass
        self.refresh()

    def _fill_corrections(self):
        from core.companion_profile import format_user_note_line, list_user_notes
        notes = list_user_notes()
        self.list_corrections.clear()
        if not notes:
            self.lbl_corrections_empty.setText("Chưa có lời sửa. Gõ một câu ngắn nếu mình nhớ nhầm.")
            self.lbl_corrections_empty.show()
            self.list_corrections.hide()
            return
        self.lbl_corrections_empty.hide()
        self.list_corrections.show()
        for note in notes:
            item = QListWidgetItem(format_user_note_line(note))
            item.setData(Qt.UserRole, str(note.get("id") or ""))
            self.list_corrections.addItem(item)

    def _hide_growth_empty(self):
        self._growth_dismissed = True
        self.lbl_growth_empty.hide()
        self.btn_growth_hide.hide()

    def _fill_growth(self):
        from core.companion_profile import GROWTH_EMPTY_VI, build_growth_timeline, format_growth_row
        rows = build_growth_timeline()
        self.list_growth.clear()
        if not rows:
            self.list_growth.hide()
            if self._growth_dismissed:
                self.lbl_growth_empty.hide()
                self.btn_growth_hide.hide()
                return
            self.lbl_growth_empty.setText(GROWTH_EMPTY_VI)
            self.lbl_growth_empty.show()
            self.btn_growth_hide.show()
            return
        self.lbl_growth_empty.hide()
        self.btn_growth_hide.hide()
        self.list_growth.show()
        for row in rows:
            text = format_growth_row(row)
            if text:
                self.list_growth.addItem(QListWidgetItem(text))

    def _fill_muted(self):
        from core.companion_profile import active_muted_topics, format_muted_browse
        from core.companion_profile import TOPIC_META
        active = active_muted_topics()
        self.list_muted.clear()
        if not active:
            self.lbl_muted.setText("Không có chủ đề đang im.")
            self.lbl_muted.show()
            return
        self.lbl_muted.setText(format_muted_browse())
        self.lbl_muted.show()
        for topic, meta in active.items():
            name = str((TOPIC_META.get(topic) or {}).get("name") or topic)
            until = str(meta.get("until") or "")
            day = f"{until[8:10]}/{until[5:7]}" if len(until) >= 10 else ""
            item = QListWidgetItem(f"{name} — đến {day}" if day else name)
            item.setData(Qt.UserRole, topic)
            self.list_muted.addItem(item)

    def _unmute_selected(self):
        item = self.list_muted.currentItem()
        if item is None:
            QMessageBox.information(self, "Chủ đề đang im", "Chọn một chủ đề để bỏ im.")
            return
        topic = item.data(Qt.UserRole)
        if topic:
            try:
                from core.companion_profile import unmute_topic
                unmute_topic(str(topic))
            except Exception:
                pass
        self.refresh()

    def _unmute_all(self):
        try:
            from core.companion_profile import clear_muted_topics
            clear_muted_topics()
        except Exception:
            pass
        self.refresh()

    def _clear_profile(self):
        if not _confirm(self, confirm_clear_prompt("profile")):
            return
        clear_profile_habits()
        self.refresh()

    def _clear_all(self):
        if not _confirm(self, confirm_clear_prompt("all")):
            return
        clear_local_memory()
        self.refresh()
