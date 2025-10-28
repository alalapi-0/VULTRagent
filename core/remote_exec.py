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
# 导入 re 模块用于解析 ssh 输出中的错误关键字。
import re
# 导入 datetime.datetime 用于创建时间戳目录。
from datetime import datetime
# 导入 pathlib.Path 以便跨平台构建路径。
from pathlib import Path
# 导入 shlex 模块用于在记录日志时安全拼接命令。
import shlex
# 导入 typing 模块中的 Dict、Optional、Sequence、Tuple 类型用于类型注解。
from typing import Dict, Optional, Sequence, Tuple

from core.env_check import detect_local_rsync, diagnose_local_ssh_environment

# 定义一个常量，指向远端诊断脚本的默认路径。
_REMOTE_DIAGNOSE_SCRIPT = "/home/ubuntu/vultragentsvc/scripts/ssh_diagnose.sh"


def _write_log_section(log_file: Path, title: str, content: str) -> None:
    """在日志文件中追加带标题的内容段落。"""

    # 以追加模式打开日志文件，确保多次写入不会覆盖之前内容。
    with log_file.open("a", encoding="utf-8") as handle:
        # 写入段落标题，统一使用 === 标记方便阅读。
        handle.write(f"=== {title} ===\n")
        # 如果内容非空，则原样写入日志文件。
        if content:
            handle.write(content)
            # 如果内容末尾缺少换行，则补齐一行避免下一段粘连。
            if not content.endswith("\n"):
                handle.write("\n")
        # 在段落末尾额外补充空行以增强可读性。
        handle.write("\n")


def _classify_ssh_error(output: str) -> Tuple[str, str]:
    """根据 ssh 输出识别错误类型并返回匹配到的关键短语。"""

    # 定义常见错误关键字与对应的错误标签。
    patterns = [
        ("timeout", r"Connection timed out"),
        ("permission", r"Permission denied"),
        ("noroute", r"No route to host"),
        ("refused", r"Connection refused"),
        ("hostkey", r"Host key verification failed"),
        ("network_unreachable", r"Network is unreachable"),
    ]
    # 遍历关键字列表，找到首个匹配的错误标签。
    for label, pattern in patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return label, pattern
    # 未匹配到任何已知错误时返回 unknown 标签。
    return "unknown", ""


