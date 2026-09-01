"""解析 zju-connect 内核输出的纯函数集合。

日志特征来源（上游 Go 源码，v1.3.1）：
- 登录成功最后一步输出 "Client IP: x.x.x.x"（request.go requestIP）
- 登录失败 log.Fatalf 输出 "VPN client setup error: ..."（main.go）
- 服务端踢人输出 "SHUTDOWN (cmd 0x08)" / "RECONNECTLATER (cmd 0x..)"（protocol.go）
"""
import re

_CLIENT_IP_RE = re.compile(r"Client IP:\s*((?:\d{1,3}\.){3}\d{1,3})")

# 认证失败模式。对真实服务器的校准见 Task 11 验证清单。
AUTH_FAILURE_PATTERNS = [
    re.compile(r"Invalid username or password", re.IGNORECASE),
    re.compile(r"用户名或密码", re.IGNORECASE),
    re.compile(r"auth\w*\s*(fail|error|invalid)", re.IGNORECASE),
    re.compile(r"setup error.*(password|credential|认证|密码)", re.IGNORECASE),
]

_SERVER_KICK_RE = re.compile(r"SHUTDOWN \(cmd|RECONNECTLATER \(cmd", re.IGNORECASE)


def _valid_ip(ip: str) -> bool:
    return all(0 <= int(part) <= 255 for part in ip.split("."))


def parse_client_ip(text: str) -> str | None:
    """从一行内核输出中提取虚拟 IP，没有则返回 None。"""
    match = _CLIENT_IP_RE.search(text)
    if match and _valid_ip(match.group(1)):
        return match.group(1)
    return None


def is_auth_failure(text: str) -> bool:
    """判断该行输出是否表示认证失败（此类失败不应触发自动重连）。"""
    return any(pattern.search(text) for pattern in AUTH_FAILURE_PATTERNS)


def is_server_kick(text: str) -> bool:
    """判断该行输出是否表示被服务器主动断开（用于日志提示）。"""
    return bool(_SERVER_KICK_RE.search(text))
