from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from danmaku_rs.types import Danmaku


@dataclass
class Issue:
    index: int
    kind: str
    message: str


def scan(items: List[Danmaku]) -> List[Issue]:
    issues: List[Issue] = []
    for idx, dm in enumerate(items):
        if "\n" in dm.content or "\r" in dm.content:
            issues.append(Issue(idx, "newline", "包含换行"))
        if len(dm.content) > 100:
            issues.append(Issue(idx, "length", f"长度 {len(dm.content)} > 100"))
        if not dm.content.strip():
            issues.append(Issue(idx, "empty", "空白内容"))
        if dm.time < 0:
            issues.append(Issue(idx, "time", "时间为负"))
        if dm.mode not in {1, 4, 5}:
            issues.append(Issue(idx, "mode", f"模式 {dm.mode} 无法发送"))
    return issues


def strip_newlines(items: List[Danmaku]) -> Tuple[List[Danmaku], int]:
    return _map_content(items, lambda text: " ".join(text.splitlines()).replace("\r", " "))


def clip_length(items: List[Danmaku], limit: int = 100) -> Tuple[List[Danmaku], int]:
    return _map_content(items, lambda text: text[:limit])


def _map_content(items: List[Danmaku], fn) -> Tuple[List[Danmaku], int]:
    fixed = 0
    out: List[Danmaku] = []
    for dm in items:
        content = fn(dm.content)
        if content != dm.content:
            fixed += 1
        out.append(
            Danmaku(
                time=dm.time,
                mode=dm.mode,
                font_size=dm.font_size,
                color=dm.color,
                content=content,
                pool=dm.pool,
                selected=dm.selected,
            )
        )
    return out, fixed


def autofix(items: List[Danmaku]) -> Tuple[List[Danmaku], int]:
    fixed = 0
    out: List[Danmaku] = []
    for dm in items:
        content = " ".join(dm.content.split())[:100]
        mode = 1 if dm.mode not in {1, 4, 5} else dm.mode
        time_sec = max(0.0, dm.time)
        changed = content != dm.content or mode != dm.mode or time_sec != dm.time
        if not content:
            continue
        if changed:
            fixed += 1
        out.append(
            Danmaku(
                time=time_sec,
                mode=mode,
                font_size=dm.font_size,
                color=dm.color,
                content=content,
                pool=dm.pool,
                selected=dm.selected,
            )
        )
    return out, fixed
