# app/utils/direct_ip.py
"""直连 IP：解析、归一化、校验与状态模型（纯函数，无 Qt 依赖）。"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field

import psutil

MAX_DIRECT_IPS = 100

_SEPARATORS = re.compile(r"[\s,;、，；]+")
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
_SURROUNDING = " \t\r\n\"'“”‘’()（）[]【】"


def normalize_ip_token(token: str) -> str:
    token = str(token).translate(_FULLWIDTH_DIGITS)
    token = token.replace("．", ".").replace("\u3000", " ")
    token = token.strip()
    if token.endswith("。"):
        token = token[:-1].strip()
    return token.strip(_SURROUNDING).strip()


def split_pasted_ips(text: str) -> list[str]:
    return [
        token
        for token in (normalize_ip_token(part) for part in _SEPARATORS.split(str(text)))
        if token
    ]


def parse_ipv4(token: str) -> str | None:
    token = normalize_ip_token(token)
    if not token:
        return None
    try:
        return str(ipaddress.IPv4Address(token))
    except ipaddress.AddressValueError:
        return None


def parse_direct_ips(value: str | list[str] | tuple[str, ...]) -> list[str]:
    """配置/粘贴输入 → 去重后的合法 IPv4 列表；非法项被丢弃。"""
    if isinstance(value, str):
        raw = split_pasted_ips(value)
    else:
        raw = []
        for item in value:
            raw.extend(split_pasted_ips(str(item)))
    result: list[str] = []
    seen: set[str] = set()
    for token in raw:
        ip = parse_ipv4(token)
        if ip and ip not in seen:
            seen.add(ip)
            result.append(ip)
    return result


@dataclass(frozen=True)
class DirectIpIssue:
    index: int
    value: str
    reason: str
    message: str


@dataclass
class DirectIpValidation:
    valid: list[str] = field(default_factory=list)
    skipped_local: list[str] = field(default_factory=list)
    issues: list[DirectIpIssue] = field(default_factory=list)


def _is_reserved(addr: ipaddress.IPv4Address) -> bool:
    return (
        addr.is_unspecified
        or addr.is_loopback
        or addr.is_multicast
        or addr == ipaddress.IPv4Address("255.255.255.255")
    )


def validate_direct_ips(
    values: list[str],
    *,
    forbidden_ips: set[str] | frozenset[str] = frozenset(),
    local_networks: tuple[ipaddress.IPv4Network, ...] = (),
) -> DirectIpValidation:
    result = DirectIpValidation()
    seen: set[str] = set()
    for index, raw in enumerate(values):
        token = normalize_ip_token(raw)
        if not token:
            continue
        ip = parse_ipv4(token)
        if ip is None:
            result.issues.append(
                DirectIpIssue(index, raw, "invalid", "不是合法的 IPv4 地址")
            )
            continue
        if ip in seen:
            result.issues.append(
                DirectIpIssue(index, ip, "duplicate", "重复的 IP")
            )
            continue
        seen.add(ip)
        addr = ipaddress.IPv4Address(ip)
        if _is_reserved(addr):
            result.issues.append(
                DirectIpIssue(index, ip, "reserved", "不能使用保留/回环/组播地址")
            )
            continue
        if ip in forbidden_ips:
            result.issues.append(
                DirectIpIssue(index, ip, "forbidden", "不能排除本机、网关或 VPN 服务器")
            )
            continue
        if any(addr in network for network in local_networks):
            result.skipped_local.append(ip)
            continue
        result.valid.append(ip)
    return result


def ip_set_changed(old: list[str], new: list[str]) -> bool:
    return set(old) != set(new)


def status_for_ip(ip: str, results: dict[str, bool], pending: set[str]) -> str:
    if ip in pending:
        return "pending"
    if ip in results:
        return "ok" if results[ip] else "failed"
    return "unapplied"


def local_ipv4_addresses() -> set[str]:
    result: set[str] = set()
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address:
                result.add(addr.address)
    return result


def local_ipv4_networks() -> tuple[ipaddress.IPv4Network, ...]:
    result: list[ipaddress.IPv4Network] = []
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.address or not addr.netmask:
                continue
            try:
                result.append(
                    ipaddress.IPv4Network(
                        f"{addr.address}/{addr.netmask}", strict=False
                    )
                )
            except ValueError:
                pass
    return tuple(result)
