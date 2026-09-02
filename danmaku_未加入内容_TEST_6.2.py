import sys
import random
import time
import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from hashlib import md5
from urllib.parse import urlparse
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QTextEdit, QFileDialog, QProgressBar, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPainter, QFont

# ==================== 线程工作类 ====================
class RestoreThread(QThread):
    update_progress = pyqtSignal(int, int)  # (current, total)
    log_message = pyqtSignal(str, bool)     # (message, is_error)
    finished = pyqtSignal(bool)             # (success)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._is_running = True
        self.success_count = 0

    def run(self):
        success = False
        try:
            total = len(self.config['danmaku_list'])
            self.log_message.emit(f"开始处理 {total} 条弹幕", False)

            if not self.config.get('simulate', False):
                if not self._validate_url(self.config.get('api_url') or ""):
                    raise ValueError("无效的API地址")
            
            for idx, dm in enumerate(self.config['danmaku_list']):
                if not self._is_running:
                    break
                
                if self._send_danmaku_with_retry(dm):
                    self.success_count += 1
                
                self.update_progress.emit(idx + 1, total)
                time.sleep(self._calculate_delay(idx))
            
            success = self.success_count > 0
            self.log_message.emit(f"完成 {self.success_count}/{total} 条", not success)
        except Exception as e:
            self.log_message.emit(f"线程错误: {str(e)}", True)
        finally:
            self.finished.emit(success)

    def _send_danmaku_with_retry(self, dm):
        for attempt in range(self.config['retry_limit']):
            try:
                # 模拟模式处理
                if self.config.get('simulate', False):
                    return True

                response = requests.post(
                    self.config['api_url'],
                    headers=self.config['headers'],
                    data={
                        "oid": self.config['oid'],
                        "type": 1,
                        "mode": dm["mode"],
                        "fontsize": dm["font_size"],
                        "color": dm["color"],
                        "message": dm["content"],
                        "csrf": self.config['csrf'],
                        "timestamp": int(time.time()*1000)
                    },
                    timeout=15
                )
                
                if response.status_code == 412:
                    raise Exception("请求被拦截(412)")
                
                return response.json().get("code") == 0
            except Exception as e:
                delay = 2 ** attempt
                self.log_message.emit(f"尝试 {attempt+1}/{self.config['retry_limit']} 失败: {str(e)}，{delay}秒后重试", True)
                time.sleep(delay)
        return False

    def _calculate_delay(self, idx):
        base_delay = self.config['min_delay']
        return base_delay * (1 + (idx % 3)/2) + random.uniform(0, 0.3)

    def _validate_url(self, url):
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception as e:
            self.log_message.emit(f"URL验证异常: {str(e)}", True)
            return False

    def stop(self):
        self._is_running = False

