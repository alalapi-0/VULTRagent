# core/remote_exec.py
# 该模块提供基于系统 ssh/scp 命令的封装，方便其他模块调用远端指令。

# 导入 json 模块用于读取状态文件以确定实例信息。
import json
# 导入 os 模块用于处理路径与目录名。
import os
# 导入 platform 模块以检测操作系统类型并提供提示。
import platform
# 导入 signal 模块用于在终止日志追踪时向子进程发送信号。
import signal
# 导入 subprocess 模块以调用外部命令并捕获输出。
import subprocess
# 导入 threading 模块用于在后台执行周期性 rsync。
import threading
# 导入 time 模块用于线程休眠控制。
import time
# 导入 datetime.datetime 用于创建时间戳目录。
from datetime import datetime
# 导入 pathlib.Path 以便跨平台构建路径。
from pathlib import Path
# 导入 shlex 模块用于在记录日志时安全拼接命令。
import shlex
# 导入 typing 模块中的 Dict、Optional、Sequence 类型用于类型注解。
from typing import Dict, Optional, Sequence

from core.env_check import detect_local_rsync


def _remote_command_available(ssh_args: Sequence[str], command: str) -> bool:
    """检测远端是否存在指定命令。"""

    check_cmd = list(ssh_args) + ["command", "-v", command]
    try:
        result = subprocess.run(check_cmd, capture_output=True, text=True)
    except Exception as exc:  # noqa: BLE001 - 捕获所有异常用于输出日志
        print(f"[ERROR] 检测远端命令 {command} 时失败：{exc}")
        return False
    return result.returncode == 0


def _attempt_remote_install(ssh_args: Sequence[str]) -> bool:
    """尝试使用常见包管理器在远端安装 rsync。"""

    install_sequences = [
        (
            "apt",
            [
                "bash",
                "-lc",
                "sudo apt update -y && sudo apt install -y rsync",
            ],
        ),
        (
            "apt-get",
            [
                "bash",
                "-lc",
                "sudo apt-get update -y && sudo apt-get install -y rsync",
            ],
        ),
        (
            "yum",
            [
                "bash",
                "-lc",
                "sudo yum install -y rsync",
            ],
        ),
        (
            "dnf",
            [
                "bash",
                "-lc",
                "sudo dnf install -y rsync",
            ],
        ),
        (
            "pacman",
            [
                "bash",
                "-lc",
                "sudo pacman -Sy --noconfirm rsync",
            ],
        ),
        (
            "apk",
            [
                "bash",
                "-lc",
                "sudo apk add rsync",
            ],
        ),
    ]

    for manager, install_cmd in install_sequences:
        if not _remote_command_available(ssh_args, manager):
            continue
        print(f"[INSTALL] 检测到远端包管理器 {manager}，尝试安装 rsync …")
        try:
            subprocess.run(list(ssh_args) + install_cmd, check=True)
        except subprocess.CalledProcessError as exc:
            print(f"[FAIL] 通过 {manager} 安装 rsync 失败，返回码 {exc.returncode}。")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] 执行 {manager} 安装命令时出错：{exc}")
            continue

        if _remote_command_available(ssh_args, "rsync"):
            version_cmd = list(ssh_args) + ["rsync", "--version"]
            try:
                version_result = subprocess.run(version_cmd, capture_output=True, text=True)
                version_line = (
                    version_result.stdout.splitlines()[0]
                    if version_result.stdout
                    else "rsync"
                )
            except Exception:  # noqa: BLE001 - 若读取版本失败，使用默认描述
                version_line = "rsync"
            print(f"[OK] 已在远端安装 rsync：{version_line}")
            return True
        print(f"[WARN] 使用 {manager} 安装后仍未检测到 rsync，尝试下一个方案。")

    return False


def install_remote_rsync(user: str, host: str, keyfile: Optional[str] = None) -> bool:
    """通过 SSH 检测并在必要时安装远端 rsync。"""

    # 若缺少主机或用户名信息，则无法继续执行。
    if not host:
        print("[ERROR] 未提供远端主机地址，无法检测 rsync。")
        return False
    if not user:
        print("[ERROR] 未提供远端用户名，无法检测 rsync。")
        return False

    # 构建 ssh 基础参数列表，后续命令在此基础上附加远端指令。
    ssh_args = ["ssh"]
    # 当提供私钥路径时添加 -i 参数。
    if keyfile:
        ssh_args.extend(["-i", keyfile])
    # 拼接目标主机字符串。
    ssh_args.append(f"{user}@{host}")

    # 打印检测提示，保持与其它日志格式一致。
    print("[CHECK] 正在检测远端 rsync ...")
    # 若命令返回码为 0，表示远端已安装 rsync。
    if _remote_command_available(ssh_args, "rsync"):
        # 进一步查询远端 rsync 版本并输出。
        version_cmd = ssh_args + ["rsync", "--version"]
        try:
            version_result = subprocess.run(version_cmd, capture_output=True, text=True)
            version_line = version_result.stdout.splitlines()[0] if version_result.stdout else "rsync"
        except Exception:
            version_line = "rsync"
        print(f"[OK] 远端 rsync 已存在：{version_line}")
        return True

    print("[WARN] 远端未检测到 rsync，尝试自动安装 …")

    if _attempt_remote_install(ssh_args):
        return True

    print("[FAIL] 已尝试所有自动方案，仍未能在远端安装 rsync。")
    print("[HINT] 请手动连接远端执行安装命令后重试。")
    return False

