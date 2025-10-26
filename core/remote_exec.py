# core/remote_exec.py
# 该模块提供基于系统 ssh/scp 命令的封装，方便其他模块调用远端指令。

# 导入 subprocess 模块以调用外部命令并捕获输出。
import subprocess
# 导入 shlex 模块用于在记录日志时安全拼接命令。
import shlex
# 导入 typing 模块中的 Dict、Optional、Sequence 类型用于类型注解。
from typing import Dict, Optional, Sequence

# 定义一个辅助函数，用于组装 ssh 目标字符串。
def _build_target(host: str, user: Optional[str]) -> str:
    # 如果提供了用户名，则拼接成 user@host 形式，否则仅返回主机名。
    return f"{user}@{host}" if user else host

# 定义一个辅助函数，用于构建 ssh 命令的公共参数列表。
def _base_ssh_args(host: str, user: Optional[str], keyfile: Optional[str]) -> Sequence[str]:
    # 从基础命令 ssh 开始，并启用 BatchMode 避免交互式提示。
    args = ["ssh", "-o", "BatchMode=yes"]
    # 若提供了私钥路径，则加入 -i 参数。
    if keyfile:
        args.extend(["-i", keyfile])
    # 拼接目标主机字符串。
    args.append(_build_target(host, user))
    # 返回最终的参数序列。
    return args

# 定义一个辅助函数，用于在终端实时打印命令输出。
def _stream_process(process: subprocess.Popen) -> str:
    # 初始化一个列表用于收集输出行，稍后拼接成字符串返回。
    collected_lines = []
    # 持续读取子进程输出直到结束。
    for line in iter(process.stdout.readline, ""):
        # 将读取到的行立即打印到本地终端，保持实时反馈。
        print(line, end="")
        # 同时将该行保存到列表中，以便调用方进一步解析。
        collected_lines.append(line)
    # 等待子进程结束并获取退出码。
    process.wait()
    # 将所有行拼接成单个字符串返回。
    return "".join(collected_lines)

# 定义运行远程命令的主函数，支持注入环境变量。
def run_ssh_command(host: str, command: str, user: Optional[str] = None,
                    keyfile: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    # 构建 ssh 基础命令参数。
    args = list(_base_ssh_args(host, user, keyfile))
    # 如果存在需要注入的环境变量，则在远端命令前增加键值对声明。
    if env:
        # 使用列表推导确保所有值都转换为字符串并进行 shell 安全转义。
        exports = [f"{key}={shlex.quote(str(value))}" for key, value in env.items() if value is not None]
        # 将环境变量与实际命令拼接在一起。
        remote_command = " ".join(exports + [command]) if exports else command
    else:
        # 如果没有环境变量，则直接使用传入的命令。
        remote_command = command
    # 将远端命令追加到 ssh 参数列表中。
    args.append(remote_command)
    # 启动子进程并开启文本模式，以便逐行读取输出。
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    # 通过辅助函数实时读取输出并收集。
    stdout_data = _stream_process(process)
    # 构造 CompletedProcess 对象以封装执行结果。
    return subprocess.CompletedProcess(args=args, returncode=process.returncode, stdout=stdout_data, stderr=None)

# 定义一个辅助函数用于将本地文件上传到远端主机。
def scp_upload(local_path: str, remote_path: str, host: str, user: Optional[str] = None,
               keyfile: Optional[str] = None) -> None:
    # 以 scp 为基础命令并启用 -p 参数保留文件时间戳。
    args = ["scp", "-p"]
    # 如果提供了私钥路径，则加入 -i 选项。
    if keyfile:
        args.extend(["-i", keyfile])
    # 组装目标主机字符串。
    remote_target = f"{_build_target(host, user)}:{remote_path}"
    # 将本地文件路径和远端路径依次加入参数列表。
    args.extend([local_path, remote_target])
    # 执行 scp 命令并在失败时抛出异常。
    subprocess.run(args, check=True)

# 以下函数仍然保留占位实现，以便后续阶段扩展具体逻辑。
def start_remote_job_in_tmux(session_name: str, command: str) -> None:
    # 打印提示说明当前函数尚未实现真实功能。
    print(f"[remote_exec] start_remote_job_in_tmux 占位调用 session={session_name}, command={command}")

# 保留实时查看日志的占位实现。
def tail_remote_log(log_file: str, lines: int = 50) -> None:
    # 打印提示说明当前函数尚未实现真实功能。
    print(f"[remote_exec] tail_remote_log 占位调用 log_file={log_file}, lines={lines}")
