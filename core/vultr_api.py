# core/vultr_api.py
# 该模块负责与 Vultr API 交互，当前实现占位逻辑返回示例数据。
# 导入 typing 中的 List 和 Dict 类型用于类型注解。
from typing import List, Dict

# 定义列出实例的占位函数。
def list_instances() -> List[Dict]:
    # 输出提示说明该函数目前为示例实现。
    print("[vultr_api] list_instances 被调用，返回示例数据。")
    # 构造示例实例列表。
    sample_instances: List[Dict] = [
        {"id": "instance-001", "name": "示例节点 A", "status": "active"},
        {"id": "instance-002", "name": "示例节点 B", "status": "stopped"},
    ]
    # 返回示例数据。
    return sample_instances

# 定义获取单个实例信息的占位函数。
def get_instance_info(instance_id: str) -> Dict:
    # 输出提示显示传入的实例 ID。
    print(f"[vultr_api] get_instance_info 被调用，实例 ID: {instance_id}")
    # 返回示例的实例详情。
    return {
        "id": instance_id,
        "name": "示例节点",
        "status": "active",
        "region": "sjc",
    }
