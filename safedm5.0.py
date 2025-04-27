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
import uuid
from queue import Queue
from bilibili_api import video, Credential
from datetime import datetime, timezone
from urllib.parse import urlencode, quote_plus

class BiliDanmakuRestorer:
    auto_shutdown_choose = False
    
    def __init__(self, root):
        self.root = root
        root.title("B站弹幕补档工具 正式版 v5.0")
        root.geometry("1100x900")
        self.color_format = tk.IntVar(value=0)
        self.xml_path = tk.StringVar()
        self.cid_list = []
        self.pages = []
        self.create_widgets()
        self.running = False
        self.stop_event = threading.Event()
        self.log_queue = Queue()
        self.progress_queue = Queue()
        self.root.after(100, self.process_queues)

    def create_widgets(self):
        config_frame = ttk.LabelFrame(self.root, text="配置参数")
        config_frame.pack(pady=5, padx=10, fill="x")

        cookie_labels = ["SESSDATA:", "bili_jct:", "buvid3:"]
        self.sessdata_entry = ttk.Entry(config_frame, width=55)
        self.bili_jct_entry = ttk.Entry(config_frame, width=55)
        self.buvid3_entry = ttk.Entry(config_frame, width=55)
        
        for i, text in enumerate(cookie_labels):
            ttk.Label(config_frame, text=text).grid(row=i, column=0, padx=5, pady=2, sticky="e")
            [self.sessdata_entry, self.bili_jct_entry, self.buvid3_entry][i].grid(row=i, column=1, padx=5, sticky="w", columnspan=2)

        ttk.Label(config_frame, text="目标BV号:").grid(row=3, column=0, padx=5, pady=2, sticky="e")
        self.bvid_entry = ttk.Entry(config_frame, width=35)
        self.bvid_entry.grid(row=3, column=1, padx=5, sticky="w")

        ttk.Label(config_frame, text="视频分P:").grid(row=3, column=3, padx=5, sticky="e")
        self.part_combobox = ttk.Combobox(config_frame, state="readonly", width=25)
        self.part_combobox.grid(row=3, column=4, padx=5, sticky="w")
        ttk.Button(config_frame, text="获取分P", command=self.fetch_parts).grid(row=3, column=5, padx=5)

        ttk.Label(config_frame, text="弹幕文件:").grid(row=4, column=0, padx=5, pady=2, sticky="e")
        ttk.Entry(config_frame, textvariable=self.xml_path, width=45).grid(row=4, column=1, padx=5, sticky="w")
        ttk.Button(config_frame, text="选择文件", command=self.select_xml).grid(row=4, column=2, padx=5)

        color_frame = ttk.Frame(config_frame)
        color_frame.grid(row=5, column=0, columnspan=3, pady=5, sticky="w")
        ttk.Label(color_frame, text="颜色格式:").pack(side="left")
        ttk.Radiobutton(color_frame, text="十进制", variable=self.color_format, value=0).pack(side="left", padx=5)
        ttk.Radiobutton(color_frame, text="十六进制", variable=self.color_format, value=1).pack(side="left")

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

        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(padx=10, pady=5, fill="both", expand=True)
        self.log_area = scrolledtext.ScrolledText(log_frame, height=22)
        self.log_area.pack(fill="both", expand=True)

    def process_queues(self):
        while not self.log_queue.empty():
            self.log_area.insert("end", self.log_queue.get())
            self.log_area.see("end")
        while not self.progress_queue.empty():
            self.progress["value"] = self.progress_queue.get()
        self.root.after(100, self.process_queues)

    def log(self, message):
        self.log_queue.put(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

    def clear_log(self):
        self.log_area.delete("1.0", "end")

    def about_us(self):
        msg = (
            "==============================================================================================================\n"
            "        B站弹幕补档工具 是一个开源的弹幕补档工具，基于Bilibili-API实现。遵从MIT开源协议。\n"
            "        项目地址：https://github.com/safedm/safedm\n"
            "        作者: iallemege\n"
            "        主要贡献者: mlfkhf\n\n"
            "        本工具最初用于【幻想万华镜补档项目】，现开源。\n"
            "=============================================================================================================="
        )
        self.log(msg)

    def fetch_parts(self):
        if not self.bvid_entry.get().strip():
            self.log("请先输入BV号")
            return
        
        video_info = self.get_video_info_sync()
        if video_info and 'pages' in video_info:
            self.pages = video_info['pages']
            display_parts = [f"P{page['page']}: {page['part']}" for page in self.pages]
            self.part_combobox['values'] = display_parts
            self.cid_list = [page['cid'] for page in self.pages]
            if self.pages:
                self.part_combobox.current(0)
                self.log(f"发现{len(self.pages)}个分P")
            else:
                self.log("未找到分P信息")
        else:
            self.log("获取分P信息失败")

    def select_xml(self):
        if path := filedialog.askopenfilename(filetypes=[("XML Files", "*.xml")]):
            self.xml_path.set(path)

    def validate_inputs(self):
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
        if not self.part_combobox['values']:
            self.log("请先获取视频分P信息")
            return False
        if self.part_combobox.current() == -1:
            self.log("请选择要补档的分P")
            return False
        return True

    def toggle_restore(self):
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
        try:
            clean_color = str(raw_color).strip().lower().replace('0x', '').replace('#', '')
            if self.color_format.get() == 1:
                if len(clean_color) != 6 or not re.match(r'^[0-9a-f]{6}$', clean_color):
                    raise ValueError("无效的十六进制颜色")
                return int(clean_color, 16)
            if '.' in clean_color:
                return int(float(clean_color))
            if not clean_color.isdigit():
                raise ValueError("非数字格式")
            return int(clean_color)
        except Exception as e:
            raise ValueError(f"颜色解析失败: {str(e)}")

    def enhanced_validate(self, dm):
        errors = []
        if not (0 <= dm['time'] <= 86400):
            errors.append(f"时间戳越界: {dm['time']}")
        if dm['mode'] not in {1, 4, 5, 6, 7}:
            errors.append(f"非法模式: {dm['mode']}")
        if not (0x000000 <= dm['color'] <= 0xFFFFFF):
            errors.append(f"颜色值越界: 0x{dm['color']:06x}")
        dm['content'] = ''.join(c for c in dm['content'] if c.isprintable()).strip()
        if not (0 < len(dm['content']) <= 100):
            errors.append("弹幕长度无效")
        if not (12 <= dm['font_size'] <= 36):
            errors.append(f"字体大小越界: {dm['font_size']}")
        return errors

    def parse_danmaku(self):
        try:
            tree = ET.parse(self.xml_path.get())
            danmaku_list = []
            for d in tree.findall('d'):
                try:
                    params = d.attrib['p'].split(',')
                    if len(params) < 9:
                        continue
                    dm_data = {
                        'time': float(params[0]),
                        'mode': int(params[1]),
                        'font_size': int(params[2]),
                        'color': self.parse_color(params[3].split('.')[0]),
                        'pool_type': int(params[5]),
                        'content': d.text.strip()
                    }
                    if errors := self.enhanced_validate(dm_data):
                        raise ValueError(" | ".join(errors))
                    danmaku_list.append(dm_data)
                except Exception as e:
                    self.log(f"弹幕过滤: {str(e)}")
            return danmaku_list[:500]
        except Exception as e:
            self.log(f"XML解析失败: {str(e)}")
            return None

    def get_server_timestamp(self, session):
        for _ in range(3):
            try:
                response = session.get("https://api.bilibili.com/x/server/date", timeout=3)
                server_time = response.json()["data"]
                return int(datetime.strptime(server_time, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
            except:
                continue
        return None

    def diagnose_error(self, resp_json):
        code = resp_json.get("code", -1)
        message = resp_json.get("message", "")
        data = resp_json.get("data", {})
        diagnosis = {
            -400: [
                ("oid" in message, "CID无效或视频不可用"),
                ("csrf" in message, "CSRF Token验证失败"),
                ("timestamp" in message, "时间戳不同步"),
                ("filter" in message, "触发敏感词过滤"),
                (data.get("message") == "啥都没有啊", "内容编码错误")
            ],
            -101: [True, "认证信息失效"],
            -111: [True, "CSRF Token格式错误"],
            -404: [True, "视频不存在"],
            -509: [True, "触发频率限制"]
        }
        for condition, reason in diagnosis.get(code, []):
            if condition is True or (callable(condition) and condition()):
                return f"{message} ({reason})"
        return f"{message} (未知错误代码: {code})"

    def restore_process(self):
        try:
            for _ in range(3):
                if self.check_credential_valid():
                    break
                time.sleep(5)
            else:
                self.log("错误：凭证验证失败")
                return

            selected_index = self.part_combobox.current()
            if selected_index == -1 or not self.cid_list:
                self.log("错误：无效的分P选择")
                return
            cid = self.cid_list[selected_index]

            danmaku_list = self.parse_danmaku()
            if not danmaku_list:
                self.log("错误：无有效弹幕")
                return
            
            total = len(danmaku_list)
            success = 0
            
            with requests.Session() as session:
                session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "X-Request-Id": str(uuid.uuid4()),
                    "X-Client-BinTrace": "1",
                    "Accept-Encoding": "gzip, deflate, br"
                })

                base_ts = self.get_server_timestamp(session) or int(datetime.now(timezone.utc).astimezone().timestamp() * 1000)

                for idx, dm in enumerate(danmaku_list):
                    if self.stop_event.is_set():
                        break

                    try:
                        safe_content = quote_plus(dm["content"], safe='')
                        data = {
                            "oid": cid,
                            "type": 1,
                            "mode": dm["mode"],
                            "color": dm["color"],
                            "message": safe_content,
                            "fontsize": dm["font_size"],
                            "pool": dm["pool_type"],
                            "csrf": self.bili_jct_entry.get().strip(),
                            "ts": base_ts + idx * 1000,
                            "rnd": random.randint(100000, 999999)
                        }
                    except Exception as e:
                        self.log(f"参数错误: {str(e)}")
                        continue

                    for attempt in range(3):
                        try:
                            response = session.post(
                                "https://api.bilibili.com/x/v2/dm/post",
                                headers={
                                    "X-CSRF-Token": data["csrf"],
                                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                    "Referer": f"https://www.bilibili.com/video/{self.bvid_entry.get()}"
                                },
                                cookies={
                                    "SESSDATA": self.sessdata_entry.get().strip(),
                                    "bili_jct": data["csrf"],
                                    "buvid3": self.buvid3_entry.get().strip()
                                },
                                data=urlencode(data, doseq=True),
                                timeout=15
                            )
                            response.raise_for_status()
                            break
                        except Exception as e:
                            if attempt == 2:
                                raise
                            time.sleep(5 * (attempt + 1))

                    try:
                        resp_json = response.json()
                        if resp_json["code"] == 0:
                            success += 1
                            self.log(f"发送成功: {dm['content'][:15]}...")
                        else:
                            error_info = self.diagnose_error(resp_json)
                            self.log(f"发送失败: {error_info}")
                    except json.JSONDecodeError:
                        self.log("错误：响应解析失败")

                    self.progress_queue.put((idx + 1) / total * 100)

                    delay = 35 + random.randint(0, 20) + 5 * (idx % 10)
                    if idx < total - 1:
                        start = time.time()
                        while time.time() - start < delay and not self.stop_event.is_set():
                            time.sleep(max(0.5, delay - (time.time() - start)))

            self.log(f"\n完成：成功发送 {success}/{total} 条弹幕")
            if self.auto_shutdown_choose and success > 0:
                os.system("shutdown -s -t 60")

        except Exception as e:
            self.log(f"严重错误: {str(e)}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.running = False
            self.start_btn.config(text="开始补档")
            self.progress_queue.put(100)

    def check_credential_valid(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            credential = Credential(
                sessdata=self.sessdata_entry.get(),
                bili_jct=self.bili_jct_entry.get(),
                buvid3=self.buvid3_entry.get()
            )
            return loop.run_until_complete(credential.check_valid())
        except Exception as e:
            self.log(f"凭证验证失败: {str(e)}")
            return False
        finally:
            loop.close()

if __name__ == "__main__":
    root = tk.Tk()
    app = BiliDanmakuRestorer(root)
    root.mainloop()
