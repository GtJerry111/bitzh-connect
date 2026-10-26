# app/privileged_helper/routes.py
"""macOS 直连 /32 路由管理（helper 内部使用，可注入 runner 便于单测）。"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from dataclasses import dataclass

STATE_PATH = "/var/run/bitzh-connect-direct-routes.json"


@dataclass
class RouteAttempt:
    ip: str
    ok: bool
    error: str = ""


def parse_default_route(text: str) -> tuple[str | None, str | None]:
    gateway = interface = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("gateway:"):
            gateway = line.split(":", 1)[1].strip() or None
        elif line.startswith("interface:"):
            interface = line.split(":", 1)[1].strip() or None
    return gateway, interface


def run_route(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


class DirectRouteManager:
    def __init__(self, state_path: str = STATE_PATH, runner=run_route):
        self._state_path = state_path
        self._runner = runner

    def default_gateway(self) -> tuple[str | None, str | None]:
        result = self._runner(["route", "-n", "get", "default"])
        if result.returncode != 0:
            return None, None
        gateway, interface = parse_default_route(result.stdout)
        if not gateway or not interface:
            return gateway, interface
        if interface.startswith(("utun", "tun")):
            return None, interface
        return gateway, interface

    def apply(
        self, ips: list[str]
    ) -> tuple[list[RouteAttempt], str | None, str | None, str | None]:
        if not ips:
            return [], None, None, None
        gateway, interface = self.default_gateway()
        if gateway is None:
            return [], gateway, interface, "no_physical_default_gateway"
        attempts: list[RouteAttempt] = []
        applied: list[str] = []
        for ip in ips:
            result = self._runner(["route", "-n", "add", "-host", ip, gateway])
            if result.returncode == 0:
                attempts.append(RouteAttempt(ip, True))
                applied.append(ip)
                continue
            stderr = (result.stderr or "").strip()
            if "File exists" in stderr:
                check = self._runner(["route", "-n", "get", ip])
                if check.returncode == 0 and f"gateway: {gateway}" in check.stdout:
                    attempts.append(RouteAttempt(ip, True))
                    applied.append(ip)
                else:
                    attempts.append(
                        RouteAttempt(ip, False, "route_exists_other_gateway")
                    )
                continue
            attempts.append(RouteAttempt(ip, False, stderr or "route_add_failed"))
        self._write_state(applied, gateway)
        return attempts, gateway, interface, None

    def cleanup(self, ips: list[str]) -> None:
        for ip in ips:
            try:
                ipaddress.IPv4Address(ip)
            except ipaddress.AddressValueError:
                continue
            self._runner(["route", "-n", "delete", "-host", ip])
        self._clear_state()

    def cleanup_stale(self) -> None:
        data = self._read_state()
        if not data:
            return
        for ip in data.get("ips", []):
            try:
                ipaddress.IPv4Address(ip)
            except ipaddress.AddressValueError:
                continue
            self._runner(["route", "-n", "delete", "-host", ip])
        self._clear_state()

    def _read_state(self) -> dict | None:
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _write_state(self, ips: list[str], gateway: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump({"gateway": gateway, "ips": ips}, f)
        except OSError:
            pass

    def _clear_state(self) -> None:
        try:
            os.unlink(self._state_path)
        except OSError:
            pass
