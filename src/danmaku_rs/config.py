from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

APP_NAME = "danmaku_rs"
DEFAULT_ARCHIVE_JSON = (
    "https://raw.githubusercontent.com/TouhouGleaners/"
    "touhou-memory-archive-data/main/public/videos.json"
)
DEFAULT_XML_BASE = (
    "https://raw.githubusercontent.com/TouhouGleaners/danmaku/main/xml"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
WEB_LOCATION = "1315873"
PROJECT_HOME = "https://github.com/iallemege/danmaku_RS-project"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
DM_LIST_URL = "https://api.bilibili.com/x/v1/dm/list.so"
DM_POST_URL = "https://api.bilibili.com/x/v2/dm/post"
QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
DEAD_VIEW_CODES = {-404, -403, 62002, 62004, 62012}


def data_dir() -> Path:
    path = Path.home() / f".{APP_NAME}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def history_path() -> Path:
    return data_dir() / "history.sqlite3"


def accounts_path() -> Path:
    return data_dir() / "accounts.json"


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


DEFAULTS: Dict[str, Any] = {
    "archive_json_url": DEFAULT_ARCHIVE_JSON,
    "xml_base_url": DEFAULT_XML_BASE,
    "delay_min": 8.0,
    "delay_max": 11.0,
    "burst_enabled": True,
    "burst_every": 5,
    "burst_rest": 25.0,
    "proxy": "",
    "prevent_sleep": True,
    "simulate_default": True,
    "monitor_interval": 20,
    "auto_stop_on_critical": False,
    "auto_audit": True,
    "max_count": 200,
    "max_minutes": 0,
    "proxy_mode": "auto",
    "humanize": True,
    "preview_port": 8765,
}


def load_settings() -> Dict[str, Any]:
    path = settings_path()
    data = dict(DEFAULTS)
    if path.exists():
        try:
            data.update(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return data


def save_settings(data: Dict[str, Any]) -> None:
    merged = dict(DEFAULTS)
    merged.update(data)
    settings_path().write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