# 定义一个辅助函数，用于组装 ssh 目标字符串。
def _build_target(host: str, user: Optional[str]) -> str:
    # 如果提供了用户名，则拼接成 user@host 形式，否则仅返回主机名。
    return f"{user}@{host}" if user else host

# 定义一个辅助函数，用于构建 ssh 命令的公共参数列表。
def _base_ssh_args(host: str, user: Optional[str], keyfile: Optional[str]) -> Sequence[str]:
    # 从基础命令 ssh 开始，并启用 BatchMode 避免交互式提示。
    args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
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
    # 强制以 UTF-8 解码远端输出，避免在 Windows 下因为默认编码 (如 gbk)
    # 无法处理部分字符而导致 UnicodeDecodeError。
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
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
    args = [
        "scp",
        "-p",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
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
    project_dir: str,
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
    # 校验项目目录，缺失时无法在远端进入正确目录执行。
    if not project_dir:
        print("[remote_exec] ❌ 缺少项目目录，无法构建远端执行命令。")
        return 1
    # 如果目标 tmux 会话已存在，则尝试提前停止，避免重复创建报错。
    if has_tmux_session(user=user, host=host, session=session, keyfile=keyfile):
        print(
            f"[remote_exec] ℹ️ tmux 会话 {session} 已存在，正在尝试停止以便重新创建。"
        )
        stop_code = stop_tmux_session(
            user=user, host=host, session=session, keyfile=keyfile
        )
        if stop_code != 0:
            print(
                f"[remote_exec] ❌ 无法停止已存在的 tmux 会话 {session}，终止启动流程。"
            )
            return stop_code
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
    # 组合注入环境变量后的真实命令，空值自动忽略。
    command_with_env = f"{env_assignments} {cmd}".strip() if env_assignments else cmd
    # 构造在日志中展示的命令，敏感变量已替换。
    redacted_assignments = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in redacted_env.items()
    )
    # 将敏感信息替换后的命令用于本地提示。
    redacted_command = (
        f"{redacted_assignments} {cmd}".strip() if redacted_assignments else cmd
    )
    # 为日志记录准备一份转义后的命令文本，避免双引号导致语法错误。
    escaped_for_log = command_with_env.replace("\"", r"\\\"")
    # 对远端日志路径进行 shell 转义，避免空格导致失败。
    quoted_log_file = shlex.quote(log_file)
    # 对项目目录进行转义，确保 cd 指令安全。
    quoted_project_dir = shlex.quote(project_dir)
    # 构造记录开始时间与命令的 echo 语句。
    start_line = (
        f'echo "[START] $(date -Is) session={session} cmd={escaped_for_log}" | '
        f"tee -a {quoted_log_file}"
    )
    # 构造执行主体，将 stdout/stderr 合并并通过 tee 追加到日志。
    pipeline = (
        f"{command_with_env} 2>&1 | tee -a {quoted_log_file}"
    )
    # 构造结束语句，记录退出码并同样写入日志。
    end_line = (
        f'echo "[END] $(date -Is) exit_code=${{exit_code}}" | tee -a {quoted_log_file}'
    )
    # 组合完整的 bash 片段，确保在项目目录下运行并维护退出码。
    bash_body = (
        f"cd {quoted_project_dir} && {{ {start_line}; {pipeline}; "
        f"exit_code=${{PIPESTATUS[0]}}; {end_line}; exit $exit_code; }}"
    )
    # 使用 bash -lc 执行组合后的脚本片段。
    bash_command = f"bash -lc {shlex.quote(bash_body)}"
    # 将命令封装为 tmux new-session 的参数，后台启动会话。
    tmux_command = f"tmux new-session -d -s {shlex.quote(session)} {shlex.quote(bash_command)}"
    # 构造敏感信息已替换的展示命令，便于用户排查问题。
    redacted_pipeline = f"{redacted_command} 2>&1 | tee -a {log_file}"
    redacted_body = (
        f"cd {project_dir} && {{ echo \"[START] $(date -Is) session={session} cmd={redacted_command}\" | "
        f"tee -a {log_file}; {redacted_pipeline}; exit_code=${{PIPESTATUS[0]}}; "
        f"echo \"[END] $(date -Is) exit_code=${{exit_code}}\" | tee -a {log_file}; exit $exit_code; }}"
    )
    redacted_display = (
        f"tmux new-session -d -s {session} \"bash -lc {shlex.quote(redacted_body)}\""
    )
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
    # tail 同样指定 UTF-8 编码，保持与 run_ssh_command 的输出行为一致。
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
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


