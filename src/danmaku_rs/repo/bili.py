from __future__ import annotations

import time
import uuid
from typing import Dict, List, Tuple

import requests

from danmaku_rs.config import DEAD_VIEW_CODES, DM_LIST_URL, DM_POST_URL, NAV_URL, USER_AGENT, VIEW_URL, WEB_LOCATION
from danmaku_rs.repo.wbi import sign_wbi
from danmaku_rs.service.parser import decode_xml_bytes, parse_xml_text
from danmaku_rs.types import Danmaku, VideoInfo, VideoPart


class BiliClient:
    def __init__(self, sessdata: str, bili_jct: str, buvid3: str = "", proxy: str = ""):
        self.sessdata = sessdata.strip()
        self.bili_jct = bili_jct.strip()
        self.buvid3 = buvid3.strip() or (str(uuid.uuid4()).upper() + "infoc")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        cookies = {"buvid3": self.buvid3}
        if self.sessdata:
            cookies["SESSDATA"] = self.sessdata
        if self.bili_jct:
            cookies["bili_jct"] = self.bili_jct
        self.session.cookies.update(cookies)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.img_key = ""
        self.sub_key = ""
        self.uname = ""
        self.uid = ""
        self.level = 0

    def _headers(self, bvid: str = "") -> Dict[str, str]:
        referer = f"https://www.bilibili.com/video/{bvid}" if bvid else "https://www.bilibili.com/"
        return {"Referer": referer, "Origin": "https://www.bilibili.com"}

    def refresh_wbi(self) -> dict:
        resp = self.session.get(NAV_URL, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or {}
        wbi = data.get("wbi_img") or {}
        img_url = wbi.get("img_url") or ""
        sub_url = wbi.get("sub_url") or ""
        if not img_url or not sub_url:
            raise RuntimeError("未能获取 WBI 密钥")
        self.img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        self.sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        if payload.get("code") == 0 and data.get("isLogin"):
            self.uname = data.get("uname") or ""
            self.uid = str(data.get("mid") or "")
            self.level = int((data.get("level_info") or {}).get("current_level") or 0)
        return payload

    def check_login(self) -> Tuple[bool, str]:
        payload = self.refresh_wbi()
        data = payload.get("data") or {}
        if payload.get("code") == 0 and data.get("isLogin"):
            return True, f"{self.uname}  UID {self.uid}  Lv.{self.level}"
        return False, payload.get("message") or "Cookie 无效或已过期"

    def inspect_view(self, bvid: str) -> dict:
        resp = self.session.get(VIEW_URL, params={"bvid": bvid}, headers=self._headers(bvid), timeout=12)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or {}
        code = int(payload.get("code") if payload.get("code") is not None else -1)
        message = str(payload.get("message") or "")
        title = str(data.get("title") or "")
        dead_text = any(word in message for word in ("失效", "不存在", "不可见", "删除", "锁定"))
        dead = code in DEAD_VIEW_CODES or (code != 0 and dead_text)
        return {
            "ok": code == 0,
            "dead": dead,
            "code": code,
            "message": message,
            "title": title,
            "data": data,
        }

    def fetch_video(self, bvid: str) -> VideoInfo:
        try:
            self.refresh_wbi()
        except Exception:
            pass
        info = self.inspect_view(bvid)
        if not info["ok"]:
            mark = "稿件已失效，可到记忆馆做跨站检索" if info["dead"] else "获取视频信息失败"
            raise RuntimeError(f"{mark} [{info['code']}] {info['message']}")
        data = info["data"]
        parts = [
            VideoPart(
                cid=int(page["cid"]),
                page=int(page.get("page") or idx + 1),
                part=str(page.get("part") or f"P{idx + 1}"),
                duration=int(page.get("duration") or 0),
            )
            for idx, page in enumerate(data.get("pages") or [])
        ]
        owner = data.get("owner") or {}
        return VideoInfo(
            aid=int(data.get("aid") or 0),
            bvid=str(data.get("bvid") or bvid),
            title=str(data.get("title") or ""),
            uploader=str(owner.get("name") or ""),
            description=str(data.get("desc") or ""),
            pic=str(data.get("pic") or ""),
            parts=parts,
        )

    def send_danmaku(self, bvid: str, oid: int, aid: int, dm: Danmaku) -> dict:
        if not self.img_key:
            self.refresh_wbi()
        body = {
            "type": 1,
            "oid": int(oid),
            "msg": dm.content,
            "bvid": bvid,
            "aid": int(aid),
            "progress": dm.progress_ms,
            "color": int(dm.color),
            "fontsize": int(dm.font_size),
            "pool": int(dm.pool),
            "mode": int(dm.mode),
            "rnd": int(time.time() * 1_000_000),
            "csrf": self.bili_jct,
        }
        query = sign_wbi({"web_location": WEB_LOCATION, "csrf": self.bili_jct}, self.img_key, self.sub_key)
        resp = self.session.post(DM_POST_URL, params=query, data=body, headers=self._headers(bvid), timeout=15)
        if resp.status_code == 412:
            raise RuntimeError("请求被拦截 (HTTP 412)")
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"响应不是 JSON: {resp.text[:120]}") from exc

    def fetch_online_danmaku(self, cid: int) -> List[Danmaku]:
        resp = self.session.get(DM_LIST_URL, params={"oid": int(cid)}, headers=self._headers(), timeout=20)
        resp.raise_for_status()
        return parse_xml_text(decode_xml_bytes(resp.content))
