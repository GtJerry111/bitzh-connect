from types import SimpleNamespace

from utils.config_utils import load_config, load_settings
from utils.connection_utils import build_command_args, mask_command_args


def _fake_window(**overrides):
    w = SimpleNamespace(
        server_address="112.91.150.228",
        port="443",
        auto_dns=True,
        dns_server="",
        http_bind="1081",
        socks_bind="1080",
        keep_alive=True,
        debug_dump=False,
        disable_multi_line=False,
        cert_file="",
        cert_password="",
        username_input=SimpleNamespace(text=lambda: "2024000001"),
        password_input=SimpleNamespace(text=lambda: "p@ss!word with space"),
    )
    for k, v in overrides.items():
        setattr(w, k, v)
    return w


def test_special_char_password_passed_verbatim():
    """含特殊字符的密码必须原样传递，不能被加引号（上游 shlex.quote bug 的回归测试）"""
    args = build_command_args(_fake_window(), "zju-connect")
    idx = args.index("-password")
    assert args[idx + 1] == "p@ss!word with space"
    assert not args[idx + 1].startswith("'")


def test_auto_dns_uses_new_flag_name():
    args = build_command_args(_fake_window(), "zju-connect")
    assert "-remote-dns-server" in args
    assert "-zju-dns-server" not in args
    assert args[args.index("-remote-dns-server") + 1] == "auto"


def test_mask_hides_credentials():
    args = build_command_args(_fake_window(), "zju-connect")
    masked = mask_command_args(args)
    assert "p@ss!word with space" not in " ".join(masked)
    assert "2024000001" not in " ".join(masked)


def test_tun_mode_default_on():
    """TUN 全局路由是产品默认形态"""
    assert load_config()["tun_mode"] is True


def test_tun_mode_forced_off_on_windows(monkeypatch):
    """Windows 提权链路未验证：即使配置被打开/默认开，也强制关闭（与硬守卫同款策略）"""
    import utils.config_utils as cu

    monkeypatch.setattr(cu, "system", lambda: "Windows")
    w = SimpleNamespace()
    load_settings(w)
    assert w.tun_mode is False
