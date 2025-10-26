# core/remote_exec.py
# 该模块提供基于系统 ssh/scp 命令的封装，方便其他模块调用远端指令。

# 导入 os 模块用于处理路径与目录名。
import os
# 导入 signal 模块用于在终止日志追踪时向子进程发送信号。
import signal
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

# 定义在远端 tmux 中启动后台任务的函数。
def start_remote_job_in_tmux(
    user: str,
    host: str,
    cmd: str,
    session: str,
    log_file: str,
    keyfile: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> int:
    # 校验必要参数，缺失时立即返回错误码 1。
    if not host or not session or not cmd:
        print("[remote_exec] ❌ 缺少 host/session/cmd 参数，无法创建 tmux 会话。")
        return 1
    # 若未指定用户名，则提示用户补全配置。
    if not user:
        print("[remote_exec] ❌ 缺少 SSH 用户名，无法连接远端主机。")
        return 1
    # 确保日志文件路径存在，若为空则提示后退出。
    if not log_file:
        print("[remote_exec] ❌ 缺少日志文件路径，无法重定向输出。")
        return 1
    # 计算日志目录并在远端创建，避免 tee 写入失败。
    log_dir = os.path.dirname(log_file)
    if log_dir:
        ensure_dir_cmd = f"bash -lc {shlex.quote(f'mkdir -p {shlex.quote(log_dir)}')}"
        dir_result = run_ssh_command(host=host, user=user, keyfile=keyfile, command=ensure_dir_cmd)
        if dir_result.returncode != 0:
            print("[remote_exec] ❌ 无法在远端创建日志目录，请检查权限。")
            return dir_result.returncode
    # 构造需要注入的环境变量字典，忽略空值。
    env_vars = {k: v for k, v in (env_vars or {}).items() if v}
    # 构造实际使用的环境变量赋值字符串。
    env_assignments = " ".join(f"{key}={shlex.quote(str(value))}" for key, value in env_vars.items())
    # 构造用于展示的环境变量，敏感键名替换为 ***。
    redacted_env = {}
    for key, value in env_vars.items():
        if any(token in key.lower() for token in ["token", "secret", "key"]):
            redacted_env[key] = "***"
        else:
            redacted_env[key] = str(value)
    # 构造日志命令管道，将 stdout/stderr 通过 tee 追加到日志文件。
    pipeline = f"{env_assignments} {cmd}".strip() if env_assignments else cmd
    pipeline = f"{pipeline} 2>&1 | tee -a {shlex.quote(log_file)}"
    # 组合为 bash -lc 调用，确保加载登录环境并支持管道。
    bash_command = f"bash -lc {shlex.quote(pipeline)}"
    # 将命令封装为 tmux new-session 的参数，后台启动会话。
    tmux_command = f"tmux new-session -d -s {shlex.quote(session)} {shlex.quote(bash_command)}"
    # 构造用于展示的命令字符串，敏感值已替换。
    redacted_assignments = " ".join(f"{key}={shlex.quote(value)}" for key, value in redacted_env.items())
    redacted_pipeline = f"{redacted_assignments} {cmd}".strip() if redacted_assignments else cmd
    redacted_pipeline = f"{redacted_pipeline} 2>&1 | tee -a {log_file}"
    redacted_display = f"tmux new-session -d -s {session} \"bash -lc '{redacted_pipeline}'\""
    # 打印最终命令，便于用户复制执行。
    print(f"[remote_exec] ▶ {redacted_display}")
    # 调用 run_ssh_command 在远端执行 tmux 命令。
    result = run_ssh_command(host=host, user=user, keyfile=keyfile, command=tmux_command)
    # 根据返回码判断是否成功创建 tmux 会话。
    if result.returncode == 0:
        print(f"[remote_exec] ✅ 已创建 tmux 会话 {session}，日志写入 {log_file}。")
    else:
        print(f"[remote_exec] ❌ tmux 会话创建失败，返回码 {result.returncode}。")
    # 返回 ssh 子命令的退出码供调用方判断。
    return result.returncode

# 定义实时追踪远端日志的函数。
def tail_remote_log(
    user: str,
    host: str,
    log_path: str,
    keyfile: Optional[str] = None,
) -> int:
    # 校验输入参数，缺失时直接返回错误码。
    if not host or not log_path:
        print("[remote_exec] ❌ 缺少 host 或 log_path，无法执行 tail。")
        return 1
    # 如果未指定用户则提示补全配置。
    if not user:
        print("[remote_exec] ❌ 缺少 SSH 用户名，无法连接远端主机。")
        return 1
    # 构造 ssh 命令参数，并追加 tail 命令。
    args = list(_base_ssh_args(host, user, keyfile))
    args.append(f"tail -n +1 -f {shlex.quote(log_path)}")
    # 提示用户如何退出日志追踪。
    print(f"[remote_exec] ▶ tail -f {log_path}（按 Ctrl+C 结束）")
    # 启动子进程并实时转发输出。
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    try:
        for line in iter(process.stdout.readline, ""):
            print(line, end="")
    except KeyboardInterrupt:
        # 捕获用户中断并通知远端停止 tail。
        print("\n[remote_exec] ⏹ 停止日志追踪，正在发送中断信号……")
        process.send_signal(signal.SIGINT)
    finally:
        # 等待子进程退出以获取退出码。
        process.wait()
    # 返回子进程退出码，130 表示被 Ctrl+C 中断。
    return process.returncode

# 定义停止远端 tmux 会话的函数。
def stop_tmux_session(
    user: str,
    host: str,
    session: str,
    keyfile: Optional[str] = None,
) -> int:
    # 检查必要参数，缺失时直接返回失败。
    if not host or not session:
        print("[remote_exec] ❌ 缺少 host 或 session，无法停止 tmux。")
        return 1
    # 同样需要远端用户名才能建立连接。
    if not user:
        print("[remote_exec] ❌ 缺少 SSH 用户名，无法连接远端主机。")
        return 1
    # 构造 tmux kill-session 命令。
    command = f"tmux kill-session -t {shlex.quote(session)}"
    # 调用 run_ssh_command 执行停止操作。
    result = run_ssh_command(host=host, user=user, keyfile=keyfile, command=command)
    # 根据返回码输出友好的提示信息。
    if result.returncode == 0:
        print(f"[remote_exec] ✅ tmux 会话 {session} 已停止。")
    else:
        print(f"[remote_exec] ⚠️ 无法停止 tmux 会话 {session}，可能不存在。")
    # 返回命令退出码供调用方处理。
    return result.returncode


# 定义一个函数用于检测远端 tmux 会话是否存在。
def has_tmux_session(
    user: str,
    host: str,
    session: str,
    keyfile: Optional[str] = None,
) -> bool:
    # 若缺少必要参数，则直接返回 False。
    if not host or not session or not user:
        print("[remote_exec] ⚠️ 缺少 host/user/session，无法检测 tmux 会话。")
        return False
    # 构造 tmux has-session 命令以检测会话存在性。
    command = f"tmux has-session -t {shlex.quote(session)}"
    # 执行命令并获取返回码。
    result = run_ssh_command(host=host, user=user, keyfile=keyfile, command=command)
    # 根据返回码判断会话是否存在。
    exists = result.returncode == 0
    # 输出调试信息帮助用户了解状态。
    if exists:
        print(f"[remote_exec] ✅ 检测到 tmux 会话 {session} 正在运行。")
    else:
        print(f"[remote_exec] ℹ️ 未检测到 tmux 会话 {session}。")
    # 返回布尔结果供调用方使用。
    return exists
