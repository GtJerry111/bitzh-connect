import pytest


@pytest.fixture(autouse=True)
def _reset_appearance():
    yield
    from common import theme

    theme.set_appearance("system")


def test_set_appearance_dark_light(qapp):
    from common import theme

    theme.set_appearance("dark")
    assert theme.is_dark() is True
    theme.set_appearance("light")
    assert theme.is_dark() is False


def test_set_appearance_triggers_refresh(qapp):
    from common import theme

    calls = []
    theme.on_scheme_changed(lambda: calls.append(1))
    theme.set_appearance("dark")
    assert len(calls) >= 1


def test_appearance_config_default():
    from utils.config_utils import load_config

    assert load_config()["appearance"] == "system"
