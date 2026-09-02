from __future__ import annotations

from copy import deepcopy
from typing import List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from danmaku_rs.config import load_settings, save_settings
from danmaku_rs.repo.accounts import AccountStore
from danmaku_rs.repo.archive import ArchiveClient
from danmaku_rs.repo.bili import BiliClient
from danmaku_rs.repo.history import HistoryStore
from danmaku_rs.repo.proxy import resolve_proxy
from danmaku_rs.service.live_session import LiveSession
from danmaku_rs.types import Account, Alert, Danmaku, SenderOptions, VideoInfo


class AppState(QObject):
    danmaku_changed = pyqtSignal()
    video_changed = pyqtSignal()
    account_changed = pyqtSignal()
    log_message = pyqtSignal(str, bool)
    alert_raised = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.accounts = AccountStore()
        self.history = HistoryStore()
        self.archive = ArchiveClient(
            self.settings["archive_json_url"],
            self.settings["xml_base_url"],
            self.resolved_proxy(),
        )
        self.live = LiveSession()
        self.alerts: List[Alert] = []
        self.video: Optional[VideoInfo] = None
        self.cid: Optional[int] = None
        self.danmaku: List[Danmaku] = []
        self.xml_name = ""
        self._undo: List[List[Danmaku]] = []

    def resolved_proxy(self) -> str:
        return resolve_proxy(str(self.settings.get("proxy_mode") or "auto"), str(self.settings.get("proxy") or ""))

    def persist_settings(self) -> None:
        save_settings(self.settings)
        url = str(self.settings["archive_json_url"]).rstrip("/")
        xml = str(self.settings["xml_base_url"]).rstrip("/")
        proxy = self.resolved_proxy()
        if self.archive.videos_url == url and self.archive.xml_base == xml and self.archive.proxy == proxy:
            return
        videos = list(self.archive._videos)
        self.archive = ArchiveClient(url, xml, proxy)
        self.archive._videos = videos

    def active_account(self) -> Optional[Account]:
        return self.accounts.active()

    def client(self) -> BiliClient:
        acc = self.active_account()
        if not acc:
            raise RuntimeError("请先在「账号」页添加并选择 Cookie")
        return self.client_for(acc)

    def client_for(self, acc: Account) -> BiliClient:
        return BiliClient(acc.sessdata, acc.bili_jct, acc.buvid3, self.resolved_proxy())

    def browse_client(self) -> BiliClient:
        acc = self.active_account()
        if acc:
            return self.client_for(acc)
        return BiliClient("", "", "", self.resolved_proxy())

    def push_undo(self) -> None:
        self._undo.append(deepcopy(self.danmaku))
        self._undo = self._undo[-30:]

    def pop_undo(self) -> bool:
        if not self._undo:
            return False
        self.danmaku = self._undo.pop()
        self.danmaku_changed.emit()
        return True

    def sender_options(self) -> SenderOptions:
        s = self.settings
        return SenderOptions(
            delay_min=float(s.get("delay_min", 8)),
            delay_max=float(s.get("delay_max", 11)),
            burst_enabled=bool(s.get("burst_enabled", True)),
            burst_every=int(s.get("burst_every", 5)),
            burst_rest=float(s.get("burst_rest", 25)),
            prevent_sleep=bool(s.get("prevent_sleep", True)),
            simulate=bool(s.get("simulate_default", True)),
            humanize=bool(s.get("humanize", True)),
            max_count=int(s.get("max_count", 200)),
            max_minutes=int(s.get("max_minutes", 0)),
        )

    def set_danmaku(self, items: List[Danmaku], name: str = "") -> None:
        self.danmaku = items
        if name:
            self.xml_name = name
        self.danmaku_changed.emit()

    def set_video(self, video: VideoInfo, cid: Optional[int] = None) -> None:
        self.video = video
        self.cid = cid or (video.parts[0].cid if video.parts else None)
        self.video_changed.emit()

    def log(self, message: str, error: bool = False) -> None:
        self.log_message.emit(message, error)