# ==================== 主界面类 ====================
class BiliDanmakuRestorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("B站弹幕补档工具 v6.1")
        self.setGeometry(100, 100, 1280, 800)
        self._init_ui()
        self._apply_stylesheet()
        
        # 初始化状态
        self.xml_path = ""
        self.current_cid = ""
        self.worker_thread = None
        self.min_delay = 1.5
        self.retry_limit = 3
        self.log_area = None  # 显式声明日志区域

    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # 侧边栏初始化
        self._init_sidebar(main_layout)
        
        # 主界面
        self.tab_widget = QTabWidget()
        self._init_config_tab()
        self._init_preview_tab()
        
        # 日志区域
        self._init_log_area()
        main_layout.addWidget(self.tab_widget, 4)
        main_layout.addWidget(self.log_area)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def _init_sidebar(self, parent_layout):
        sidebar = QVBoxLayout()
        sidebar.setContentsMargins(5, 20, 5, 20)
        
        # 控制按钮
        self.btn_start = QPushButton("▶ 开始")
        self.btn_start.clicked.connect(self._toggle_restore)
        self.btn_test = QPushButton("📶 网络测试")
        self.btn_test.clicked.connect(self._network_check)
        self.btn_clean = QPushButton("🧹 清除缓存")
        self.btn_clean.clicked.connect(self._clean_cache)
        
        # 进度显示
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.lbl_progress = QLabel("就绪")
        
        sidebar.addWidget(self.btn_start)
        sidebar.addWidget(self.btn_test)
        sidebar.addWidget(self.btn_clean)
        sidebar.addWidget(self.progress_bar)
        sidebar.addWidget(self.lbl_progress)
        sidebar.addStretch()
        
        parent_layout.addLayout(sidebar, 1)

    def _init_config_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        
        # 凭证输入
        self._create_input_field("SESSDATA:", layout)
        self._create_input_field("bili_jct:", layout)
        self._create_input_field("buvid3:", layout)
        self._create_input_field("目标BV号:", layout)
        
        # 分P选择
        self.combo_parts = QComboBox()
        layout.addWidget(QLabel("视频分P:"))
        layout.addWidget(self.combo_parts)
        self.btn_fetch = QPushButton("获取分P")
        self.btn_fetch.clicked.connect(self._fetch_parts)
        
        # 文件选择
        self.btn_xml = QPushButton("📂 选择弹幕文件")
        self.btn_xml.clicked.connect(self._select_xml)
        
        # 选项
        self.check_simulate = QCheckBox("模拟模式（不实际发送）")
        
        layout.addWidget(self.btn_fetch)
        layout.addWidget(self.btn_xml)
        layout.addWidget(self.check_simulate)
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "⚙ 配置")

    def _init_preview_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        
        # 弹幕表格
        self.table_danmaku = QTableWidget()
        self.table_danmaku.setColumnCount(3)
        self.table_danmaku.setHorizontalHeaderLabels(["时间", "内容", "类型"])
        self.table_danmaku.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        
        # 统计面板
        self.table_stats = QTableWidget()
        self.table_stats.setColumnCount(3)
        self.table_stats.setHorizontalHeaderLabels(["类型", "数量", "占比"])
        self.table_stats.verticalHeader().setVisible(False)
        
        splitter = QHBoxLayout()
        splitter.addWidget(self.table_danmaku, 3)
        splitter.addWidget(self.table_stats, 1)
        
        layout.addLayout(splitter)
        tab.setLayout(layout)
        self.tab_widget.addTab(tab, "🔍 预览")

    def _init_log_area(self):
        """初始化日志区域"""
        self.log_area = QTextEdit()
        self.log_area.setObjectName("log_area")
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(120)
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #dcdcdc;
                border: 1px solid #444;
                padding: 5px;
            }
        """)

    def _create_input_field(self, label, layout):
        row = QHBoxLayout()
        lbl = QLabel(label)
        input_field = QLineEdit()
        field_name = label.strip(":")
        input_field.setProperty("fieldName", field_name)
        if field_name in {"SESSDATA", "bili_jct"}:
            input_field.setEchoMode(QLineEdit.Password)
        row.addWidget(lbl)
        row.addWidget(input_field)
        layout.addLayout(row)
        setattr(self, f"input_{label.strip(':').lower()}", input_field)

    def _validate_url(self, url):
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception as e:
            self._log(f"URL验证异常: {str(e)}", True)
            return False

    def _select_xml(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择弹幕文件", "", "XML文件 (*.xml)"
        )
        if path:
            self.xml_path = path
            self._load_preview()
            self._log(f"已加载弹幕文件: {Path(path).name}")

    def _fetch_parts(self):
        try:
            if not self._validate_inputs(True):
                return
            
            bvid = self.input_目标bv号.text().strip()
            api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            
            if not self._validate_url(api_url):
                return
                
            response = requests.get(
                api_url,
                headers=self._build_headers(),
                timeout=10
            )
            data = response.json()
            
            if data['code'] != 0:
                raise Exception(data['message'])
            
            self.combo_parts.clear()
            for p in data['data']['pages']:
                self.combo_parts.addItem(f"P{p['page']}: {p['part']}", p['cid'])
            
            self._log(f"成功获取 {len(data['data']['pages'])} 个分P")
        except Exception as e:
            self._log(f"获取分P失败: {str(e)}", True)

    def _toggle_restore(self):
        if self.worker_thread and self.worker_thread.isRunning():
            self._stop_restore()
        else:
            self._start_restore()

    def _start_restore(self):
        if not self._validate_inputs():
            return
        
        try:
            config = {
                'danmaku_list': self._parse_danmaku(),
                'headers': self._build_headers(),
                'oid': self.combo_parts.currentData(),
                'csrf': self.input_bili_jct.text(),
                'min_delay': self.min_delay,
                'retry_limit': self.retry_limit,
                'api_url': "https://api.bilibili.com/x/v2/dm/post",
                'simulate': self.check_simulate.isChecked()
            }
            
            if config['simulate']:
                self._log("进入模拟模式，不会实际发送弹幕", False)
                
            self.worker_thread = RestoreThread(config)
            self.worker_thread.update_progress.connect(self._update_progress)
            self.worker_thread.log_message.connect(self._log)
            self.worker_thread.finished.connect(self._on_restore_finished)
            
            self.btn_start.setText("⏹ 停止")
            self.btn_start.setStyleSheet("background-color: #ff4444;")
            self.worker_thread.start()
            
        except Exception as e:
            self._log(f"启动失败: {str(e)}", True)

    def _stop_restore(self):
        if self.worker_thread:
            self.worker_thread.stop()
            self.worker_thread.quit()
            self.btn_start.setText("▶ 开始")
            self.btn_start.setStyleSheet("")
            self._log("操作已中止")

    def _parse_danmaku(self):
        if not self.xml_path:
            raise Exception("未选择弹幕文件")
        
        danmaku_list = []
        type_counter = defaultdict(int)
        
        for event, elem in ET.iterparse(self.xml_path, events=('end',)):
            if elem.tag == 'd':
                    try:
                        params = elem.attrib.get('p', '').split(',')
                        if len(params) < 4:
                            continue
                        content = (elem.text or "").strip()[:100]
                        if not content:
                            continue
                        dm = {
                            "time": float(params[0]),
                            "mode": int(params[1]),
                            "font_size": int(params[2]),
                            "color": int(params[3]),
                            "content": content
                        }
                        danmaku_list.append(dm)
                        type_counter[dm['mode']] += 1
                        elem.clear()
                    except Exception:
                        continue
        
        self._update_stats(type_counter, len(danmaku_list))
        return danmaku_list

    def _update_stats(self, counter, total):
        self.table_stats.setRowCount(0)
        if total <= 0:
            return
        
        stats = [
            ("总计", total, "100%"),
            *[(self._get_danmaku_type(k), v, f"{v/total:.1%}") 
             for k, v in counter.items()]
        ]
        
        for row, (dtype, count, ratio) in enumerate(stats):
            self.table_stats.insertRow(row)
            self.table_stats.setItem(row, 0, QTableWidgetItem(dtype))
            self.table_stats.setItem(row, 1, QTableWidgetItem(str(count)))
            self.table_stats.setItem(row, 2, QTableWidgetItem(ratio))

    def _get_danmaku_type(self, mode):
        type_map = {
            1: "滚动弹幕",
            4: "底部弹幕",
            5: "顶部弹幕",
            6: "逆向弹幕",
            7: "高级弹幕"
        }
        return type_map.get(mode, "未知类型")

    def _build_headers(self):
        bvid = self.input_目标bv号.text().strip() or "BV_DEFAULT"
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": f"SESSDATA={self.input_sessdata.text() or ''};"
                    f"bili_jct={self.input_bili_jct.text() or ''};"
                    f"buvid3={self.input_buvid3.text() or ''};",
            "Referer": f"https://www.bilibili.com/video/{bvid}",
            "X-Access-Token": self._generate_token()
        }

    def _generate_token(self):
        raw = f"{self.input_sessdata.text()}|{int(time.time())}"
        return md5(raw.encode()).hexdigest()[:12]

    def _network_check(self):
        try:
            headers = self._build_headers()
            response = requests.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 412:
                self._log("请求被拦截，请检查：\n• Cookie有效性\n• 系统时间\n• 网络代理", True)
                return
                
            if response.json()["code"] == 0:
                self._log("网络连接正常，身份验证成功")
            else:
                self._log(f"服务器返回错误: {response.json()['message']}", True)
        except Exception as e:
            self._log(f"网络检测失败: {str(e)}", True)

    def _load_preview(self):
        self.table_danmaku.setRowCount(0)
        try:
            tree = ET.parse(self.xml_path)
            preview_row = 0
            for elem in tree.findall('.//d'):
                if preview_row >= 200:
                    break
                params = elem.attrib.get('p', '').split(',')
                if len(params) < 2:
                    continue
                content = (elem.text or "").strip()[:50]
                self.table_danmaku.insertRow(preview_row)
                self.table_danmaku.setItem(preview_row, 0, QTableWidgetItem(f"{float(params[0]):.1f}s"))
                self.table_danmaku.setItem(preview_row, 1, QTableWidgetItem(content))
                self.table_danmaku.setItem(preview_row, 2, QTableWidgetItem(self._get_danmaku_type(int(params[1]))))
                preview_row += 1
            
            self.table_danmaku.resizeColumnsToContents()
        except Exception as e:
            self._log(f"预览加载失败: {str(e)}", True)

    def _update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        ratio = (current / total) if total else 0
        self.lbl_progress.setText(f"处理中: {current}/{total} ({ratio:.1%})")

    def _on_restore_finished(self, success):
        self.btn_start.setText("▶ 开始")
        self.btn_start.setStyleSheet("")
        if success:
            QMessageBox.information(self, "完成", "弹幕恢复任务已完成")
        else:
            QMessageBox.warning(self, "警告", "部分弹幕发送失败，请检查日志")

    def _clean_cache(self):
        cache_dir = Path.home() / ".bili_dm_cache"
        try:
            if cache_dir.exists():
                for f in cache_dir.glob("*"):
                    f.unlink()
                cache_dir.rmdir()
                self._log("缓存已清除")
        except Exception as e:
            self._log(f"清除缓存失败: {str(e)}", True)

    def _validate_inputs(self, basic_only=False):
        """完整的输入验证逻辑"""
        errors = []
        bvid = self.input_目标bv号.text().strip()
        
        # 基础验证
        if not bvid.startswith("BV"):
            errors.append("BV号必须以BV开头")
            
        if not basic_only:
            # 完整验证
            required_fields = {
                "SESSDATA": self.input_sessdata.text(),
                "bili_jct": self.input_bili_jct.text(),
                "buvid3": self.input_buvid3.text()
            }
            for name, value in required_fields.items():
                if not value.strip():
                    errors.append(f"{name} 不能为空")
            
            if self.combo_parts.currentIndex() == -1:
                errors.append("请选择视频分P")
                
            if not self.xml_path or not Path(self.xml_path).exists():
                errors.append("弹幕文件不存在")

        if errors:
            self._log("输入错误: " + "，".join(errors), True)
            return False
            
        return True

    def _log(self, message, is_error=False):
        """增强的日志记录方法"""
        try:
            timestamp = time.strftime("%H:%M:%S")
            color = "#ff4444" if is_error else "#44ff44"
            
            if self.log_area is not None:
                self.log_area.append(
                    f"<span style='color: {color};'>[{timestamp}] {message}</span>"
                )
            else:
                print(f"[Fallback Log] {message}")
                
            self.statusBar().showMessage(message, 5000)
        except Exception as e:
            print(f"日志记录失败: {str(e)}")

    def _apply_stylesheet(self):
        """完整的界面样式表"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2d2d2d;
                color: #ffffff;
                font-family: 'Microsoft YaHei';
            }
            QPushButton {
                background-color: #444;
                color: white;
                border: 1px solid #666;
                border-radius: 4px;
                padding: 8px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #555;
            }
            QLineEdit {
                background-color: #333;
                color: #fff;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #444;
                border-radius: 3px;
                text-align: center;
                background: #333;
            }
            QProgressBar::chunk {
                background-color: #00a1d6;
                border-radius: 2px;
            }
            QTableWidget {
                background-color: #333;
                alternate-background-color: #2a2a2a;
                gridline-color: #444;
            }
            QHeaderView::section {
                background-color: #444;
                color: white;
                padding: 4px;
            }
            QTabWidget::pane {
                border: 1px solid #444;
            }
            QTabBar::tab {
                background: #444;
                color: white;
                padding: 8px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #555;
            }
        """)

def excepthook(exc_type, exc_value, traceback_obj):
    """全局异常处理函数"""
    import traceback
    error_msg = ''.join(traceback.format_exception(exc_type, exc_value, traceback_obj))
    QMessageBox.critical(None, "致命错误", f"未捕获异常:\n\n{error_msg}")
    sys.exit(1)

if __name__ == "__main__":
    # 必须先设置DPI属性
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    # 设置全局异常处理
    sys.excepthook = excepthook
    
    window = BiliDanmakuRestorer()
    window.show()
    sys.exit(app.exec_())
