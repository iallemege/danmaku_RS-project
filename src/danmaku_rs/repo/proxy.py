from __future__ import annotations

import os
import re
from typing import Optional, Tuple

import requests

from danmaku_rs.config import NAV_URL, USER_AGENT


def detect_system_proxy() -> str:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            if enabled and server:
                server = str(server).strip()
                if "=" in server:
                    match = re.search(r"https?=([^;]+)", server, re.I)
                    server = match.group(1) if match else server.split(";")[0]
                if server and "://" not in server:
                    server = "http://" + server
                return server
        except OSError:
            pass
    return ""


def resolve_proxy(mode: str, custom: str = "") -> str:
    custom = (custom or "").strip()
    mode = (mode or "auto").lower()
    if mode == "direct":
        return ""
    if mode == "custom":
        return custom
    system = detect_system_proxy()
    if mode == "system":
        return system
    return system or custom


def probe_proxy(proxy: str, timeout: float = 8.0) -> Tuple[bool, str]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    try:
        resp = session.get(NAV_URL, timeout=timeout)
        if resp.status_code == 200:
            label = proxy or "直连"
            return True, f"{label} 可用 ({resp.status_code})"
        return False, f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        return False, str(exc)
