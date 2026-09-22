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

# 握手时内核打印的服务器 RSA 公钥材料（RSA key: <hex> / RSA exp: <exp>）。
# 公钥本身可公开（密码正是用它加密后才发出），但对用户是噪音且易误读为泄密
_RSA_MATERIAL_RE = re.compile(r"RSA (key|exp):", re.IGNORECASE)


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


def is_rsa_material(text: str) -> bool:
    """判断该行是否为 RSA 公钥材料（GUI 日志折叠为一行中文说明）。"""
    return bool(_RSA_MATERIAL_RE.search(text))


_TUN_IFACE_RE = re.compile(r"Interface Name:\s*([^,\s]+)")
_KEEPALIVE_RE = re.compile(r"KeepAlive", re.IGNORECASE)

# 网络层断开特征（非服务器主动踢、非认证失败）
_NETWORK_ERROR_PATTERNS = [
    re.compile(r"i/o timeout", re.IGNORECASE),
    re.compile(r"connection reset", re.IGNORECASE),
    re.compile(r"broken pipe", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"no route to host", re.IGNORECASE),
    re.compile(r"EOF", re.IGNORECASE),
]


def parse_tun_interface(text: str) -> str | None:
    """从内核输出解析本连接创建的 TUN 接口名（如 utun11）。"""
    match = _TUN_IFACE_RE.search(text)
    return match.group(1) if match else None


def is_keepalive(text: str) -> bool:
    """是否为本连接的 keepalive 输出行（用于假死活跃度打点）。"""
    return bool(_KEEPALIVE_RE.search(text))


def classify_disconnect(text: str) -> str | None:
    """把一行内核输出分类为断开原因：server_kick/auth/network/None。"""
    if is_server_kick(text):
        return "server_kick"
    if is_auth_failure(text):
        return "auth"
    if any(pattern.search(text) for pattern in _NETWORK_ERROR_PATTERNS):
        return "network"
    return None
