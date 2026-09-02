from __future__ import annotations

import time
from typing import Dict, List, Optional

from danmaku_rs.repo.bili import BiliClient
from danmaku_rs.repo.history import HistoryStore
from danmaku_rs.service.inspector import compare
from danmaku_rs.service.live_session import LiveSession
from danmaku_rs.types import Danmaku, DanmakuStatus, LiveSnapshot, SenderOptions


def apply_audit(
    history: HistoryStore,
    bvid: str,
    cid: int,
    online_fps: set,
    min_age: float = 0.0,
) -> Dict[str, int]:
    pending: List[dict] = history.pending(bvid, cid)
    verified = lost = skipped = 0
    now = time.time()
    for row in pending:
        fp = row["fingerprint"]
        if fp in online_fps:
            history.update_status(bvid, cid, fp, DanmakuStatus.VERIFIED)
            verified += 1
            continue
        created = float(row.get("created_at") or 0)
        if min_age and now - created < min_age:
            skipped += 1
            continue
        history.update_status(bvid, cid, fp, DanmakuStatus.LOST)
        lost += 1
    return {
        "checked": len(pending),
        "verified": verified,
        "lost": lost,
        "waiting": skipped,
        "online": len(online_fps),
    }


def audit(client: BiliClient, history: HistoryStore, bvid: str, cid: int) -> Dict[str, int]:
    online = {dm.fingerprint for dm in client.fetch_online_danmaku(cid)}
    return apply_audit(history, bvid, cid, online)


def collect_snapshot(
    client: Optional[BiliClient],
    history: HistoryStore,
    session: LiveSession,
    local: List[Danmaku],
    bvid: str,
    cid: Optional[int],
    options: Optional[SenderOptions] = None,
    previous: Optional[LiveSnapshot] = None,
    auto_audit: bool = True,
) -> LiveSnapshot:
    counters = session.snapshot_counters()
    login_ok: Optional[bool] = None
    login_msg = "未选择账号"
    poll_error = ""
    online: List[Danmaku] = []

    if client is not None:
        if client.sessdata:
            try:
                login_ok, login_msg = client.check_login()
            except Exception as exc:
                login_ok, login_msg = False, str(exc)
        else:
            login_ok, login_msg = None, "游客模式（仅巡检公开数据）"
        if cid:
            try:
                online = client.fetch_online_danmaku(int(cid))
            except Exception as exc:
                poll_error = str(exc)

    if auto_audit and bvid and cid and client is not None and not poll_error:
        apply_audit(history, bvid, int(cid), {dm.fingerprint for dm in online}, min_age=180)

    cmp = compare(local, online) if local or online else {"coverage": 0.0}
    counts = history.counts(bvid, int(cid)) if bvid and cid else {}
    delay_min = options.delay_min if options else 8.0
    burst = options.burst_enabled if options else True
    online_count = len(online)
    return LiveSnapshot(
        ts=time.time(),
        login_ok=login_ok,
        login_msg=login_msg,
        online_count=online_count,
        local_count=len(local),
        coverage=float(cmp.get("coverage") or 0.0),
        pending=int(counts.get("pending") or 0),
        verified=int(counts.get("verified") or 0),
        lost=int(counts.get("lost") or 0),
        send_success=counters["success"],
        send_failed=counters["failed"],
        send_skipped=counters["skipped"],
        consecutive_fail=counters["consecutive_fail"],
        rate_limit_hits=counters["rate_limit_hits"],
        intercept_412=counters["intercept_412"],
        last_code=counters["last_code"],
        sending=counters["sending"],
        simulate=counters["simulate"],
        online_delta=online_count - (previous.online_count if previous else online_count),
        delay_min=delay_min,
        burst_enabled=burst,
        poll_error=poll_error,
        accounts_active=counters["accounts_active"],
    )
