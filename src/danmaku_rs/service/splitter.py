from __future__ import annotations

from typing import List, Sequence, Tuple

from danmaku_rs.types import Danmaku


def split_by_count(items: Sequence[Danmaku], chunk: int) -> List[List[Danmaku]]:
    size = max(1, int(chunk))
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def split_by_duration(items: Sequence[Danmaku], seconds: float) -> List[List[Danmaku]]:
    window = max(1.0, float(seconds))
    buckets: List[List[Danmaku]] = []
    for dm in items:
        idx = int(dm.time // window)
        while len(buckets) <= idx:
            buckets.append([])
        buckets[idx].append(dm)
    return [chunk for chunk in buckets if chunk]


def split_by_names(items: Sequence[Danmaku], names: Sequence[str]) -> List[Tuple[str, List[Danmaku]]]:
    labels = [name.strip() for name in names if name.strip()] or ["Part1"]
    if not items:
        return [(label, []) for label in labels]
    n = len(labels)
    per = max(1, (len(items) + n - 1) // n)
    out: List[Tuple[str, List[Danmaku]]] = []
    for i, label in enumerate(labels):
        out.append((label, list(items[i * per : (i + 1) * per])))
    return out
