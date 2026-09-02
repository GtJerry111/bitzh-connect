def test_two_resource_buttons_with_urls(qtbot):
    from common.constants import RESOURCES
    from views.resource_section import ResourceSection

    section = ResourceSection()
    qtbot.addWidget(section)
    assert len(section._buttons) == 2
    assert section._buttons[0].text() == RESOURCES[0][0]
    assert section._buttons[0].property("resource_url") == RESOURCES[0][1]


def test_click_opens_url(qtbot, monkeypatch):
    from views import resource_section
    from views.resource_section import ResourceSection

    opened = []
    monkeypatch.setattr(
        resource_section.QDesktopServices, "openUrl", lambda url: opened.append(url)
    )
    section = ResourceSection()
    qtbot.addWidget(section)
    section._buttons[1].click()
    assert len(opened) == 1
    assert "s.bitzh.edu.cn" in opened[0].toString()


def test_pill_style_uses_accent(qtbot):
    from common import theme
    from views.resource_section import ResourceSection

    section = ResourceSection()
    qtbot.addWidget(section)
    assert theme.semantic_color("accent").lower() in section._buttons[0].styleSheet().lower()
