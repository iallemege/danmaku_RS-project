from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.clock import Clock
from functools import partial
import requests
import xml.etree.ElementTree as ET
import time
import random
import os

class BiliConfig:
    def __init__(self):
        self.config_path = os.path.join(os.environ['ANDROID_PRIVATE'], 'config.ini')
        self.cookies = {
            'SESSDATA': '',
            'bili_jct': '',
            'buvid3': ''
        }
        
    def load(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                for line in f:
                    k, v = line.strip().split('=', 1)
                    if k in self.cookies:
                        self.cookies[k] = v
                        
    def save(self):
        with open(self.config_path, 'w') as f:
            for k, v in self.cookies.items():
                f.write(f"{k}={v}\n")

class BiliWorker:
    def __init__(self, callback):
        self.running = False
        self.callback = callback
        self.progress = 0
        self.total = 0
        
    def send_danmaku(self, bvid, xml_path, part, delay):
        try:
            config = BiliConfig()
            config.load()
            
            cid = self._get_cid(bvid, part, config)
            if not cid:
                self.callback('获取CID失败', 'error')
                return
                
            danmaku = self._parse_xml(xml_path)
            if not danmaku:
                self.callback('无效弹幕文件', 'error')
                return
                
            self.total = len(danmaku)
            success = 0
            
            for idx, dm in enumerate(danmaku):
                if not self.running:
                    break
                
                if self._send_single(cid, dm, config):
                    success += 1
                    
                self.progress = (idx + 1) / self.total * 100
                self.callback(f"进度: {idx+1}/{self.total}", 'progress')
                time.sleep(delay + random.uniform(0,5))
                
            self.callback(f"完成！成功发送 {success}/{self.total}", 'success')
            
        except Exception as e:
            self.callback(f"错误: {str(e)}", 'error')
            
    def _get_cid(self, bvid, part, config):
        # 实现同前...
        
    def _parse_xml(self, path):
        # 实现同前...
        
    def _send_single(self, cid, dm, config):
        # 实现同前...

class BiliUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.worker = None
        self.config = BiliConfig()
        self.config.load()
        self.update_fields()
        
    def update_fields(self):
        self.ids.sessdata.text = self.config.cookies['SESSDATA']
        self.ids.bili_jct.text = self.config.cookies['bili_jct']
        self.ids.buvid3.text = self.config.cookies['buvid3']
        
    def save_config(self):
        self.config.cookies = {
            'SESSDATA': self.ids.sessdata.text,
            'bili_jct': self.ids.bili_jct.text,
            'buvid3': self.ids.buvid3.text
        }
        self.config.save()
        self.show_message("配置已保存", 'success')
        
    def select_file(self):
        content = FileChooserListView(path='/sdcard/Download')
        popup = Popup(title="选择弹幕文件", content=content, size_hint=(0.9, 0.7))
        content.bind(on_submit=lambda x: self.file_selected(x.selection, popup))
        popup.open()
        
    def file_selected(self, selection, popup):
        if selection:
            self.ids.xml_path.text = selection[0]
            popup.dismiss()
            
    def start_task(self):
        if self.worker and self.worker.running:
            self.worker.running = False
            self.ids.start_btn.text = "开始"
            return
            
        params = {
            'bvid': self.ids.bvid.text,
            'xml_path': self.ids.xml_path.text,
            'part': int(self.ids.part.text),
            'delay': int(self.ids.delay.text)
        }
        
        if not all(params.values()):
            self.show_message("请填写所有字段", 'error')
            return
            
        self.worker = BiliWorker(self.update_status)
        Clock.schedule_once(lambda dt: self.worker.send_danmaku(**params))
        self.ids.start_btn.text = "停止"
        
    def update_status(self, msg, type):
        if type == 'progress':
            self.ids.progress.value = self.worker.progress
        self.ids.status.text = msg
        
    def show_message(self, text, type):
        popup = Popup(title="提示" if type=='success' else "错误",
                     content=Label(text=text),
                     size_hint=(0.8, 0.4))
        popup.open()

class BiliApp(App):
    def build(self):
        self.title = 'B站弹幕补档'
        return BiliUI()

if __name__ == '__main__':
    BiliApp().run()
