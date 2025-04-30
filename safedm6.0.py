import sys
import random
import time
import requests
import xml.etree.ElementTree as ET
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QTextEdit, QFileDialog, QProgressBar, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter
from pathlib import Path

class BiliDanmakuRestorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("B站弹幕补档工具 - PyQt版")
        self.setGeometry(100, 100, 1200, 800)
        
        # 初始化状态变量
        self.xml_path = ""
        self.cid_list = []
        self.pages = []
        self.running = False
        self.max_danmaku = 500
        self.min_delay = 20
        self.retry_limit = 3
        self.simulate_mode = False
        
        # 显式初始化UI组件
        self.sessdata_input = QLineEdit()
        self.bili_jct_input = QLineEdit()
        self.buvid3_input = QLineEdit()
        self.bvid_input = QLineEdit()
        
        self.init_ui()
        self.apply_stylesheet()
        self.check_local_environment()
    
    def init_ui(self):
        main_layout = QHBoxLayout()
        
        # 侧边栏
        self.sidebar = QVBoxLayout()
        self.init_sidebar()
        
        # 主内容区
        self.tabs = QTabWidget()
        self.config_tab = QWidget()
        self.preview_tab = QWidget()
        self.tabs.addTab(self.config_tab, "配置参数")
        self.tabs.addTab(self.preview_tab, "弹幕预览")
        
        main_layout.addLayout(self.sidebar, 1)
        main_layout.addWidget(self.tabs, 4)
        
        # 初始化各选项卡
        self.init_config_tab()
        self.init_preview_tab()
        
        # 日志区域
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(200)
        main_layout.addWidget(self.log_area)
        
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def init_sidebar(self):
        # 侧边栏按钮（关键修复部分）
        btn_size = 40
        button_configs = [
            ("开始", self.toggle_restore, "start_btn"),
            ("清除", self.clean_checkpoint, "clear_btn"),
            ("导出", self.export_log, "export_btn"),
            ("检测", self.network_check, "check_btn"),
            ("关于", self.show_about_dialog, "about_btn")
        ]
        
        for text, callback, attr_name in button_configs:
            btn = QPushButton(text)
            btn.setFixedSize(btn_size, btn_size)
            btn.clicked.connect(callback)
            setattr(self, attr_name, btn)  # 动态设置实例属性
            self.sidebar.addWidget(btn)
        
        self.progress_bar = QProgressBar()
        self.sidebar.addWidget(self.progress_bar)
    
    def init_config_tab(self):
        layout = QVBoxLayout()
        
        # 凭证输入字段
        layout.addWidget(QLabel("SESSDATA:"))
        layout.addWidget(self.sessdata_input)
        layout.addWidget(QLabel("bili_jct:"))
        layout.addWidget(self.bili_jct_input)
        layout.addWidget(QLabel("buvid3:"))
        layout.addWidget(self.buvid3_input)
        layout.addWidget(QLabel("目标BV号:"))
        layout.addWidget(self.bvid_input)
        
        # 分P选择
        self.part_combobox = QComboBox()
        layout.addWidget(QLabel("视频分P:"))
        layout.addWidget(self.part_combobox)
        
        # 功能按钮
        self.fetch_parts_btn = QPushButton("获取分P")
        self.fetch_parts_btn.clicked.connect(self.fetch_parts)
        layout.addWidget(self.fetch_parts_btn)
        
        self.xml_select_btn = QPushButton("选择弹幕文件")
        self.xml_select_btn.clicked.connect(self.select_xml)
        layout.addWidget(self.xml_select_btn)
        
        # 选项
        self.resume_checkbox = QCheckBox("断点续传")
        self.simulate_checkbox = QCheckBox("模拟发送模式")
        layout.addWidget(self.resume_checkbox)
        layout.addWidget(self.simulate_checkbox)
        
        self.config_tab.setLayout(layout)
    
    def init_preview_tab(self):
        layout = QVBoxLayout()
        self.danmaku_table = QTableWidget()
        self.danmaku_table.setColumnCount(3)
        self.danmaku_table.setHorizontalHeaderLabels(["时间", "内容", "类型"])
        self.danmaku_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.danmaku_table)
        self.preview_tab.setLayout(layout)
    
    def select_xml(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择弹幕文件", 
            "", 
            "XML文件 (*.xml)"
        )
        if file_path:
            self.xml_path = file_path
            self.log(f"已选择弹幕文件: {file_path}")
            self.load_danmaku_preview()
    
    def fetch_parts(self):
        """获取视频分P信息"""
        bvid = self.bvid_input.text().strip()
        if not bvid.startswith("BV"):
            self.log("BV号格式错误", error=True)
            return
        
        try:
            url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Cookie": f"SESSDATA={self.sessdata_input.text().strip()};"
                        f"bili_jct={self.bili_jct_input.text().strip()};"
                        f"buvid3={self.buvid3_input.text().strip()}"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data["code"] != 0:
                raise ValueError(data["message"])
            
            self.pages = data["data"]["pages"]
            self.cid_list = [p["cid"] for p in self.pages]
            self.part_combobox.clear()
            for idx, page in enumerate(self.pages):
                self.part_combobox.addItem(f"P{idx+1}: {page['part']}", page["cid"])
            
            self.log(f"成功获取{len(self.pages)}个分P")
        except Exception as e:
            self.log(f"获取分P失败: {str(e)}", error=True)
    
    def toggle_restore(self):
        """切换任务状态"""
        if self.running:
            self.running = False
            self.start_btn.setText("开始")
            self.log("任务已停止")
        else:
            if self.validate_inputs():
                self.running = True
                self.start_btn.setText("停止")
                self.simulate_mode = self.simulate_checkbox.isChecked()
                self.restore_process()
    
    def validate_inputs(self):
        """验证输入有效性"""
        required = {
            "SESSDATA": self.sessdata_input.text().strip(),
            "bili_jct": self.bili_jct_input.text().strip(),
            "BV号": self.bvid_input.text().strip(),
            "分P选择": self.part_combobox.currentIndex(),
            "弹幕文件": self.xml_path
        }
        
        for name, value in required.items():
            if not value and name != "分P选择":
                self.log(f"{name}不能为空", error=True)
                return False
            if name == "分P选择" and value == -1:
                self.log("请选择视频分P", error=True)
                return False
        return True
    
    def restore_process(self):
        """执行弹幕修复流程"""
        try:
            # 解析XML文件
            tree = ET.parse(self.xml_path)
            root = tree.getroot()
            danmaku_list = []
            
            for d in root.findall("d"):
                params = d.attrib.get("p", "")
                if len(params.split(",")) < 4:
                    continue
                
                try:
                    p = params.split(",")
                    danmaku_list.append({
                        "time": float(p[0]),
                        "mode": int(p[1]),
                        "font_size": int(p[2]),
                        "color": int(p[3]),
                        "content": d.text.strip()[:100]  # 限制长度
                    })
                except (ValueError, IndexError) as e:
                    self.log(f"无效弹幕参数: {str(e)}", error=True)
                    continue
            
            total = len(danmaku_list)
            if total == 0:
                raise ValueError("未找到有效弹幕")
            
            self.progress_bar.setMaximum(total)
            success_count = 0
            
            for idx, dm in enumerate(danmaku_list):
                if not self.running:
                    break
                
                # 发送逻辑
                if self.simulate_mode:
                    self.log(f"[模拟] {dm['content']}")
                    status = True
                else:
                    status = self.send_danmaku_with_retry(dm)
                
                if status:
                    success_count += 1
                
                # 更新进度
                self.progress_bar.setValue(idx + 1)
                time.sleep(self.min_delay + random.uniform(0, 3))
            
            self.log(f"任务完成，成功发送 {success_count}/{total} 条弹幕")
        
        except ET.ParseError:
            self.log("XML文件解析失败", error=True)
        except Exception as e:
            self.log(f"运行错误: {str(e)}", error=True)
        finally:
            self.running = False
            self.start_btn.setText("开始")
    
    def send_danmaku_with_retry(self, dm):
        """带重试机制的弹幕发送"""
        for attempt in range(self.retry_limit):
            try:
                response = self.send_danmaku(dm)
                if response.json()["code"] == 0:
                    self.log(f"发送成功: {dm['content']}")
                    return True
                else:
                    msg = response.json().get("message", "未知错误")
                    self.log(f"尝试 {attempt+1}/{self.retry_limit} 失败: {msg}", error=True)
            except requests.exceptions.Timeout:
                self.log(f"请求超时（尝试 {attempt+1}/{self.retry_limit}）", error=True)
            except requests.exceptions.JSONDecodeError:
                self.log("响应解析失败", error=True)
            except Exception as e:
                self.log(f"网络错误: {str(e)}", error=True)
            time.sleep(2)
        return False
    
    def send_danmaku(self, dm):
        """发送单个弹幕"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": f"https://www.bilibili.com/video/{self.bvid_input.text()}",
            "Cookie": f"SESSDATA={self.sessdata_input.text()};"
                    f"bili_jct={self.bili_jct_input.text()};"
                    f"buvid3={self.buvid3_input.text()}"
        }
        
        data = {
            "oid": self.cid_list[self.part_combobox.currentIndex()],
            "type": 1,
            "mode": dm["mode"],
            "fontsize": dm["font_size"],
            "color": dm["color"],
            "message": dm["content"],
            "csrf": self.bili_jct_input.text()
        }
        
        return requests.post(
            "https://api.bilibili.com/x/v2/dm/post",
            headers=headers,
            data=data,
            timeout=15
        )
    
    def load_danmaku_preview(self):
        """加载弹幕预览"""
        try:
            tree = ET.parse(self.xml_path)
            root = tree.getroot()
            
            self.danmaku_table.setRowCount(0)
            for row, d in enumerate(root.findall("d")):
                if row >= 100:  # 限制预览数量
                    break
                
                params = d.attrib.get("p", "").split(",")
                if len(params) < 4:
                    continue
                
                self.danmaku_table.insertRow(row)
                self.danmaku_table.setItem(row, 0, QTableWidgetItem(params[0]))
                self.danmaku_table.setItem(row, 1, QTableWidgetItem(d.text.strip()))
                self.danmaku_table.setItem(row, 2, QTableWidgetItem(self.parse_mode(params[1])))
        
        except Exception as e:
            self.log(f"预览加载失败: {str(e)}", error=True)
    
    def parse_mode(self, mode_code):
        """解析弹幕类型"""
        modes = {
            "1": "滚动弹幕",
            "4": "底部弹幕",
            "5": "顶部弹幕"
        }
        return modes.get(mode_code, "未知类型")
    
    def log(self, message, error=False):
        """记录日志"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if error:
            self.log_area.append(f"<span style='color: red;'>{timestamp} - {message}</span>")
        else:
            self.log_area.append(f"<span style='color: green;'>{timestamp} - {message}</span>")
    
    def clean_checkpoint(self):
        """清除缓存"""
        cache_file = Path.home() / ".bili_dm_cache" / "session.json"
        try:
            if cache_file.exists():
                cache_file.unlink()
                self.log("已清除缓存文件")
        except Exception as e:
            self.log(f"清除缓存失败: {str(e)}", error=True)
    
    def export_log(self):
        """导出日志"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志",
            "",
            "文本文件 (*.txt)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.log_area.toPlainText())
                self.log(f"日志已导出到: {file_path}")
            except Exception as e:
                self.log(f"导出失败: {str(e)}", error=True)
    
    def network_check(self):
        """网络检测"""
        try:
            response = requests.get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
            if response.status_code == 200:
                self.log("网络连接正常")
            else:
                self.log(f"网络异常，状态码: {response.status_code}", error=True)
        except Exception as e:
            self.log(f"网络检测失败: {str(e)}", error=True)
    
    def show_about_dialog(self):
        """显示关于对话框"""
        about_text = (
            "B站弹幕补档工具\n\n"
            "版本: 2.1\n"
            "作者: IAllemege\n"
        )
        QMessageBox.about(self, "关于", about_text)
    
    def check_local_environment(self):
        """检查本地环境"""
        cache_dir = Path.home() / ".bili_dm_cache"
        try:
            cache_dir.mkdir(exist_ok=True)
            (cache_dir / "session.json").touch(exist_ok=True)
        except Exception as e:
            self.log(f"环境初始化失败: {str(e)}", error=True)
    
    def apply_stylesheet(self):
        """应用样式表"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F5F5F5;
                font-family: "Microsoft YaHei";
            }
            QPushButton {
                background-color: #00A1D6;
                color: white;
                border-radius: 4px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #008BBA;
            }
            QLineEdit {
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                padding: 3px;
            }
            QProgressBar {
                border: 1px solid #CCCCCC;
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #00A1D6;
            }
            QTableWidget {
                background-color: white;
                alternate-background-color: #F5F5F5;
            }
        """)

def init_preview_tab(self):
    layout = QVBoxLayout()
    
    # 创建分栏布局
    split_layout = QHBoxLayout()
    
    # 原始弹幕表格
    self.danmaku_table = QTableWidget()
    self.danmaku_table.setColumnCount(3)
    self.danmaku_table.setHorizontalHeaderLabels(["时间", "内容", "类型"])
    
    # 新增统计表格
    self.stats_table = QTableWidget()
    self.stats_table.setColumnCount(3)
    self.stats_stats_header = ["统计项", "数量", "占比"]
    self.stats_table.setHorizontalHeaderLabels(self.stats_stats_header)
    self.stats_table.setFixedWidth(300)
    
    split_layout.addWidget(self.danmaku_table, 3)
    split_layout.addWidget(self.stats_table, 1)
    
    layout.addLayout(split_layout)
    self.preview_tab.setLayout(layout)

def load_danmaku_preview(self):
    try:
        # 清空原有数据
        self.danmaku_table.setRowCount(0)
        
        # 解析XML并加载预览
        tree = ET.parse(self.xml_path)
        root = tree.getroot()
        
        danmaku_data = []
        type_counter = defaultdict(int)
        
        for idx, d in enumerate(root.findall("d")):
            # 原有解析逻辑...
            
            # 统计弹幕类型
            type_counter[dm["mode"]] += 1
            
            # 添加预览行
            row = self.danmaku_table.rowCount()
            self.danmaku_table.insertRow(row)
            self.danmaku_table.setItem(row, 0, QTableWidgetItem(f"{dm['time']:.1f}s"))
            self.danmaku_table.setItem(row, 1, QTableWidgetItem(dm["content"]))
            self.danmaku_table.setItem(row, 2, QTableWidgetItem(self.get_danmaku_type(dm["mode"])))
        
        # 更新统计表格
        self.update_stats_table(type_counter, len(danmaku_data))
        
    except Exception as e:
        self.log(f"加载弹幕失败: {str(e)}", error=True)

def get_danmaku_type(self, mode):
    type_map = {
        1: "滚动弹幕",
        4: "底部弹幕",
        5: "顶部弹幕",
        6: "逆向弹幕",
        7: "特殊弹幕"
    }
    return type_map.get(mode, "未知类型")

def update_stats_table(self, counter, total):
    self.stats_table.setRowCount(0)
    
    # 添加统计数据行
    stats_items = [
        ("总弹幕数", total, "100%"),
        *[(self.get_danmaku_type(k), v, f"{v/total:.1%}") 
         for k, v in counter.items()]
    ]
    
    for row, (item, count, ratio) in enumerate(stats_items):
        self.stats_table.insertRow(row)
        self.stats_table.setItem(row, 0, QTableWidgetItem(item))
        self.stats_table.setItem(row, 1, QTableWidgetItem(str(count)))
        self.stats_table.setItem(row, 2, QTableWidgetItem(ratio))
    
    # 设置样式
    self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    for col in [1, 2]:
        for row in range(self.stats_table.rowCount()):
            item = self.stats_table.item(row, col)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BiliDanmakuRestorer()
    window.show()
    sys.exit(app.exec_())
