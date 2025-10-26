# core/asr_runner.py
# 该模块用于封装 ASR 任务执行逻辑，目前提供占位实现。
# 导入 typing 模块中的 Dict 类型用于类型注解。
from typing import Dict

# 定义占位函数以演示 ASR 任务执行流程。
def run_asr_job(config: Dict) -> None:
    # 打印提示说明当前为占位实现。
    print(f"[asr_runner] run_asr_job 占位调用 config_keys={list(config.keys())}")
