import os
import re
import threading
import time
import requests
import xml.etree.ElementTree as ET
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.progressbar import ProgressBar
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.core.text import LabelBase
from kivy.clock import Clock
from kivy.utils import platform
from kivy.properties import ObjectProperty, BooleanProperty

# ================ 字体配置 ================
try:
    LabelBase.register(
        name="NotoSansSC",
        fn_regular="fonts/NotoSansSC-Regular.ttf",
        fn_bold="fonts/NotoSansSC-Bold.ttf"
    )
except:
    print("字体配置失败, 请检查fonts目录和字体文件是否存在")
    exit()

# ================ 主界面 ================
class BiliToolUI(BoxLayout):
    sessdata_input = ObjectProperty(None)
    bili_jct_input = ObjectProperty(None)
    bvid_input = ObjectProperty(None)
    part_spinner = ObjectProperty(None)
    progress_bar = ObjectProperty(None)
    log_label = ObjectProperty(None)
    
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=10, padding=10)
        self.running = False
        self.xml_path = ""
        self.cid_list = []
        self._init_ui()
        
    def _init_ui(self):
        # 输入区域
        self._create_input_fields()
        # 功能按钮
        self._create_action_buttons()
        # 进度条
        self.progress_bar = ProgressBar(max=100, size_hint_y=None, height=20)
        self.add_widget(self.progress_bar)
        # 日志区域
        self._create_log_view()

    def _create_input_fields(self):
        input_grid = BoxLayout(orientation='vertical', spacing=5, size_hint_y=None, height=200)
        
        fields = [
            ("SESSDATA:", self.sessdata_input),
            ("bili_jct:", self.bili_jct_input),
            ("目标BV号:", self.bvid_input)
        ]
        
        for label_text, field in fields:
            input_grid.add_widget(Label(text=label_text, font_name=self._get_font()))
            field = TextInput(
                multiline=False, 
                font_name=self._get_font(),
                size_hint_y=None,
                height=40
            )
            input_grid.add_widget(field)
            setattr(self, label_text.replace(":", "").lower() + "_input", field)
        
        self.add_widget(input_grid)

    def _create_action_buttons(self):
        btn_box = BoxLayout(spacing=5, size_hint_y=None, height=50)
        buttons = [
            ("选择文件", self._show_file_chooser),
            ("获取分P", self.fetch_parts),
            ("开始/停止", self.toggle_restore)
        ]
        
        for text, callback in buttons:
            btn = Button(
                text=text, 
                font_name=self._get_font(),
                on_press=callback
            )
            btn_box.add_widget(btn)
        
        self.add_widget(btn_box)

    def _create_log_view(self):
        self.log_label = Label(
            text="准备就绪...", 
            font_name=self._get_font(),
            font_size=14,
            size_hint_y=None,
            halign='left',
            valign='top'
        )
        scroll = ScrollView()
        scroll.add_widget(self.log_label)
        self.add_widget(scroll)

    def _get_font(self):
        font_map = {
            "win": "msyh",
            "linux": "wqy-microhei",
            "macosx": "PingFang",
            "android": "NotoSansSC",
            "ios": "NotoSansSC"
        }
        return font_map.get(platform, "NotoSansSC")

