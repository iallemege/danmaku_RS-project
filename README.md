# 弹幕补档机 RS

窗口标题：**弹幕补档机 RS**。程序入口与发行包名称为 **DanmakuSender**。

**本仓库主页：<https://github.com/iallemege/danmaku_RS-project>**  


## 下载使用（推荐）

到 [Releases](https://github.com/iallemege/danmaku_RS-project/releases) 下载 `DanmakuSender.exe`，双击打开即可，无需安装 Python。

请先勾选模拟模式。真实发送仅用于你有权补档的稿件。

## 源码运行

```text
pip install -r requirements.txt
python danmaku_sender.py
```

也可 `python run.py`。

## 自行打包 exe

```text
pip install -r requirements.txt -r requirements-build.txt
python scripts/build_exe.py
```

生成文件：`dist/DanmakuSender.exe`。

## 主要能力

- 官方扫码登录（passport 二维码，本地绘制，不走第三方短链）
- 代理：自动探测 / 直连 / 系统 / 自定义
- 发射补档、拟人间隔、爆发休息、时间轴平移、断点续传、多账号并行
- 记忆馆检索（标题/标签加权），**失效稿跨站检索**（B 站补档、Internet Archive、YouTube/Invidious，以及 AcFun / niconico / DuckDuckGo 检索页）
- 馆藏 XML、线上抓取、本地预览服务器、校验（去换行 / 截断）、分割、实时监视核销

默认只读数据源：

- `https://raw.githubusercontent.com/TouhouGleaners/touhou-memory-archive-data/main/public/videos.json`
- `https://raw.githubusercontent.com/TouhouGleaners/danmaku/main/xml/{cid}.xml`

## 仓库结构

```text
danmaku_sender.py          官方入口
run.py                     同上
src/danmaku_rs/            程序包
  types.py / config.py
  repo/      bili · wbi · archive · history · accounts · secret · login · proxy
  service/   parser · sender · validator · splitter · inspector · monitor · analyzer · exporter · search · preview
  ui/        app · window · state · workers
tests/                     核心测试
scripts/                   PyInstaller 打包
.github/workflows/         Windows exe CI
legacy/                    旧版单文件存档
新手教程.txt
```

快捷键：`Ctrl+O` 打开 XML/JSONL，`Ctrl+Enter` 开始，`Ctrl+Z` 撤销编辑，`Ctrl+,` 设置。

Cookie 在 Windows 下用 DPAPI 加密后写入 `~/.danmaku_rs/`，不要提交到 Git。获取分 P / 抓取线上弹幕不强制登录。
