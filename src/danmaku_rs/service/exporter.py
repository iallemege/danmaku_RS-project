from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, List

from danmaku_rs.types import Danmaku


def danmaku_to_xml(items: Iterable[Danmaku], chatserver: str = "chat.bilibili.com") -> str:
    root = ET.Element("i")
    ET.SubElement(root, "chatserver").text = chatserver
    ET.SubElement(root, "source").text = "danmaku_rs"
    for dm in items:
        node = ET.SubElement(
            root,
            "d",
            {"p": f"{dm.time:.3f},{dm.mode},{dm.font_size},{dm.color},0,{dm.pool},0,0"},
        )
        node.text = dm.content
    return ET.tostring(root, encoding="unicode")


def write_xml(path: str, items: List[Danmaku]) -> None:
    Path(path).write_text(danmaku_to_xml(items), encoding="utf-8")


def write_jsonl(path: str, items: List[Danmaku]) -> None:
    import json

    lines = [
        json.dumps(
            {
                "time": dm.time,
                "mode": dm.mode,
                "font_size": dm.font_size,
                "color": dm.color,
                "pool": dm.pool,
                "content": dm.content,
            },
            ensure_ascii=False,
        )
        for dm in items
    ]
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
