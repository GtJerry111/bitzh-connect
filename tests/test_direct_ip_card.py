import ipaddress

from views.direct_ip_card import DirectIpCard


def test_default_off_and_empty(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    assert card.toggle.isChecked() is False
    assert card.body.isHidden()
    assert card.ips() == []


def test_toggle_on_adds_one_empty_row(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    assert not card.body.isHidden()
    assert len(card.rows) == 1
    assert card.rows[0].text() == ""


def test_add_and_remove_rows(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.rows[0].set_text("10.182.37.18")
    card.add_row("10.182.37.19")
    assert card.ips() == ["10.182.37.18", "10.182.37.19"]
    card.remove_row(card.rows[1])
    assert card.ips() == ["10.182.37.18"]


def test_delete_last_row_keeps_one_empty_row(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.rows[0].set_text("10.182.37.18")
    card.remove_row(card.rows[0])
    assert len(card.rows) == 1
    assert card.rows[0].text() == ""
    assert not card.rows[0].delete_btn.isEnabled()


def test_validate_marks_invalid_and_duplicate(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.rows[0].set_text("10.182.37.18")
    card.add_row("10.182.37")
    card.add_row("10.182.37.18")
    validation = card.validate()
    assert validation is None
    assert card.rows[1].edit.property("invalid") is True
    assert card.rows[2].edit.property("invalid") is True


def test_validate_forbidden_marks_row(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.rows[0].set_text("10.182.37.18")
    validation = card.validate(forbidden_ips={"10.182.37.18"})
    assert validation is None
    assert card.rows[0].edit.property("invalid") is True


def test_validate_local_skip_returns_validation(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.rows[0].set_text("10.0.0.20")
    validation = card.validate(
        local_networks=(ipaddress.IPv4Network("10.0.0.0/24"),)
    )
    assert validation is not None
    assert validation.valid == []
    assert validation.skipped_local == ["10.0.0.20"]
    assert card.rows[0].edit.property("invalid") is not True


def test_paste_multiple_tokens_creates_rows(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card._on_paste(card.rows[0], ["10.182.37.18", "10.182.37.19"])
    assert [r.text() for r in card.rows] == ["10.182.37.18", "10.182.37.19"]


def test_status_dots(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.rows[0].set_text("10.182.37.18")
    card.add_row("10.182.37.19")
    card.set_status_results(
        {"10.182.37.18": True, "10.182.37.19": False}, pending=set()
    )
    assert card.rows[0].dot.state == "ok"
    assert card.rows[1].dot.state == "failed"


def test_tun_off_shows_note_and_gray_dots(qtbot):
    card = DirectIpCard()
    qtbot.addWidget(card)
    card.toggle.setChecked(True)
    card.set_tun_enabled(False)
    assert not card.note.isHidden()
    assert card.rows[0].dot.state == "unapplied"
