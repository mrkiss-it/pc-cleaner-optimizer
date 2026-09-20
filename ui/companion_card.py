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
    empty_states_vi,
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
    pending_skill_offer,
    stage_legend_vi,
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

        self.lbl_blurb = QLabel("")
        self.lbl_blurb.setWordWrap(True)
        self.lbl_blurb.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent; border: none;")
        layout.addWidget(self.lbl_blurb)

        self.lbl_legend = QLabel(stage_legend_vi())
        self.lbl_legend.setWordWrap(True)
        self.lbl_legend.setStyleSheet("color: #64748b; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_legend)

        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet("color: #cbd5e1; font-size: 11px; background: transparent; border: none;")
        layout.addWidget(self.lbl_progress)

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
            layout.addWidget(self.chk_enabled)
            layout.addWidget(self.chk_reflect)
            layout.addWidget(self.chk_propose)
            if self.config_manager:
                self.chk_enabled.setChecked(bool(self.config_manager.get("companion_enabled", True)))
                self.chk_reflect.setChecked(bool(self.config_manager.get("companion_reflection_enabled", True)))
                self.chk_propose.setChecked(bool(self.config_manager.get("companion_may_propose_actions", True)))
            self.chk_enabled.toggled.connect(self._persist_toggles)
            self.chk_reflect.toggled.connect(self._persist_toggles)
            self.chk_propose.toggled.connect(self._persist_toggles)

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
        self.btn_manage = QPushButton("Xem & xóa bộ nhớ")
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
        digest = diary_digest(limit=3, days=14)
        if stage.empty or "còn trống" in digest:
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
                self.lbl_skills.setText(f"Đã lưu {stage.skills_count} kỹ năng (mẹo máy này, không phải mã chạy).")
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
        self.stage_changed.emit()

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
        self.resize(560, 640)
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
        self.list_diary.setMaximumHeight(150)
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
        self.list_skills.setMaximumHeight(120)
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
        self.lbl_legend.setText(stage_legend_vi())

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

    def _clear_all(self):
        if not _confirm(self, confirm_clear_prompt("all")):
            return
        clear_local_memory()
        self.refresh()