# 定义实时追踪并镜像远端日志的函数。
def tail_and_mirror_log(
    user: str,
    host: str,
    remote_log: str,
    local_log_dir: str,
    local_filename: str = "run.log",
    keyfile: Optional[str] = None,
    mirror_interval_sec: int = 3,
) -> int:
    # 校验必需的连接参数，缺失时直接返回错误码。
    if not host or not remote_log:
        print("[remote_exec] ❌ 缺少 host 或 remote_log，无法执行日志镜像。")
        return 1
    # 若未提供 SSH 用户名，则无法建立连接。
    if not user:
        print("[remote_exec] ❌ 缺少 SSH 用户名，无法连接远端主机。")
        return 1
    # 解析状态文件以确定实例标签或 ID。
    state_path = Path(__file__).resolve().parent.parent / ".state.json"
    instance_label = ""
    instance_id = ""
    if state_path.exists():
        try:
            with state_path.open("r", encoding="utf-8") as handle:
                state_data = json.load(handle)
            instance_label = state_data.get("label", "") or ""
            instance_id = state_data.get("instance_id", "") or ""
        except json.JSONDecodeError:
            print("[remote_exec] ⚠️ .state.json 无法解析，将使用主机地址作为日志目录。")
    else:
        print("[remote_exec] ⚠️ 未找到 .state.json，将使用主机地址作为日志目录。")
    # 计算用于存放本地日志的目录名称，优先使用实例标签，其次 ID，最后使用主机名。
    base_name = instance_label or instance_id or host.replace(".", "-")
    # 生成时间戳目录，采用本地时间以方便对应操作时间。
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 构建最终的本地日志目录路径。
    local_root_path = Path(local_log_dir).expanduser()
    session_dir = local_root_path / base_name / timestamp
    # 确保目录存在，必要时递归创建。
    session_dir.mkdir(parents=True, exist_ok=True)
    # 拼接本地日志文件的完整路径。
    local_log_path = session_dir / local_filename
    # 输出路径摘要，帮助用户定位本地日志。
    print(f"[remote_exec] 📁 本地日志将保存到 {local_log_path}。")
    # 检测本地是否安装 rsync，用于决定是否启用镜像线程。
    detected_rsync = detect_local_rsync()
    rsync_path = str(detected_rsync) if detected_rsync else os.environ.get("RSYNC_PATH")
    rsync_available = rsync_path is not None
    if not rsync_available:
        # 若 rsync 不可用，则给出安装提示并说明降级行为。
        system_name = platform.system().lower()
        print("[remote_exec] ⚠️ 未检测到本地 rsync，日志镜像将降级为仅使用 tail 输出。")
        if "windows" in system_name:
            print("[remote_exec] ℹ️ Windows 环境建议安装 Git for Windows 或启用 WSL 以获得 rsync 支持。")
        else:
            print("[remote_exec] ℹ️ 请通过包管理器安装 rsync，例如 sudo apt install -y rsync。")
    # 构建远端目标字符串，使用 shlex.quote 确保路径安全。
    remote_target = f"{user}@{host}:{shlex.quote(remote_log)}"
    # 构建 ssh 传输配置，若提供密钥则拼接 -i 选项。
    ssh_transport = "ssh"
    if keyfile:
        ssh_transport = f"ssh -i {shlex.quote(keyfile)}"
    # 组装 rsync 命令列表，便于后续重复调用。
    rsync_cmd = [
        rsync_path or "rsync",
        "-avz",
        "--progress",
        "-e",
        ssh_transport,
        remote_target,
        str(local_log_path),
    ]
    # 定义一个辅助函数用于执行 rsync，并根据需要输出警告。
    def _run_rsync(show_warnings: bool, suppress_output: bool) -> int:
        # 声明使用外层的 rsync 可用状态，以便在降级时更新。
        nonlocal rsync_available
        # 当 rsync 不可用时直接返回成功，避免重复打印提示。
        if not rsync_available:
            return 0
        try:
            # 根据 suppress_output 参数决定是否隐藏 rsync 详细输出。
            stdout_target = subprocess.DEVNULL if suppress_output else None
            stderr_target = subprocess.STDOUT if suppress_output else None
            # 执行 rsync 命令并返回退出码。
            result = subprocess.run(
                rsync_cmd,
                check=False,
                stdout=stdout_target,
                stderr=stderr_target,
            )
            # 在需要时输出警告，提醒用户关注同步失败。
            if result.returncode != 0 and show_warnings:
                print(
                    f"[remote_exec] ⚠️ rsync 同步失败，退出码 {result.returncode}。稍后将重试。"
                )
            return result.returncode
        except FileNotFoundError:
            # 在极端情况下，即使之前检测成功仍可能无法调用 rsync，此时退回降级模式。
            print("[remote_exec] ⚠️ 未找到 rsync 命令，已降级为仅 tail 模式。")
            rsync_available = False
            return 1
    # 在进入实时查看之前执行一次全量 rsync，保证本地拥有最新快照。
    if rsync_available:
        print("[remote_exec] 🔄 正在执行初次 rsync，同步远端日志。")
        initial_code = _run_rsync(show_warnings=True, suppress_output=False)
        if initial_code != 0:
            print("[remote_exec] ⚠️ 初次 rsync 失败，将继续通过 tail 获取实时输出。")
    # 创建用于停止后台线程的事件对象。
    stop_event = threading.Event()
    # 定义后台线程逻辑，周期性地触发 rsync 增量同步。
    def _mirror_worker() -> None:
        # 持续运行直到主线程发出停止信号。
        while not stop_event.is_set():
            # 等待指定的时间间隔，期间若收到停止信号则提前退出。
            interval = mirror_interval_sec if mirror_interval_sec > 0 else 3
            if stop_event.wait(timeout=interval):
                break
            # 执行 rsync 并忽略非零退出码，仅在需要时输出警告。
            _run_rsync(show_warnings=True, suppress_output=True)
    # 当 rsync 可用时启动后台镜像线程。
    mirror_thread: Optional[threading.Thread] = None
    if rsync_available:
        mirror_thread = threading.Thread(target=_mirror_worker, name="log-mirror", daemon=True)
        mirror_thread.start()
    # 构建 tail -F 命令以实时跟踪远端日志。
    tail_args = list(_base_ssh_args(host, user, keyfile))
    tail_args.append(f"tail -n +1 -F {shlex.quote(remote_log)}")
    # 打印提示，告知用户如何退出实时查看。
    print(f"[remote_exec] ▶ tail -F {remote_log}（按 Ctrl+C 结束）")
    # 预先声明子进程变量，便于在上下文外部访问退出码。
    process: Optional[subprocess.Popen] = None
    # 以追加模式打开本地日志文件，确保实时输出同步写入。
    with local_log_path.open("a", encoding="utf-8", errors="replace") as local_handle:
        # 启动 ssh 子进程，并将 stdout 合并 stderr。
        process = subprocess.Popen(
            tail_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        try:
            # 逐行读取远端输出，既打印到控制台也写入本地文件。
            for line in iter(process.stdout.readline, ""):
                print(line, end="")
                local_handle.write(line)
                local_handle.flush()
        except KeyboardInterrupt:
            # 当用户按下 Ctrl+C 时提示并向远端 tail 发送中断信号。
            print("\n[remote_exec] ⏹ 捕获到中断信号，正在停止 tail 会话……")
            interrupt_signal = getattr(signal, "SIGINT", signal.SIGTERM)
            process.send_signal(interrupt_signal)
        finally:
            # 等待子进程退出以获取最终退出码。
            process.wait()
            # 通知后台镜像线程可以停止运行。
            stop_event.set()
    # 等待镜像线程结束，确保最后一次同步完成。
    if mirror_thread is not None:
        mirror_thread.join()
    # 在退出界面前执行最后一次 rsync，确保遗漏的内容被补齐。
    if rsync_available:
        print("[remote_exec] 🔁 正在进行最终 rsync，确保日志完整。")
        _run_rsync(show_warnings=True, suppress_output=True)
    # 取得 tail 子进程的退出码，若为 130（Ctrl+C）则视为正常退出。
    exit_code = process.returncode if process else 0
    if exit_code == 130:
        exit_code = 0
    # 输出收尾信息，告知用户本地日志的存放位置。
    print(f"[remote_exec] 📦 日志查看结束，本地副本位于 {local_log_path}。")
    # 返回最终的退出码。
    return exit_code

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
