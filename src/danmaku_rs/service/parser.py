from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from danmaku_rs.types import SENDABLE_MODES, Danmaku

_D_TAG = re.compile(r"<d\s+p=\"([^\"]+)\"[^>]*>(.*?)</d>", re.I | re.S)


def parse_cookie_blob(raw: str) -> dict:
    found = {}
    for part in raw.replace("\n", ";").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key in {"SESSDATA", "bili_jct", "buvid3", "DedeUserID"}:
            found[key] = unquote(value.strip())
    return found


def extract_bvid(text: str) -> Tuple[str, int]:
    """Return (bvid, page). Page is 1 if not specified."""
    match = re.search(r"(BV[0-9A-Za-z]{10,})", text.strip())
    bvid = match.group(1) if match else text.strip()
    page = 1
    try:
        parsed = urlparse(text)
        page = int((parse_qs(parsed.query).get("p") or ["1"])[0])
    except (TypeError, ValueError):
        page = 1
    return bvid, max(page, 1)


def decode_xml_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_xml_text(text: str) -> List[Danmaku]:
    text = (text or "").lstrip("\ufeff")
    try:
        root = ET.fromstring(text)
        items = [dm for dm in (_from_elem(elem) for elem in root.iter("d")) if dm]
        if items:
            return items
    except ET.ParseError:
        pass
    return _parse_d_tags(text)


def parse_xml_file(path: str) -> List[Danmaku]:
    return parse_xml_text(decode_xml_bytes(Path(path).read_bytes()))


def parse_jsonl_text(text: str) -> List[Danmaku]:
    items: List[Danmaku] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        content = str(obj.get("content") or obj.get("text") or "")
        if not content.strip():
            continue
        if "time" in obj:
            stamp = float(obj.get("time") or 0)
        else:
            stamp = float(obj.get("progress") or 0) / 1000.0
        items.append(
            Danmaku(
                time=max(0.0, stamp),
                mode=int(obj.get("mode") or 1),
                font_size=int(obj.get("font_size") or obj.get("fontsize") or 25),
                color=int(obj.get("color") or 16777215),
                content=content,
                pool=int(obj.get("pool") or 0),
            )
        )
    return items


def parse_jsonl_file(path: str) -> List[Danmaku]:
    return parse_jsonl_text(Path(path).read_text(encoding="utf-8-sig"))


def _parse_d_tags(text: str) -> List[Danmaku]:
    items: List[Danmaku] = []
    for params, body in _D_TAG.findall(text):
        content = re.sub(r"<[^>]+>", "", body).replace("\r", "")
        dm = _from_params(params.split(","), content)
        if dm:
            items.append(dm)
    return items


def _from_elem(elem: ET.Element) -> Danmaku | None:
    return _from_params((elem.attrib.get("p") or "").split(","), (elem.text or "").replace("\r", ""))


def _from_params(params: List[str], content: str) -> Danmaku | None:
    if len(params) < 4:
        return None
    if not content.strip():
        return None
    try:
        time_sec = float(params[0])
        mode = int(float(params[1]))
        font_size = int(float(params[2]))
        color = int(float(str(params[3]).split(".")[0]))
        pool = int(float(params[5])) if len(params) > 5 else 0
    except (TypeError, ValueError):
        return None
    if mode == 6:
        mode = 1
    if mode not in SENDABLE_MODES:
        return None
    if not 0 <= color <= 0xFFFFFF:
        color = 16777215
    if font_size not in {12, 16, 18, 25, 36}:
        font_size = 25
    if pool not in {0, 1}:
        pool = 0
    return Danmaku(
        time=max(0.0, time_sec),
        mode=mode,
        font_size=font_size,
        color=color,
        content=content,
        pool=pool,
    )
