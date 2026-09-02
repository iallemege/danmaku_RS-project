import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from danmaku_rs.repo.history import row_to_danmaku
from danmaku_rs.repo.secret import protect, unprotect
from danmaku_rs.service.analyzer import analyze, merge_alerts
from danmaku_rs.service.exporter import danmaku_to_xml, write_jsonl
from danmaku_rs.service.inspector import drop_duplicates, sort_by_time
from danmaku_rs.service.parser import extract_bvid, parse_cookie_blob, parse_jsonl_text, parse_xml_text
from danmaku_rs.repo.proxy import resolve_proxy
from danmaku_rs.repo.wbi import encode_query, mixin_key, sign_wbi
from danmaku_rs.service.search import directory_links
from danmaku_rs.service.seo import expand_title, score_video, tokenize
from danmaku_rs.service.sender import FingerprintGate, human_delay, prepare_work, shard_round_robin
from danmaku_rs.service.splitter import split_by_count, split_by_names
from danmaku_rs.service.validator import autofix, clip_length, scan, strip_newlines
from danmaku_rs.types import Alert, AlertLevel, Danmaku, LiveSnapshot, SenderOptions, VideoInfo


def test_parse_and_roundtrip():
    xml = """<?xml version="1.0"?><i>
    <d p="12.5,1,25,16777215,0,0,0,0">hello</d>
    <d p="8,6,25,16777215,0,0,0,0">reverse</d>
    <d p="1,7,25,1,0,2,0,0">skip</d>
    </i>"""
    items = parse_xml_text(xml)
    assert len(items) == 2
    assert items[1].mode == 1
    text = danmaku_to_xml(items)
    assert "hello" in text


def test_cookie_and_bvid():
    cookie = parse_cookie_blob("SESSDATA=aaa; bili_jct=bbb; buvid3=ccc")
    assert cookie["SESSDATA"] == "aaa"
    encoded = parse_cookie_blob("SESSDATA=aaa%2Cbbb; bili_jct=ccc")
    assert encoded["SESSDATA"] == "aaa,bbb"
    bvid, page = extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD?p=3")
    assert bvid.startswith("BV")
    assert page == 3


def test_validator_and_split():
    items = [
        Danmaku(1, 1, 25, 1, "ok"),
        Danmaku(2, 1, 25, 1, "too\nlong " + "x" * 120),
    ]
    assert scan(items)
    fixed, n = autofix(items)
    assert n >= 1
    assert all(len(dm.content) <= 100 for dm in fixed)
    chunks = split_by_count(fixed, 1)
    assert len(chunks) == len(fixed)
    named = split_by_names(fixed, ["灵梦", "魔理沙"])
    assert named[0][0] == "灵梦"


def test_jsonl(tmp_path=None):
    items = [Danmaku(1.2, 1, 25, 7, "hi")]
    folder = Path(tmpfile := tempfile.mkdtemp())
    path = folder / "a.jsonl"
    write_jsonl(str(path), items)
    assert "hi" in path.read_text(encoding="utf-8")


def test_shard_and_gate():
    items = [Danmaku(float(i), 1, 25, 1, f"m{i}") for i in range(5)]
    shards = shard_round_robin(items, 2)
    assert [len(chunk) for chunk in shards] == [3, 2]
    left = {dm.fingerprint for dm in shards[0]}
    right = {dm.fingerprint for dm in shards[1]}
    assert not (left & right)
    shifted = prepare_work(items[:1], SenderOptions(max_count=10, time_offset=2.5))
    assert shifted[0].time == 2.5
    gate = FingerprintGate()
    assert not gate.contains("a")
    gate.add("a")
    assert gate.contains("a")


def test_analyzer_alerts():
    snap = LiveSnapshot(
        ts=1,
        login_ok=False,
        login_msg="expired",
        send_success=2,
        send_failed=4,
        consecutive_fail=4,
        intercept_412=1,
        local_count=10,
        coverage=0.1,
    )
    alerts = analyze(snap)
    codes = {item.code for item in alerts}
    assert "login" in codes
    assert "http412" in codes
    assert "fail_streak" in codes
    recovered = LiveSnapshot(ts=2, login_ok=True, login_msg="ok")
    info = analyze(recovered, snap)
    assert any(item.code == "login_ok" for item in info)
    merged = merge_alerts([], alerts, cooldown=0)
    assert merged
    keep = merge_alerts(merged, [Alert(AlertLevel.WARNING, "login", "old", ts=0)], cooldown=999)
    assert any(item.level is AlertLevel.CRITICAL and item.code == "login" for item in keep)


