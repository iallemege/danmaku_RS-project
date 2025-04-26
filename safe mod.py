# security.py
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Tuple

class SecurityManager:
    """
    B站API请求安全管理系统
    功能：
    - 请求头安全管理
    - CSRF参数管理
    - 请求频率控制
    - Cookie有效性验证
    - 网络重试策略
    """
    
    def __init__(self, sessdata: str, bili_jct: str, buvid3: str):
        """
        初始化安全配置
        
        :param sessdata: 登录Cookie中的SESSDATA
        :param bili_jct: CSRF令牌
        :param buvid3: 设备标识
        """
        self.sessdata = sessdata
        self.bili_jct = bili_jct
        self.buvid3 = buvid3
        self.last_request_time = 0
        self.base_interval = 20  # 基础请求间隔（秒）

    def get_headers(self, bvid: str) -> dict:
        """
        生成安全请求头
        
        :param bvid: 目标视频BV号
        :return: 包含安全参数的请求头字典
        """
        return {
            "Referer": f"https://www.bilibili.com/video/{bvid}",
            "Origin": "https://www.bilibili.com",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    def get_secured_data(self, **kwargs) -> dict:
        """
        生成包含安全参数的请求数据
        
        :param kwargs: 业务请求参数
        :return: 包含CSRF和时间戳的安全数据字典
        """
        return {
            "csrf": self.bili_jct,
            "csrf_token": self.bili_jct,
            "ts": int(time.time() * 1000),
            **kwargs
        }

    def configure_session(self, session: requests.Session) -> None:
        """
        配置安全会话参数
        
        :param session: requests会话对象
        """
        # 设置重试策略
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["POST"]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        
        # 设置全局Cookie
        session.cookies.update({
            "SESSDATA": self.sessdata,
            "bili_jct": self.bili_jct,
            "buvid3": self.buvid3
        })

    def enforce_rate_limit(self) -> None:
        """
        执行请求频率控制
        """
        elapsed = time.time() - self.last_request_time
        if elapsed < self.base_interval:
            sleep_time = self.base_interval - elapsed
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def validate_credentials(self) -> Tuple[bool, str]:
        """
        验证凭证有效性
        
        :return: (是否有效, 错误信息)
        """
        try:
            response = requests.get(
                "https://api.bilibili.com/x/web-interface/nav",
                cookies={
                    "SESSDATA": self.sessdata,
                    "buvid3": self.buvid3
                },
                timeout=5
            )
            
            if response.status_code != 200:
                return False, f"服务器返回异常状态码：{response.status_code}"
                
            json_data = response.json()
            if json_data["code"] == 0:
                return True, ""
            return False, f"凭证无效：{json_data.get('message', '未知错误')}"
            
        except requests.exceptions.RequestException as e:
            return False, f"网络请求失败：{str(e)}"
        except Exception as e:
            return False, f"验证异常：{str(e)}"

    def safe_request(self, session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
        """
        执行安全请求封装
        
        :param session: 配置好的会话对象
        :param method: HTTP方法
        :param url: 请求URL
        :return: 响应对象
        """
        self.enforce_rate_limit()
        return session.request(method, url, **kwargs)
