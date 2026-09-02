from __future__ import annotations

import html
import time
import webbrowser
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QShortcut,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from danmaku_rs import APP_TITLE, __version__
from danmaku_rs.config import PROJECT_HOME
from danmaku_rs.repo.archive import status_label
from danmaku_rs.repo.bili import BiliClient
from danmaku_rs.repo.login import qr_matrix
from danmaku_rs.repo.proxy import probe_proxy
from danmaku_rs.service.exporter import write_jsonl, write_xml
from danmaku_rs.service.analyzer import analyze, merge_alerts, worst_level
from danmaku_rs.service.inspector import compare, density, drop_duplicates, sort_by_time, type_stats
from danmaku_rs.service.monitor import audit, collect_snapshot
from danmaku_rs.service.parser import extract_bvid, parse_cookie_blob, parse_jsonl_file, parse_xml_file, parse_xml_text
from danmaku_rs.service.preview import PreviewServer
from danmaku_rs.service.search import search_restore_targets
from danmaku_rs.service.sender import SendJob, build_multi_job, estimate_parallel_seconds, estimate_seconds
from danmaku_rs.service.splitter import split_by_count, split_by_duration, split_by_names
from danmaku_rs.service.validator import autofix, clip_length, scan, strip_newlines
from danmaku_rs.types import Account, AlertLevel, Danmaku, MODE_LABELS, SenderOptions
from danmaku_rs.ui.state import AppState
from danmaku_rs.ui.workers import MonitorWorker, MultiSendWorker, QrLoginWorker, SendWorker, Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.worker = None
        self.bg_worker = None
        self.monitor = None
        self.qr_worker = None
        self.preview = PreviewServer()
        self._lane_stats = {}
        self._last_failed = []
        self._search_hits = []
        self.setWindowTitle(f"{APP_TITLE} v{__version__}")
        self.resize(1280, 820)
        self._build()
        self._bind_shortcuts()
        self._apply_style()
        self._load_sender_settings()
        self.state.danmaku_changed.connect(self._refresh_tables)
        self.state.video_changed.connect(self._refresh_video_label)
        self.state.log_message.connect(self._log)
        self._reload_fleet()

    def _build(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_sender(), "发射补档")
        self.tabs.addTab(self._tab_archive(), "记忆馆")
        self.tabs.addTab(self._tab_editor(), "编辑器")
        self.tabs.addTab(self._tab_validator(), "校验器")
        self.tabs.addTab(self._tab_splitter(), "分割器")
        self.tabs.addTab(self._tab_inspect(), "监视巡检")
        self.tabs.addTab(self._tab_history(), "历史")
        self.tabs.addTab(self._tab_accounts(), "账号")
        self.tabs.addTab(self._tab_settings(), "设置")
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("就绪")

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._open_xml)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._start_send)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.tabs.setCurrentIndex(8))
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #1f1f1f; color: #f2f2f2; font-size: 13px; }
            QGroupBox { border: 1px solid #3a3a3a; margin-top: 10px; padding: 8px; }
            QGroupBox::title { color: #00a1d6; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QTableWidget {
                background: #2b2b2b; color: #f2f2f2; border: 1px solid #4a4a4a; padding: 3px;
            }
            QPushButton { background: #00a1d6; color: #fff; border: none; padding: 7px 10px; }
            QPushButton:hover { background: #008bb8; }
            QPushButton:disabled { background: #444; color: #aaa; }
            QHeaderView::section { background: #333; color: #fff; padding: 4px; border: none; }
            QProgressBar { border: 1px solid #444; text-align: center; background: #2b2b2b; }
            QProgressBar::chunk { background: #00a1d6; }
            QTabBar::tab { background: #2b2b2b; padding: 8px 12px; }
            QTabBar::tab:selected { background: #00a1d6; color: #fff; }
            """
        )

    def _log(self, message: str, error: bool = False) -> None:
        color = "#ff6b6b" if error else "#7dcea0"
        stamp = time.strftime("%H:%M:%S")
        self.log_area.append(f"<span style='color:{color}'>[{stamp}] {html.escape(message)}</span>")
        self.statusBar().showMessage(message, 8000)

    def _open_xml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开弹幕文件", "", "弹幕 (*.xml *.jsonl);;XML (*.xml);;JSONL (*.jsonl)")
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        try:
            if path.lower().endswith(".jsonl"):
                items = parse_jsonl_file(path)
            else:
                items = parse_xml_file(path)
        except Exception as exc:
            self._log(f"解析失败: {exc}", True)
            return
        self.state.push_undo()
        self.state.set_danmaku(items, Path(path).name)
        self._log(f"已加载 {len(items)} 条 · {Path(path).name}")

    def _refresh_tables(self) -> None:
        shown = self._filtered(self.state.danmaku)
        self._fill_table(self.sender_table, shown[:800])
        self._fill_table(self.editor_table, self.state.danmaku)
        picked = sum(1 for dm in self.state.danmaku if dm.selected)
        extra = f" · 筛选 {len(shown)}" if hasattr(self, "sender_filter") and self.sender_filter.text().strip() else ""
        self.lbl_count.setText(f"{len(self.state.danmaku)} 条 / 发送 {picked}  {self.state.xml_name}{extra}")

    def _refresh_video_label(self) -> None:
        video = self.state.video
        if not video:
            self.lbl_video.setText("未选择视频")
            return
        self.lbl_video.setText(f"{video.bvid}  {video.title}  cid={self.state.cid}")
        self.input_bvid.setText(video.bvid)
        self.combo_parts.clear()
        current = 0
        for idx, part in enumerate(video.parts):
            self.combo_parts.addItem(f"P{part.page}: {part.part}", part.cid)
            if part.cid == self.state.cid:
                current = idx
        self.combo_parts.setCurrentIndex(current)

    def _fill_table(self, table: QTableWidget, items) -> None:
        table.setRowCount(0)
        for dm in items:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(f"{dm.time:.2f}"))
            table.setItem(row, 1, QTableWidgetItem(dm.content))
            table.setItem(row, 2, QTableWidgetItem(MODE_LABELS.get(dm.mode, str(dm.mode))))
            table.setItem(row, 3, QTableWidgetItem(f"#{dm.color:06X}"))

    def _table(self) -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["时间", "内容", "类型", "颜色"])
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        return table

    def _tab_sender(self) -> QWidget:
        page = QWidget()
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        form = QVBoxLayout(left)
        box = QGroupBox("目标")
        grid = QFormLayout(box)
        self.input_bvid = QLineEdit()
        self.input_bvid.setPlaceholderText("BV 号或完整链接")
        self.combo_parts = QComboBox()
        btn_parts = QPushButton("获取分P")
        btn_parts.clicked.connect(self._fetch_parts)
        self.combo_parts.currentIndexChanged.connect(self._on_part_changed)
        grid.addRow("视频", self.input_bvid)
        grid.addRow(btn_parts)
        grid.addRow("分P", self.combo_parts)
        self.lbl_video = QLabel("未选择视频")
        self.lbl_video.setWordWrap(True)
        grid.addRow(self.lbl_video)
        form.addWidget(box)

        files = QGroupBox("弹幕")
        fl = QVBoxLayout(files)
        self.lbl_count = QLabel("未加载 XML")
        btn_xml = QPushButton("打开本地 XML / JSONL (Ctrl+O)")
        btn_xml.clicked.connect(self._open_xml)
        btn_live = QPushButton("抓取线上弹幕")
        btn_live.clicked.connect(self._fetch_live)
        btn_fix = QPushButton("一键批量修复（去换行 / 截断）")
        btn_fix.clicked.connect(self._validate)
        btn_preview = QPushButton("本地预览弹幕")
        btn_preview.clicked.connect(self._open_preview)
        self.sender_filter = QLineEdit()
        self.sender_filter.setPlaceholderText("预览筛选内容 / 时间")
        self.sender_filter.textChanged.connect(self._refresh_tables)
        fl.addWidget(self.lbl_count)
        fl.addWidget(btn_xml)
        fl.addWidget(btn_live)
        fl.addWidget(btn_fix)
        fl.addWidget(btn_preview)
        fl.addWidget(self.sender_filter)
        form.addWidget(files)

        opts = QGroupBox("策略")
        of = QFormLayout(opts)
        self.spin_dmin = QDoubleSpinBox()
        self.spin_dmax = QDoubleSpinBox()
        for spin, value in ((self.spin_dmin, 8.0), (self.spin_dmax, 11.0)):
            spin.setRange(3.0, 90.0)
            spin.setValue(value)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 8000)
        self.spin_max.setValue(200)
        self.spin_minutes = QSpinBox()
        self.spin_minutes.setRange(0, 1440)
        self.spin_minutes.setSpecialValueText("不限")
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-86400, 86400)
        self.check_burst = QCheckBox("爆发模式：每")
        self.spin_burst_n = QSpinBox()
        self.spin_burst_n.setRange(1, 50)
        self.spin_burst_n.setValue(5)
        self.spin_burst_rest = QDoubleSpinBox()
        self.spin_burst_rest.setRange(5, 180)
        self.spin_burst_rest.setValue(25)
        burst_row = QHBoxLayout()
        burst_row.addWidget(self.check_burst)
        burst_row.addWidget(self.spin_burst_n)
        burst_row.addWidget(QLabel("条休息"))
        burst_row.addWidget(self.spin_burst_rest)
        burst_row.addWidget(QLabel("秒"))
        self.check_sim = QCheckBox("模拟模式")
        self.check_sim.setChecked(True)
        self.check_resume = QCheckBox("断点续传")
        self.check_resume.setChecked(True)
        self.check_human = QCheckBox("拟人间隔（高斯抖动，偶发停顿）")
        self.check_human.setChecked(True)
        self.check_multi = QCheckBox("多账号同时发送（队列均分，互不重复）")
        of.addRow("间隔最短", self.spin_dmin)
        of.addRow("间隔最长", self.spin_dmax)
        of.addRow("最多发送", self.spin_max)
        of.addRow("最长分钟", self.spin_minutes)
        of.addRow("时间轴平移", self.spin_offset)
        of.addRow(burst_row)
        of.addRow(self.check_sim)
        of.addRow(self.check_resume)
        of.addRow(self.check_human)
        of.addRow(self.check_multi)
        self.fleet_table = QTableWidget(0, 3)
        self.fleet_table.setHorizontalHeaderLabels(["UID", "昵称", "参与"])
        self.fleet_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.fleet_table.setMaximumHeight(150)
        of.addRow(self.fleet_table)
        self.lane_table = QTableWidget(0, 5)
        self.lane_table.setHorizontalHeaderLabels(["账号", "成功", "失败", "跳过", "进度"])
        self.lane_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lane_table.setMaximumHeight(150)
        of.addRow(self.lane_table)
        form.addWidget(opts)

        self.progress = QProgressBar()
        self.lbl_eta = QLabel("ETA —")
        self.btn_start = QPushButton("开始补档 (Ctrl+Enter)")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self._start_send)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_send)
        row = QHBoxLayout()
        row.addWidget(self.btn_start, 2)
        row.addWidget(self.btn_stop, 1)
        form.addWidget(self.progress)
        form.addWidget(self.lbl_eta)
        form.addLayout(row)
        form.addStretch()

        right = QWidget()
        rl = QVBoxLayout(right)
        self.sender_table = self._table()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        rl.addWidget(self.sender_table, 3)
        rl.addWidget(QLabel("日志"))
        rl.addWidget(self.log_area, 2)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([380, 880])
        layout = QVBoxLayout(page)
        layout.addWidget(split)
        return page

    def _tab_archive(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.archive_q = QLineEdit()
        self.archive_q.setPlaceholderText("搜索标题 / UP / BV / 标签")
        self.archive_status = QComboBox()
        self.archive_status.addItem("全部状态", None)
        for code, label in ((0, "未检查"), (1, "自动·东方"), (2, "自动·其他"), (3, "人工·东方"), (4, "人工·其他")):
            self.archive_status.addItem(label, code)
        btn_load = QPushButton("同步记忆馆")
        btn_load.clicked.connect(lambda: self._load_archive(False))
        btn_force = QPushButton("强制刷新")
        btn_force.clicked.connect(lambda: self._load_archive(True))
        btn_use = QPushButton("导入到发射器")
        btn_use.clicked.connect(self._use_archive_video)
        btn_xml = QPushButton("拉取馆藏 XML")
        btn_xml.clicked.connect(self._fetch_archive_xml)
        btn_dead = QPushButton("失效稿跨站检索")
        btn_dead.clicked.connect(self._search_dead)
        btn_open = QPushButton("打开选中链接")
        btn_open.clicked.connect(self._open_search_url)
        self.archive_q.returnPressed.connect(lambda: self._load_archive(False))
        bar.addWidget(self.archive_q, 2)
        bar.addWidget(self.archive_status)
        bar.addWidget(btn_load)
        bar.addWidget(btn_force)
        bar.addWidget(btn_use)
        bar.addWidget(btn_xml)
        bar.addWidget(btn_dead)
        bar.addWidget(btn_open)
        self.archive_table = QTableWidget(0, 6)
        self.archive_table.setHorizontalHeaderLabels(["BV", "标题", "UP", "状态", "分P", "标签"])
        self.archive_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.archive_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.archive_table.cellDoubleClicked.connect(lambda *_: self._use_archive_video())
        self.search_table = QTableWidget(0, 4)
        self.search_table.setHorizontalHeaderLabels(["来源", "标题", "说明", "链接"])
        self.search_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.search_table.cellDoubleClicked.connect(lambda *_: self._use_search_hit())
        hint = QLabel(
            f"本工具只发布在 {PROJECT_HOME} ，不会发到 TouhouGleaners 组织。"
            "记忆馆 / 馆藏 XML 仅作只读数据源。失效稿会同时搜 B 站补档、Internet Archive、YouTube，并给出 AcFun / niconico 检索页。"
        )
        hint.setWordWrap(True)
        layout.addLayout(bar)
        layout.addWidget(hint)
        layout.addWidget(self.archive_table, 3)
        layout.addWidget(QLabel("跨站命中（针对原来失效的视频）"))
        layout.addWidget(self.search_table, 2)
        return page

    def _tab_editor(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.edit_offset = QDoubleSpinBox()
        self.edit_offset.setRange(-86400, 86400)
        btn_all = QPushButton("全体平移")
        btn_sel = QPushButton("选中平移")
        btn_del = QPushButton("删除选中")
        btn_xml = QPushButton("导出 XML")
        btn_jsonl = QPushButton("导出 JSONL")
        btn_dedup = QPushButton("去重")
        btn_sort = QPushButton("按时间排序")
        btn_pick = QPushButton("选中参与发送")
        btn_skip = QPushButton("选中不发送")
        btn_undo = QPushButton("撤销 (Ctrl+Z)")
        btn_all.clicked.connect(lambda: self._shift(False))
        btn_sel.clicked.connect(lambda: self._shift(True))
        btn_del.clicked.connect(self._delete_selected)
        btn_xml.clicked.connect(lambda: self._export("xml"))
        btn_jsonl.clicked.connect(lambda: self._export("jsonl"))
        btn_dedup.clicked.connect(self._dedup)
        btn_sort.clicked.connect(self._sort_time)
        btn_pick.clicked.connect(lambda: self._mark_selected(True))
        btn_skip.clicked.connect(lambda: self._mark_selected(False))
        btn_undo.clicked.connect(self._undo)
        bar.addWidget(QLabel("秒"))
        bar.addWidget(self.edit_offset)
        bar.addWidget(btn_all)
        bar.addWidget(btn_sel)
        bar.addWidget(btn_del)
        bar.addWidget(btn_dedup)
        bar.addWidget(btn_sort)
        bar.addWidget(btn_pick)
        bar.addWidget(btn_skip)
        bar.addWidget(btn_xml)
        bar.addWidget(btn_jsonl)
        bar.addWidget(btn_undo)
        bar.addStretch()
        self.editor_table = self._table()
        self.editor_table.itemDoubleClicked.connect(self._edit_cell)
        layout.addLayout(bar)
        layout.addWidget(self.editor_table)
        return page

    def _tab_validator(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        btn_scan = QPushButton("仅扫描")
        btn_nl = QPushButton("去换行")
        btn_clip = QPushButton("截断超长")
        btn_fix = QPushButton("一键全部修复")
        btn_undo = QPushButton("撤销修复")
        btn_scan.clicked.connect(self._scan_only)
        btn_nl.clicked.connect(self._strip_newlines)
        btn_clip.clicked.connect(self._clip_length)
        btn_fix.clicked.connect(self._validate)
        btn_undo.clicked.connect(self._undo)
        row.addWidget(btn_scan)
        row.addWidget(btn_nl)
        row.addWidget(btn_clip)
        row.addWidget(btn_fix)
        row.addWidget(btn_undo)
        self.valid_table = QTableWidget(0, 3)
        self.valid_table.setHorizontalHeaderLabels(["行", "类型", "说明"])
        self.valid_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addLayout(row)
        layout.addWidget(self.valid_table)
        return page

    def _tab_splitter(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        self.split_mode = QComboBox()
        self.split_mode.addItems(["按条数", "按时长秒", "按署名均分"])
        self.split_n = QSpinBox()
        self.split_n.setRange(1, 20000)
        self.split_n.setValue(3000)
        self.split_names = QLineEdit()
        self.split_names.setPlaceholderText("灵梦,魔理沙,咲夜")
        btn = QPushButton("分割并保存到目录")
        btn.clicked.connect(self._split)
        layout.addRow("方式", self.split_mode)
        layout.addRow("条数/秒数", self.split_n)
        layout.addRow("署名", self.split_names)
        layout.addRow(btn)
        return page

    def _tab_inspect(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        live = QGroupBox("实时监视")
        live_form = QFormLayout(live)
        self.spin_mon_interval = QSpinBox()
        self.spin_mon_interval.setRange(8, 180)
        self.spin_mon_interval.setValue(int(self.state.settings.get("monitor_interval", 20)))
        self.spin_mon_interval.setSuffix(" 秒")
        self.btn_live_start = QPushButton("开始实时监视")
        self.btn_live_stop = QPushButton("停止监视")
        self.btn_live_stop.setEnabled(False)
        self.btn_live_start.clicked.connect(self._start_live_monitor)
        self.btn_live_stop.clicked.connect(self._stop_live_monitor)
        live_btns = QHBoxLayout()
        live_btns.addWidget(self.btn_live_start)
        live_btns.addWidget(self.btn_live_stop)
        self.mon_status = QLabel("监视未启动")
        self.mon_login = QLabel("登录 —")
        self.mon_cover = QLabel("覆盖率 —")
        self.mon_send = QLabel("发送 —")
        self.mon_hist = QLabel("核销 —")
        live_form.addRow("轮询间隔", self.spin_mon_interval)
        live_form.addRow(live_btns)
        live_form.addRow(self.mon_status)
        live_form.addRow(self.mon_login)
        live_form.addRow(self.mon_cover)
        live_form.addRow(self.mon_send)
        live_form.addRow(self.mon_hist)
        layout.addWidget(live)

        bar = QHBoxLayout()
        btn_cmp = QPushButton("对比本地 XML 与线上弹幕")
        btn_mon = QPushButton("核销历史（待验证→存活/丢失）")
        btn_cmp.clicked.connect(self._inspect)
        btn_mon.clicked.connect(self._monitor)
        bar.addWidget(btn_cmp)
        bar.addWidget(btn_mon)
        layout.addLayout(bar)

        self.alert_table = QTableWidget(0, 4)
        self.alert_table.setHorizontalHeaderLabels(["级别", "代码", "分析", "建议"])
        self.alert_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.alert_table.setMaximumHeight(220)
        layout.addWidget(QLabel("态势告警"))
        layout.addWidget(self.alert_table)

        self.inspect_out = QTextEdit()
        self.inspect_out.setReadOnly(True)
        layout.addWidget(self.inspect_out)
        return page

    def _tab_history(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.hist_q = QLineEdit()
        self.hist_bvid = QLineEdit()
        self.hist_status = QComboBox()
        self.hist_status.addItems(["", "pending", "verified", "lost", "failed"])
        btn = QPushButton("查询")
        btn.clicked.connect(self._query_history)
        btn_fail = QPushButton("载入失败到发射器")
        btn_lost = QPushButton("载入丢失到发射器")
        btn_exp = QPushButton("导出查询 XML")
        btn_fail.clicked.connect(lambda: self._reload_history_status("failed"))
        btn_lost.clicked.connect(lambda: self._reload_history_status("lost"))
        btn_exp.clicked.connect(self._export_history_query)
        self.hist_q.returnPressed.connect(self._query_history)
        bar.addWidget(QLabel("内容"))
        bar.addWidget(self.hist_q)
        bar.addWidget(QLabel("BV"))
        bar.addWidget(self.hist_bvid)
        bar.addWidget(self.hist_status)
        bar.addWidget(btn)
        bar.addWidget(btn_fail)
        bar.addWidget(btn_lost)
        bar.addWidget(btn_exp)
        self.hist_table = QTableWidget(0, 7)
        self.hist_table.setHorizontalHeaderLabels(["时间", "BV", "内容", "状态", "cid", "账号", "指纹"])
        self.hist_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.hist_table.cellDoubleClicked.connect(self._history_detail)
        layout.addLayout(bar)
        layout.addWidget(self.hist_table)
        return page

    def _tab_accounts(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.acc_cookie = QLineEdit()
        self.acc_cookie.setPlaceholderText("整段 Cookie 或只填 SESSDATA")
        self.acc_jct = QLineEdit()
        self.acc_jct.setEchoMode(QLineEdit.Password)
        self.acc_sess = QLineEdit()
        self.acc_sess.setEchoMode(QLineEdit.Password)
        form.addRow("Cookie 串", self.acc_cookie)
        form.addRow("SESSDATA", self.acc_sess)
        form.addRow("bili_jct", self.acc_jct)
        btns = QHBoxLayout()
        add = QPushButton("检测并保存")
        add.clicked.connect(self._save_account)
        chk = QPushButton("批量检测")
        chk.clicked.connect(self._check_accounts)
        use = QPushButton("设为当前")
        use.clicked.connect(self._use_account)
        rm = QPushButton("删除")
        rm.clicked.connect(self._del_account)
        qr = QPushButton("扫码登录")
        qr.clicked.connect(self._start_qr_login)
        stop_qr = QPushButton("取消扫码")
        stop_qr.clicked.connect(self._stop_qr_login)
        for b in (add, chk, use, rm, qr, stop_qr):
            btns.addWidget(b)
        qr_row = QHBoxLayout()
        self.qr_label = QLabel("点「扫码登录」后在此显示官方二维码，不经过第三方短链。")
        self.qr_label.setMinimumHeight(180)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_status = QLabel("未开始扫码")
        qr_row.addWidget(self.qr_label)
        qr_row.addWidget(self.qr_status, 1)
        self.acc_table = QTableWidget(0, 5)
        self.acc_table.setHorizontalHeaderLabels(["UID", "昵称", "等级", "当前", "群发"])
        self.acc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addLayout(form)
        layout.addLayout(btns)
        layout.addLayout(qr_row)
        layout.addWidget(self.acc_table)
        self._reload_accounts()
        return page

    def _tab_settings(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.set_archive = QLineEdit(self.state.settings["archive_json_url"])
        self.set_xml = QLineEdit(self.state.settings["xml_base_url"])
        self.set_proxy_mode = QComboBox()
        for key, label in (("auto", "自动探测"), ("direct", "直连"), ("system", "系统代理"), ("custom", "自定义")):
            self.set_proxy_mode.addItem(label, key)
        mode = str(self.state.settings.get("proxy_mode") or "auto")
        idx = max(0, self.set_proxy_mode.findData(mode))
        self.set_proxy_mode.setCurrentIndex(idx)
        self.set_proxy = QLineEdit(self.state.settings.get("proxy") or "")
        self.set_proxy.setPlaceholderText("仅自定义时填写，例如 http://127.0.0.1:7890")
        btn_probe = QPushButton("探测当前代理")
        btn_probe.clicked.connect(self._probe_proxy)
        self.set_sleep = QCheckBox("发送时阻止休眠")
        self.set_sleep.setChecked(bool(self.state.settings.get("prevent_sleep", True)))
        self.set_mon_interval = QSpinBox()
        self.set_mon_interval.setRange(8, 180)
        self.set_mon_interval.setValue(int(self.state.settings.get("monitor_interval", 20)))
        self.set_autostop = QCheckBox("致命告警时停止发送")
        self.set_autostop.setChecked(bool(self.state.settings.get("auto_stop_on_critical", False)))
        self.set_audit = QCheckBox("实时监视时自动核销待验证弹幕")
        self.set_audit.setChecked(bool(self.state.settings.get("auto_audit", True)))
        save = QPushButton("保存设置")
        save.clicked.connect(self._save_settings)
        form.addRow("记忆馆 videos.json", self.set_archive)
        form.addRow("馆藏 XML 根路径", self.set_xml)
        form.addRow("代理策略", self.set_proxy_mode)
        form.addRow("自定义代理", self.set_proxy)
        form.addRow(btn_probe)
        form.addRow(self.set_sleep)
        form.addRow("监视间隔（秒）", self.set_mon_interval)
        form.addRow(self.set_autostop)
        form.addRow(self.set_audit)
        form.addRow(save)
        hint = QLabel(
            f"主页：{PROJECT_HOME}。TouhouGleaners 只作为可选只读数据源，本工具不会发布到该组织。"
            "能力：官方扫码登录、代理自动探测、失效稿跨站检索、本地弹幕预览、拟人间隔。"
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        return page

    def _fetch_parts(self) -> None:
        bvid, page = extract_bvid(self.input_bvid.text())
        if not bvid.startswith("BV"):
            self._log("BV 号无效", True)
            return

        def job():
            return self.state.browse_client().fetch_video(bvid)

        self._run(job, lambda video: self._on_video(video, page))

    def _on_video(self, video, page: int) -> None:
        cid = None
        for part in video.parts:
            if part.page == page:
                cid = part.cid
        self.state.set_video(video, cid)
        self._log(f"已加载《{video.title}》 {len(video.parts)}P")

    def _on_part_changed(self, _idx: int = 0) -> None:
        cid = self.combo_parts.currentData()
        if cid and self.state.video:
            self.state.cid = int(cid)
            self.lbl_video.setText(f"{self.state.video.bvid}  {self.state.video.title}  cid={self.state.cid}")

    def _fetch_live(self) -> None:
        if not self.state.cid:
            self._log("请先获取分P", True)
            return

        def job():
            return self.state.browse_client().fetch_online_danmaku(int(self.state.cid))

        def ok(items):
            self.state.push_undo()
            self.state.set_danmaku(items, f"live-{self.state.cid}.xml")
            self._log(f"线上抓取 {len(items)} 条")

        self._run(job, ok)

    def _start_send(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not self.state.video or not self.state.cid:
            self._log("请先选择视频分P", True)
            return
        if not self.state.danmaku:
            self._log("请先加载弹幕", True)
            return
        fleet = self._selected_fleet()
        if not fleet:
            self._log("请先添加账号，并在发射页勾选要参与的账号", True)
            return
        names = [f"{acc.uname or '未命名'} ({acc.uid})" for acc in fleet]
        if not self.check_sim.isChecked():
            detail = "即将向 B 站真实发送弹幕。\n账号：\n- " + "\n- ".join(names)
            if QMessageBox.question(self, "确认", detail) != QMessageBox.Yes:
                return
        cid = int(self.combo_parts.currentData() or self.state.cid)
        options = SenderOptions(
            delay_min=self.spin_dmin.value(),
            delay_max=self.spin_dmax.value(),
            burst_enabled=self.check_burst.isChecked(),
            burst_every=self.spin_burst_n.value(),
            burst_rest=self.spin_burst_rest.value(),
            max_count=self.spin_max.value(),
            simulate=self.check_sim.isChecked(),
            resume=self.check_resume.isChecked(),
            prevent_sleep=bool(self.state.settings.get("prevent_sleep", True)),
            time_offset=self.spin_offset.value(),
            max_minutes=self.spin_minutes.value(),
            humanize=self.check_human.isChecked(),
        )
        self._persist_sender_settings()
        self._sync_participate()
        self._lane_stats = {}
        self._reset_lane_table(fleet)
        count = min(len([dm for dm in self.state.danmaku if dm.selected]), options.max_count)
        eta = estimate_parallel_seconds(count, len(fleet), options) if self.check_multi.isChecked() else estimate_seconds(count, options)
        self.lbl_eta.setText(f"{len(fleet)} 账号 · 预计约 {eta / 60:.1f} 分钟")
        self.progress.setValue(0)
        self.state.live.reset_run(options.simulate, len(fleet))

        if self.check_multi.isChecked() and len(fleet) > 1:
            job = build_multi_job(
                fleet,
                self.state.client_for,
                self.state.history,
                self.state.danmaku,
                self.state.video.bvid,
                cid,
                self.state.video.aid,
                options,
            )
            if not job.jobs:
                self._log("没有可分配给各账号的弹幕", True)
                self.state.live.finish()
                return
            self.worker = MultiSendWorker(job)
            self._log(f"多账号并行：{len(job.jobs)} 个账号均分 {count} 条")
        else:
            acc = fleet[0]
            job = SendJob(
                self.state.client_for(acc),
                self.state.history,
                self.state.danmaku,
                self.state.video.bvid,
                cid,
                self.state.video.aid,
                options,
                acc.uid,
                acc.uname,
            )
            self.worker = SendWorker(job)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(lambda c, t, _k: (self.progress.setMaximum(t), self.progress.setValue(c)))
        self.worker.event.connect(self._on_send_event)
        self.worker.lane.connect(self._on_lane)
        self.worker.done.connect(self._send_done)
        self.worker.failed.connect(lambda e: self._log(e, True))
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.worker.start()

    def _stop_send(self) -> None:
        if isinstance(self.worker, (SendWorker, MultiSendWorker)):
            self.worker.stop()
            self._log("正在停止…")

    def _send_done(self, result: dict) -> None:
        self.state.live.finish()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        lanes = result.get("lanes") or []
        extra = ""
        if lanes:
            extra = "；".join(
                f"{item.get('uname') or item.get('uid')} +{item.get('success', 0)}/-{item.get('failed', 0)}"
                for item in lanes
            )
            extra = f" · {extra}"
        self._log(f"结束：成功 {result['success']} 失败 {result['failed']} 跳过 {result['skipped']}{extra}")
        self._last_failed = list(result.get("failed_items") or [])
        if self._last_failed:
            if QMessageBox.question(self, "失败弹幕", f"是否导出 {len(self._last_failed)} 条失败弹幕为 XML？") == QMessageBox.Yes:
                self._export("xml", self._last_failed)

    def _load_archive(self, force: bool = False) -> None:
        keyword = self.archive_q.text()
        status = self.archive_status.currentData()

        def job():
            self.state.archive.load_videos(force=force)
            return self.state.archive.search(keyword, status, 400)

        self._run(job, self._fill_archive)

    def _fill_archive(self, videos) -> None:
        self.archive_table.setRowCount(0)
        for video in videos:
            row = self.archive_table.rowCount()
            self.archive_table.insertRow(row)
            values = [
                video.bvid,
                video.title,
                video.uploader,
                status_label(video.touhou_status),
                str(len(video.parts)),
                ",".join(video.tags[:6]),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, video if col == 0 else None)
                self.archive_table.setItem(row, col, item)
        self._log(f"记忆馆命中 {len(videos)} 条")

    def _search_dead(self) -> None:
        query = self.archive_q.text().strip() or (self.input_bvid.text().strip() if hasattr(self, "input_bvid") else "")
        if not query:
            self._log("请输入失效稿 BV 或原标题", True)
            return
        status = self.archive_status.currentData()

        def job():
            if not self.state.archive._videos:
                self.state.archive.load_videos(False)
            result = search_restore_targets(
                query,
                self.state.archive,
                self.state.browse_client(),
                True,
                self.state.resolved_proxy(),
            )
            videos = result.get("archive_hits") or []
            if status is not None:
                videos = [video for video in videos if video.touhou_status == status]
            result["archive_hits"] = videos
            return result

        def ok(result):
            self._fill_archive(result.get("archive_hits") or [])
            self._fill_search(result.get("hits") or [])
            status_info = result.get("status") or {}
            if result.get("dead"):
                self._log(
                    f"稿件已失效 [{status_info.get('code')}] {status_info.get('message') or ''} · 跨站 {len(result.get('hits') or [])} 条"
                )
            else:
                self._log(f"跨站检索完成 · {len(result.get('hits') or [])} 条")
            for warn in result.get("warnings") or []:
                self._log(warn, True)

        self._log("正在针对失效稿做跨站检索…")
        self._run(job, ok)

    def _fill_search(self, hits) -> None:
        self._search_hits = list(hits)
        self.search_table.setRowCount(0)
        for hit in hits:
            row = self.search_table.rowCount()
            self.search_table.insertRow(row)
            values = [hit.source, hit.title, hit.extra, hit.url]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, hit)
                self.search_table.setItem(row, col, item)

    def _selected_search_hit(self):
        row = self.search_table.currentRow()
        if row < 0:
            return None
        item = self.search_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _use_search_hit(self) -> None:
        hit = self._selected_search_hit()
        if not hit:
            self._log("请先选中跨站命中", True)
            return
        if hit.video:
            self.state.set_video(hit.video)
            self.tabs.setCurrentIndex(0)
            self._log(f"已导入记忆馆 {hit.video.bvid}")
            return
        if hit.bvid:
            self.input_bvid.setText(hit.bvid)
            self.tabs.setCurrentIndex(0)
            self._log(f"已填入 {hit.bvid}，可获取分P")
            return
        self._open_search_url()

    def _open_search_url(self) -> None:
        hit = self._selected_search_hit()
        if not hit or not hit.url:
            self._log("请先选中跨站命中", True)
            return
        webbrowser.open(hit.url)

    def _open_search_hit(self) -> None:
        self._use_search_hit()

    def _selected_archive_video(self):
        row = self.archive_table.currentRow()
        if row < 0:
            return None
        item = self.archive_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _use_archive_video(self) -> None:
        video = self._selected_archive_video()
        if not video:
            self._log("请先选中记忆馆条目", True)
            return
        self.state.set_video(video)
        self.tabs.setCurrentIndex(0)
        self._log(f"已导入 {video.bvid}")

    def _fetch_archive_xml(self) -> None:
        video = self._selected_archive_video()
        if not video or not video.parts:
            self._log("条目没有 cid", True)
            return
        cid = self._pick_archive_cid(video)
        if not cid:
            return

        def job():
            text = self.state.archive.fetch_xml(cid)
            return parse_xml_text(text), cid

        def ok(pair):
            self.state.push_undo()
            self.state.set_video(video, pair[1])
            self.state.set_danmaku(pair[0], f"{pair[1]}.xml")
            self._log(f"馆藏 XML {len(pair[0])} 条")

        self._run(job, ok)

    def _pick_archive_cid(self, video) -> int:
        if len(video.parts) == 1:
            return video.parts[0].cid
        labels = [f"P{part.page}: {part.part}  cid={part.cid}" for part in video.parts]
        item, ok = QInputDialog.getItem(self, "选择分P", "馆藏 XML 对应分P", labels, 0, False)
        if not ok:
            return 0
        return video.parts[labels.index(item)].cid

    def _shift(self, selected_only: bool) -> None:
        self.state.push_undo()
        delta = self.edit_offset.value()
        rows = {i.row() for i in self.editor_table.selectedIndexes()} if selected_only else None
        for idx, dm in enumerate(self.state.danmaku):
            if rows is None or idx in rows:
                dm.time = max(0.0, dm.time + delta)
        self.state.danmaku_changed.emit()
        self._log(f"已平移 {delta}s")

    def _delete_selected(self) -> None:
        self.state.push_undo()
        rows = sorted({i.row() for i in self.editor_table.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.state.danmaku):
                del self.state.danmaku[row]
        self.state.danmaku_changed.emit()

    def _edit_cell(self, item: QTableWidgetItem) -> None:
        row, col = item.row(), item.column()
        if col != 1 or not (0 <= row < len(self.state.danmaku)):
            return
        self.state.push_undo()
        self.state.danmaku[row].content = item.text()[:100]

    def _export(self, kind: str, items=None) -> None:
        payload = list(items if items is not None else self.state.danmaku)
        if not payload:
            return
        filt = "XML (*.xml)" if kind == "xml" else "JSONL (*.jsonl)"
        path, _ = QFileDialog.getSaveFileName(self, "导出", f"export.{kind}", filt)
        if not path:
            return
        (write_xml if kind == "xml" else write_jsonl)(path, payload)
        self._log(f"已导出 {len(payload)} 条 → {path}")

    def _fill_issues(self, issues) -> None:
        self.valid_table.setRowCount(0)
        for issue in issues:
            row = self.valid_table.rowCount()
            self.valid_table.insertRow(row)
            self.valid_table.setItem(row, 0, QTableWidgetItem(str(issue.index + 1)))
            self.valid_table.setItem(row, 1, QTableWidgetItem(issue.kind))
            self.valid_table.setItem(row, 2, QTableWidgetItem(issue.message))

    def _scan_only(self) -> None:
        issues = scan(self.state.danmaku)
        self._fill_issues(issues)
        self._log(f"扫描到 {len(issues)} 个问题")

    def _validate(self) -> None:
        issues = scan(self.state.danmaku)
        self._fill_issues(issues)
        self.state.push_undo()
        fixed, n = autofix(self.state.danmaku)
        self.state.set_danmaku(fixed, self.state.xml_name)
        self._log(f"校验 {len(issues)} 个问题，已修复 {n} 条（Ctrl+Z 可撤销）")

    def _strip_newlines(self) -> None:
        self.state.push_undo()
        items, n = strip_newlines(self.state.danmaku)
        self.state.set_danmaku(items, self.state.xml_name)
        self._fill_issues(scan(self.state.danmaku))
        self._log(f"已去除 {n} 条换行")

    def _clip_length(self) -> None:
        self.state.push_undo()
        items, n = clip_length(self.state.danmaku)
        self.state.set_danmaku(items, self.state.xml_name)
        self._fill_issues(scan(self.state.danmaku))
        self._log(f"已截断 {n} 条超长弹幕")

    def _open_preview(self) -> None:
        if not self.state.danmaku:
            self._log("请先加载弹幕", True)
            return
        try:
            url = self.preview.start(self.state.danmaku, int(self.state.settings.get("preview_port") or 8765))
        except Exception as exc:
            self._log(str(exc), True)
            return
        webbrowser.open(url)
        self._log(f"本地预览 {url}")

    def _split(self) -> None:
        if not self.state.danmaku:
            self._log("没有可分割弹幕", True)
            return
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not folder:
            return
        mode = self.split_mode.currentText()
        chunks = []
        if mode == "按条数":
            chunks = [(f"part{i+1}", part) for i, part in enumerate(split_by_count(self.state.danmaku, self.split_n.value()))]
        elif mode == "按时长秒":
            chunks = [(f"t{i+1}", part) for i, part in enumerate(split_by_duration(self.state.danmaku, self.split_n.value()))]
        else:
            names = [n.strip() for n in self.split_names.text().replace("，", ",").split(",") if n.strip()]
            chunks = split_by_names(self.state.danmaku, names)
        for name, part in chunks:
            write_xml(str(Path(folder) / f"{name}_{len(part)}.xml"), part)
        self._log(f"已写出 {len(chunks)} 个分片")

    def _inspect(self) -> None:
        if not self.state.cid:
            self._log("请先选择分P", True)
            return

        def job():
            online = self.state.browse_client().fetch_online_danmaku(int(self.state.cid))
            return compare(self.state.danmaku, online), type_stats(self.state.danmaku), density(self.state.danmaku), len(online)

        def show(result):
            cmp, stats, dens, online_n = result
            lines = [f"线上 {online_n} 条", str(cmp), "类型统计:"]
            lines.extend(f"  {name}: {count} ({ratio:.1%})" for name, count, ratio in stats)
            lines.append("密度（每 30 秒）:")
            lines.extend(f"  {start:.0f}s: {count}" for start, count in dens[:24])
            self.inspect_out.setPlainText("\n".join(lines))

        self._run(job, show)

    def _monitor(self) -> None:
        if not self.state.video or not self.state.cid:
            self._log("请先选择视频", True)
            return

        def job():
            return audit(self.state.browse_client(), self.state.history, self.state.video.bvid, int(self.state.cid))

        self._run(job, lambda r: self.inspect_out.setPlainText(f"监视结果: {r}"))

    def _query_history(self) -> None:
        rows = self.state.history.query(self.hist_q.text(), self.hist_bvid.text().strip(), self.hist_status.currentText())
        self.hist_table.setRowCount(0)
        for row in rows:
            i = self.hist_table.rowCount()
            self.hist_table.insertRow(i)
            values = [
                time.strftime("%m-%d %H:%M", time.localtime(row["created_at"] or 0)),
                row["bvid"],
                row["content"],
                row["status"],
                str(row["cid"]),
                str(row.get("account_uid") or ""),
                row["fingerprint"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, row)
                self.hist_table.setItem(i, col, item)

    def _save_account(self) -> None:
        blob = parse_cookie_blob(self.acc_cookie.text())
        sess = blob.get("SESSDATA") or self.acc_sess.text().strip()
        jct = blob.get("bili_jct") or self.acc_jct.text().strip()
        buvid = blob.get("buvid3") or ""
        if not sess or not jct:
            self._log("SESSDATA / bili_jct 不能为空", True)
            return
        from danmaku_rs.repo.bili import BiliClient

        client = BiliClient(sess, jct, buvid, self.state.resolved_proxy())
        try:
            ok, msg = client.check_login()
        except Exception as exc:
            self._log(str(exc), True)
            return
        if not ok:
            self._log(msg, True)
            return
        self.state.accounts.upsert(Account(client.uid, client.uname, sess, jct, client.buvid3, client.level, True))
        self._reload_accounts()
        self._log(msg)

    def _reload_accounts(self) -> None:
        self.acc_table.blockSignals(True)
        self.acc_table.setRowCount(0)
        for acc in self.state.accounts.accounts:
            row = self.acc_table.rowCount()
            self.acc_table.insertRow(row)
            self.acc_table.setItem(row, 0, QTableWidgetItem(acc.uid))
            self.acc_table.setItem(row, 1, QTableWidgetItem(acc.uname))
            self.acc_table.setItem(row, 2, QTableWidgetItem(str(acc.level)))
            self.acc_table.setItem(row, 3, QTableWidgetItem("是" if acc.uid == self.state.accounts.active_uid else ""))
            flag = QTableWidgetItem()
            flag.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            flag.setCheckState(Qt.Checked if acc.participate else Qt.Unchecked)
            self.acc_table.setItem(row, 4, flag)
        self.acc_table.blockSignals(False)
        try:
            self.acc_table.itemChanged.disconnect(self._acc_item_changed)
        except TypeError:
            pass
        self.acc_table.itemChanged.connect(self._acc_item_changed)
        self._reload_fleet()

    def _acc_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 4:
            return
        uid_item = self.acc_table.item(item.row(), 0)
        if not uid_item:
            return
        self.state.accounts.set_participate(uid_item.text(), item.checkState() == Qt.Checked)
        self._reload_fleet()

    def _use_account(self) -> None:
        row = self.acc_table.currentRow()
        if row < 0:
            return
        uid = self.acc_table.item(row, 0).text()
        self.state.accounts.active_uid = uid
        self.state.accounts.save()
        self._reload_accounts()
        self._log(f"当前账号 {uid}")

    def _del_account(self) -> None:
        row = self.acc_table.currentRow()
        if row < 0:
            return
        self.state.accounts.remove(self.acc_table.item(row, 0).text())
        self._reload_accounts()

    def _check_accounts(self) -> None:
        from danmaku_rs.repo.bili import BiliClient

        def job():
            result = []
            for acc in self.state.accounts.accounts:
                client = BiliClient(acc.sessdata, acc.bili_jct, acc.buvid3, self.state.resolved_proxy())
                try:
                    ok, msg = client.check_login()
                    acc.valid = ok
                    acc.uname = client.uname or acc.uname
                    acc.level = client.level or acc.level
                except Exception as exc:
                    acc.valid = False
                    msg = str(exc)
                result.append(f"{acc.uid} {acc.uname}: {msg}")
            self.state.accounts.save()
            return result

        self._run(job, lambda lines: (self._reload_accounts(), self._log("；".join(lines))))

    def _qr_pixmap(self, url: str) -> QPixmap:
        matrix = qr_matrix(url)
        height = len(matrix)
        width = len(matrix[0]) if matrix else 0
        image = QImage(width, height, QImage.Format_RGB32)
        for y, row in enumerate(matrix):
            for x, cell in enumerate(row):
                image.setPixel(x, y, 0xFF000000 if cell else 0xFFFFFFFF)
        return QPixmap.fromImage(image.scaled(220, 220, Qt.KeepAspectRatio, Qt.FastTransformation))

    def _start_qr_login(self) -> None:
        if self.qr_worker and self.qr_worker.isRunning():
            self._log("已在扫码等待中")
            return
        self.qr_worker = QrLoginWorker(self.state.resolved_proxy())
        self.qr_worker.ready.connect(self._on_qr_ready)
        self.qr_worker.status.connect(self.qr_status.setText)
        self.qr_worker.logged_in.connect(self._on_qr_logged_in)
        self.qr_worker.failed.connect(lambda e: (self.qr_status.setText(e), self._log(e, True)))
        self.qr_status.setText("正在申请官方二维码…")
        self.qr_worker.start()

    def _stop_qr_login(self) -> None:
        if self.qr_worker and self.qr_worker.isRunning():
            self.qr_worker.stop()
            self.qr_worker.wait(1500)
        self.qr_status.setText("已取消扫码")

    def _on_qr_ready(self, url: str) -> None:
        try:
            self.qr_label.setPixmap(self._qr_pixmap(url))
        except Exception as exc:
            self._log(f"二维码绘制失败: {exc}", True)
            return
        self.qr_status.setText("请用哔哩哔哩 App 扫码")

    def _on_qr_logged_in(self, payload: dict) -> None:
        account = payload.get("account")
        message = str(payload.get("message") or "登录成功")
        if not account:
            self._log("扫码成功但账号数据不完整", True)
            return
        self.state.accounts.upsert(account)
        self._reload_accounts()
        self.qr_status.setText(message)
        self._log(f"扫码登录成功 · {message}")

    def _probe_proxy(self) -> None:
        self._apply_proxy_fields()
        proxy = self.state.resolved_proxy()

        def job():
            return probe_proxy(proxy)

        def ok(pair):
            good, text = pair
            self._log(text, not good)

        self._run(job, ok)

    def _apply_proxy_fields(self) -> None:
        self.state.settings["proxy_mode"] = self.set_proxy_mode.currentData() or "auto"
        self.state.settings["proxy"] = self.set_proxy.text().strip()

    def _save_settings(self) -> None:
        self.state.settings["archive_json_url"] = self.set_archive.text().strip()
        self.state.settings["xml_base_url"] = self.set_xml.text().strip()
        self._apply_proxy_fields()
        self.state.settings["prevent_sleep"] = self.set_sleep.isChecked()
        self.state.settings["monitor_interval"] = self.set_mon_interval.value()
        self.state.settings["auto_stop_on_critical"] = self.set_autostop.isChecked()
        self.state.settings["auto_audit"] = self.set_audit.isChecked()
        self.spin_mon_interval.setValue(self.set_mon_interval.value())
        self._persist_sender_settings()
        self.state.persist_settings()
        self._log("设置已保存")

    def _run(self, fn, on_ok) -> None:
        if self.bg_worker and self.bg_worker.isRunning():
            self._log("已有后台任务在运行", True)
            return
        self.bg_worker = Worker(fn)
        self.bg_worker.done.connect(on_ok)
        self.bg_worker.failed.connect(lambda e: self._log(e, True))
        self.bg_worker.start()

    def _selected_fleet(self) -> list:
        if not self.check_multi.isChecked():
            acc = self.state.active_account()
            return [acc] if acc else []
        picked = []
        for row in range(self.fleet_table.rowCount()):
            flag = self.fleet_table.item(row, 2)
            uid_item = self.fleet_table.item(row, 0)
            if not uid_item or not flag or flag.checkState() != Qt.Checked:
                continue
            for acc in self.state.accounts.accounts:
                if acc.uid == uid_item.text():
                    picked.append(acc)
                    break
        return picked

    def _sync_participate(self) -> None:
        if not hasattr(self, "fleet_table"):
            return
        for row in range(self.fleet_table.rowCount()):
            uid_item = self.fleet_table.item(row, 0)
            flag = self.fleet_table.item(row, 2)
            if uid_item and flag:
                for acc in self.state.accounts.accounts:
                    if acc.uid == uid_item.text():
                        acc.participate = flag.checkState() == Qt.Checked
        self.state.accounts.save()

    def _reload_fleet(self) -> None:
        if not hasattr(self, "fleet_table"):
            return
        self.fleet_table.blockSignals(True)
        self.fleet_table.setRowCount(0)
        for acc in self.state.accounts.accounts:
            row = self.fleet_table.rowCount()
            self.fleet_table.insertRow(row)
            self.fleet_table.setItem(row, 0, QTableWidgetItem(acc.uid))
            self.fleet_table.setItem(row, 1, QTableWidgetItem(acc.uname))
            flag = QTableWidgetItem()
            flag.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            flag.setCheckState(Qt.Checked if acc.participate else Qt.Unchecked)
            self.fleet_table.setItem(row, 2, flag)
        self.fleet_table.blockSignals(False)

    def _reset_lane_table(self, fleet) -> None:
        self.lane_table.setRowCount(0)
        for acc in fleet:
            row = self.lane_table.rowCount()
            self.lane_table.insertRow(row)
            self.lane_table.setItem(row, 0, QTableWidgetItem(f"{acc.uname} ({acc.uid})"))
            self.lane_table.item(row, 0).setData(Qt.UserRole, acc.uid)
            for col, value in enumerate(("0", "0", "0", "0/0"), start=1):
                self.lane_table.setItem(row, col, QTableWidgetItem(value))

    def _on_send_event(self, event: dict) -> None:
        self.state.live.note(event)

    def _on_lane(self, stats: dict) -> None:
        uid = str(stats.get("uid") or "")
        self._lane_stats[uid] = stats
        for row in range(self.lane_table.rowCount()):
            item = self.lane_table.item(row, 0)
            if not item or item.data(Qt.UserRole) != uid:
                continue
            self.lane_table.setItem(row, 1, QTableWidgetItem(str(stats.get("success", 0))))
            self.lane_table.setItem(row, 2, QTableWidgetItem(str(stats.get("failed", 0))))
            self.lane_table.setItem(row, 3, QTableWidgetItem(str(stats.get("skipped", 0))))
            self.lane_table.setItem(row, 4, QTableWidgetItem(f"{stats.get('done', 0)}/{stats.get('total', 0)}"))
            break

    def _start_live_monitor(self) -> None:
        if self.monitor and self.monitor.isRunning():
            return
        interval = self.spin_mon_interval.value()
        self.state.settings["monitor_interval"] = interval
        self.state.persist_settings()

        def collect(previous):
            acc = self.state.active_account()
            client = self.state.client_for(acc) if acc else None
            options = SenderOptions(
                delay_min=self.spin_dmin.value(),
                delay_max=self.spin_dmax.value(),
                burst_enabled=self.check_burst.isChecked(),
            )
            return collect_snapshot(
                client or self.state.browse_client(),
                self.state.history,
                self.state.live,
                list(self.state.danmaku),
                self.state.video.bvid if self.state.video else "",
                self.state.cid,
                options,
                previous,
                auto_audit=bool(self.state.settings.get("auto_audit", True)),
            )

        self.monitor = MonitorWorker(collect, analyze, interval)
        self.monitor.snapshot.connect(self._on_snapshot)
        self.monitor.alerts.connect(self._on_alerts)
        self.monitor.failed.connect(lambda e: self._log(f"监视失败: {e}", True))
        self.btn_live_start.setEnabled(False)
        self.btn_live_stop.setEnabled(True)
        self.mon_status.setText(f"监视运行中 · 每 {interval}s")
        self.monitor.start()
        self._log(f"实时监视已启动，间隔 {interval}s")

    def _stop_live_monitor(self) -> None:
        if self.monitor and self.monitor.isRunning():
            self.monitor.stop()
            self.monitor.wait(1500)
        self.btn_live_start.setEnabled(True)
        self.btn_live_stop.setEnabled(False)
        self.mon_status.setText("监视已停止")
        self._log("实时监视已停止")

    def _on_snapshot(self, snap) -> None:
        login = "未检测" if snap.login_ok is None else ("正常" if snap.login_ok else "失效")
        self.mon_login.setText(f"登录 {login}  {snap.login_msg}")
        self.mon_cover.setText(
            f"覆盖率 {snap.coverage:.1%}  本地 {snap.local_count}  线上 {snap.online_count}  Δ{snap.online_delta:+d}"
        )
        mode = "模拟" if snap.simulate else "实发"
        sending = "发送中" if snap.sending else "空闲"
        self.mon_send.setText(
            f"{sending} · {mode} · {snap.accounts_active} 账号  成功 {snap.send_success}  失败 {snap.send_failed}  跳过 {snap.send_skipped}"
        )
        self.mon_hist.setText(f"待核 {snap.pending}  存活 {snap.verified}  丢失 {snap.lost}")
        lines = [
            f"时间 {time.strftime('%H:%M:%S', time.localtime(snap.ts))}",
            f"登录 {login} / {snap.login_msg}",
            f"覆盖 {snap.coverage:.1%}  本地 {snap.local_count}  线上 {snap.online_count}  Δ{snap.online_delta:+d}",
            f"发送 {sending} {mode}  成功 {snap.send_success} 失败 {snap.send_failed} 跳过 {snap.send_skipped}  连败 {snap.consecutive_fail}",
            f"核销 待验证 {snap.pending} 存活 {snap.verified} 丢失 {snap.lost}",
            f"最近接口码 {snap.last_code}  36703×{snap.rate_limit_hits}  412×{snap.intercept_412}",
        ]
        if snap.poll_error:
            lines.append(f"拉取错误 {snap.poll_error}")
        self.inspect_out.setPlainText("\n".join(lines))

    def _on_alerts(self, incoming) -> None:
        self.state.alerts = merge_alerts(self.state.alerts, incoming)
        self._fill_alerts()
        worst = worst_level(incoming)
        top = next((alert for alert in incoming if alert.level == worst), incoming[0])
        if worst is AlertLevel.CRITICAL:
            self._log(top.message, True)
            serious = any(alert.code.startswith("fatal") or alert.code in {"login", "http412"} for alert in incoming)
            if serious and self.state.live.sending and self.state.settings.get("auto_stop_on_critical"):
                self._stop_send()
                self._log("已按设置在致命告警时停止发送", True)
        elif worst is AlertLevel.WARNING:
            self.statusBar().showMessage(top.message, 8000)

    def _fill_alerts(self) -> None:
        colors = {
            AlertLevel.CRITICAL: QColor("#ff6b6b"),
            AlertLevel.WARNING: QColor("#f4d03f"),
            AlertLevel.INFO: QColor("#7dcea0"),
        }
        labels = {AlertLevel.CRITICAL: "严重", AlertLevel.WARNING: "警告", AlertLevel.INFO: "提示"}
        self.alert_table.setRowCount(0)
        for alert in self.state.alerts:
            row = self.alert_table.rowCount()
            self.alert_table.insertRow(row)
            values = [labels.get(alert.level, alert.level.value), alert.code, alert.message, alert.action]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setForeground(colors.get(alert.level, QColor("#f2f2f2")))
                self.alert_table.setItem(row, col, item)

    def _filtered(self, items):
        query = self.sender_filter.text().strip().lower() if hasattr(self, "sender_filter") else ""
        if not query:
            return list(items)
        return [dm for dm in items if query in dm.content.lower() or query in f"{dm.time:.2f}"]

    def _undo(self) -> None:
        if self.state.pop_undo():
            self._log("已撤销上一步编辑")
        else:
            self._log("没有可撤销的编辑", True)

    def _dedup(self) -> None:
        self.state.push_undo()
        items, dropped = drop_duplicates(self.state.danmaku)
        self.state.set_danmaku(items, self.state.xml_name)
        self._log(f"去重删除 {dropped} 条")

    def _sort_time(self) -> None:
        self.state.push_undo()
        self.state.set_danmaku(sort_by_time(self.state.danmaku), self.state.xml_name)
        self._log("已按时间排序")

    def _mark_selected(self, flag: bool) -> None:
        rows = {i.row() for i in self.editor_table.selectedIndexes()}
        if not rows:
            for dm in self.state.danmaku:
                dm.selected = flag
        else:
            for idx, dm in enumerate(self.state.danmaku):
                if idx in rows:
                    dm.selected = flag
        self._refresh_tables()
        self._log("已标记参与发送" if flag else "已标记不发送")

    def _load_sender_settings(self) -> None:
        s = self.state.settings
        self.spin_dmin.setValue(float(s.get("delay_min", 8)))
        self.spin_dmax.setValue(float(s.get("delay_max", 11)))
        self.check_burst.setChecked(bool(s.get("burst_enabled", True)))
        self.spin_burst_n.setValue(int(s.get("burst_every", 5)))
        self.spin_burst_rest.setValue(float(s.get("burst_rest", 25)))
        self.spin_max.setValue(int(s.get("max_count", 200)))
        self.spin_minutes.setValue(int(s.get("max_minutes", 0)))
        self.check_sim.setChecked(bool(s.get("simulate_default", True)))
        self.check_human.setChecked(bool(s.get("humanize", True)))

    def _persist_sender_settings(self) -> None:
        self.state.settings.update(
            {
                "delay_min": self.spin_dmin.value(),
                "delay_max": self.spin_dmax.value(),
                "burst_enabled": self.check_burst.isChecked(),
                "burst_every": self.spin_burst_n.value(),
                "burst_rest": self.spin_burst_rest.value(),
                "max_count": self.spin_max.value(),
                "max_minutes": self.spin_minutes.value(),
                "simulate_default": self.check_sim.isChecked(),
                "humanize": self.check_human.isChecked(),
            }
        )
        self.state.persist_settings()

    def _reload_history_status(self, status: str) -> None:
        bvid = self.hist_bvid.text().strip() or (self.state.video.bvid if self.state.video else "")
        cid = self.state.cid
        items = self.state.history.danmaku_of(status, bvid, cid)
        if not items:
            self._log(f"没有可载入的 {status} 记录", True)
            return
        self.state.push_undo()
        self.state.set_danmaku(items, f"history-{status}.xml")
        self.tabs.setCurrentIndex(0)
        self._log(f"已载入 {len(items)} 条 {status} 弹幕，可直接重发")

    def _export_history_query(self) -> None:
        rows = self.state.history.query(self.hist_q.text(), self.hist_bvid.text().strip(), self.hist_status.currentText())
        from danmaku_rs.repo.history import row_to_danmaku

        items = [row_to_danmaku(row) for row in rows]
        self._export("xml", items)

    def _history_detail(self, row: int, _col: int) -> None:
        item = self.hist_table.item(row, 0)
        data = item.data(Qt.UserRole) if item else None
        if not data:
            return
        text = "\n".join(
            [
                f"BV: {data.get('bvid')}",
                f"cid: {data.get('cid')}",
                f"状态: {data.get('status')}",
                f"账号: {data.get('account_uid')}",
                f"内容: {data.get('content')}",
                f"时间: {(data.get('progress_ms') or 0) / 1000:.3f}s",
                f"模式: {data.get('mode')}  字号: {data.get('font_size')}  颜色: #{int(data.get('color') or 0):06X}",
                f"指纹: {data.get('fingerprint')}",
                f"记录时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data.get('created_at') or 0))}",
            ]
        )
        QMessageBox.information(self, "弹幕档案", text)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.preview.stop()
        if self.qr_worker and self.qr_worker.isRunning():
            self.qr_worker.stop()
            self.qr_worker.wait(1200)
        if self.monitor and self.monitor.isRunning():
            self.monitor.stop()
            self.monitor.wait(1200)
        if isinstance(self.worker, (SendWorker, MultiSendWorker)) and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
        if self.bg_worker and self.bg_worker.isRunning():
            self.bg_worker.wait(1200)
        event.accept()
