from __future__ import annotations

import re
from typing import List, Sequence

from danmaku_rs.types import VideoInfo

BOOST = (
    "补档",
    "弹幕",
    "东方",
    "失效",
    "镜像",
    "转载",
    "备份",
    "reupload",
    "mirror",
    "archive",
    "touhou",
)


def tokenize(keyword: str) -> List[str]:
    text = (keyword or "").strip()
    parts = [part.lower() for part in re.split(r"[\s,，/|]+", text) if part]
    lowered = text.lower()
    if lowered and lowered not in parts:
        parts.insert(0, lowered)
    return parts


def expand_title(title: str) -> str:
    cleaned = re.sub(
        r"[\[【（(]?(失效|已删除|已失效|已和谐|deleted|unavailable)[\]】）)]?",
        " ",
        title or "",
        flags=re.I,
    )
    return re.sub(r"\s+", " ", cleaned).strip() or (title or "").strip()


def score_video(video: VideoInfo, tokens: Sequence[str]) -> float:
    if not tokens:
        return 1.0
    title = video.title.lower()
    tags = " ".join(video.tags).lower()
    uploader = video.uploader.lower()
    desc = video.description.lower()
    bvid = video.bvid.lower()
    score = 0.0
    for raw in tokens:
        tok = raw.lower()
        if tok and tok in bvid:
            score += 50
        if tok and tok in title:
            score += 12
            if title == tok:
                score += 10
        if tok and tok in tags:
            score += 5
        if tok and tok in uploader:
            score += 3
        if tok and tok in desc:
            score += 1
    blob = f"{title} {tags}"
    for word in BOOST:
        if word in blob:
            score += 2
    return score


def score_fields(title: str, extra: str, tokens: Sequence[str], source_boost: float = 0.0) -> float:
    blob = f"{title} {extra}".lower()
    score = source_boost
    for tok in tokens:
        if tok and tok in blob:
            score += 8
    for word in BOOST:
        if word in blob:
            score += 2
    return score
