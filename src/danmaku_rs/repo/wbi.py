from functools import reduce
from hashlib import md5
from typing import Dict
from urllib.parse import quote
import time

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    if len(raw) < 64:
        raise RuntimeError("WBI 密钥长度不足")
    return reduce(lambda acc, idx: acc + raw[idx], MIXIN_KEY_ENC_TAB, "")[:32]


def _clean(value: object) -> str:
    return "".join(ch for ch in str(value) if ch not in "!'()*")


def encode_query(params: Dict[str, object]) -> str:
    items = sorted((str(key), _clean(value)) for key, value in params.items())
    return "&".join(f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in items)


def sign_wbi(params: Dict[str, object], img_key: str, sub_key: str) -> str:
    signed = dict(params)
    signed["wts"] = int(time.time())
    query = encode_query(signed)
    w_rid = md5((query + mixin_key(img_key, sub_key)).encode("utf-8")).hexdigest()
    return f"{query}&w_rid={w_rid}"
