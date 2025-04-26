import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import xml.etree.ElementTree as ET
import time
import threading
import requests
import re
import random
import asyncio
import os
import json
from queue import Queue
from bilibili_api import video, Credential
from datetime import datetime, timezone
from urllib.parse import urlencode

class BiliDanmakuRestorer:
    auto_shutdown_choose = False
    def __init__(self, root):
        self.root = root
        root.title("B站弹幕补档工具 正式版 v4.0")
        root.geometry("1000x850")
        
        # 初始化Tkinter变量
        self.color_format = tk.IntVar(value=0)
        self.xml_path = tk.StringVar()
        
        # 创建UI组件
        self.create_widgets()
        
        # 初始化运行时变量
        self.running = False
        self.stop_event = threading.Event()
        self.log_queue = Queue()
        self.progress_queue = Queue()
        
        # 启动队列处理
        self.root.after(100, self.process_queues)

    def clear_log(self):
        """清空日志"""
        self.log_area.delete("1.0", "end")

    def about_us(self):
        """关于我们"""
        msg = \
        """
        \n
        ==============================================================================================================
        B站弹幕补档工具 是一个开源的弹幕补档工具，基于Bilibili-API实现。遵从MIT开源协议。
        项目地址：https://github.com/safedm/safedm
        作者: iallemege
        主要贡献者: mlfkhf

        本工具最初用于【幻想万华镜补档项目】，现开源。
        ==============================================================================================================
        """
        self.log(msg)
    
    def create_widgets(self):
        """创建界面组件"""
        config_frame = ttk.LabelFrame(self.root, text="配置参数")
        config_frame.pack(pady=5, padx=10, fill="x")

        # Cookie信息输入
        cookie_labels = ["SESSDATA:", "bili_jct:", "buvid3:"]
        self.sessdata_entry = ttk.Entry(config_frame, width=55)
        self.bili_jct_entry = ttk.Entry(config_frame, width=55)
        self.buvid3_entry = ttk.Entry(config_frame, width=55)
        
        for i, text in enumerate(cookie_labels):
            ttk.Label(config_frame, text=text).grid(row=i, column=0, padx=5, pady=2, sticky="e")
            [self.sessdata_entry, self.bili_jct_entry, self.buvid3_entry][i].grid(
                row=i, column=1, padx=5, sticky="w", columnspan=2)

        # 视频信息
        ttk.Label(config_frame, text="目标BV号:").grid(row=3, column=0, padx=5, pady=2, sticky="e")
        self.bvid_entry = ttk.Entry(config_frame, width=35)
        self.bvid_entry.grid(row=3, column=1, padx=5, sticky="w")

        # 文件选择
        ttk.Label(config_frame, text="弹幕文件:").grid(row=4, column=0, padx=5, pady=2, sticky="e")
        ttk.Entry(config_frame, textvariable=self.xml_path, width=45).grid(row=4, column=1, padx=5, sticky="w")
        ttk.Button(config_frame, text="选择文件", command=self.select_xml).grid(row=4, column=2, padx=5)

        # 颜色格式选择
        color_frame = ttk.Frame(config_frame)
        color_frame.grid(row=5, column=0, columnspan=3, pady=5, sticky="w")
        ttk.Label(color_frame, text="颜色格式:").pack(side="left")
        ttk.Radiobutton(color_frame, text="十进制", variable=self.color_format, value=0).pack(side="left", padx=5)
        ttk.Radiobutton(color_frame, text="十六进制", variable=self.color_format, value=1).pack(side="left")

        # 控制区
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=5, fill="x")
        self.start_btn = ttk.Button(control_frame, text="开始补档", command=self.toggle_restore)
        self.start_btn.pack(side="left", padx=20)
        self.progress = ttk.Progressbar(control_frame, mode="determinate")
        self.progress.pack(side="left", expand=True, fill="x", padx=10)
        self.auto_shutdown = ttk.Checkbutton(control_frame, onvalue=True, offvalue=False ,text="自动关机", variable=self.auto_shutdown_choose)
        self.auto_shutdown.pack(side="left", padx=10)
        ttk.Button(config_frame, text="清空日志", command=self.clear_log).grid(row=4, column=7, padx=5)
        ttk.Button(config_frame, text="关于我们", command=self.about_us).grid(row=4, column=12, padx=5)

        # 日志区
        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(padx=10, pady=5, fill="both", expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, height=22)
        self.log_area.pack(fill="both", expand=True)

    def select_xml(self):
        """选择XML文件"""
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
        """记录日志"""
        self.log_queue.put(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

    def validate_inputs(self):
        """验证输入有效性"""
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
        """切换开始/停止状态"""
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

    def parse_color(self, raw_color):
        """解析颜色值"""
        try:
            clean_color = str(raw_color).strip().lower().replace('0x', '').replace('#', '')
            
            if self.color_format.get() == 1:  # 十六进制模式
                if len(clean_color) != 6 or not re.match(r'^[0-9a-f]{6}$', clean_color):
                    raise ValueError("无效的十六进制颜色")
                return int(clean_color, 16)
            
            # 十进制模式
            if '.' in clean_color:
                return int(float(clean_color))
            if not clean_color.isdigit():
                raise ValueError("非数字格式")
            return int(clean_color)
            
        except Exception as e:
            raise ValueError(f"颜色解析失败: {str(e)}")

    def parse_danmaku(self):
        """解析XML弹幕文件"""
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
                    if mode not in {1, 4, 5, 6, 7}:
                        raise ValueError(f"不支持的弹幕模式: {mode}")

                    color = self.parse_color(params[3].split('.')[0])
                    if not (0x000000 <= color <= 0xFFFFFF):
                        raise ValueError(f"颜色值越界: 0x{color:06x}")

                    pool_type = int(params[5])
                    if not (0 <= pool_type <= 2):
                        raise ValueError("无效弹幕池类型")

                    content = d.text.strip()
                    if not (0 < len(content) <= 100):
                        raise ValueError("弹幕长度无效")

                    danmaku_list.append({
                        'time': float(params[0]),
                        'mode': mode,
                        'color': color,
                        'font_size': int(params[2]),
                        'pool_type': pool_type,
                        'content': content
                    })
                    
                except Exception as e:
                    self.log(f"弹幕过滤: {str(e)}")
            
            return danmaku_list[:500]  # 限制最大数量
        
        except Exception as e:
            self.log(f"XML解析失败: {str(e)}")
            return None

    def check_credential_valid(self):
        """验证Cookie有效性"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            credential = Credential(
                sessdata=self.sessdata_entry.get(),
                bili_jct=self.bili_jct_entry.get(),
                buvid3=self.buvid3_entry.get()
            )
            loop.run_until_complete(credential.check_valid())
            return True
        except Exception as e:
            self.log(f"凭证验证失败: {str(e)}")
            return False
        finally:
            loop.close()

    def get_video_info_sync(self):
        """同步获取视频信息"""
        for attempt in range(3):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
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
                time.sleep(2)
            finally:
                loop.close()

    def restore_process(self):
        """核心补档流程"""
        try:
            # 凭证验证
            if not self.check_credential_valid():
                return

            # 获取视频信息
            video_info = self.get_video_info_sync()
            if not video_info:
                return
            cid = video_info['pages'][0]['cid']
            self.log(f"视频CID获取成功: {cid}")

            # 解析弹幕
            danmaku_list = self.parse_danmaku()
            if not danmaku_list:
                self.log("错误：未解析到有效弹幕")
                return
            
            total = len(danmaku_list)
            success = 0
            
            with requests.Session() as session:
                # 配置会话参数
                session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive"
                })

                for idx, dm in enumerate(danmaku_list):
                    if self.stop_event.is_set():
                        break

                    # 获取CSRF Token
                    csrf_token = self.bili_jct_entry.get().strip()
                    if not re.fullmatch(r'^[a-f0-9]{32}$', csrf_token):
                        self.log("错误：无效的CSRF Token")
                        continue

                    # 生成时间戳（优先使用服务器时间）
                    try:
                        server_resp = requests.get("https://api.bilibili.com/x/server/date", timeout=3)
                        server_time = server_resp.json()["data"]
                        ts = int(datetime.strptime(server_time, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
                    except:
                        ts = int(datetime.now(timezone.utc).timestamp() * 1000)

                    # 构造请求参数
                    data = {
                        "oid": cid,
                        "type": 1,
                        "mode": dm["mode"],
                        "color": dm["color"],
                        "message": dm["content"],
                        "fontsize": dm["font_size"],
                        "pool": dm["pool_type"],
                        "csrf": csrf_token,
                        "ts": ts,
                        "rnd": random.randint(100000, 999999)
                    }

                    # 发送请求
                    try:
                        response = session.post(
                            "https://api.bilibili.com/x/v2/dm/post",
                            headers={
                                "X-CSRF-Token": csrf_token,
                                "X-Requested-With": "XMLHttpRequest",
                                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                "Referer": f"https://www.bilibili.com/video/{self.bvid_entry.get()}"
                            },
                            cookies={
                                "SESSDATA": self.sessdata_entry.get().strip(),
                                "bili_jct": csrf_token,
                                "buvid3": self.buvid3_entry.get().strip()
                            },
                            data=urlencode(data, doseq=True),
                            timeout=15
                        )
                        response.raise_for_status()
                    except requests.exceptions.RequestException as e:
                        self.log(f"请求失败: {str(e)}")
                        continue

                    # 处理响应
                    try:
                        resp_json = response.json()
                        if resp_json["code"] == 0:
                            success += 1
                            self.log(f"发送成功: {dm['content'][:15]}...")
                        else:
                            error_data = resp_json.get("data", {})
                            self.log(f"发送失败（代码{resp_json['code']}）: {resp_json.get('message')}")
                            self.log(f"问题字段: {error_data.get('fields', '未知')}")
                    except json.JSONDecodeError:
                        self.log("错误：响应解析失败")

                    # 更新进度
                    self.progress_queue.put((idx+1)/total*100)

                    # 频率控制（35-55秒）
                    delay = 35 + random.randint(0, 20)
                    if idx < total-1 and not self.stop_event.is_set():
                        start = time.time()
                        while time.time() - start < delay and not self.stop_event.is_set():
                            time.sleep(1)

            self.log(f"\n操作完成: 成功发送 {success}/{total} 条弹幕 ({success/total:.1%})")
            if self.auto_shutdown_choose:
                os.system("shutdown -s -t 0");
                exit()

        except Exception as e:
            self.log(f"严重错误: {str(e)}")
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
