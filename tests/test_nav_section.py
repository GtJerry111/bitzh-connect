"""校内导航折叠条：分组网格内容、点击打开链接、展开状态记忆。"""

import pytest


@pytest.fixture(autouse=True)
def _instant(monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)


@pytest.fixture
def nav(qtbot):
    from views.nav_section import NavSection

    n = NavSection()
    qtbot.addWidget(n)
    n.show()
    return n


def test_grid_contains_all_sites_grouped(nav):
    """10 个站点全部进网格，按校区分组（珠海在前、本部在后）"""
    from common.constants import NAV_GROUPS

    expected = sum(len(items) for _, items in NAV_GROUPS)
    assert expected == 10
    assert len(nav._cells) == 10
    assert NAV_GROUPS[0][0] == "珠海校区"
    assert NAV_GROUPS[1][0] == "校本部"


def test_click_opens_url(nav, monkeypatch):
    from views import nav_section

    opened = []
    monkeypatch.setattr(
        nav_section.QDesktopServices, "openUrl", lambda url: opened.append(url)
    )
    nav._cells[1].click()  # 教务处
    assert len(opened) == 1
    assert "jw.bitzh.edu.cn" in opened[0].toString()


def test_default_collapsed_and_toggle(nav):
    """默认收起；点击折叠条展开/收起"""
    assert nav.is_expanded is False
    assert nav._panel.isHidden()
    nav.set_expanded(True)
    assert not nav._panel.isHidden()
    nav.set_expanded(False)
    assert nav._panel.isHidden()


def test_expanded_state_persists(qtbot):
    """展开状态写入配置，下次构造恢复（重启记忆）"""
    from utils.config_utils import load_config
    from views.nav_section import NavSection

    n1 = NavSection()
    qtbot.addWidget(n1)
    n1.set_expanded(True)
    assert load_config()["nav_expanded"] is True

    n2 = NavSection()
    qtbot.addWidget(n2)
    assert n2.is_expanded is True
    assert not n2._panel.isHidden()
