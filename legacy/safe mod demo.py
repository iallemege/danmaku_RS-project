import importlib.util
from pathlib import Path
import requests

module_path = Path(__file__).with_name("safe mod.py")
spec = importlib.util.spec_from_file_location("safe_mod", module_path)
safe_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe_mod)
SecurityManager = safe_mod.SecurityManager

security = SecurityManager(
    sessdata="your_sessdata",
    bili_jct="your_bili_jct",
    buvid3="your_buvid3",
)

is_valid, msg = security.validate_credentials()
if not is_valid:
    print(f"凭证无效: {msg}")
    raise SystemExit(1)

session = requests.Session()
security.configure_session(session)

try:
    response = security.safe_request(
        session=session,
        method="POST",
        url="https://api.bilibili.com/x/v2/dm/post",
        headers=security.get_headers("BV1xx411x7xx"),
        data=security.get_secured_data(
            oid=123456,
            type=1,
            message="测试弹幕",
        ),
    )
    response.raise_for_status()
    print("请求成功")
except Exception as e:
    print(f"请求失败: {str(e)}")
