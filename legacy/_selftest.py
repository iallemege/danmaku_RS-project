import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import danmaku_restorer as d

xml = """<?xml version="1.0"?><i>
<d p="12.5,1,25,16777215,0,0,0,0">hello</d>
<d p="1,7,25,1,0,2,0,0">skip special</d>
<d p="3,1,25,255,0,0,0,0"></d>
<d p="8,6,25,16777215,0,0,0,0">reverse becomes scroll</d>
</i>
"""
tmp = Path(tempfile.gettempdir()) / "dm_test.xml"
tmp.write_text(xml, encoding="utf-8")
items = d.parse_danmaku_xml(str(tmp))
assert len(items) == 2, items
assert items[0]["content"] == "hello"
assert items[1]["mode"] == 1
cookie = d.parse_cookie_blob("SESSDATA=aaa; bili_jct=bbb; buvid3=ccc")
assert cookie["SESSDATA"] == "aaa" and cookie["bili_jct"] == "bbb"
print("parser tests ok", items)
