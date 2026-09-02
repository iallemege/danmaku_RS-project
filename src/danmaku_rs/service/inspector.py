from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from danmaku_rs.types import Danmaku, MODE_LABELS


def fingerprints(items: Iterable[Danmaku]) -> set:
    return {dm.fingerprint for dm in items}


def compare(local: List[Danmaku], online: List[Danmaku]) -> Dict[str, object]:
    local_fp = fingerprints(local)
    online_fp = fingerprints(online)
    missing = local_fp - online_fp
    extra = online_fp - local_fp
    return {
        "local": len(local),
        "online": len(online),
        "matched": len(local_fp & online_fp),
        "missing_online": len(missing),
        "only_online": len(extra),
        "coverage": (len(local_fp & online_fp) / len(local_fp)) if local_fp else 0.0,
    }


def density(items: List[Danmaku], bucket: float = 30.0) -> List[tuple]:
    counts: Dict[int, int] = defaultdict(int)
    for dm in items:
        counts[int(dm.time // bucket)] += 1
    return [(idx * bucket, counts[idx]) for idx in sorted(counts)]


def type_stats(items: List[Danmaku]) -> List[tuple]:
    counts: Dict[int, int] = defaultdict(int)
    for dm in items:
        counts[dm.mode] += 1
    total = len(items) or 1
    return [(MODE_LABELS.get(mode, str(mode)), count, count / total) for mode, count in sorted(counts.items())]


def drop_duplicates(items: List[Danmaku]) -> tuple:
    seen = set()
    out: List[Danmaku] = []
    dropped = 0
    for dm in items:
        if dm.fingerprint in seen:
            dropped += 1
            continue
        seen.add(dm.fingerprint)
        out.append(dm)
    return out, dropped


def sort_by_time(items: List[Danmaku]) -> List[Danmaku]:
    return sorted(items, key=lambda dm: (dm.time, dm.mode, dm.content))
