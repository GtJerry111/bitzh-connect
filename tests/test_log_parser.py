from utils.log_parser import is_auth_failure, is_server_kick, parse_client_ip


def test_parse_client_ip():
    assert parse_client_ip("2026/09/01 12:00:00 Client IP: 10.0.43.17") == "10.0.43.17"


def test_parse_client_ip_absent():
    assert parse_client_ip("TLS: connected to: 112.91.150.228:443") is None


def test_parse_client_ip_rejects_malformed():
    assert parse_client_ip("Client IP: 999.1.2.3") is None


def test_auth_failure_server_message():
    assert is_auth_failure("VPN client setup error: Invalid username or password!")


def test_auth_failure_chinese():
    assert is_auth_failure("VPN client setup error: 用户名或密码错误")


def test_auth_failure_not_triggered_by_normal_log():
    assert not is_auth_failure("Client IP: 10.0.43.17")
    assert not is_auth_failure("TLS: connected to: 112.91.150.228:443")


def test_server_kick():
    assert is_server_kick("SendConn: server returned SHUTDOWN (cmd 0x08); session terminated by server")
    assert is_server_kick("SendConn: server returned RECONNECTLATER (cmd 0x05); should re-login and retry")
    assert not is_server_kick("Client IP: 10.0.43.17")


def test_parse_tun_interface():
    from utils.log_parser import parse_tun_interface

    assert parse_tun_interface("2026/09/22 14:32:17 Interface Name: utun11, index 32") == "utun11"
    assert parse_tun_interface("nothing") is None


def test_is_keepalive():
    from utils.log_parser import is_keepalive

    assert is_keepalive("2026/09/22 14:33:17 KeepAlive using UDP: OK")
    assert not is_keepalive("Client IP: 10.0.43.58")


def test_classify_disconnect():
    from utils.log_parser import classify_disconnect

    assert classify_disconnect("SHUTDOWN (cmd 0x08)") == "server_kick"
    assert classify_disconnect("RECONNECTLATER (cmd 0x01)") == "server_kick"
    assert classify_disconnect("Invalid username or password") == "auth"
    assert classify_disconnect("dial tcp: i/o timeout") == "network"
    assert classify_disconnect("connection reset by peer") == "network"
    assert classify_disconnect("ordinary line") is None
