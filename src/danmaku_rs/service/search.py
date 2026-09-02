from __future__ import annotations

import re
from typing import Iterable, List, Sequence
from urllib.parse import quote, quote_plus

import requests

from danmaku_rs.config import IA_SEARCH_URL, SEARCH_URL, USER_AGENT, WEB_LOCATION
from danmaku_rs.repo.archive import ArchiveClient
from danmaku_rs.repo.bili import BiliClient
from danmaku_rs.repo.wbi import sign_wbi
from danmaku_rs.service.parser import extract_bvid
from danmaku_rs.service.seo import expand_title, score_fields, score_video, tokenize
from danmaku_rs.types import SearchHit, VideoInfo

INVIDIOUS = (
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://invidious.privacyredirect.com",
    "https://inv.tux.pizza",
    "https://invidious.materialio.us",
)
PIPED = (
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
)


def lucene_query(text: str) -> str:
    cleaned = re.sub(r'[:()"\\]', " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _text_field(value) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    return str(value or "")


def directory_links(title: str, bvid: str = "") -> List[SearchHit]:
    query = expand_title(title) or bvid
    encoded = quote(query)
    plus = quote_plus(query)
    extras = f"对应失效稿 {bvid}" if bvid else "人工打开检索页"
    return [
        SearchHit("B站检索页", f"B站搜索：{query}", f"https://search.bilibili.com/all?keyword={encoded}", extras, bvid="", score=1.2),
        SearchHit("YouTube", f"YouTube 搜索：{query}", f"https://www.youtube.com/results?search_query={plus}", extras, score=1.1),
        SearchHit("互联网档案馆", f"Internet Archive：{query}", f"https://archive.org/search?query={encoded}", extras, score=1.1),
        SearchHit("AcFun", f"AcFun 搜索：{query}", f"https://www.acfun.cn/search?keyword={encoded}", extras, score=1.0),
        SearchHit("ニコニコ", f"niconico 搜索：{query}", f"https://www.nicovideo.jp/search/{encoded}", extras, score=1.0),
        SearchHit("其它站", f"DuckDuckGo：{query} 补档 OR reupload OR archive", f"https://duckduckgo.com/?q={plus}+%E8%A1%A5%E6%A1%A3+OR+reupload+OR+archive", extras, score=0.9),
    ]


def _session(proxy: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def search_internet_archive(query: str, tokens: Sequence[str], timeout: float = 10.0, proxy: str = "") -> List[SearchHit]:
    q = lucene_query(expand_title(query))
    if not q:
        return []
    params = {
        "q": f'("{q}") AND (mediatype:(movies) OR mediatype:(video))',
        "fl[]": ["identifier", "title", "description", "mediatype"],
        "output": "json",
        "rows": 12,
    }
    try:
        resp = _session(proxy).get(IA_SEARCH_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        docs = ((resp.json() or {}).get("response") or {}).get("docs") or []
    except Exception:
        return []
    hits: List[SearchHit] = []
    for doc in docs:
        ident = str(doc.get("identifier") or "")
        title = _text_field(doc.get("title")) or ident
        desc = _text_field(doc.get("description"))[:160]
        if not ident:
            continue
        hits.append(
            SearchHit(
                "互联网档案馆",
                title,
                f"https://archive.org/details/{ident}",
                desc or "Internet Archive",
                score=score_fields(title, desc, tokens, 6.0),
            )
        )
    return hits


def _youtube_hits(rows, tokens: Sequence[str], id_key: str, author_key: str) -> List[SearchHit]:
    hits: List[SearchHit] = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        video_id = str(row.get(id_key) or "")
        if not video_id:
            url = str(row.get("url") or "")
            match = re.search(r"(?:v=|/shorts/)([A-Za-z0-9_-]{6,})", url)
            video_id = match.group(1) if match else ""
        title = str(row.get("title") or "")
        author = str(row.get(author_key) or "")
        if not video_id or not title:
            continue
        hits.append(
            SearchHit(
                "YouTube",
                title,
                f"https://www.youtube.com/watch?v={video_id}",
                author,
                score=score_fields(title, author, tokens, 5.0),
            )
        )
    return hits


def search_youtube(query: str, tokens: Sequence[str], timeout: float = 4.0, proxy: str = "") -> List[SearchHit]:
    q = expand_title(query)
    if not q:
        return []
    session = _session(proxy)
    for base in INVIDIOUS:
        try:
            resp = session.get(f"{base}/api/v1/search", params={"q": q, "type": "video"}, timeout=timeout)
            if resp.status_code != 200:
                continue
            rows = resp.json()
            if not isinstance(rows, list):
                continue
        except Exception:
            continue
        hits = _youtube_hits(rows, tokens, "videoId", "author")
        if hits:
            return hits
    for base in PIPED:
        try:
            resp = session.get(f"{base}/search", params={"q": q, "filter": "videos"}, timeout=timeout)
            if resp.status_code != 200:
                continue
            rows = resp.json()
            if not isinstance(rows, list):
                continue
        except Exception:
            continue
        hits = _youtube_hits(rows, tokens, "id", "uploaderName")
        if hits:
            return hits
    return []


def search_bili_reupload(client: BiliClient, query: str, tokens: Sequence[str], skip_bvid: str = "") -> List[SearchHit]:
    keyword = expand_title(query)
    if not keyword:
        return []
    queries = [keyword]
    if "补档" not in keyword:
        queries.append(f"{keyword} 补档")
    skip = skip_bvid.lower()
    hits: List[SearchHit] = []
    seen = set()
    try:
        if not client.img_key:
            client.refresh_wbi()
    except Exception:
        return []
    for keyword_q in queries:
        try:
            signed = sign_wbi(
                {
                    "search_type": "video",
                    "keyword": keyword_q,
                    "page": 1,
                    "web_location": WEB_LOCATION,
                },
                client.img_key,
                client.sub_key,
            )
            resp = client.session.get(SEARCH_URL, params=signed, headers=client._headers(), timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            rows = ((payload.get("data") or {}).get("result")) or []
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            bvid = str(row.get("bvid") or "")
            title = re.sub(r"<[^>]+>", "", str(row.get("title") or ""))
            author = str(row.get("author") or "")
            if not bvid or bvid.lower() == skip or bvid in seen:
                continue
            seen.add(bvid)
            hits.append(
                SearchHit(
                    "B站",
                    title,
                    f"https://www.bilibili.com/video/{bvid}",
                    author,
                    bvid=bvid,
                    score=score_fields(title, author, tokens, 8.0),
                )
            )
    return hits


def rank_archive(videos: Iterable[VideoInfo], keyword: str, limit: int = 200) -> List[SearchHit]:
    tokens = tokenize(keyword)
    scored: List[SearchHit] = []
    for video in videos:
        score = score_video(video, tokens) if tokens else 1.0
        if tokens and score <= 0:
            continue
        scored.append(
            SearchHit(
                "记忆馆",
                video.title,
                f"https://www.bilibili.com/video/{video.bvid}" if video.bvid else "",
                f"{video.uploader} · {','.join(video.tags[:4])}",
                bvid=video.bvid,
                score=score,
                video=video,
            )
        )
    scored.sort(key=lambda hit: -hit.score)
    return scored[:limit]


def search_restore_targets(
    query: str,
    archive: ArchiveClient,
    client: BiliClient,
    cross_site: bool = True,
    proxy: str = "",
) -> dict:
    raw = (query or "").strip()
    bvid, _ = extract_bvid(raw)
    status = None
    title = raw
    dead = False
    warnings: List[str] = []
    if bvid.startswith("BV") and len(bvid) >= 12:
        try:
            status = client.inspect_view(bvid)
            dead = bool(status.get("dead"))
            if status.get("title"):
                title = status["title"]
            else:
                for video in archive._videos:
                    if video.bvid == bvid:
                        title = video.title or title
                        break
            if dead:
                title = expand_title(title) or bvid
        except Exception as exc:
            warnings.append(f"B站稿件探测失败: {exc}")
            for video in archive._videos:
                if video.bvid == bvid:
                    title = expand_title(video.title) or title
                    break
    if bvid.startswith("BV"):
        for video in archive._videos:
            if video.bvid == bvid and video.title:
                if title == raw or title == bvid:
                    title = expand_title(video.title) or title
                break
    tokens = tokenize(f"{title} {raw}")
    archive_hits = rank_archive(archive._videos, title or raw, 80)
    hits: List[SearchHit] = list(archive_hits)
    if cross_site:
        try:
            hits.extend(search_bili_reupload(client, title, tokens, skip_bvid=bvid if dead else ""))
        except Exception as exc:
            warnings.append(f"B站检索失败: {exc}")
        ia = search_internet_archive(title, tokens, proxy=proxy)
        yt = search_youtube(title, tokens, proxy=proxy)
        if not ia and not yt:
            warnings.append("部分站点接口未命中，已保留检索页")
        hits.extend(ia)
        hits.extend(yt)
        hits.extend(directory_links(title, bvid if bvid.startswith("BV") else ""))
    seen = set()
    unique: List[SearchHit] = []
    for hit in hits:
        key = hit.url or f"{hit.source}:{hit.title}"
        if key in seen:
            continue
        seen.add(key)
        if dead:
            hit.dead = True
            if bvid.startswith("BV") and bvid not in hit.extra:
                hit.extra = (hit.extra + f" · 对应失效稿 {bvid}").strip(" ·")
        unique.append(hit)
    unique.sort(key=lambda hit: -hit.score)
    return {
        "status": status,
        "title": title,
        "dead": dead,
        "bvid": bvid if bvid.startswith("BV") else "",
        "hits": unique[:80],
        "archive_hits": [hit.video for hit in archive_hits if hit.video][:400],
        "warnings": warnings,
    }
