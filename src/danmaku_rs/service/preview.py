from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional
from urllib.parse import urlparse

from danmaku_rs.types import Danmaku


def _page(items: List[Danmaku]) -> bytes:
    payload = [
        {
            "t": float(dm.time),
            "text": dm.content,
            "mode": int(dm.mode),
            "color": f"#{int(dm.color) & 0xFFFFFF:06x}",
        }
        for dm in items[:2000]
    ]
    body = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"/>
<title>弹幕预览</title>
<style>
html,body {{ margin:0; height:100%; background:#101010; color:#eee; font-family:sans-serif; }}
#stage {{ position:relative; width:100%; height:75vh; overflow:hidden; background:#181818; }}
.dm {{ position:absolute; white-space:nowrap; font-size:22px; text-shadow:0 0 2px #000; pointer-events:none; }}
#bar {{ padding:12px 16px; }}
button {{ margin-right:8px; }}
</style></head>
<body>
<div id="stage"></div>
<div id="bar">
  <button id="play">播放</button>
  <button id="pause">暂停</button>
  <span id="clock">0.0s</span>
  · 本地预览 {len(payload)} 条，不会发送到 B 站
</div>
<script>
const items = {body};
const stage = document.getElementById("stage");
const clock = document.getElementById("clock");
let t = 0, last = 0, playing = false, idx = 0, lanes = [];
function spawn(dm) {{
  const el = document.createElement("div");
  el.className = "dm";
  el.textContent = dm.text;
  el.style.color = dm.color || "#ffffff";
  const lane = (lanes.length % 10);
  lanes.push(1);
  el.style.top = (12 + lane * 28) + "px";
  if (dm.mode === 4) {{ el.style.left = "40%"; el.style.bottom = "12px"; el.style.top = "auto"; }}
  else if (dm.mode === 5) {{ el.style.left = "40%"; el.style.top = "12px"; }}
  else {{ el.style.left = "100%"; }}
  stage.appendChild(el);
  const dist = stage.clientWidth + el.offsetWidth + 40;
  const dur = 7000;
  const start = performance.now();
  function tick(now) {{
    const p = Math.min(1, (now - start) / dur);
    if (dm.mode === 1 || dm.mode === 6) el.style.transform = "translateX(" + (-dist * p) + "px)";
    if (p < 1) requestAnimationFrame(tick); else el.remove();
  }}
  requestAnimationFrame(tick);
}}
function loop(now) {{
  if (!playing) {{ last = now; return; }}
  t += (now - last) / 1000;
  last = now;
  clock.textContent = t.toFixed(1) + "s";
  while (idx < items.length && items[idx].t <= t) spawn(items[idx++]);
  requestAnimationFrame(loop);
}}
document.getElementById("play").onclick = () => {{
  if (!playing) {{ playing = true; last = performance.now(); requestAnimationFrame(loop); }}
}};
document.getElementById("pause").onclick = () => {{ playing = false; }};
</script>
</body></html>"""
    return html.encode("utf-8")


class PreviewServer:
    def __init__(self):
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._items: List[Danmaku] = []
        self.port = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/" if self.port else ""

    def start(self, items: List[Danmaku], port: int = 8765) -> str:
        self._items = list(items)
        if self._httpd:
            self.stop()
        last_error = None
        for candidate in range(int(port), int(port) + 12):
            try:
                server = ThreadingHTTPServer(("127.0.0.1", candidate), self._handler())
                self._httpd = server
                self.port = candidate
                break
            except OSError as exc:
                last_error = exc
                self._httpd = None
        if not self._httpd:
            raise RuntimeError(f"无法绑定预览端口: {last_error}")
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="danmaku-preview", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(2.0)
        self._httpd = None
        self.port = 0
        self._thread = None

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                if path not in {"/", "/index.html"}:
                    self.send_error(404)
                    return
                body = _page(server._items)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        return Handler
