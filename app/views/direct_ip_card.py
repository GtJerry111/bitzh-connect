# app/views/direct_ip_card.py
"""高级设置：直连 IP 动态列表卡片。"""
from __future__ import annotations

import ipaddress

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from common import theme
from utils.direct_ip import (
    MAX_DIRECT_IPS,
    DirectIpValidation,
    parse_ipv4,
    split_pasted_ips,
    status_for_ip,
    validate_direct_ips,
)
from views.toggle_switch import ToggleSwitch


class _StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self.state = "unapplied"

    def set_state(self, state: str):
        self.state = state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        color_name = {
            "ok": "connected",
            "failed": "working",
            "pending": "idle",
            "unapplied": "idle",
        }.get(self.state, "idle")
        painter.setBrush(theme.qcolor(color_name))
        painter.drawEllipse(0, 0, self.width(), self.height())
        painter.end()


class _DirectIpLineEdit(QLineEdit):
    pasted_multiple = Signal(list)

    def insertFromMimeData(self, source):
        tokens = split_pasted_ips(source.text())
        if len(tokens) > 1:
            self.pasted_multiple.emit(tokens)
            return
        super().insertFromMimeData(source)


class DirectIpRow(QWidget):
    remove_requested = Signal(object)
    changed = Signal()
    pasted_multiple = Signal(list)

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.dot = _StatusDot()
        row.addWidget(self.dot, 0, Qt.AlignVCenter)
        self.edit = _DirectIpLineEdit()
        self.edit.setPlaceholderText("10.182.37.18")
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(12)
        self.edit.setFont(font)
        self.edit.setAccessibleName("直连 IP 地址")
        self.edit.setStyleSheet(
            f"QLineEdit {{ border: 1px solid {theme.semantic_color('separator')};"
            " border-radius: 6px; padding: 4px 8px; }"
            f"QLineEdit[invalid=\"true\"] {{ border: 1px solid"
            f" {theme.semantic_color('error')}; }}"
        )
        row.addWidget(self.edit, 1)
        self.delete_btn = QPushButton("−")
        self.delete_btn.setFixedSize(26, 26)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setToolTip("删除这个 IP")
        self.delete_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        row.addWidget(self.delete_btn, 0, Qt.AlignVCenter)
        self.edit.textChanged.connect(self.changed)
        self.edit.pasted_multiple.connect(self.pasted_multiple)
        self.set_text(text)

    def set_text(self, text: str):
        self.edit.setText(text)

    def text(self) -> str:
        return self.edit.text()

    def set_status(self, state: str, tooltip: str = ""):
        self.dot.set_state(state)
        self.dot.setToolTip(tooltip)

    def set_invalid(self, message: str):
        self.edit.setProperty("invalid", True)
        self.edit.setToolTip(message)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)

    def clear_error(self):
        self.edit.setProperty("invalid", False)
        self.edit.setToolTip("")
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)


