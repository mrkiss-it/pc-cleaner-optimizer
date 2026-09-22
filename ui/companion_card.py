"""
Thẻ AI đồng hành — giai đoạn, nhật ký, kỹ năng, sổ tay (tiếng Việt).

Empty-state trung thực khi cài mới. Không nhận là AGI.
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
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


class CompanionInsightBar(QFrame):
    """One calm, dismissible line: «Hôm nay: …». Hidden when there is nothing to say."""

    dismissed = pyqtSignal()

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self._insight_id = ""
        self.setObjectName("CompanionInsightBar")
        self.setStyleSheet(
            "QFrame#CompanionInsightBar { background-color: #1e1b4b; border: 1px solid #4338ca; "
            "border-radius: 10px; }"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        self.lbl_insight = QLabel("")
        self.lbl_insight.setWordWrap(True)
        self.lbl_insight.setTextFormat(Qt.PlainText)
        self.lbl_insight.setStyleSheet(
            "color: #e0e7ff; font-size: 12px; background: transparent; border: none;"
        )
        self.btn_dismiss = QPushButton("Ẩn")
        self.btn_dismiss.setStyleSheet(_BTN_STYLE)
        self.btn_dismiss.setToolTip("Ẩn insight này. AI không hiện lại cùng một dòng.")
        self.btn_dismiss.clicked.connect(self._dismiss)
        row.addWidget(self.lbl_insight, stretch=1)
        row.addWidget(self.btn_dismiss)
        self.hide()

    def refresh(self):
        enabled = is_enabled(self.config_manager)
        if enabled:
            try:
                from core.companion_profile import refresh_profile
                refresh_profile()
            except Exception:
                pass
        insight = current_insight(enabled=enabled) if enabled else None
        if not insight:
            self._insight_id = ""
            self.lbl_insight.setText("")
            self.hide()
            return
        self._insight_id = str(insight.get("id") or "")
        self.lbl_insight.setText(str(insight.get("text") or ""))
        self.show()

    def _dismiss(self):
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


class CompanionCard(QFrame):
    """Settings / Copilot card for companion stage, diary, skills."""

    stage_changed = pyqtSignal()

    def __init__(self, config_manager=None, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.config_manager = config_manager
        self.compact = bool(compact)
        self._reflect_worker: Optional[CompanionReflectWorker] = None
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
            layout.addWidget(self.chk_enabled)
            layout.addWidget(self.chk_reflect)
            layout.addWidget(self.chk_propose)
            layout.addWidget(self.chk_nudges)
            if self.config_manager:
                self.chk_enabled.setChecked(bool(self.config_manager.get("companion_enabled", True)))
                self.chk_reflect.setChecked(bool(self.config_manager.get("companion_reflection_enabled", True)))
                self.chk_propose.setChecked(bool(self.config_manager.get("companion_may_propose_actions", True)))
                self.chk_nudges.setChecked(bool(self.config_manager.get("companion_nudges_enabled", True)))
            self.chk_enabled.toggled.connect(self._persist_toggles)
            self.chk_reflect.toggled.connect(self._persist_toggles)
            self.chk_propose.toggled.connect(self._persist_toggles)
            self.chk_nudges.toggled.connect(self._persist_toggles)

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
        self.btn_manage = QPushButton("Xem và xóa bộ nhớ")
        self.btn_manage.setStyleSheet(_BTN_STYLE)
        self.btn_manage.setToolTip("Xem nhật ký, kỹ năng và xóa dữ liệu local (có xác nhận).")
        self.btn_manage.clicked.connect(self._open_manage)
        btns.addWidget(self.btn_helpful)
        btns.addWidget(self.btn_meh)
        btns.addWidget(self.btn_reflect)
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

    def _persist_toggles(self, *_args):
        if not self.config_manager or not hasattr(self, "chk_enabled"):
            return
        self.config_manager.set("companion_enabled", self.chk_enabled.isChecked())
        self.config_manager.set("companion_reflection_enabled", self.chk_reflect.isChecked())
        self.config_manager.set("companion_may_propose_actions", self.chk_propose.isChecked())
        if hasattr(self, "chk_nudges"):
            self.config_manager.set("companion_nudges_enabled", self.chk_nudges.isChecked())
        self.refresh()

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
        learning_bits = [bit for bit in (learned, guidance) if bit]
        self.lbl_learning.setText("\n".join(learning_bits))
        digest = diary_digest(limit=3, days=14)
        preview_kinds = (
            "high_ram", "ram_optimized", "wifi_weak", "wifi_repaired", "ping_high",
            "clean_freed", "clean_light", "focus_mode", "thermal_warn", "session_day",
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
            elif src:
                prefix = "Sổ tay: "
            preview = note.replace("\n", " ")
            if len(preview) > 220:
                preview = preview[:219] + "…"
            self.lbl_note.setText(prefix + preview)
        if hasattr(self, "insight_bar"):
            self.insight_bar.refresh()
        self._refresh_goal()
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

    def _feedback(self, helpful: bool):
        try:
            note_user_feedback(helpful, config_manager=self.config_manager)
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


class CompanionDialog(QDialog):
    """Xem nhật ký / kỹ năng / sổ tay và xóa bộ nhớ local (có xác nhận)."""

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self._reflect_worker: Optional[CompanionReflectWorker] = None
        self.setWindowTitle(f"AI đồng hành — {APP_NAME}")
        self.resize(560, 720)
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
        self.lbl_profile.setText(format_profile_browse() or empty["profile"])

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
