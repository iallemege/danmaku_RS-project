from __future__ import annotations

import sqlite3
import threading
import time
from typing import List, Optional

from danmaku_rs.config import history_path
from danmaku_rs.types import Danmaku, DanmakuStatus


class HistoryStore:
    def __init__(self):
        self.path = history_path()
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY,
                    bvid TEXT NOT NULL,
                    cid INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    content TEXT,
                    progress_ms INTEGER,
                    color INTEGER,
                    mode INTEGER,
                    font_size INTEGER,
                    status TEXT,
                    account_uid TEXT,
                    created_at INTEGER,
                    UNIQUE(bvid, cid, fingerprint)
                )
                """
            )

    def sent_fingerprints(self, bvid: str, cid: int) -> set:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT fingerprint FROM history WHERE bvid=? AND cid=? AND status IN ('pending','verified')",
                (bvid, cid),
            ).fetchall()
        return {row["fingerprint"] for row in rows}

    def record(self, bvid: str, cid: int, dm: Danmaku, status: DanmakuStatus, account_uid: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO history (bvid, cid, fingerprint, content, progress_ms, color, mode, font_size, status, account_uid, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bvid, cid, fingerprint) DO UPDATE SET status=excluded.status
                """,
                (
                    bvid,
                    cid,
                    dm.fingerprint,
                    dm.content,
                    dm.progress_ms,
                    dm.color,
                    dm.mode,
                    dm.font_size,
                    status.value,
                    account_uid,
                    int(time.time()),
                ),
            )

    def update_status(self, bvid: str, cid: int, fingerprint: str, status: DanmakuStatus) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE history SET status=? WHERE bvid=? AND cid=? AND fingerprint=?",
                (status.value, bvid, cid, fingerprint),
            )

    def query(self, keyword: str = "", bvid: str = "", status: str = "") -> List[dict]:
        sql = "SELECT * FROM history WHERE 1=1"
        args: List[object] = []
        if keyword:
            sql += " AND content LIKE ?"
            args.append(f"%{keyword}%")
        if bvid:
            sql += " AND bvid=?"
            args.append(bvid)
        if status:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT 500"
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def danmaku_of(self, status: str, bvid: str = "", cid: Optional[int] = None) -> List[Danmaku]:
        sql = "SELECT * FROM history WHERE status=?"
        args: List[object] = [status]
        if bvid:
            sql += " AND bvid=?"
            args.append(bvid)
        if cid:
            sql += " AND cid=?"
            args.append(int(cid))
        sql += " ORDER BY id DESC LIMIT 4000"
        with self._lock, self._connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, args).fetchall()]
        return [row_to_danmaku(row) for row in rows]

    def counts(self, bvid: str, cid: int) -> dict:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM history WHERE bvid=? AND cid=? GROUP BY status",
                (bvid, cid),
            ).fetchall()
        out = {"pending": 0, "verified": 0, "lost": 0, "failed": 0, "skipped": 0}
        for row in rows:
            out[str(row["status"])] = int(row["n"])
        return out

    def pending(self, bvid: str, cid: int) -> List[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM history WHERE bvid=? AND cid=? AND status='pending'",
                (bvid, cid),
            ).fetchall()
        return [dict(row) for row in rows]


def row_to_danmaku(row: dict) -> Danmaku:
    return Danmaku(
        time=(int(row.get("progress_ms") or 0)) / 1000.0,
        mode=int(row.get("mode") or 1),
        font_size=int(row.get("font_size") or 25),
        color=int(row.get("color") or 16777215),
        content=str(row.get("content") or ""),
    )
