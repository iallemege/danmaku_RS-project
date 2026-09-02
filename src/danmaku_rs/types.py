from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class DanmakuStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    LOST = "lost"
    FAILED = "failed"
    SKIPPED = "skipped"


class TouhouStatus(int, Enum):
    UNCHECKED = 0
    AUTO_TOUHOU = 1
    AUTO_OTHER = 2
    MANUAL_TOUHOU = 3
    MANUAL_OTHER = 4


TOUHOU_LABELS = {
    0: "未检查",
    1: "自动·东方",
    2: "自动·其他",
    3: "人工·东方",
    4: "人工·其他",
}

MODE_LABELS = {1: "滚动", 4: "底部", 5: "顶部", 6: "逆向", 7: "高级"}
SENDABLE_MODES = {1, 4, 5}
FATAL_API_CODES = {-101, -102, -111, 36704, 36711, 36713, 36715}


@dataclass
class Danmaku:
    time: float
    mode: int
    font_size: int
    color: int
    content: str
    pool: int = 0
    selected: bool = True

    @property
    def progress_ms(self) -> int:
        return int(self.time * 1000)

    @property
    def fingerprint(self) -> str:
        return f"{self.time:.3f}|{self.mode}|{self.color}|{self.content}"


@dataclass
class VideoPart:
    cid: int
    page: int
    part: str
    duration: int = 0


@dataclass
class VideoInfo:
    aid: int
    bvid: str
    title: str
    uploader: str = ""
    description: str = ""
    pic: str = ""
    created: int = 0
    tags: List[str] = field(default_factory=list)
    touhou_status: int = 0
    parts: List[VideoPart] = field(default_factory=list)


@dataclass
class Account:
    uid: str
    uname: str
    sessdata: str
    bili_jct: str
    buvid3: str = ""
    level: int = 0
    valid: Optional[bool] = None
    participate: bool = True


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    level: AlertLevel
    code: str
    message: str
    action: str = ""
    ts: float = 0.0


@dataclass
class LiveSnapshot:
    ts: float
    login_ok: Optional[bool] = None
    login_msg: str = ""
    online_count: int = 0
    local_count: int = 0
    coverage: float = 0.0
    pending: int = 0
    verified: int = 0
    lost: int = 0
    send_success: int = 0
    send_failed: int = 0
    send_skipped: int = 0
    consecutive_fail: int = 0
    rate_limit_hits: int = 0
    intercept_412: int = 0
    last_code: Optional[int] = None
    sending: bool = False
    simulate: bool = False
    online_delta: int = 0
    delay_min: float = 8.0
    burst_enabled: bool = True
    poll_error: str = ""
    accounts_active: int = 1


@dataclass
class SenderOptions:
    delay_min: float = 8.0
    delay_max: float = 11.0
    burst_enabled: bool = True
    burst_every: int = 5
    burst_rest: float = 25.0
    retry_limit: int = 3
    max_count: int = 500
    max_minutes: int = 0
    simulate: bool = True
    resume: bool = True
    prevent_sleep: bool = True
    time_offset: float = 0.0
    humanize: bool = True


@dataclass
class SearchHit:
    source: str
    title: str
    url: str
    extra: str = ""
    bvid: str = ""
    score: float = 0.0
    dead: Optional[bool] = None
    video: Optional[VideoInfo] = None
