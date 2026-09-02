#!/usr/bin/env python3
"""Bilibili danmaku restorer v6.3 — desktop GUI."""

from __future__ import annotations

import html
import json
import random
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import reduce
from hashlib import md5
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

VERSION = "6.3.0"
DM_POST_URL = "https://api.bilibili.com/x/v2/dm/post"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
WEB_LOCATION = "1315873"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]
SENDABLE_MODES = {1, 4, 5}
MODE_LABELS = {1: "滚动", 4: "底部", 5: "顶部", 6: "逆向", 7: "高级"}
FATAL_CODES = {-101, -102, -111, 36704, 36711, 36713, 36715}


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return reduce(lambda acc, idx: acc + raw[idx], MIXIN_KEY_ENC_TAB, "")[:32]


def sign_wbi(params: Dict[str, object], img_key: str, sub_key: str) -> Dict[str, str]:
    signed = dict(params)
    signed["wts"] = int(time.time())
    cleaned = {
        str(key): "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in sorted(signed.items(), key=lambda item: item[0])
    }
    query = urlencode(cleaned)
    cleaned["w_rid"] = md5((query + mixin_key(img_key, sub_key)).encode("utf-8")).hexdigest()
    return cleaned


def fingerprint(dm: Dict) -> str:
    return f"{dm['time']:.3f}|{dm['mode']}|{dm['content']}"


