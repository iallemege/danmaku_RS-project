# main.py
from security import SecurityManager
import requests

# 初始化安全模块
security = SecurityManager(
    sessdata="your_sessdata",
    bili_jct="your_bili_jct",
    buvid3="your_buvid3"
)

# 验证凭证
is_valid, msg = security.validate_credentials()
if not is_valid:
    print(f"凭证无效: {msg}")
    exit()

# 创建会话并配置
session = requests.Session()
security.configure_session(session)

# 构造安全请求
try:
    response = security.safe_request(
        session=session,
        method="POST",
        url="https://api.bilibili.com/x/v2/dm/post",
        headers=security.get_headers("BV1xx411x7xx"),
        data=security.get_secured_data(
            oid=123456,
            type=1,
            message="测试弹幕"
        )
    )
    response.raise_for_status()
    print("请求成功")
except Exception as e:
    print(f"请求失败: {str(e)}")
