from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional
import requests

from danmaku_rs.config import USER_AGENT, cache_dir
from danmaku_rs.service.parser import decode_xml_bytes
from danmaku_rs.service.seo import score_video, tokenize
from danmaku_rs.types import TOUHOU_LABELS, VideoInfo, VideoPart


class ArchiveClient:
    def __init__(self, videos_url: str, xml_base: str, proxy: str = ""):
        self.videos_url = videos_url.rstrip("/")
        self.xml_base = xml_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.proxy = proxy
        self._videos: List[VideoInfo] = []

    def cache_path(self) -> Path:
        return cache_dir() / "videos.json"

    def load_videos(self, force: bool = False) -> List[VideoInfo]:
        cache = self.cache_path()
        if not force and cache.exists() and time.time() - cache.stat().st_mtime < 6 * 3600:
            raw = json.loads(cache.read_text(encoding="utf-8"))
        else:
            resp = self.session.get(self.videos_url, timeout=30)
            resp.raise_for_status()
            raw = resp.json()
            cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        if isinstance(raw, dict):
            raw = raw.get("videos") or raw.get("data") or raw.get("items") or []
        if not isinstance(raw, list):
            raise RuntimeError("记忆馆 videos.json 格式无法识别")
        self._videos = [self._to_video(item) for item in raw if isinstance(item, dict)]
        return self._videos

    def _to_video(self, item: dict) -> VideoInfo:
        parts = [
            VideoPart(
                cid=int(part.get("cid") or 0),
                page=int(part.get("page") or idx + 1),
                part=str(part.get("part") or f"P{idx + 1}"),
                duration=int(part.get("duration") or 0),
            )
            for idx, part in enumerate(item.get("parts") or [])
        ]
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.replace("，", ",").split(",") if part.strip()]
        elif not isinstance(tags, list):
            tags = []
        return VideoInfo(
            aid=int(item.get("aid") or 0),
            bvid=str(item.get("bvid") or ""),
            title=str(item.get("title") or ""),
            uploader=str(item.get("uploader_name") or ""),
            description=str(item.get("description") or ""),
            pic=str(item.get("pic") or ""),
            created=int(item.get("created") or 0),
            tags=list(tags),
            touhou_status=int(item.get("touhou_status") or 0),
            parts=parts,
        )

    def search(
        self,
        keyword: str = "",
        status: Optional[int] = None,
        limit: int = 200,
    ) -> List[VideoInfo]:
        tokens = tokenize(keyword)
        scored: List[tuple] = []
        for video in self._videos:
            if status is not None and video.touhou_status != status:
                continue
            score = score_video(video, tokens) if tokens else 1.0
            if tokens and score <= 0:
                continue
            scored.append((score, video))
        scored.sort(key=lambda item: -item[0])
        return [video for _score, video in scored[:limit]]

    def fetch_xml(self, cid: int) -> str:
        url = f"{self.xml_base}/{cid}.xml"
        resp = self.session.get(url, timeout=20)
        if resp.status_code == 404:
            raise RuntimeError(f"记忆馆弹幕库没有 cid={cid} 的 XML")
        resp.raise_for_status()
        return decode_xml_bytes(resp.content)

    def pages_url(self) -> str:
        return "https://touhougleaners.github.io/touhou-memory-archive-data/"


def status_label(code: int) -> str:
    return TOUHOU_LABELS.get(code, str(code))
