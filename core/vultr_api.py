"""Vultr API 客户端模块。"""
# 导入 os 模块以便读取环境变量中的 API 密钥。
import os
# 导入 time 模块以实现指数退避等待。
import time
# 从 typing 模块导入 Dict 和 List 类型用于类型注解。
from typing import Dict, List

# 导入 requests 库用于执行 HTTP 请求。
import requests

# 定义默认的请求超时时间（连接超时 5 秒，读取超时 30 秒）。
DEFAULT_TIMEOUT = (5, 30)
# 定义最大重试次数以满足题目要求。
MAX_RETRIES = 3


def _build_url(api_base: str, path: str) -> str:
    """Join ``api_base`` and ``path`` ensuring there is exactly one slash between them."""

    return f"{api_base.rstrip('/')}/{path.lstrip('/')}"


# 定义一个内部帮助函数负责带重试的 HTTP 请求。
def _perform_request(method: str, url: str, headers: Dict[str, str], params: Dict[str, str] | None = None) -> requests.Response:
    # 使用 for 循环在允许的重试次数内尝试发送请求。
    for attempt in range(1, MAX_RETRIES + 1):
        # 记录当前重试的尝试序号，后续用于指数退避。
        try:
            # 调用 requests.request 发送 HTTP 请求，传入方法、URL、头信息和查询参数。
            response = requests.request(method, url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)
            # 如果响应状态码为 401、429 或 5xx，则视为需要重试的错误。
            if response.status_code in {401, 429} or response.status_code >= 500:
                # 当达到最大重试次数时直接返回响应以便调用者处理。
                if attempt == MAX_RETRIES:
                    return response
                # 计算指数退避的等待时间，基础为 1 秒。
                sleep_seconds = 2 ** (attempt - 1)
                # 在等待前短暂休眠，避免触发限流。
                time.sleep(sleep_seconds)
                # 继续下一次重试。
                continue
            # 对于非重试错误或成功响应，直接返回响应。
            return response
        except requests.RequestException:
            # 捕获请求异常以进行重试，若达到最大次数则重新抛出。
            if attempt == MAX_RETRIES:
                # 将异常重新抛出给调用者处理。
                raise
            # 计算指数退避的等待时间。
            sleep_seconds = 2 ** (attempt - 1)
            # 在下一次重试前等待指定时间。
            time.sleep(sleep_seconds)
    # 理论上不会到达此处，添加返回语句满足类型检查要求。
    return response  # type: ignore[UnboundLocalError]


# 定义函数用于列出所有 Vultr 实例。
def list_instances(api_base: str) -> List[Dict]:
    # 从环境变量中读取 Vultr API 密钥。
    api_key = os.environ.get("VULTR_API_KEY", "")
    # 如果没有提供密钥，则抛出 ValueError 以便上层提示用户。
    if not api_key:
        raise ValueError("VULTR_API_KEY is not set")
    # 构造请求头，包含授权信息和内容类型。
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # 构造实例列表接口的 URL。
    url = _build_url(api_base, "instances")
    # 初始化列表用于保存所有实例信息。
    instances: List[Dict] = []
    # 初始化 cursor 为 None，表示从第一页开始。
    cursor: str | None = None
    # 使用 while 循环处理分页。
    while True:
        # 构造查询参数，当 cursor 存在时带上它。
        params = {"cursor": cursor} if cursor else None
        # 调用内部请求函数执行 HTTP 请求。
        response = _perform_request("GET", url, headers, params)
        # 如果响应状态码不是 200，则抛出异常供上层处理。
        if response.status_code != 200:
            raise RuntimeError(f"Failed to list instances: {response.status_code} {response.text}")
        # 将响应解析为 JSON 数据。
        data = response.json()
        # 从 JSON 数据中提取实例列表，若不存在则使用空列表。
        page_instances = data.get("instances", [])
        # 遍历页面中的每个实例。
        for item in page_instances:
            # 按要求提取关键字段并构造新的字典。
            instances.append(
                {
                    "id": item.get("id", ""),
                    "label": item.get("label", ""),
                    "main_ip": item.get("main_ip", ""),
                    "status": item.get("status", ""),
                    "power_status": item.get("power_status", ""),
                    "region": item.get("region", ""),
                    "plan": item.get("plan", ""),
                    "os": item.get("os", ""),
                    "ram": item.get("ram", 0),
                    "disk": item.get("disk", 0),
                    "vcpu_count": item.get("vcpu_count", 0),
                    "created_at": item.get("created_at", ""),
                }
            )
        # 从 meta 信息中读取下一页的 cursor。
        meta = data.get("meta", {})
        links = meta.get("links", {})
        cursor = links.get("next")
        # 如果没有下一页则跳出循环。
        if not cursor:
            break
    # 返回收集到的所有实例。
    return instances


# 定义函数用于获取指定实例的详细信息。
def get_instance_info(api_base: str, instance_id: str) -> Dict:
    # 从环境变量中读取 Vultr API 密钥。
    api_key = os.environ.get("VULTR_API_KEY", "")
    # 如果密钥缺失则抛出异常提醒调用方。
    if not api_key:
        raise ValueError("VULTR_API_KEY is not set")
    # 构造请求头以携带授权信息。
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # 构造实例详情接口的 URL。
    url = _build_url(api_base, f"instances/{instance_id}")
    # 调用内部请求函数获取实例详情。
    response = _perform_request("GET", url, headers)
    # 如果响应状态码不是 200，则抛出异常。
    if response.status_code != 200:
        raise RuntimeError(f"Failed to get instance info: {response.status_code} {response.text}")
    # 返回解析后的 JSON 数据中的实例信息。
    return response.json().get("instance", {})
