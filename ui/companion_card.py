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
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app_meta import APP_NAME
from core.companion import (
    accept_skill_offer,
    current_stage,
    decline_skill_offer,
    diary_digest,
    empty_states_vi,
    is_enabled,
    latest_reflection,
    load_reflection_meta,
    maybe_run_reflection,
    note_user_feedback,
    pending_skill_offer,
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
"""


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
            self.chk_reflect = QCheckBox("Phản tỉnh buổi tối / sổ tay (Gemini hoặc Ollama nếu đã bật; không thì chỉ số liệu)")
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
        self.btn_reflect = QPushButton("Ghi sổ tay")
        self.btn_reflect.setStyleSheet(_BTN_STYLE)
        self.btn_reflect.clicked.connect(self._reflect_now)
        btns.addWidget(self.btn_helpful)
        btns.addWidget(self.btn_meh)
        btns.addWidget(self.btn_reflect)
        btns.addStretch()
        layout.addLayout(btns)

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
            elif src:
                prefix = f"Sổ tay ({src}): "
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

    def _reflect_now(self):
        if self._reflect_worker and self._reflect_worker.isRunning():
            return
        self.btn_reflect.setEnabled(False)
        self.btn_reflect.setText("Đang ghi…")
        worker = CompanionReflectWorker(self.config_manager, parent=self)
        self._reflect_worker = worker
        worker.finished_ok.connect(self._on_reflect_done)
        worker.start()

    def _on_reflect_done(self, result):
        self.btn_reflect.setEnabled(True)
        self.btn_reflect.setText("Ghi sổ tay")
        self.refresh()
        if isinstance(result, Exception):
            QMessageBox.warning(self, "Sổ tay", f"Không ghi được sổ tay: {result}")


class CompanionDialog(QDialog):
    """Chi tiết nhật ký / sổ tay từ Copilot."""

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"AI đồng hành — {APP_NAME}")
        self.resize(520, 560)
        self.setStyleSheet("QDialog { background: #0f172a; color: #e2e8f0; }")
        root = QVBoxLayout(self)
        self.card = CompanionCard(config_manager=config_manager, parent=self, compact=False)
        root.addWidget(self.card)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setStyleSheet(
            "QTextEdit { background: #1e293b; color: #e2e8f0; border: 1px solid #334155; "
            "border-radius: 8px; font-size: 12px; }"
        )
        digest = diary_digest(limit=20, days=30)
        note = latest_reflection() or "(chưa có sổ tay)"
        body.setPlainText(f"Nhật ký:\n{digest}\n\n---\nSổ tay:\n{note}")
        root.addWidget(body, stretch=1)
        close_btn = QPushButton("Đóng")
        close_btn.setStyleSheet(_BTN_STYLE)
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        root.addLayout(row)
