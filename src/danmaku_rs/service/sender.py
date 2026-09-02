from __future__ import annotations

import random
import threading
import time
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Sequence

from danmaku_rs.repo.bili import BiliClient
from danmaku_rs.repo.history import HistoryStore
from danmaku_rs.types import FATAL_API_CODES, Account, Danmaku, DanmakuStatus, SenderOptions


def human_delay(options: SenderOptions) -> float:
    lo = float(options.delay_min)
    hi = float(options.delay_max)
    if hi < lo:
        lo, hi = hi, lo
    if not options.humanize:
        return random.uniform(lo, hi)
    mid = (lo + hi) / 2.0
    spread = max(0.15, (hi - lo) / 4.0)
    delay = random.gauss(mid, spread)
    delay = min(hi, max(lo, delay))
    if random.random() < 0.08:
        delay += random.uniform(1.5, 5.0)
    return delay


def estimate_seconds(count: int, options: SenderOptions) -> float:
    avg = (options.delay_min + options.delay_max) / 2
    bursts = (count // options.burst_every) if options.burst_enabled and options.burst_every else 0
    return count * avg + bursts * options.burst_rest


def estimate_parallel_seconds(count: int, accounts: int, options: SenderOptions) -> float:
    lanes = max(1, int(accounts))
    per = (int(count) + lanes - 1) // lanes
    return estimate_seconds(per, options)


def prevent_sleep(enable: bool) -> None:
    try:
        import ctypes

        es_continuous = 0x80000000
        es_system = 0x00000001
        flag = es_continuous | es_system if enable else es_continuous
        ctypes.windll.kernel32.SetThreadExecutionState(flag)
    except Exception:
        pass


def prepare_work(items: Sequence[Danmaku], options: SenderOptions) -> List[Danmaku]:
    selected = [dm for dm in items if dm.selected][: options.max_count]
    if not options.time_offset:
        return list(selected)
    return [replace(dm, time=max(0.0, dm.time + options.time_offset)) for dm in selected]


def shard_round_robin(items: Sequence[Danmaku], n: int) -> List[List[Danmaku]]:
    lanes = max(1, int(n))
    buckets: List[List[Danmaku]] = [[] for _ in range(lanes)]
    for idx, dm in enumerate(items):
        buckets[idx % lanes].append(dm)
    return buckets


class FingerprintGate:
    def __init__(self, initial: Optional[set] = None):
        self._lock = threading.Lock()
        self._seen = set(initial or ())

    def contains(self, fingerprint: str) -> bool:
        with self._lock:
            return fingerprint in self._seen

    def add(self, fingerprint: str) -> None:
        with self._lock:
            self._seen.add(fingerprint)

    def add_many(self, fingerprints) -> None:
        with self._lock:
            self._seen.update(fingerprints)


class SendJob:
    def __init__(
        self,
        client: BiliClient,
        history: HistoryStore,
        items: List[Danmaku],
        bvid: str,
        cid: int,
        aid: int,
        options: SenderOptions,
        account_uid: str = "",
        account_name: str = "",
        on_log: Optional[Callable[[str, bool], None]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        on_lane: Optional[Callable[[dict], None]] = None,
        gate: Optional[FingerprintGate] = None,
        manage_sleep: bool = True,
    ):
        self.client = client
        self.history = history
        self.items = items
        self.bvid = bvid
        self.cid = cid
        self.aid = aid
        self.options = options
        self.account_uid = account_uid
        self.account_name = account_name
        self.on_log = on_log or (lambda *_: None)
        self.on_progress = on_progress or (lambda *_: None)
        self.on_event = on_event or (lambda *_: None)
        self.on_lane = on_lane or (lambda *_: None)
        self.gate = gate
        self.manage_sleep = manage_sleep
        self.running = True
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.total = 0
        self.processed = 0
        self.failed_items: List[Danmaku] = []

    def stop(self) -> None:
        self.running = False

    def _sleep(self, seconds: float) -> None:
        end = time.time() + max(0.0, seconds)
        while self.running and time.time() < end:
            time.sleep(min(0.2, end - time.time()))

    def _tag(self, message: str) -> str:
        who = self.account_name or self.account_uid
        return f"[{who}] {message}" if who else message

    def _emit(self, kind: str, **payload) -> None:
        event = {"kind": kind, "uid": self.account_uid, "uname": self.account_name, **payload}
        self.on_event(event)

    def _report(self) -> None:
        self.on_lane(
            {
                "uid": self.account_uid,
                "uname": self.account_name,
                "success": self.success,
                "failed": self.failed,
                "skipped": self.skipped,
                "done": self.processed,
                "total": self.total,
                "running": self.running,
            }
        )

    def run(self) -> dict:
        if self.manage_sleep:
            prevent_sleep(self.options.prevent_sleep)
        started = time.time()
        work = prepare_work(self.items, self.options)
        self.total = len(work)
        if self.gate is None:
            initial = self.history.sent_fingerprints(self.bvid, self.cid) if self.options.resume else set()
            self.gate = FingerprintGate(initial)
        elif self.options.resume:
            self.gate.add_many(self.history.sent_fingerprints(self.bvid, self.cid))
        try:
            if not self.options.simulate:
                self.client.refresh_wbi()
            for idx, dm in enumerate(work):
                if not self.running:
                    break
                if self.options.max_minutes and (time.time() - started) / 60 >= self.options.max_minutes:
                    self.on_log(self._tag("达到最长运行时间，已停止"), True)
                    break
                self.processed = idx + 1
                if self.gate.contains(dm.fingerprint):
                    self.skipped += 1
                    self._emit("skip", fingerprint=dm.fingerprint)
                    self.on_progress(self.processed, self.total, "skip")
                    self._report()
                    continue
                ok = self._send_one(dm, idx)
                if ok:
                    self.success += 1
                    self.gate.add(dm.fingerprint)
                    if not self.options.simulate:
                        self.history.record(self.bvid, self.cid, dm, DanmakuStatus.PENDING, self.account_uid)
                else:
                    self.failed += 1
                    self.failed_items.append(dm)
                    if not self.options.simulate:
                        self.history.record(self.bvid, self.cid, dm, DanmakuStatus.FAILED, self.account_uid)
                self.on_progress(self.processed, self.total, "ok" if ok else "fail")
                self._report()
                if idx < self.total - 1 and self.running:
                    delay = human_delay(self.options)
                    if self.options.burst_enabled and self.options.burst_every and (idx + 1) % self.options.burst_every == 0:
                        delay += self.options.burst_rest
                        self.on_log(self._tag(f"爆发休息 {delay:.1f}s"), False)
                    self._sleep(delay)
        finally:
            if self.manage_sleep:
                prevent_sleep(False)
            self._report()
        return {
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "total": self.total,
            "uid": self.account_uid,
            "failed_items": list(self.failed_items),
        }

    def _send_one(self, dm: Danmaku, idx: int) -> bool:
        if self.options.simulate:
            self.on_log(self._tag(f"[模拟] {dm.time:.1f}s  {dm.content}"), False)
            self._emit("success", simulate=True)
            return True
        for attempt in range(self.options.retry_limit):
            if not self.running:
                return False
            try:
                payload = self.client.send_danmaku(self.bvid, self.cid, self.aid, dm)
            except Exception as exc:
                text = str(exc)
                kind = "intercept" if "412" in text else "network"
                self._emit(kind, code=412 if kind == "intercept" else None, message=text)
                self.on_log(self._tag(f"#{idx + 1} 网络错误: {exc}"), True)
                self._sleep(2 ** attempt)
                continue
            code = payload.get("code", -1)
            message = payload.get("message") or str(code)
            if code == 0:
                self.on_log(self._tag(f"#{idx + 1} 发送成功: {dm.content}"), False)
                self._emit("success", code=0)
                return True
            if code in FATAL_API_CODES:
                self.on_log(self._tag(f"致命错误 [{code}] {message}"), True)
                self._emit("fatal", code=code, message=message)
                self.running = False
                return False
            if code == 36703:
                wait = 12 + attempt * 8
                self.on_log(self._tag(f"频率过快，{wait}s 后重试"), True)
                self._emit("rate_limit", code=36703, message=message)
                self._sleep(wait)
                continue
            self.on_log(self._tag(f"#{idx + 1} 失败 [{code}] {message}"), True)
            self._emit("fail", code=code, message=message)
            self._sleep(2 ** attempt)
        return False


class MultiSendJob:
    def __init__(
        self,
        jobs: List[SendJob],
        options: SenderOptions,
        on_log: Optional[Callable[[str, bool], None]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        on_lane: Optional[Callable[[dict], None]] = None,
    ):
        self.jobs = jobs
        self.options = options
        self.on_log = on_log or (lambda *_: None)
        self.on_event = on_event or (lambda *_: None)
        self.on_lane = on_lane or (lambda *_: None)
        self.running = True
        self._lanes: Dict[str, dict] = {}
        for job in self.jobs:
            job.manage_sleep = False
            job.on_log = self._forward_log
            job.on_event = self._forward_event
            job.on_lane = self._forward_lane

    def stop(self) -> None:
        self.running = False
        for job in self.jobs:
            job.stop()

    def _forward_log(self, message: str, error: bool) -> None:
        self.on_log(message, error)

    def _forward_event(self, event: dict) -> None:
        self.on_event(event)

    def _forward_lane(self, stats: dict) -> None:
        uid = str(stats.get("uid") or "")
        self._lanes[uid] = stats
        self.on_lane(stats)

    def totals(self) -> dict:
        success = failed = skipped = total = 0
        lanes = []
        failed_items: List[Danmaku] = []
        for job in self.jobs:
            success += job.success
            failed += job.failed
            skipped += job.skipped
            total += job.total
            failed_items.extend(job.failed_items)
            lanes.append(
                {
                    "uid": job.account_uid,
                    "uname": job.account_name,
                    "success": job.success,
                    "failed": job.failed,
                    "skipped": job.skipped,
                    "total": job.total,
                }
            )
        return {
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "total": total,
            "lanes": lanes,
            "failed_items": failed_items,
        }

    def run(self) -> dict:
        prevent_sleep(self.options.prevent_sleep)
        threads = [threading.Thread(target=job.run, name=f"send-{job.account_uid}", daemon=True) for job in self.jobs]
        try:
            for thread in threads:
                thread.start()
            while any(thread.is_alive() for thread in threads):
                if not self.running:
                    for job in self.jobs:
                        job.stop()
                time.sleep(0.2)
            for thread in threads:
                thread.join()
        finally:
            prevent_sleep(False)
        return self.totals()


def build_multi_job(
    accounts: Sequence[Account],
    make_client: Callable[[Account], BiliClient],
    history: HistoryStore,
    items: Sequence[Danmaku],
    bvid: str,
    cid: int,
    aid: int,
    options: SenderOptions,
) -> MultiSendJob:
    work = prepare_work(items, options)
    shards = shard_round_robin(work, len(accounts))
    gate = FingerprintGate(history.sent_fingerprints(bvid, cid) if options.resume else set())
    jobs = []
    for account, shard in zip(accounts, shards):
        if not shard:
            continue
        lane_opts = replace(options, time_offset=0.0, max_count=len(shard), prevent_sleep=False)
        jobs.append(
            SendJob(
                make_client(account),
                history,
                shard,
                bvid,
                cid,
                aid,
                lane_opts,
                account.uid,
                account.uname,
                gate=gate,
                manage_sleep=False,
            )
        )
    return MultiSendJob(jobs, options)
