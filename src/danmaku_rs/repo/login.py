from __future__ import annotations

from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests

from danmaku_rs.config import QR_GENERATE_URL, QR_POLL_URL, USER_AGENT


def qr_matrix(url: str):
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


def cookies_from_login(session_cookies: Dict[str, str], redirect_url: str = "") -> Dict[str, str]:
    cookies = {str(key): str(value) for key, value in (session_cookies or {}).items() if value}
    if redirect_url:
        query = parse_qs(urlparse(redirect_url).query)
        for key in ("SESSDATA", "bili_jct", "buvid3", "DedeUserID"):
            if cookies.get(key):
                continue
            values = query.get(key)
            if values:
                cookies[key] = unquote(values[0])
    return cookies


class QrSession:
    def __init__(self, proxy: str = ""):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Origin": "https://www.bilibili.com",
                "Referer": "https://www.bilibili.com/",
            }
        )
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.qrcode_key = ""
        self.url = ""

    def generate(self) -> Tuple[str, str]:
        resp = self.session.get(QR_GENERATE_URL, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or "申请二维码失败")
        data = payload.get("data") or {}
        self.url = str(data.get("url") or "")
        self.qrcode_key = str(data.get("qrcode_key") or "")
        if not self.url or not self.qrcode_key:
            raise RuntimeError("二维码数据不完整")
        return self.url, self.qrcode_key

    def poll(self) -> Tuple[int, str, Optional[Dict[str, str]]]:
        resp = self.session.get(QR_POLL_URL, params={"qrcode_key": self.qrcode_key}, timeout=12)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or {}
        code = int(data.get("code") if data.get("code") is not None else payload.get("code") or -1)
        message = str(data.get("message") or payload.get("message") or "")
        if code != 0:
            return code, message, None
        cookies = cookies_from_login(
            {cookie.name: cookie.value for cookie in self.session.cookies},
            str(data.get("url") or ""),
        )
        return 0, "登录成功", cookies