def _run_remote_diagnose(
    user: str,
    host: str,
    port: int,
    keyfile: Optional[str],
    script_path: str,
    log_file: Path,
) -> Dict[str, str]:
    """尝试通过 SSH 调用远端诊断脚本并记录输出。"""

    # 组装基础 ssh 命令参数，启用 BatchMode 避免交互式输入。
    ssh_args = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-p",
        str(port),
    ]
    # 当提供了私钥文件时，将其加入 ssh 参数。
    if keyfile:
        ssh_args.extend(["-i", keyfile])
    # 组合目标地址字符串，保持与其它函数一致的 user@host 形式。
    ssh_args.append(f"{user}@{host}")
    # 使用 bash 调用远端脚本，同时保证路径中的特殊字符得到转义。
    remote_command = f"bash {shlex.quote(script_path)}"
    ssh_args.append(remote_command)
    # 在日志中记录即将执行的诊断命令，帮助用户回溯问题。
    _write_log_section(
        log_file,
        "remote_diagnose_command",
        " ".join(shlex.quote(part) for part in ssh_args),
    )
    try:
        # 执行 ssh 命令并捕获标准输出与错误输出。
        proc = subprocess.run(ssh_args, capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001 - 需捕获所有异常用于提示
        # 当命令执行失败时记录异常信息，便于分析根因。
        failure_message = f"调用远端诊断脚本失败：{exc}"
        _write_log_section(log_file, "remote_diagnose_error", failure_message)
        # 返回执行失败的摘要信息给上层调用者。
        return {
            "ran": "false",
            "returncode": "",
            "error": failure_message,
            "output": "",
        }
    # 合并 stdout 与 stderr 便于统一写入日志。
    combined = (proc.stdout or "") + (proc.stderr or "")
    # 将命令输出写入日志文件供用户查阅详情。
    _write_log_section(log_file, "remote_diagnose_output", combined)
    # 构造执行结果摘要以供 check_ssh_connection 使用。
    return {
        "ran": "true",
        "returncode": str(proc.returncode),
        "error": "" if proc.returncode == 0 else "远端诊断脚本返回非零退出码",
        "output": combined,
    }


def check_ssh_connection(
    user: str,
    host: str,
    port: int = 22,
    keyfile: Optional[str] = None,
    timeout: int = 20,
    remote_script: str = _REMOTE_DIAGNOSE_SCRIPT,
) -> Dict[str, str]:
    """测试 SSH 连接状态并根据错误类型给出诊断建议。"""

    # 若缺少主机地址则无法继续诊断，立即返回提示。
    if not host:
        print("[remote_exec] ❌ 未提供 SSH 主机地址，无法执行连通性检测。")
        return {"ok": "false", "reason": "missing_host"}
    # 若缺少用户名同样无法构建 ssh 目标，需提醒用户补全配置。
    if not user:
        print("[remote_exec] ❌ 未提供 SSH 用户名，无法执行连通性检测。")
        return {"ok": "false", "reason": "missing_user"}
    # 创建日志目录并生成带时间戳的日志文件名。
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"ssh_check_{timestamp}.log"
    # 初始化日志文件，写入简单的标头以区分不同段落。
    log_file.write_text("=== ssh_check ===\n\n", encoding="utf-8")
    # 构建 ssh 命令基础参数，开启详细输出以捕获错误原因。
    ssh_args = [
        "ssh",
        "-v",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={timeout}",
        "-p",
        str(port),
    ]
    # 若提供私钥则追加 -i 参数以指定凭据。
    if keyfile:
        ssh_args.extend(["-i", keyfile])
    # 组合远端目标并附加 exit 命令用于快速验证。
    ssh_args.append(f"{user}@{host}")
    ssh_args.append("exit")
    # 将最终命令写入日志，方便用户复现。
    _write_log_section(
        log_file,
        "ssh_command",
        " ".join(shlex.quote(part) for part in ssh_args),
    )
    # 在控制台告知用户检测目标与端口。
    print(f"[CHECK] 正在检测 SSH 连接：{user}@{host}:{port}")
    try:
        # 运行 ssh 命令并捕获输出内容。
        proc = subprocess.run(ssh_args, capture_output=True, text=True)
    except FileNotFoundError:
        # 当本地缺少 ssh 命令时，提示用户安装并记录日志。
        message = "本地未找到 ssh 命令，请先安装 OpenSSH 客户端。"
        print(f"[remote_exec] ❌ {message}")
        _write_log_section(log_file, "ssh_error", message)
        print(f"\n📁 详细日志已保存：{log_file}")
        return {"ok": "false", "reason": "ssh_not_found"}
    # 将 ssh 输出合并后写入日志文件。
    combined_output = (proc.stdout or "") + (proc.stderr or "")
    _write_log_section(log_file, "ssh_output", combined_output)
    # 使用辅助函数识别错误类型并拿到匹配到的关键短语。
    error_label, matched_keyword = _classify_ssh_error(combined_output)
    # 根据返回码判断是否需要输出成功提示。
    if proc.returncode == 0:
        print("✅ SSH 检测通过，远端可正常建立连接。")
    else:
        # 针对不同错误标签输出个性化的排障建议。
        if error_label == "timeout":
            print("\n❌ SSH 连接超时，可能原因如下：")
            print("  1️⃣ VPS SSH 服务未运行 → 尝试执行：sudo systemctl restart ssh")
            print("  2️⃣ 防火墙未放行 22 端口 → 运行：sudo ufw allow 22/tcp && sudo ufw reload")
            print("  3️⃣ 云防火墙未放行 22 → 检查 Vultr Firewall Group 规则。")
            print("  4️⃣ 本地网络屏蔽 22 → 尝试切换其他网络或手机热点。")
            print("  5️⃣ SSH 端口被修改 → 检查 /etc/ssh/sshd_config 中的 Port。")
            print("\n🧩 已自动尝试执行远端诊断脚本，详见日志。")
        elif error_label == "permission":
            print("\n⚠️ 登录失败：密钥或用户信息可能不正确。")
            print("  - 请确认当前使用的用户是否正确（如 ubuntu / root）。")
            print("  - 请确认私钥与 Vultr 面板中的公钥匹配。")
            print("  - 若 VPS 禁用 root 登录，尝试改用普通用户。")
        elif error_label == "noroute":
            print("\n🚫 无法路由到主机，说明网络不通或路由异常。")
            print("  - 请检查实例是否正在运行且网络接口已启用。")
            print("  - 若使用内网 IP，请改用公网 IP。")
            print("  - 可在 Vultr 控制台确认实例网络状态。")
            print("\n🧩 已自动尝试执行远端诊断脚本，详见日志。")
        elif error_label == "refused":
            print("\n🔒 目标拒绝连接，可能是 SSH 服务未监听指定端口。")
            print("  - 可执行 sudo systemctl enable --now ssh 恢复服务。")
            print("  - 请确认 sshd_config 中的 Port 与本次检测端口一致。")
            print("\n🧩 已自动尝试执行远端诊断脚本，详见日志。")
        elif error_label == "hostkey":
            print("\n⚠️ Host key 验证失败，建议清理已缓存的 known_hosts 记录。")
            print(f"  - 可执行 ssh-keygen -R {host} 然后重试连接。")
            print("  - 若实例重装后 IP 未变化，需要重新接受新的指纹。")
        elif error_label == "network_unreachable":
            print("\n🚫 本地网络不可达目标主机，请检查当前网络环境。")
            print("  - 可尝试切换到其他网络，或检查本地路由配置。")
        else:
            print("\n❌ SSH 检测失败，未识别的错误类型。请查阅日志获取更多细节。")
        print(f"\n[remote_exec] ssh 返回码：{proc.returncode}，匹配关键字：{matched_keyword or '无'}")
    # 调用环境检测函数收集本地端口与防火墙信息。
    local_env = diagnose_local_ssh_environment(host=host, port=port)
    # 将环境信息写入日志以便后续分析。
    _write_log_section(log_file, "local_environment", json.dumps(local_env, ensure_ascii=False, indent=2))
    # 如果检测结果显示端口不可达，则在控制台给出提示。
    reachability = local_env.get("port_reachability", "unknown")
    if reachability != "reachable":
        print("\n[remote_exec] ⚠️ 本地端口检测结果提示连接可能受限，请检查网络或防火墙。")
    # 根据错误标签决定是否触发远端诊断脚本。
    if error_label in {"timeout", "noroute", "refused", "network_unreachable"}:
        diagnose_result = _run_remote_diagnose(
            user=user,
            host=host,
            port=port,
            keyfile=keyfile,
            script_path=remote_script,
            log_file=log_file,
        )
        # 根据返回值在终端输出执行情况摘要。
        if diagnose_result.get("ran") == "true":
            print("\n[remote_exec] 已尝试远端诊断脚本，请查看日志了解详细输出。")
            if diagnose_result.get("returncode") != "0":
                print(
                    "[remote_exec] ⚠️ 远端诊断脚本返回非零退出码，可能需要手动登录进一步排查。"
                )
        else:
            print("\n[remote_exec] ⚠️ 未能调用远端诊断脚本：")
            print(f"  {diagnose_result.get('error', '未知错误')}")
    # 在控制台提示日志保存位置，方便用户查看详细报告。
    print(f"\n📁 详细日志已保存：{log_file}")
    # 返回执行摘要供调用方在需要时进一步处理。
    return {
        "ok": "true" if proc.returncode == 0 else "false",
        "error": error_label,
        "log_file": str(log_file),
    }


def _remote_command_available(ssh_args: Sequence[str], command: str) -> bool:
    """检测远端是否存在指定命令。"""

    check_cmd = list(ssh_args) + ["command", "-v", command]
    try:
        result = subprocess.run(check_cmd, capture_output=True, text=True)
    except Exception as exc:  # noqa: BLE001 - 捕获所有异常用于输出日志
        print(f"[ERROR] 检测远端命令 {command} 时失败：{exc}")
        return False
    return result.returncode == 0


def _attempt_remote_install(host: str, user: str, keyfile: Optional[str]) -> bool:
    """尝试使用常见包管理器在远端安装 rsync。"""

    ssh_args = list(_base_ssh_args(host, user, keyfile))

    install_sequences = [
        (
            "apt",
            "bash -lc \"sudo apt update && sudo apt install -y rsync\"",
        ),
        (
            "apt-get",
            "bash -lc \"sudo apt-get update && sudo apt-get install -y rsync\"",
        ),
        (
            "yum",
            "bash -lc \"sudo yum install -y rsync\"",
        ),
        (
            "dnf",
            "bash -lc \"sudo dnf install -y rsync\"",
        ),
        (
            "pacman",
            "bash -lc \"sudo pacman -Sy --noconfirm rsync\"",
        ),
        (
            "apk",
            "bash -lc \"sudo apk add rsync\"",
        ),
    ]

    for manager, install_cmd in install_sequences:
        if not _remote_command_available(ssh_args, manager):
            continue
        print(f"[INSTALL] 检测到远端包管理器 {manager}，尝试安装 rsync …")
        try:
            print(f"[INSTALL] ▶ {install_cmd}")
            result = run_ssh_command(
                host=host,
                user=user,
                keyfile=keyfile,
                command=install_cmd,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] 执行 {manager} 安装命令时出错：{exc}")
            continue

        if result.returncode != 0:
            print(
                f"[FAIL] 通过 {manager} 安装 rsync 失败，返回码 {result.returncode}。"
            )
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
    ssh_args = list(_base_ssh_args(host, user, keyfile))

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

    if _attempt_remote_install(host, user, keyfile):
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
    # 预构建 ssh 基础参数，供后续 rsync 与 tail 复用。
    ssh_base_args = list(_base_ssh_args(host, user, keyfile))

    # 在存在本地 rsync 的前提下，优先确认远端同样具备 rsync 能力。
    if rsync_available and not _remote_command_available(ssh_base_args, "rsync"):
        print("[remote_exec] ⚠️ 远端未检测到 rsync，日志镜像将降级为仅使用 tail 输出。")
        print(
            "[remote_exec] ℹ️ 请在远端安装 rsync（例如执行 sudo apt install -y rsync）后重试。"
        )
        rsync_available = False

    # 构建远端目标字符串，使用 shlex.quote 确保路径安全。
    remote_target = f"{user}@{host}:{shlex.quote(remote_log)}"
    # 基于 ssh_base_args 生成 -e 参数所需的 ssh 传输配置。
    ssh_transport_parts = ssh_base_args[:-1]
    ssh_transport = " ".join(shlex.quote(part) for part in ssh_transport_parts)
    if rsync_available and not ssh_transport:
        print("[remote_exec] ⚠️ 无法构建 rsync 所需的 ssh 参数，已降级为仅使用 tail 输出。")
        rsync_available = False
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
    tail_args = list(ssh_base_args)
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