def test_xml_recover_and_jsonl():
    broken = '<?xml version="1.0"?><i><d p="1.5,1,25,16777215,0,0,0,0">ok</d><d p="2,1,25,1,0,0,0,0">bad & raw</i>'
    items = parse_xml_text(broken)
    assert items and items[0].content == "ok"
    lines = '{"time": 3.2, "mode": 1, "font_size": 25, "color": 7, "content": "hi"}\n{"progress": 4500, "content": "ms"}'
    parsed = parse_jsonl_text(lines)
    assert parsed[0].time == 3.2
    assert abs(parsed[1].time - 4.5) < 1e-6


def test_dedup_sort_and_history_row():
    items = [
        Danmaku(2, 1, 25, 1, "b"),
        Danmaku(1, 1, 25, 1, "a"),
        Danmaku(2, 1, 25, 1, "b"),
    ]
    unique, dropped = drop_duplicates(items)
    assert dropped == 1
    assert [dm.content for dm in sort_by_time(unique)] == ["a", "b"]
    dm = row_to_danmaku({"progress_ms": 1500, "mode": 5, "font_size": 18, "color": 255, "content": "x"})
    assert dm.time == 1.5
    assert dm.mode == 5


def test_secret_roundtrip():
    text = "SESSDATA=abc; bili_jct=def"
    token = protect(text)
    assert unprotect(token) == text


def test_wbi_query_encoding():
    query = encode_query({"foo": "a b", "bar": "1"})
    assert "a%20b" in query
    assert "+" not in query.split("foo=", 1)[-1]
    assert len(mixin_key("x" * 64, "y" * 64)) == 32
    signed = sign_wbi({"web_location": "1"}, "x" * 64, "y" * 64)
    assert "w_rid=" in signed and "wts=" in signed


def test_batch_fix_and_human_delay():
    items = [Danmaku(1, 1, 25, 1, "a\nb" + "x" * 120)]
    stripped, n1 = strip_newlines(items)
    assert n1 == 1 and "\n" not in stripped[0].content
    clipped, n2 = clip_length(stripped, 100)
    assert n2 == 1 and len(clipped[0].content) == 100
    delay = human_delay(SenderOptions(delay_min=8, delay_max=11, humanize=False))
    assert 8 <= delay <= 11


def test_seo_and_directory_links():
    video = VideoInfo(1, "BV1xx411c7mD", "东方 红魔乡 补档", "up", "desc", tags=["东方", "弹幕"])
    tokens = tokenize("东方 失效")
    assert score_video(video, tokens) > score_video(VideoInfo(2, "BV2", "unrelated", tags=[]), tokens)
    assert "红魔乡" in expand_title("【失效】红魔乡")
    links = directory_links("红魔乡", "BV1xx411c7mD")
    sources = {hit.source for hit in links}
    assert "YouTube" in sources and "AcFun" in sources and "ニコニコ" in sources
    assert resolve_proxy("direct", "http://127.0.0.1:9") == ""
    assert resolve_proxy("custom", "http://127.0.0.1:9") == "http://127.0.0.1:9"


def test_qr_cookies_and_lucene():
    from danmaku_rs.repo.login import cookies_from_login
    from danmaku_rs.service.search import lucene_query

    url = "https://passport.biligame.com/x/passport-login/web/crossDomain?DedeUserID=1&SESSDATA=aaa%2Cbbb&bili_jct=csrf"
    cookies = cookies_from_login({}, url)
    assert cookies["SESSDATA"] == "aaa,bbb"
    assert cookies["bili_jct"] == "csrf"
    assert "(" not in lucene_query('foo (bar):"baz"')
    try:
        mixin_key("short", "key")
        raise AssertionError("expected short WBI key to fail")
    except RuntimeError:
        pass


def test_audit_grace_keeps_fresh_pending():
    import time as time_mod

    from danmaku_rs.service.monitor import apply_audit
    from danmaku_rs.types import DanmakuStatus

    class Hist:
        def __init__(self):
            now = time_mod.time()
            self.rows = [
                {"fingerprint": "old", "created_at": now - 400},
                {"fingerprint": "new", "created_at": now - 10},
                {"fingerprint": "seen", "created_at": now - 400},
            ]
            self.updated = []

        def pending(self, bvid, cid):
            return list(self.rows)

        def update_status(self, bvid, cid, fp, status):
            self.updated.append((fp, status))

    hist = Hist()
    result = apply_audit(hist, "BV1", 1, {"seen"}, min_age=120)
    kinds = {fp: status for fp, status in hist.updated}
    assert kinds["seen"] is DanmakuStatus.VERIFIED
    assert kinds["old"] is DanmakuStatus.LOST
    assert "new" not in kinds
    assert result["waiting"] == 1
