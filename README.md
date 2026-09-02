# 弹幕补档机 (danmaku RSP)

面向 B 站稿件的本地弹幕补档工具。正式版入口：`danmaku_restorer.py`。

```text
pip install -r requirements.txt
python danmaku_restorer.py
```

## 使用

1. 浏览器登录 B 站，F12 → Application → Cookies，复制 `SESSDATA`、`bili_jct`、`buvid3`（也可把整段 Cookie 贴进 SESSDATA 框自动拆分）。
2. 点击「检测登录」确认账号有效。
3. 填写目标 BV 号，获取分 P。
4. 导入 B 站弹幕 XML。
5. **先勾选模拟模式试跑**，确认预览无误后再真实发送。

默认间隔 8 秒/条（带 `rnd` 后平台冷却约 5 秒）。单次默认最多 200 条，请遵守账号与稿件权限。

`safedm6.0.py` / `danmaku_restorer_6.1_TEST.py` 仍可启动，会打开同一套正式版界面。Tk 旧版 `safedm5.3.py` 仅作存档。
