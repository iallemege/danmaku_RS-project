import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import xml.etree.ElementTree as ET
import time
import threading
import requests
import re
import random
import asyncio
from queue import Queue
from bilibili_api import video, Credential

class BiliDanmakuRestorer:
    def __init__(self, root):
        self.root = root
        root.title("B站弹幕补档工具 3.0")
        root.geometry("850x700")
        
        self.create_widgets()
        self.running = False
        self.stop_event = threading.Event()
        self.log_queue = Queue()
        self.progress_queue = Queue()
        
        self.root.after(100, self.process_queues)

    def create_widgets(self):
        """界面组件"""
        config_frame = ttk.LabelFrame(self.root, text="配置参数")
        config_frame.pack(pady=5, padx=10, fill="x")

        # Cookie信息
        ttk.Label(config_frame, text="SESSDATA:").grid(row=0, column=0, padx=5, pady=2, sticky="e")
        self.sessdata_entry = ttk.Entry(config_frame, width=50)
        self.sessdata_entry.grid(row=0, column=1, padx=5, sticky="w")

        ttk.Label(config_frame, text="bili_jct:").grid(row=1, column=0, padx=5, pady=2, sticky="e")
        self.bili_jct_entry = ttk.Entry(config_frame, width=50)
        self.bili_jct_entry.grid(row=1, column=1, padx=5, sticky="w")

        ttk.Label(config_frame, text="buvid3:").grid(row=2, column=0, padx=5, pady=2, sticky="e")
        self.buvid3_entry = ttk.Entry(config_frame, width=50)
        self.buvid3_entry.grid(row=2, column=1, padx=5, sticky="w")

        # 视频信息
        ttk.Label(config_frame, text="目标BV号:").grid(row=3, column=0, padx=5, pady=2, sticky="e")
        self.bvid_entry = ttk.Entry(config_frame, width=30)
        self.bvid_entry.grid(row=3, column=1, padx=5, sticky="w")

        # 文件选择
        ttk.Label(config_frame, text="弹幕文件:").grid(row=4, column=0, padx=5, pady=2, sticky="e")
        self.xml_path = tk.StringVar()
        ttk.Entry(config_frame, textvariable=self.xml_path, width=40).grid(row=4, column=1, padx=5, sticky="w")
        ttk.Button(config_frame, text="选择文件", command=self.select_xml).grid(row=4, column=2, padx=5)

        # 控制区
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=5, fill="x")
        self.start_btn = ttk.Button(control_frame, text="开始补档", command=self.toggle_restore)
        self.start_btn.pack(side="left", padx=20)
        self.progress = ttk.Progressbar(control_frame, mode="determinate")
        self.progress.pack(side="left", expand=True, fill="x", padx=10)

        # 日志区
        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(padx=10, pady=5, fill="both", expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, height=20)
        self.log_area.pack(fill="both", expand=True)

    def select_xml(self):
        """文件选择"""
        if path := filedialog.askopenfilename(filetypes=[("XML Files", "*.xml")]):
            self.xml_path.set(path)

    def process_queues(self):
        """处理日志和进度更新"""
        while not self.log_queue.empty():
            self.log_area.insert("end", self.log_queue.get())
            self.log_area.see("end")
        while not self.progress_queue.empty():
            self.progress["value"] = self.progress_queue.get()
        self.root.after(100, self.process_queues)

    def log(self, message):
        """日志记录"""
        self.log_queue.put(f"{time.strftime('%H:%M:%S')} - {message}\n")

    def validate_inputs(self):
        """输入验证"""
        required = [
            (self.sessdata_entry, "SESSDATA"),
            (self.bili_jct_entry, "bili_jct"),
            (self.buvid3_entry, "buvid3"),
            (self.bvid_entry, "BV号")
        ]
        for entry, name in required:
            if not entry.get().strip():
                self.log(f"{name}不能为空")
                return False
        if not re.fullmatch(r'BV1[0-9A-HJ-NP-Za-km-z]{9}', self.bvid_entry.get().strip()):
            self.log("BV号格式错误")
            return False
        return True

    def toggle_restore(self):
        """开始/停止控制"""
        if self.running:
            self.stop_event.set()
            self.running = False
            self.start_btn.config(text="开始补档")
        else:
            if self.validate_inputs():
                self.running = True
                self.stop_event.clear()
                self.start_btn.config(text="停止补档")
                threading.Thread(target=self.restore_process, daemon=True).start()

    def parse_danmaku(self):
        """增强版XML解析"""
        try:
            tree = ET.parse(self.xml_path.get())
            danmaku_list = []
            for d in tree.findall('d'):
                try:
                    params = d.attrib['p'].split(',')
                    if len(params) < 9:
                        continue

                    # 参数验证
                    mode = int(params[1])
                    if mode not in {1, 4, 5}:
                        raise ValueError(f"无效弹幕类型: {mode}")
                        
                    color = int(params[3].split('.')[0])  # 处理浮点格式
                    if not (0 <= color <= 0xFFFFFF):
                        raise ValueError(f"颜色值越界: {color}")

                    content = d.text.strip()
                    if len(content) > 100 or len(content) == 0:
                        raise ValueError("弹幕长度无效")

                    danmaku = {
                        'time': float(params[0]),
                        'mode': mode,
                        'font_size': int(params[2]),
                        'color': color,
                        'timestamp': int(params[4]),
                        'pool_type': int(params[5]),
                        'sender_hash': params[6],
                        'row_id': params[7],
                        'weight': int(params[8]),
                        'content': content
                    }
                    danmaku_list.append(danmaku)
                except (ValueError, IndexError, AttributeError) as e:
                    self.log(f"弹幕过滤: {str(e)}")
                    continue
            return danmaku_list[:500]
        except Exception as e:
            self.log(f"XML解析失败: {str(e)}")
            return None

    def get_video_info_sync(self):
        """视频信息获取（带重试）"""
        for attempt in range(3):
            try:
                loop = asyncio.new_event_loop()
                v = video.Video(
                    bvid=self.bvid_entry.get().strip(),
                    credential=Credential(
                        sessdata=self.sessdata_entry.get(),
                        bili_jct=self.bili_jct_entry.get(),
                        buvid3=self.buvid3_entry.get()
                    )
                )
                return loop.run_until_complete(v.get_info())
            except Exception as e:
                if attempt == 2:
                    self.log(f"视频信息获取失败: {str(e)}")
                    return None
                time.sleep(2)
            finally:
                if 'loop' in locals():
                    loop.close()

    def restore_process(self):
        """终极版补档逻辑"""
        try:
            # 获取凭证信息
            sessdata = self.sessdata_entry.get().strip()
            bili_jct = self.bili_jct_entry.get().strip()
            buvid3 = self.buvid3_entry.get().strip()

            # 获取视频信息
            if not (info := self.get_video_info_sync()):
                return
            cid = info['pages'][0]['cid']

            # 解析弹幕
            if (danmaku_list := self.parse_danmaku()) is None:
                return
            total = len(danmaku_list)
            success = 0
            
            with requests.Session() as session:
                session.headers.update({
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive"
                })
                
                for idx, dm in enumerate(danmaku_list):
                    if self.stop_event.is_set():
                        break

                    # 构造请求数据
                    data = {
                        "oid": cid,
                        "type": 1,
                        "mode": dm["mode"],
                        "color": dm["color"],
                        "message": dm["content"],
                        "fontsize": dm["font_size"],
                        "pool": dm["pool_type"],
                        "csrf": bili_jct,
                        "csrf_token": bili_jct,
                        "ts": int(time.time() * 1000),
                        "rnd": random.randint(100000, 999999)
                    }

                    # 构造请求头
                    headers = {
                        "Referer": f"https://www.bilibili.com/video/{self.bvid_entry.get()}",
                        "Origin": "https://www.bilibili.com",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "X-Requested-With": "XMLHttpRequest"
                    }

                    # 请求重试机制
                    for retry in range(3):
                        try:
                            response = session.post(
                                "https://api.bilibili.com/x/v2/dm/post",
                                headers=headers,
                                cookies={
                                    "SESSDATA": sessdata,
                                    "bili_jct": bili_jct,
                                    "buvid3": buvid3
                                },
                                data=data,
                                timeout=(5.0, 10.0)
                            )
                            response.raise_for_status()
                            break
                        except requests.exceptions.RequestException as e:
                            if retry == 2:
                                raise
                            self.log(f"请求重试 {retry+1}/3...")
                            time.sleep(2 ** retry)

                    # 处理响应
                    try:
                        resp_json = response.json()
                        if resp_json["code"] != 0:
                            raise Exception(f"{resp_json.get('message')} (代码: {resp_json['code']})")
                            
                        success += 1
                        self.log(f"发送成功: {dm['content'][:15]}...")
                    except Exception as e:
                        self.log(f"API错误: {str(e)}")
                        if resp_json.get("code") == -412:
                            self.log("触发风控限制，建议更换网络环境")
                            self.stop_event.set()
                            break

                    # 更新进度
                    self.progress_queue.put((idx+1)/total*100)

                    # 智能频率控制
                    base_delay = 20 + (idx % 10)  # 动态基础延迟
                    jitter = random.uniform(-3, 5)
                    delay = max(base_delay + jitter, 15)
                    
                    if idx < total-1 and not self.stop_event.is_set():
                        self.log(f"等待 {delay:.1f} 秒...")
                        start = time.time()
                        while time.time() - start < delay and not self.stop_event.is_set():
                            time.sleep(0.5)

            self.log(f"\n补档完成! 成功率: {success}/{total} ({success/total:.1%})")

        except Exception as e:
            self.log(f"运行异常: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.running = False
            self.start_btn.config(text="开始补档")
            self.progress_queue.put(100)

if __name__ == "__main__":
    root = tk.Tk()
    app = BiliDanmakuRestorer(root)
    root.mainloop()