class DirectIpCard(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DirectIpCard")
        self.setStyleSheet(
            f"#DirectIpCard {{ background: {theme.card_background()};"
            " border-radius: 10px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title = QLabel("直连 IP（不走校园 VPN）")
        title_font = self.title.font()
        title_font.setPointSize(12)
        title_font.setWeight(title_font.Weight.DemiBold)
        self.title.setFont(title_font)
        title_col.addWidget(self.title)
        self.desc = QLabel(
            "这些 IP 会走当前物理网卡；只填公司/其他直连地址，不要填学校地址。"
        )
        self.desc.setWordWrap(True)
        self.desc.setFont(theme.card_title_font())
        self.desc.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')};"
        )
        title_col.addWidget(self.desc)
        header.addLayout(title_col, 1)
        self.toggle = ToggleSwitch()
        self.toggle.setAccessibleName("启用直连 IP")
        header.addWidget(self.toggle, 0, Qt.AlignTop)
        outer.addLayout(header)

        self.note = QLabel("仅 TUN 模式生效")
        self.note.setFont(theme.card_title_font())
        self.note.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        self.note.hide()
        outer.addWidget(self.note)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setFixedHeight(150)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch()
        self.scroll.setWidget(self.rows_host)
        body.addWidget(self.scroll)

        self.add_btn = QPushButton("＋ 添加 IP")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet(
            f"QPushButton {{ border: none; color: {theme.semantic_color('accent')};"
            " font-size: 12px; text-align: left; padding: 2px 0; }"
        )
        self.add_btn.clicked.connect(lambda: self.add_row())
        body.addWidget(self.add_btn, 0, Qt.AlignLeft)

        self.hint = QLabel("每行一个 IPv4；空行忽略；自动去重；最多 100 个。")
        self.hint.setFont(theme.card_title_font())
        self.hint.setStyleSheet(
            f"color: {theme.semantic_color('secondary_text')};"
        )
        body.addWidget(self.hint)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setFont(theme.card_title_font())
        self.error.setStyleSheet(f"color: {theme.semantic_color('error')};")
        self.error.hide()
        body.addWidget(self.error)
        outer.addWidget(self.body)

        self.rows: list[DirectIpRow] = []
        self._platform_supported = True
        self._tun_enabled = True
        self._results: dict[str, bool] = {}
        self._pending: set[str] = set()

        self.toggle.toggled.connect(self._on_toggle)
        self._update_visibility()

    def _on_toggle(self, checked: bool):
        self._update_visibility()
        if checked and not self.rows:
            self.add_row()
        self.changed.emit()

    def _update_visibility(self):
        self.setEnabled(self._platform_supported)
        if not self._platform_supported:
            self.note.setText("当前平台暂不支持")
            self.note.show()
            self.body.setVisible(False)
            return
        self.note.setText("仅 TUN 模式生效")
        self.note.setVisible(not self._tun_enabled)
        self.body.setVisible(self.toggle.isChecked())

    def add_row(self, text: str = "", focus: bool = True):
        if len(self.rows) >= MAX_DIRECT_IPS:
            self._show_error(f"最多只能添加 {MAX_DIRECT_IPS} 个 IP")
            return None
        row = DirectIpRow(text)
        row.remove_requested.connect(self.remove_row)
        row.changed.connect(self._on_row_changed)
        row.pasted_multiple.connect(lambda tokens, r=row: self._on_paste(r, tokens))
        self.rows.append(row)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        if not self.toggle.isChecked():
            self.toggle.setChecked(True)
        if focus:
            row.edit.setFocus()
        self._update_delete_buttons()
        self._refresh_statuses()
        self.changed.emit()
        return row

    def remove_row(self, row: DirectIpRow):
        if row not in self.rows:
            return
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        if not self.rows and self.toggle.isChecked():
            self.add_row(focus=False)
        self._update_delete_buttons()
        self.changed.emit()

    def _on_row_changed(self):
        self._update_delete_buttons()
        self.changed.emit()

    def _update_delete_buttons(self):
        only_empty = len(self.rows) == 1 and not self.rows[0].text().strip()
        for row in self.rows:
            row.delete_btn.setEnabled(not only_empty)

    def _on_paste(self, row: DirectIpRow, tokens: list[str]):
        if not tokens:
            return
        row.set_text(tokens[0])
        for token in tokens[1:]:
            self.add_row(token, focus=False)
        if self.rows:
            self.rows[-1].edit.setFocus()
        self.changed.emit()

    def set_ips(self, ips: list[str]):
        for row in list(self.rows):
            row.setParent(None)
            row.deleteLater()
        self.rows.clear()
        for ip in ips:
            self.add_row(ip, focus=False)
        if self.toggle.isChecked() and not self.rows:
            self.add_row(focus=False)
        self._update_delete_buttons()

    def ips(self) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for row in self.rows:
            ip = parse_ipv4(row.text())
            if ip and ip not in seen:
                seen.add(ip)
                result.append(ip)
        return result

    def validate(
        self,
        *,
        forbidden_ips: set[str] | frozenset[str] = frozenset(),
        local_networks: tuple[ipaddress.IPv4Network, ...] = (),
    ) -> DirectIpValidation | None:
        for row in self.rows:
            row.clear_error()
        indexed = [
            (index, row.text().strip())
            for index, row in enumerate(self.rows)
            if row.text().strip()
        ]
        raw = [text for _, text in indexed]
        if len(raw) > MAX_DIRECT_IPS:
            self._show_error(f"最多只能添加 {MAX_DIRECT_IPS} 个 IP")
            return None
        validation = validate_direct_ips(
            raw,
            forbidden_ips=forbidden_ips,
            local_networks=local_networks,
        )
        for issue in validation.issues:
            if 0 <= issue.index < len(indexed):
                row_index = indexed[issue.index][0]
                self.rows[row_index].set_invalid(issue.message)
        if validation.issues:
            self._show_error("请修正标红的 IP 后再保存")
            first = next(
                (r for r in self.rows if r.edit.property("invalid")), None
            )
            if first is not None:
                first.edit.setFocus()
            return None
        self._hide_error()
        return validation

    def set_status_results(
        self, results: dict[str, bool], pending: set[str] | None = None
    ):
        self._results = dict(results)
        self._pending = set(pending or set())
        self._refresh_statuses()

    def _refresh_statuses(self):
        if not self._tun_enabled:
            for row in self.rows:
                row.set_status("unapplied", "仅 TUN 模式生效")
            return
        for row in self.rows:
            ip = parse_ipv4(row.text())
            if not ip:
                row.set_status("unapplied", "")
                continue
            state = status_for_ip(ip, self._results, self._pending)
            tooltip = {
                "ok": "已生效",
                "failed": "未能添加路由",
                "pending": "修改将在下次连接生效",
                "unapplied": "未应用",
            }.get(state, "")
            row.set_status(state, tooltip)

    def set_tun_enabled(self, enabled: bool):
        self._tun_enabled = bool(enabled)
        self._update_visibility()
        self._refresh_statuses()

    def set_platform_supported(self, supported: bool):
        self._platform_supported = bool(supported)
        self._update_visibility()

    def focus_first(self):
        if not self.rows and self.toggle.isChecked():
            self.add_row()
        if self.rows:
            self.rows[0].edit.setFocus()
            self.scroll.ensureWidgetVisible(self.rows[0], 0, 0)

    def _show_error(self, message: str):
        self.error.setText(message)
        self.error.show()

    def _hide_error(self):
        self.error.clear()
        self.error.hide()