def parse_cookie_blob(raw: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for part in raw.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key in {"SESSDATA", "bili_jct", "buvid3", "DedeUserID"}:
            found[key] = value.strip()
    return found


def parse_danmaku_xml(path: str) -> List[Dict]:
    tree = ET.parse(path)
    items: List[Dict] = []
    for elem in tree.iter("d"):
        params = (elem.attrib.get("p") or "").split(",")
        if len(params) < 4:
            continue
        content = " ".join((elem.text or "").split())[:100]
        if not content:
            continue
        try:
            time_sec = float(params[0])
            mode = int(float(params[1]))
            font_size = int(float(params[2]))
            color = int(float(str(params[3]).split(".")[0]))
            pool = int(float(params[5])) if len(params) > 5 else 0
        except (TypeError, ValueError):
            continue
        if mode == 6:
            mode = 1
        if mode not in SENDABLE_MODES:
            continue
        if not 0 <= time_sec <= 86400:
            continue
        if not 0 <= color <= 0xFFFFFF:
            color = 16777215
        font_size = 25 if font_size not in {12, 16, 18, 25, 36} else font_size
        if pool not in {0, 1}:
            pool = 0
        items.append(
            {
                "time": time_sec,
                "mode": mode,
                "font_size": font_size,
                "color": color,
                "pool": pool,
                "content": content,
            }
        )
    return items


class BiliClient:
    def __init__(self, sessdata: str, bili_jct: str, buvid3: str):
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.buvid3 = buvid3 or (str(uuid.uuid4()).upper() + "infoc")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Origin": "https://www.bilibili.com",
                "Accept": "application/json, text/plain, */*",
            }
        )
        self.session.cookies.update(
            {
                "SESSDATA": sessdata,
                "bili_jct": bili_jct,
                "buvid3": buvid3,
            }
        )
        self.img_key = ""
        self.sub_key = ""
        self.uname = ""

    def _headers(self, bvid: str = "") -> Dict[str, str]:
        referer = f"https://www.bilibili.com/video/{bvid}" if bvid else "https://www.bilibili.com/"
        return {
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
        }

    def refresh_wbi(self) -> None:
        resp = self.session.get(NAV_URL, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or {}
        wbi = data.get("wbi_img") or {}
        img_url = wbi.get("img_url") or ""
        sub_url = wbi.get("sub_url") or ""
        if not img_url or not sub_url:
            raise RuntimeError("未能获取 WBI 密钥，请检查网络或 Cookie")
        self.img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        self.sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        if payload.get("code") == 0 and data.get("isLogin"):
            self.uname = data.get("uname") or ""

    def check_login(self) -> Tuple[bool, str]:
        self.refresh_wbi()
        resp = self.session.get(NAV_URL, headers=self._headers(), timeout=10)
        payload = resp.json()
        if payload.get("code") == 0 and (payload.get("data") or {}).get("isLogin"):
            uname = payload["data"].get("uname") or "已登录"
            level = (payload["data"].get("level_info") or {}).get("current_level", "?")
            return True, f"已登录 {uname}（Lv.{level}）"
        return False, payload.get("message") or "Cookie 无效或已过期"

    def fetch_video(self, bvid: str) -> dict:
        self.refresh_wbi()
        resp = self.session.get(
            VIEW_URL,
            params={"bvid": bvid},
            headers=self._headers(bvid),
            timeout=12,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or "获取视频信息失败")
        return payload["data"]

    def send_danmaku(self, bvid: str, oid: int, aid: int, dm: Dict) -> dict:
        if not self.img_key:
            self.refresh_wbi()
        body = {
            "type": 1,
            "oid": int(oid),
            "msg": dm["content"],
            "bvid": bvid,
            "aid": int(aid),
            "progress": int(dm["time"] * 1000),
            "color": int(dm["color"]),
            "fontsize": int(dm["font_size"]),
            "pool": int(dm["pool"]),
            "mode": int(dm["mode"]),
            "rnd": int(time.time() * 1_000_000),
            "csrf": self.bili_jct,
        }
        query = sign_wbi(
            {"web_location": WEB_LOCATION, "csrf": self.bili_jct},
            self.img_key,
            self.sub_key,
        )
        resp = self.session.post(
            DM_POST_URL,
            params=query,
            data=body,
            headers=self._headers(bvid),
            timeout=15,
        )
        if resp.status_code == 412:
            raise RuntimeError("请求被拦截 (HTTP 412)，请降低频率或更换 Cookie")
        try:
            return resp.json()
        except ValueError as exc:
            raise RuntimeError(f"响应不是 JSON: {resp.text[:120]}") from exc


class RestoreWorker(QThread):
    progress = pyqtSignal(int, int)
    log = pyqtSignal(str, bool)
    finished_ok = pyqtSignal(int, int)

    def __init__(self, client: BiliClient, config: dict):
        super().__init__()
        self.client = client
        self.config = config
        self._running = True

    def stop(self) -> None:
        self._running = False

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(min(0.2, end - time.time()))

    def run(self) -> None:
        danmaku_list: List[Dict] = self.config["danmaku_list"]
        sent: set = self.config["sent"]
        total = len(danmaku_list)
        success = 0
        try:
            self.client.refresh_wbi()
            for idx, dm in enumerate(danmaku_list):
                if not self._running:
                    break
                key = fingerprint(dm)
                if key in sent:
                    self.progress.emit(idx + 1, total)
                    continue
                if self.config["simulate"]:
                    self.log.emit(f"[模拟] {dm['time']:.1f}s  {dm['content']}", False)
                    success += 1
                    sent.add(key)
                    self.progress.emit(idx + 1, total)
                    self._sleep(0.05)
                    continue
                ok = self._send_one(dm, idx)
                if ok:
                    success += 1
                    sent.add(key)
                    self._save_checkpoint(idx)
                self.progress.emit(idx + 1, total)
                if idx < total - 1 and self._running:
                    delay = self.config["min_delay"] + random.uniform(0, self.config["jitter"])
                    self.log.emit(f"等待 {delay:.1f}s 后发送下一条", False)
                    self._sleep(delay)
            self.finished_ok.emit(success, total)
        except Exception as exc:
            self.log.emit(f"任务中断: {exc}", True)
            self.finished_ok.emit(success, total)

    def _send_one(self, dm: Dict, idx: int) -> bool:
        retries = int(self.config["retry_limit"])
        for attempt in range(retries):
            if not self._running:
                return False
            try:
                payload = self.client.send_danmaku(
                    self.config["bvid"],
                    self.config["oid"],
                    self.config["aid"],
                    dm,
                )
            except Exception as exc:
                self.log.emit(f"#{idx + 1} 网络错误: {exc}", True)
                self._sleep(2 ** attempt)
                continue
            code = payload.get("code", -1)
            message = payload.get("message") or str(code)
            if code == 0:
                self.log.emit(f"#{idx + 1} 发送成功: {dm['content']}", False)
                return True
            if code in FATAL_CODES:
                self.log.emit(f"致命错误 [{code}] {message}，已停止", True)
                self._running = False
                return False
            if code == 36703:
                wait = 12 + attempt * 8
                self.log.emit(f"频率过快，{wait}s 后重试", True)
                self._sleep(wait)
                continue
            self.log.emit(
                f"#{idx + 1} 失败 [{code}] {message}（{attempt + 1}/{retries}）",
                True,
            )
            self._sleep(2 ** attempt)
        return False

    def _save_checkpoint(self, idx: int) -> None:
        path = self.config.get("checkpoint_file")
        if not path or (idx + 1) % 5 != 0:
            return
        payload = {
            "bvid": self.config["bvid"],
            "oid": self.config["oid"],
            "sent": list(self.config["sent"]),
            "timestamp": int(time.time()),
        }
        tmp = Path(path).with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"B站弹幕补档工具 v{VERSION}")
        self.resize(1180, 760)
        self.xml_path = ""
        self.danmaku_list: List[Dict] = []
        self.aid = 0
        self.worker: Optional[RestoreWorker] = None
        self.checkpoint_file = Path.home() / ".bili_dm_cache" / "progress.json"
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        root = QSplitter(Qt.Horizontal)
        root.addWidget(self._build_left())
        root.addWidget(self._build_right())
        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 1)
        root.setSizes([380, 800])
        self.setCentralWidget(root)
        status = QStatusBar()
        status.showMessage("就绪")
        self.setStatusBar(status)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 8, 12)

        cred = QGroupBox("登录凭证")
        form = QFormLayout(cred)
        self.input_sessdata = QLineEdit()
        self.input_bili_jct = QLineEdit()
        self.input_buvid3 = QLineEdit()
        for field in (self.input_sessdata, self.input_bili_jct):
            field.setEchoMode(QLineEdit.Password)
        self.input_sessdata.setPlaceholderText("可粘贴整段 Cookie")
        self.input_sessdata.editingFinished.connect(self._maybe_parse_cookie)
        form.addRow("SESSDATA", self.input_sessdata)
        form.addRow("bili_jct", self.input_bili_jct)
        form.addRow("buvid3", self.input_buvid3)
        login_row = QHBoxLayout()
        self.btn_login = QPushButton("检测登录")
        self.btn_login.clicked.connect(self._check_login)
        self.lbl_login = QLabel("未验证")
        self.lbl_login.setWordWrap(True)
        login_row.addWidget(self.btn_login)
        login_row.addWidget(self.lbl_login, 1)
        form.addRow(login_row)
        layout.addWidget(cred)

        video = QGroupBox("目标视频")
        video_form = QFormLayout(video)
        self.input_bvid = QLineEdit()
        self.input_bvid.setPlaceholderText("BV1xxxxxxxxxx")
        self.combo_parts = QComboBox()
        self.btn_parts = QPushButton("获取分P")
        self.btn_parts.clicked.connect(self._fetch_parts)
        video_form.addRow("BV 号", self.input_bvid)
        video_form.addRow(self.btn_parts)
        video_form.addRow("分P", self.combo_parts)
        layout.addWidget(video)

        files = QGroupBox("弹幕文件")
        files_layout = QVBoxLayout(files)
        self.lbl_xml = QLabel("未选择 XML")
        self.lbl_xml.setWordWrap(True)
        self.btn_xml = QPushButton("选择弹幕 XML")
        self.btn_xml.clicked.connect(self._select_xml)
        files_layout.addWidget(self.lbl_xml)
        files_layout.addWidget(self.btn_xml)
        layout.addWidget(files)

        opts = QGroupBox("发送设置")
        opts_form = QFormLayout(opts)
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(5, 90)
        self.spin_delay.setValue(8)
        self.spin_delay.setSuffix(" 秒")
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 5000)
        self.spin_max.setValue(200)
        self.spin_retry = QSpinBox()
        self.spin_retry.setRange(1, 5)
        self.spin_retry.setValue(3)
        self.check_simulate = QCheckBox("模拟模式（不真正发送）")
        self.check_simulate.setChecked(True)
        self.check_resume = QCheckBox("断点续传")
        opts_form.addRow("间隔", self.spin_delay)
        opts_form.addRow("最多发送", self.spin_max)
        opts_form.addRow("重试次数", self.spin_retry)
        opts_form.addRow(self.check_simulate)
        opts_form.addRow(self.check_resume)
        layout.addWidget(opts)

        self.progress = QProgressBar()
        self.lbl_progress = QLabel("等待开始")
        self.btn_start = QPushButton("开始补档")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self._toggle)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_start, 2)
        btn_row.addWidget(self.btn_stop, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.lbl_progress)
        layout.addLayout(btn_row)
        layout.addStretch()
        return panel

    def _build_right(self) -> QWidget:
        splitter = QSplitter(Qt.Vertical)
        preview = QWidget()
        preview_layout = QHBoxLayout(preview)
        preview_layout.setContentsMargins(0, 12, 12, 0)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["时间", "内容", "类型"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.stats = QTableWidget(0, 3)
        self.stats.setHorizontalHeaderLabels(["类型", "数量", "占比"])
        self.stats.verticalHeader().setVisible(False)
        self.stats.setMaximumWidth(260)
        preview_layout.addWidget(self.table, 3)
        preview_layout.addWidget(self.stats, 1)

        log_wrap = QWidget()
        log_layout = QVBoxLayout(log_wrap)
        log_layout.setContentsMargins(0, 0, 12, 12)
        log_head = QHBoxLayout()
        log_head.addWidget(QLabel("运行日志"))
        log_head.addStretch()
        btn_export = QPushButton("导出日志")
        btn_export.clicked.connect(self._export_log)
        log_head.addWidget(btn_export)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        log_layout.addLayout(log_head)
        log_layout.addWidget(self.log_area)

        splitter.addWidget(preview)
        splitter.addWidget(log_wrap)
        splitter.setSizes([420, 260])
        return splitter

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #1f1f1f; color: #f2f2f2; font-size: 13px; }
            QGroupBox { border: 1px solid #3a3a3a; margin-top: 10px; padding: 10px 8px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #00a1d6; }
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget {
                background: #2b2b2b; color: #f2f2f2; border: 1px solid #4a4a4a; padding: 4px;
            }
            QPushButton {
                background: #00a1d6; color: #fff; border: none; padding: 8px 12px;
            }
            QPushButton:hover { background: #008bb8; }
            QPushButton:disabled { background: #444; color: #aaa; }
            QHeaderView::section { background: #333; color: #fff; padding: 4px; border: none; }
            QProgressBar { border: 1px solid #444; text-align: center; background: #2b2b2b; }
            QProgressBar::chunk { background: #00a1d6; }
            """
        )

    def _log(self, message: str, error: bool = False) -> None:
        stamp = time.strftime("%H:%M:%S")
        color = "#ff6b6b" if error else "#7dcea0"
        self.log_area.append(
            f"<span style='color:{color}'>[{stamp}] {html.escape(message)}</span>"
        )
        self.statusBar().showMessage(message, 6000)

    def _maybe_parse_cookie(self) -> None:
        blob = self.input_sessdata.text()
        if "bili_jct=" not in blob and "SESSDATA=" not in blob:
            return
        found = parse_cookie_blob(blob)
        if found.get("SESSDATA"):
            self.input_sessdata.setText(found["SESSDATA"])
        if found.get("bili_jct"):
            self.input_bili_jct.setText(found["bili_jct"])
        if found.get("buvid3"):
            self.input_buvid3.setText(found["buvid3"])
        self._log("已从 Cookie 字符串解析凭证")

    def _client(self) -> BiliClient:
        return BiliClient(
            self.input_sessdata.text().strip(),
            self.input_bili_jct.text().strip(),
            self.input_buvid3.text().strip(),
        )

    def _check_login(self) -> None:
        if not self.input_sessdata.text().strip() or not self.input_bili_jct.text().strip():
            self._log("请先填写 SESSDATA 和 bili_jct", True)
            return
        try:
            ok, msg = self._client().check_login()
            self.lbl_login.setText(msg)
            self._log(msg, not ok)
        except Exception as exc:
            self._log(f"登录检测失败: {exc}", True)

    def _fetch_parts(self) -> None:
        bvid = self.input_bvid.text().strip()
        if not bvid.startswith("BV"):
            self._log("BV 号格式不正确", True)
            return
        try:
            data = self._client().fetch_video(bvid)
            self.aid = int(data.get("aid") or 0)
            self.combo_parts.clear()
            for page in data.get("pages") or []:
                self.combo_parts.addItem(f"P{page.get('page')}: {page.get('part')}", page.get("cid"))
            title = data.get("title") or ""
            self._log(f"已加载《{title}》，共 {self.combo_parts.count()} 个分P")
        except Exception as exc:
            self._log(f"获取分P失败: {exc}", True)

    def _select_xml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择弹幕文件", "", "XML 文件 (*.xml)")
        if not path:
            return
        self.xml_path = path
        self.lbl_xml.setText(Path(path).name)
        try:
            self.danmaku_list = parse_danmaku_xml(path)
        except Exception as exc:
            self.danmaku_list = []
            self._log(f"XML 解析失败: {exc}", True)
            return
        self._fill_preview()
        self._log(f"已解析 {len(self.danmaku_list)} 条可发送弹幕")

    def _fill_preview(self) -> None:
        self.table.setRowCount(0)
        counter: Dict[int, int] = defaultdict(int)
        for idx, dm in enumerate(self.danmaku_list):
            counter[dm["mode"]] += 1
            if idx >= 300:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"{dm['time']:.1f}s"))
            self.table.setItem(row, 1, QTableWidgetItem(dm["content"]))
            self.table.setItem(row, 2, QTableWidgetItem(MODE_LABELS.get(dm["mode"], str(dm["mode"]))))
        total = len(self.danmaku_list) or 1
        self.stats.setRowCount(0)
        rows = [("总计", len(self.danmaku_list), "100%")]
        rows.extend(
            (MODE_LABELS.get(mode, str(mode)), count, f"{count / total:.1%}")
            for mode, count in sorted(counter.items())
        )
        for row, (name, count, ratio) in enumerate(rows):
            self.stats.insertRow(row)
            self.stats.setItem(row, 0, QTableWidgetItem(str(name)))
            self.stats.setItem(row, 1, QTableWidgetItem(str(count)))
            self.stats.setItem(row, 2, QTableWidgetItem(ratio))

    def _validate(self) -> bool:
        if not self.input_sessdata.text().strip() or not self.input_bili_jct.text().strip():
            self._log("SESSDATA / bili_jct 不能为空", True)
            return False
        if not self.input_bvid.text().strip().startswith("BV"):
            self._log("请填写正确 BV 号", True)
            return False
        if self.combo_parts.currentIndex() < 0 or self.combo_parts.currentData() in (None, ""):
            self._log("请先获取并选择分P", True)
            return False
        if not self.danmaku_list:
            self._log("请先选择有效的弹幕 XML", True)
            return False
        return True

    def _load_sent(self) -> set:
        if not self.check_resume.isChecked() or not self.checkpoint_file.exists():
            return set()
        try:
            data = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
        except Exception:
            return set()
        if data.get("bvid") != self.input_bvid.text().strip():
            return set()
        if str(data.get("oid")) != str(self.combo_parts.currentData()):
            return set()
        sent = set(data.get("sent") or [])
        self._log(f"已加载断点，跳过 {len(sent)} 条")
        return sent

    def _toggle(self) -> None:
        if self.worker and self.worker.isRunning():
            self._stop()
            return
        if not self._validate():
            return
        if not self.check_simulate.isChecked():
            reply = QMessageBox.question(
                self,
                "确认发送",
                "即将向 B 站真实发送弹幕。请确认这是你有权补档的稿件。\n建议先用模拟模式试跑。",
            )
            if reply != QMessageBox.Yes:
                return
        client = self._client()
        try:
            ok, msg = client.check_login()
            self.lbl_login.setText(msg)
            if not ok and not self.check_simulate.isChecked():
                self._log(msg, True)
                return
        except Exception as exc:
            if not self.check_simulate.isChecked():
                self._log(f"无法验证登录: {exc}", True)
                return
            self._log(f"登录检测跳过: {exc}", True)

        limit = self.spin_max.value()
        payload = {
            "danmaku_list": self.danmaku_list[:limit],
            "bvid": self.input_bvid.text().strip(),
            "oid": int(self.combo_parts.currentData()),
            "aid": self.aid,
            "min_delay": float(self.spin_delay.value()),
            "jitter": 3.0,
            "retry_limit": self.spin_retry.value(),
            "simulate": self.check_simulate.isChecked(),
            "sent": self._load_sent(),
            "checkpoint_file": str(self.checkpoint_file),
        }
        self.progress.setMaximum(len(payload["danmaku_list"]))
        self.progress.setValue(0)
        self.worker = RestoreWorker(client, payload)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._log)
        self.worker.finished_ok.connect(self._on_done)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._log(
            f"开始任务：{len(payload['danmaku_list'])} 条，"
            f"{'模拟' if payload['simulate'] else '真实发送'}，间隔 {payload['min_delay']}s"
        )
        self.worker.start()

    def _stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self._log("正在停止…")

    def _on_progress(self, current: int, total: int) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        ratio = current / total if total else 0
        self.lbl_progress.setText(f"{current}/{total}  ({ratio:.1%})")

    def _on_done(self, success: int, total: int) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._log(f"任务结束：成功 {success}/{total}")
        if success:
            QMessageBox.information(self, "完成", f"成功处理 {success}/{total} 条弹幕")

    def _export_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出日志", "danmaku_log.txt", "文本文件 (*.txt)")
        if path:
            Path(path).write_text(self.log_area.toPlainText(), encoding="utf-8")
            self._log(f"日志已导出到 {path}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        event.accept()


def main() -> None:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
