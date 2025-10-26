# core/remote_exec.py
# 该模块提供远程命令执行相关的占位实现。
# 导入 typing 中的 Optional 类型用于类型注解。
from typing import Optional

# 定义占位函数用于执行 SSH 命令。
def run_ssh_command(host: str, command: str, user: Optional[str] = None) -> None:
    # 打印提示说明目前未实际执行命令。
    print(f"[remote_exec] run_ssh_command 占位调用 host={host}, user={user}, command={command}")

# 定义占位函数用于在 tmux 中启动远程任务。
def start_remote_job_in_tmux(session_name: str, command: str) -> None:
    # 打印提示说明占位行为。
    print(f"[remote_exec] start_remote_job_in_tmux 占位调用 session={session_name}, command={command}")

# 定义占位函数用于查看远端日志。
def tail_remote_log(log_file: str, lines: int = 50) -> None:
    # 打印提示说明占位行为。
    print(f"[remote_exec] tail_remote_log 占位调用 log_file={log_file}, lines={lines}")
