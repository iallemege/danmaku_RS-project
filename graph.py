import sys
import random
import time
import numpy as np
from threading import Thread
from queue import Queue
import xml.etree.ElementTree as ET
import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QTextEdit, QFileDialog
)
from PyQt5.QtCore import Qt, QTimer

class BiliDanmakuRestorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("弹幕修复工具 - PyQtGraph 专业版")
        self.setGeometry(100, 100, 1400, 800)
        
        # 初始化核心属性
        self.sessdata_input = QLineEdit()
        self.bili_jct_input = QLineEdit()
        self.buvid3_input = QLineEdit()
        self.bvid_input = QLineEdit()
        self.part_combobox = QComboBox()
        
        # 数据存储
        self.danmaku_queue = Queue()
        self.progress_data = []
        self.time_bins = []
        self.histogram = None
        self.sending = False
        
        # 初始化UI
        self.init_ui()
        
        # 设置定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_visualization)
        self.timer.start(50)  # 20 FPS刷新率

    def init_ui(self):
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        
        # 左侧控制面板
        control_panel = self.create_control_panel()
        main_layout.addLayout(control_panel, stretch=1)
        
        # 右侧可视化面板
        vis_widget = self.create_visualization_panel()
        main_layout.addWidget(vis_widget, stretch=3)
        
        self.setCentralWidget(main_widget)

    def create_control_panel(self):
        layout = QVBoxLayout()
        
        # 凭证输入
        layout.addWidget(QLabel("SESSDATA:"))
        layout.addWidget(self.sessdata_input)
        layout.addWidget(QLabel("bili_jct:"))
        layout.addWidget(self.bili_jct_input)
        layout.addWidget(QLabel("buvid3:"))
        layout.addWidget(self.buvid3_input)
        
        # BV号输入
        layout.addWidget(QLabel("目标BV号:"))
        layout.addWidget(self.bvid_input)
        
        # 分P选择
        layout.addWidget(QLabel("视频分P:"))
        layout.addWidget(self.part_combobox)
        
        # 文件操作
        self.xml_btn = QPushButton("加载弹幕文件")
        self.xml_btn.clicked.connect(self.load_danmaku_file)
        layout.addWidget(self.xml_btn)
        
        # 控制按钮
        self.start_btn = QPushButton("开始发送")
        self.start_btn.clicked.connect(self.toggle_sending)
        layout.addWidget(self.start_btn)
        
        # 日志显示
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)
        
        return layout

    def create_visualization_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 实时进度图
        self.progress_plot = pg.PlotWidget(title="发送进度监控")
        self.progress_plot.setLabel('left', "完成百分比")
        self.progress_plot.setLabel('bottom', "时间 (s)")
        self.progress_curve = self.progress_plot.plot(pen=pg.mkPen('y', width=2))
        
        # 时间分布直方图
        self.hist_plot = pg.PlotWidget(title="弹幕时间分布")
        self.hist_plot.setLabel('left', "数量")
        self.hist_plot.setLabel('bottom', "时间轴 (s)")
        
        # 实时状态仪表
        self.status_plot = pg.PlotWidget(title="实时状态")
        self.status_text = pg.TextItem(color='w')
        self.status_plot.addItem(self.status_text)
        
        layout.addWidget(self.progress_plot)
        layout.addWidget(self.hist_plot)
        layout.addWidget(self.status_plot)
        
        return widget

    def load_danmaku_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择弹幕文件", "", "XML文件 (*.xml)")
        if path:
            self.parse_xml(path)
            
    def parse_xml(self, path):
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            times = []
            
            for d in root.findall('d'):
                params = d.attrib.get('p', '').split(',')
                if len(params) >= 4:
                    times.append(float(params[0]))
            
            # 生成直方图数据
            hist, edges = np.histogram(times, bins=20)
            x = edges[:-1]
            width = np.diff(edges)
            
            if self.histogram:
                self.hist_plot.removeItem(self.histogram)
            
            self.histogram = pg.BarGraphItem(
                x=x, height=hist, width=width*0.8,
                brush='r', pen=pg.mkPen('w', width=1)
            )
            self.hist_plot.addItem(self.histogram)
            
            self.log_area.append(f"成功加载 {len(times)} 条弹幕")
            
        except Exception as e:
            self.log_area.append(f"<font color='red'>解析错误: {str(e)}</font>")

    def toggle_sending(self):
        if self.sending:
            self.sending = False
            self.start_btn.setText("开始发送")
        else:
            if self.validate_inputs():
                self.sending = True
                self.start_btn.setText("停止发送")
                Thread(target=self.sending_thread).start()

    def validate_inputs(self):
        required = [
            self.sessdata_input.text().strip(),
            self.bili_jct_input.text().strip(),
            self.bvid_input.text().strip(),
            self.xml_path
        ]
        if not all(required):
            self.log_area.append("<font color='red'>错误：请填写所有必填项</font>")
            return False
        return True

    def sending_thread(self):
        # 模拟发送过程
        total = 100
        start_time = time.time()
        
        for i in range(total):
            if not self.sending:
                break
            
            # 模拟发送延迟
            time.sleep(0.1 + random.random()*0.2)
            
            # 更新队列数据
            self.danmaku_queue.put({
                'progress': (i+1)/total,
                'timestamp': time.time() - start_time,
                'status': f"正在发送 {i+1}/{total}"
            })

    def update_visualization(self):
        # 处理队列数据
        while not self.danmaku_queue.empty():
            data = self.danmaku_queue.get()
            
            # 更新进度数据
            if 'progress' in data:
                self.progress_data.append(data['progress'])
            
            # 更新状态文本
            if 'status' in data:
                self.status_text.setText(data['status'], color=(255,255,255))
        
        # 实时更新曲线
        if self.progress_data:
            x = np.linspace(0, len(self.progress_data)/10, len(self.progress_data))
            self.progress_curve.setData(x, self.progress_data)
        
        # 限制数据量
        if len(self.progress_data) > 200:
            self.progress_data = self.progress_data[-200:]

if __name__ == "__main__":
    pg.setConfigOptions(antialias=True)  # 开启抗锯齿
    app = QApplication(sys.argv)
    window = BiliDanmakuRestorer()
    window.show()
    sys.exit(app.exec_())
