from PyQt5.QtCore import QThread, pyqtSignal

from danmaku_rs.repo.bili import BiliClient
from danmaku_rs.repo.login import QrSession
from danmaku_rs.service.sender import MultiSendJob, SendJob
from danmaku_rs.types import Account


class Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    log = pyqtSignal(str, bool)
    progress = pyqtSignal(int, int, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class SendWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    log = pyqtSignal(str, bool)
    progress = pyqtSignal(int, int, str)
    event = pyqtSignal(object)
    lane = pyqtSignal(object)

    def __init__(self, job: SendJob):
        super().__init__()
        self.job = job
        job.on_log = lambda msg, err: self.log.emit(msg, err)
        job.on_progress = lambda cur, tot, kind: self.progress.emit(cur, tot, kind)
        job.on_event = lambda ev: self.event.emit(ev)
        job.on_lane = lambda stats: self.lane.emit(stats)

    def stop(self):
        self.job.stop()

    def run(self):
        try:
            self.done.emit(self.job.run())
        except Exception as exc:
            self.failed.emit(str(exc))


class MultiSendWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    log = pyqtSignal(str, bool)
    progress = pyqtSignal(int, int, str)
    event = pyqtSignal(object)
    lane = pyqtSignal(object)

    def __init__(self, job: MultiSendJob):
        super().__init__()
        self.job = job
        job.on_log = lambda msg, err: self.log.emit(msg, err)
        job.on_event = lambda ev: self.event.emit(ev)
        job.on_lane = self._on_lane

    def _on_lane(self, stats: dict) -> None:
        self.lane.emit(stats)
        done = sum(item.get("done", 0) for item in self.job._lanes.values())
        total = sum(item.get("total", 0) for item in self.job._lanes.values()) or sum(j.total for j in self.job.jobs)
        self.progress.emit(done, max(total, 1), "lane")

    def stop(self):
        self.job.stop()

    def run(self):
        try:
            self.done.emit(self.job.run())
        except Exception as exc:
            self.failed.emit(str(exc))


class MonitorWorker(QThread):
    snapshot = pyqtSignal(object)
    alerts = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, collect, analyze, interval: float):
        super().__init__()
        self.collect = collect
        self.analyze = analyze
        self.interval = max(5.0, float(interval))
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        previous = None
        while self._running:
            try:
                snap = self.collect(previous)
                incoming = self.analyze(snap, previous)
                self.snapshot.emit(snap)
                if incoming:
                    self.alerts.emit(incoming)
                previous = snap
            except Exception as exc:
                self.failed.emit(str(exc))
            waited = 0.0
            while self._running and waited < self.interval:
                self.msleep(200)
                waited += 0.2


class QrLoginWorker(QThread):
    ready = pyqtSignal(str)
    status = pyqtSignal(str)
    logged_in = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, proxy: str = ""):
        super().__init__()
        self.proxy = proxy
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            session = QrSession(self.proxy)
            url, _key = session.generate()
            self.ready.emit(url)
            self.status.emit("等待扫码")
            while self._running:
                code, message, cookies = session.poll()
                if code == 0:
                    sess = str((cookies or {}).get("SESSDATA") or "")
                    jct = str((cookies or {}).get("bili_jct") or "")
                    buvid = str((cookies or {}).get("buvid3") or "")
                    if not sess or not jct:
                        self.failed.emit("扫码成功但未拿到 SESSDATA / bili_jct")
                        return
                    self.status.emit("正在验证登录…")
                    client = BiliClient(sess, jct, buvid, self.proxy)
                    ok, msg = client.check_login()
                    if not ok:
                        self.failed.emit(msg)
                        return
                    self.logged_in.emit(
                        {
                            "account": Account(
                                client.uid,
                                client.uname,
                                sess,
                                jct,
                                client.buvid3,
                                client.level,
                                True,
                            ),
                            "message": msg,
                        }
                    )
                    return
                if code == 86038:
                    self.failed.emit("二维码已过期，请重新生成")
                    return
                if code == 86090:
                    self.status.emit("已扫码，请在手机上确认")
                elif code == 86101:
                    self.status.emit("等待扫码")
                elif message:
                    self.status.emit(message)
                waited = 0.0
                while self._running and waited < 1.8:
                    self.msleep(200)
                    waited += 0.2
            self.status.emit("已取消扫码")
        except Exception as exc:
            self.failed.emit(str(exc))