# ================ 核心功能 ================
class BiliDanmakuApp(App):
    def build(self):
        self.title = "B站弹幕补档工具"
        return BiliToolUI()

    def log(self, message, error=False):
        color_tag = "[color=ff0000]" if error else "[color=00ff00]"
        Clock.schedule_once(
            lambda dt: setattr(
                self.root.log_label, 
                "text", 
                f"{self.root.log_label.text}\n{color_tag}{message}[/color]"
            )
        )

    def fetch_parts(self, instance):
        bvid = self.root.bvid_input.text.strip()
        if not re.match(r'^BV1[0-9A-Za-z]{9}$', bvid):
            self.log("BV号格式错误", error=True)
            return
        
        threading.Thread(target=self._fetch_parts_thread, args=(bvid,)).start()

    def _fetch_parts_thread(self, bvid):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Cookie": f"SESSDATA={self.root.sessdata_input.text.strip()};"
                        f"bili_jct={self.root.bili_jct_input.text.strip()};"
            }
            
            response = requests.get(
                f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                headers=headers,
                timeout=10
            )
            
            data = response.json()
            if data["code"] == 0:
                self.cid_list = [p["cid"] for p in data["data"]["pages"]]
                values = [f"P{idx+1}: {page['part']}" for idx, page in enumerate(data["data"]["pages"])]
                Clock.schedule_once(lambda dt: setattr(self.root.part_spinner, 'values', values))
                self.log(f"成功获取{len(values)}个分P")
            else:
                self.log(f"获取失败: {data['message']}", error=True)
        except Exception as e:
            self.log(f"获取分P失败: {str(e)}", error=True)

    def toggle_restore(self, instance):
        if self.root.running:
            self.root.running = False
            self.log("任务已停止")
        else:
            if self._validate_inputs():
                self.root.running = True
                threading.Thread(target=self.restore_process).start()

    def _validate_inputs(self):
        required = {
            "SESSDATA": self.root.sessdata_input.text.strip(),
            "bili_jct": self.root.bili_jct_input.text.strip(),
            "BV号": self.root.bvid_input.text.strip(),
            "弹幕文件": self.xml_path
        }
        
        for name, value in required.items():
            if not value:
                self.log(f"{name}不能为空", error=True)
                return False
        return True

    def restore_process(self):
        try:
            tree = ET.parse(self.xml_path)
            root = tree.getroot()
            danmaku_list = []
            
            for d in root.findall("d"):
                params = d.attrib.get("p", "").split(",")
                if len(params) >= 4:
                    try:
                        danmaku_list.append({
                            "time": float(params[0]),
                            "mode": int(params[1]),
                            "font_size": int(params[2]),
                            "color": int(params[3]),
                            "content": d.text.strip()[:100]
                        })
                    except (ValueError, IndexError):
                        continue

            total = len(danmaku_list)
            if total == 0:
                self.log("未找到有效弹幕", error=True)
                return

            success = 0
            for idx, dm in enumerate(danmaku_list):
                if not self.root.running:
                    break

                # 更新进度
                Clock.schedule_once(lambda dt, v=idx+1: setattr(self.root.progress_bar, 'value', v/total*100))
                
                # 发送逻辑
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                        "Referer": f"https://www.bilibili.com/video/{self.root.bvid_input.text.strip()}",
                        "Cookie": f"SESSDATA={self.root.sessdata_input.text.strip()};"
                                f"bili_jct={self.root.bili_jct_input.text.strip()};"
                    }
                    
                    data = {
                        "oid": self.cid_list[self.root.part_spinner.values.index(self.root.part_spinner.text)],
                        "type": 1,
                        "mode": dm["mode"],
                        "fontsize": dm["font_size"],
                        "color": dm["color"],
                        "message": dm["content"],
                        "csrf": self.root.bili_jct_input.text.strip()
                    }
                    
                    response = requests.post(
                        "https://api.bilibili.com/x/v2/dm/post",
                        headers=headers,
                        data=data,
                        timeout=15
                    )
                    
                    if response.json().get("code") == 0:
                        success += 1
                        self.log(f"发送成功: {dm['content']}")
                    else:
                        self.log(f"发送失败: {response.json().get('message', '未知错误')}", error=True)
                except Exception as e:
                    self.log(f"发送失败: {str(e)}", error=True)

                time.sleep(self.root.min_delay + random.uniform(0, 3))

            self.log(f"任务完成！成功发送 {success}/{total} 条弹幕")
        
        except Exception as e:
            self.log(f"运行错误: {str(e)}", error=True)
        finally:
            self.root.running = False

# ================ 文件选择器 ================
class FileChooserPopup(Popup):
    def __init__(self, callback, **kwargs):
        super().__init__(**kwargs)
        self.title = "选择弹幕文件"
        self.size_hint = (0.9, 0.8)
        self.callback = callback
        
        content = BoxLayout(orientation='vertical')
        self.file_chooser = FileChooserListView(filters=["*.xml"])
        content.add_widget(self.file_chooser)
        
        btn_box = BoxLayout(size_hint_y=None, height=50)
        btn_box.add_widget(Button(text="取消", on_press=self.dismiss))
        btn_box.add_widget(Button(text="选择", on_press=self._select_file))
        content.add_widget(btn_box)
        
        self.content = content

    def _select_file(self, instance):
        if self.file_chooser.selection:
            self.callback(self.file_chooser.selection[0])
            self.dismiss()

# ================ 运行应用 ================
if __name__ == "__main__":
    # 检查字体目录
    if not os.path.exists("fonts"):
        os.makedirs("fonts")
        print("请将中文字体文件放入fonts目录！")
    
    BiliDanmakuApp().run()
