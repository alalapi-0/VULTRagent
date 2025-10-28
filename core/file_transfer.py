# core/file_transfer.py
# 该模块负责处理文件上传、结果下载以及 Round 4 要求的远端仓库部署逻辑。
# 导入 json 模块用于在调试时格式化输出内容。
import json
# 导入 os 模块以便在本地进行文件遍历和平台判断。
import os
# 导入 shlex 模块以确保在构建 shell 命令时进行安全转义。
import shlex
import sys
# 导入 subprocess 模块以执行本地外部命令（rsync 或 scp）。
import subprocess
# 导入 shutil 模块以检测 rsync 是否可用。
import shutil
# 导入 time 模块用于在重试时执行退避等待。
import time
# 导入 datetime 模块用于生成结果目录中的时间戳。
from datetime import datetime
# 导入 fnmatch 模块在 Windows 降级模式下执行本地过滤。
from fnmatch import fnmatch
# 导入 pathlib.Path 以处理本地路径的展开与校验。
from pathlib import Path
# 导入 typing 模块中的 Dict、List、Optional 以完善类型注解。
from typing import Dict, List, Optional
from urllib.parse import urlparse

# 导入 rich.console.Console 以便在终端呈现彩色输出。
from rich.console import Console
# 导入 rich.table.Table 以便在总结阶段生成信息表格。
from rich.table import Table

# 从 core.remote_exec 模块导入 run_ssh_command 函数以执行远端命令。
from core.remote_exec import run_ssh_command

# 创建全局 Console 实例，便于在本模块中统一输出日志。
console = Console()


# 定义一个辅助函数，用于在本地更新 ASR 仓库以保持最新状态。
def update_local_repo(local_dir: str, branch: str) -> Dict[str, object]:
    """Update the local ASR repository before deploying to the remote host."""
    messages: List[str] = []
    result: Dict[str, object] = {
        "ok": False,
        "path": local_dir,
        "branch": branch,
        "commit": "",
        "messages": messages,
    }
    if not local_dir:
        messages.append("local_repo_dir 未配置")
        return result
    repo_path = Path(local_dir).expanduser()
    if not repo_path.exists():
        messages.append(f"本地仓库目录不存在：{repo_path}")
        return result
    if not (repo_path / ".git").exists():
        messages.append(f"目标目录不是 Git 仓库：{repo_path}")
        return result
    console.print(f"[blue][file_transfer] 更新本地仓库 {repo_path}（分支 {branch}）。[/blue]")
    try:
        fetch_proc = subprocess.run(
            ["git", "-C", str(repo_path), "fetch", "--all", "--prune"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        messages.append("未检测到 git 可执行文件，请在本地安装 git。")
        return result
    if fetch_proc.returncode != 0:
        messages.append("git fetch 执行失败，请检查网络连接或凭据。")
        messages.append(fetch_proc.stderr.strip() or fetch_proc.stdout.strip())
        return result
    checkout_proc = subprocess.run(
        ["git", "-C", str(repo_path), "checkout", branch],
        check=False,
        capture_output=True,
        text=True,
    )
    if checkout_proc.returncode != 0:
        messages.append("git checkout 执行失败，请确认分支存在且无本地冲突。")
        messages.append(checkout_proc.stderr.strip() or checkout_proc.stdout.strip())
        return result
    pull_proc = subprocess.run(
        ["git", "-C", str(repo_path), "pull", "--ff-only", "origin", branch],
        check=False,
        capture_output=True,
        text=True,
    )
    if pull_proc.returncode != 0:
        messages.append("git pull 执行失败，请手动解决冲突后重试。")
        messages.append(pull_proc.stderr.strip() or pull_proc.stdout.strip())
        return result
    status_proc = subprocess.run(
        ["git", "-C", str(repo_path), "status", "-sb"],
        check=False,
        capture_output=True,
        text=True,
    )
    if status_proc.stdout:
        messages.append(f"git status:\n{status_proc.stdout.strip()}")
    commit_proc = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if commit_proc.returncode != 0:
        messages.append("无法获取当前提交哈希。")
        messages.append(commit_proc.stderr.strip() or commit_proc.stdout.strip())
        return result
    commit_hash = commit_proc.stdout.strip().splitlines()[-1] if commit_proc.stdout else ""
    result["commit"] = commit_hash
    result["ok"] = True
    console.print(
        f"[green][file_transfer] 本地仓库已更新至 commit {commit_hash or 'UNKNOWN'}。[/green]"
    )
    return result


# 定义一个辅助函数，用于在远端幂等地创建项目、音频与输出目录。
def ensure_remote_io_dirs(
    user: str,
    host: str,
    project_dir: str,
    remote_inputs_dir: Optional[str],
    remote_outputs_dir: Optional[str],
    keyfile: Optional[str] = None,
) -> None:
    """确保远端项目目录及音频/输出子目录存在，并统一调整所有权。"""

    # 初始化一个列表，用于收集需要创建的所有目录。
    candidate_dirs: List[str] = []
    # 若提供了项目目录，则加入候选列表。
    if project_dir:
        candidate_dirs.append(project_dir)  # 将项目目录加入待创建列表。
    # 若提供了音频目录，则加入候选列表。
    if remote_inputs_dir:
        candidate_dirs.append(remote_inputs_dir)  # 将音频目录加入待创建列表。
    # 若提供了输出目录，则加入候选列表。
    if remote_outputs_dir:
        candidate_dirs.append(remote_outputs_dir)  # 将输出目录加入待创建列表。
    # 使用有序去重逻辑，避免重复执行 mkdir。
    unique_dirs: List[str] = []
    for directory in candidate_dirs:
        if directory not in unique_dirs:  # 避免重复加入相同路径。
            unique_dirs.append(directory)
    # 构造需要执行的远端命令列表。
    commands: List[str] = []
    # 当存在目录需要创建时，拼接 mkdir -p 命令。
    if unique_dirs:
        quoted = " ".join(_quote(path) for path in unique_dirs)  # 拼接经转义的目录参数。
        commands.append(f"mkdir -p {quoted}")  # 构造 mkdir 命令。
    # 初始化一个列表，用于收集需要执行 chown 的目录。
    chown_targets: List[str] = []
    # 若配置了音频目录，则将其加入 chown 列表。
    if remote_inputs_dir:
        chown_targets.append(remote_inputs_dir)  # 将音频目录加入 chown 列表。
    # 若配置了输出目录，则将其加入 chown 列表。
    if remote_outputs_dir:
        chown_targets.append(remote_outputs_dir)  # 将输出目录加入 chown 列表。
    # 同样执行有序去重，避免重复参数。
    unique_chown: List[str] = []
    for directory in chown_targets:
        if directory not in unique_chown:  # 确保同一目录仅出现一次。
            unique_chown.append(directory)
    # 当存在需要调整所有权的目录时，拼接 chown 命令。
    if unique_chown:
        quoted_chown = " ".join(_quote(path) for path in unique_chown)  # 拼接 chown 参数。
        commands.append(f"chown -R ubuntu:ubuntu {quoted_chown}")  # 构造 chown 命令。
    # 如果没有命令需要执行，则提前返回。
    if not commands:
        return
    # 依次执行构建好的命令列表，一旦失败则抛出异常。
    for command in commands:
        result = _execute_remote(user=user, host=host, command=command, keyfile=keyfile)  # 执行远端命令。
        if result["returncode"] != 0:
            raise RuntimeError(f"failed to ensure remote directory via: {command}")
    # 构造一个用于展示的目录摘要，优先突出音频与输出路径。
    display_targets = [
        path  # 保留需要在日志中展示的路径。
        for path in [remote_inputs_dir or "", remote_outputs_dir or ""]
        if path
    ]
    # 当有需要展示的目录时输出统一的日志格式。
    if display_targets:
        console.print(
            f"[green][file_transfer] [OK] Created directories: {', '.join(display_targets)}[/green]"
        )


# 定义一个辅助函数，用于安全地将路径或参数转换为 shell 可接受的形式。
def _quote(value: str) -> str:
    # 通过 shlex.quote 处理可能包含空格或特殊字符的值。
    return shlex.quote(value)


# 定义一个辅助函数，在 Windows 平台上将本地路径转换为 rsync 可识别的 /cygdrive 形式。
def _format_local_path_for_rsync(local_dir: Path) -> str:
    """返回适用于 rsync 的本地路径表示，兼容 Windows/msys 环境。"""

    path_str = str(local_dir)
    # 仅在 Windows 平台上尝试转换盘符路径。
    if sys.platform.startswith("win"):
        normalized = path_str.replace("\\", "/")
        # 匹配形如 C:/path 或 C: 后紧跟目录的写法。
        if len(normalized) >= 2 and normalized[1] == ":":
            drive_letter = normalized[0].lower()
            remainder = normalized[2:].lstrip("/")
            cygdrive_path = f"/cygdrive/{drive_letter}"
            if remainder:
                cygdrive_path = f"{cygdrive_path}/{remainder}"
            return cygdrive_path
    return path_str


def _format_local_path_for_scp(local_path: Path) -> str:
    """返回用于 scp 命令的本地路径，避免 Windows 平台的 /cygdrive 转换。"""

    # Windows 下的原生命令行工具（例如 OpenSSH for Windows）不识别
    # /cygdrive 前缀，因此直接传递标准文件系统路径即可。其他平台沿用
    # POSIX 形式的字符串表示。
    if sys.platform.startswith("win"):
        return str(local_path)
    return str(local_path)


# 定义一个辅助函数，用于构造带 bash -lc 的远端命令并执行。
def _execute_remote(user: str, host: str, command: str, keyfile: Optional[str]) -> Dict[str, object]:
    # 先拼接 bash -lc 包装层，保证能够执行复合命令。
    wrapped = f"bash -lc {_quote(command)}"
    # 调用 run_ssh_command 执行远端指令，并捕获输出与返回码。
    result = run_ssh_command(host=host, user=user, keyfile=keyfile, command=wrapped)
    # 将执行结果组装成统一的字典格式，便于后续处理。
    return {"returncode": result.returncode, "stdout": result.stdout, "args": result.args}


def _bootstrap_existing_repo(
    *,
    user: str,
    host: str,
    project_dir: str,
    repo_url: str,
    branch: str,
    keyfile: Optional[str],
    shallow: bool,
) -> Dict[str, object]:
    """在已存在的目录中初始化 Git 仓库。

    当项目目录预先创建了 audio/output 等子目录时，直接执行
    ``git clone <repo> .`` 会因为目录非空而失败。该函数尝试在原位
    初始化仓库并拉取指定分支，以兼容这类预初始化目录。
    """

    messages: List[str] = []
    commands = [
        f"cd {_quote(project_dir)} && git init",
        # 允许目录里已经存在名为 origin 的 remote，移除失败也不应终止流程。
        f"cd {_quote(project_dir)} && (git remote remove origin || true)",
        f"cd {_quote(project_dir)} && git remote add origin {_quote(repo_url)}",
    ]

    fetch_parts = [
        "cd",
        _quote(project_dir),
        "&&",
        "git",
        "fetch",
        "origin",
        _quote(branch),
    ]
    if shallow:
        fetch_parts.extend(["--depth", "1"])
    commands.append(" ".join(fetch_parts))

    # checkout -B 可以在本地分支不存在时创建它，并强制对齐到远端分支。
    commands.append(
        " ".join(
            [
                "cd",
                _quote(project_dir),
                "&&",
                "git",
                "checkout",
                "-B",
                _quote(branch),
                _quote(f"origin/{branch}"),
            ]
        )
    )

    for command in commands:
        result = _execute_remote(user=user, host=host, command=command, keyfile=keyfile)
        if result["returncode"] != 0:
            messages.append(
                f"命令执行失败：{command}. 返回码 {result['returncode']}"
            )
            return {"ok": False, "messages": messages}

    return {"ok": True, "messages": ["已在现有目录中初始化 Git 仓库。"]}


# 定义辅助函数，从仓库地址中解析出 SSH 主机名，便于写入 known_hosts。
def _extract_repo_host(repo_url: str) -> Optional[str]:
    if not repo_url:
        return None
    # 处理常见的 git@host:path 形式。
    if repo_url.startswith("git@"):
        host_part = repo_url.split("@", 1)[1]
        return host_part.split(":", 1)[0]
    # 处理 ssh:// 或 git+ssh:// 协议。
    parsed = urlparse(repo_url)
    if parsed.scheme in {"ssh", "git+ssh"}:
        return parsed.hostname
    # 对于 https/http 仓库不需要写入 known_hosts。
    return None


# 定义辅助函数，将常见的 SSH 仓库地址转换为 HTTPS 形式。
def _convert_repo_url_to_https(repo_url: str) -> Optional[str]:
    if not repo_url:
        return None
    if repo_url.startswith("git@"):
        host_part = repo_url.split("@", 1)[1]
        if ":" in host_part:
            host, path = host_part.split(":", 1)
            normalized_path = path.lstrip("/")
            return f"https://{host}/{normalized_path}"
    parsed = urlparse(repo_url)
    if parsed.scheme in {"ssh", "git+ssh"} and parsed.hostname:
        path = (parsed.path or "").lstrip("/")
        if path:
            return f"https://{parsed.hostname}/{path}"
        return f"https://{parsed.hostname}"
    return None


# 定义辅助函数，确保远端 known_hosts 中存在目标仓库的 SSH 指纹。
def _ensure_known_host(
    user: str,
    host: str,
    repo_host: str,
    keyfile: Optional[str],
) -> bool:
    if not repo_host:
        return True
    command = (
        "set -euo pipefail; "
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh; "
        f"if ssh-keygen -F {_quote(repo_host)} >/dev/null 2>&1; then exit 0; fi; "
        f"ssh-keyscan -H {_quote(repo_host)} >> ~/.ssh/known_hosts"
    )
    result = _execute_remote(user=user, host=host, command=command, keyfile=keyfile)
    return result["returncode"] == 0


# 定义一个辅助函数，用于在步骤开始前输出提示。
def _print_step(step: int, total: int, message: str) -> None:
    # 使用 Console 打印统一格式的步骤提示，方便用户追踪进度。
    console.print(f"[cyan][{step}/{total}] {message}[/cyan]")


# 定义上传文件到远端 inputs 目录的函数，实现 rsync 优先、scp 回退的逻辑。
def upload_local_to_remote(
    local_path: str,
    user: str,
    host: str,
    remote_inputs_dir: str,
    keyfile: Optional[str] = None,
    remote_project_dir: Optional[str] = None,  # 远端项目根目录，可为空。
    remote_outputs_dir: Optional[str] = None,  # 远端输出目录，可为空。
) -> None:
    # 展开本地路径以确保兼容 ~ 与相对路径。
    local_dir = Path(local_path).expanduser().resolve()
    # 校验远端主机与用户是否提供。
    if not host or not user:
        console.print("[red][file_transfer] 缺少 SSH 主机或用户名，无法上传素材。[/red]")
        raise ValueError("missing ssh host or user")
    # 校验远端 inputs 目录是否配置。
    if not remote_inputs_dir:
        console.print("[red][file_transfer] 缺少 remote.inputs_dir 配置，无法确定上传目标。[/red]")
        raise ValueError("missing remote inputs_dir")
    # 在上传前确保远端项目、音频与输出目录存在。
    ensure_remote_io_dirs(
        user=user,
        host=host,
        project_dir=remote_project_dir or "",
        remote_inputs_dir=remote_inputs_dir,
        remote_outputs_dir=remote_outputs_dir or "",
        keyfile=keyfile,
    )
    # 检查本地目录是否存在。
    if not local_dir.exists():
        console.print(f"[red][file_transfer] 本地目录不存在：{local_dir}[/red]")
        raise FileNotFoundError(local_dir)
    # 确认本地路径为目录，否则提示用户检查配置。
    if not local_dir.is_dir():
        console.print(f"[red][file_transfer] {local_dir} 不是目录，请确认 transfer.upload_local_dir 设置。[/red]")
        raise NotADirectoryError(local_dir)
    # 提示用户正在创建远端目录，保证 rsync/scp 可以写入。
    console.print(f"[blue][file_transfer] 确保远端目录存在：{remote_inputs_dir}[/blue]")
    ensure_result = _execute_remote(
        user=user,
        host=host,
        command=f"mkdir -p {_quote(remote_inputs_dir)}",
        keyfile=keyfile,
    )
    # 检查远端目录创建命令的返回码，非零表示执行失败。
    if ensure_result["returncode"] != 0:
        console.print("[red][file_transfer] 创建远端目录失败，请检查 SSH 权限。[/red]")
        raise RuntimeError("failed to create remote inputs directory")
    # 根据系统是否存在 rsync 选择上传方式。
    rsync_path = shutil.which("rsync") or os.environ.get("RSYNC_PATH")
    # 统一构造远端目标字符串，确保以斜杠结尾表示目录。
    remote_target = f"{user}@{host}:{remote_inputs_dir.rstrip('/')}/"
    # 构造 SSH 选项字符串，用于 rsync -e 传递。
    ssh_parts = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    formatted_keyfile: Optional[str] = None
    if keyfile:
        # 在 Windows 平台上需要将路径转换为 /cygdrive/x 形式，避免 ssh 无法识别。
        formatted_keyfile = _format_local_path_for_rsync(
            Path(keyfile).expanduser().resolve()
        )
        ssh_parts.extend(["-i", formatted_keyfile])

    # 将 SSH 命令拼接成字符串，根据平台采用合适的转义方式。
    if os.name == "nt":
        ssh_command = subprocess.list2cmdline(ssh_parts)
    else:
        ssh_command = " ".join(shlex.quote(part) for part in ssh_parts)
    # 当检测到 rsync 可用时优先使用，以获得增量与进度显示能力。
    rsync_failed = False
    if rsync_path:
        console.print("[green][file_transfer] 检测到 rsync，使用 rsync -avz --progress 进行同步。[/green]")
        # 构造 rsync 参数列表，确保末尾带有斜杠以复制目录内容。
        rsync_args = [
            rsync_path,
            "-avz",
            "--progress",
            "-e",
            ssh_command,
            f"{_format_local_path_for_rsync(local_dir)}/",
            remote_target,
        ]
        # 输出命令摘要以便用户复现，密钥路径不会包含敏感信息。
        console.print(f"[cyan][file_transfer] 执行命令：{' '.join(rsync_args)}[/cyan]")
        try:
            subprocess.run(rsync_args, check=True)
        except subprocess.CalledProcessError as exc:
            console.print(
                "[yellow][file_transfer] rsync 上传失败，将自动降级为 scp。"
                f" (退出码: {exc.returncode})[/yellow]"
            )
            rsync_failed = True
        else:
            # 成功后告知用户上传完成。
            console.print("[green][file_transfer] rsync 上传完成。[/green]")
            return
    # 根据 rsync 可用性或执行结果打印降级提示。
    if not rsync_path:
        console.print("[yellow][file_transfer] 未检测到 rsync，降级使用 scp -r 批量上传，性能较差。[/yellow]")
    elif rsync_failed:
        console.print("[yellow][file_transfer] rsync 未成功，已改用 scp 继续上传。[/yellow]")
    # 构建 scp 参数，保留时间戳并递归复制。
    scp_args = [
        "scp",
        "-p",
        "-r",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    # 若配置了密钥文件则同样传递给 scp。
    if keyfile:
        scp_key_path = Path(keyfile).expanduser().resolve()
        scp_args.extend(["-i", _format_local_path_for_scp(scp_key_path)])
    # 获取待上传目录中的所有项目，确保多文件复制到同一目标。
    items = sorted(local_dir.iterdir())
    # 当目录为空时提示用户并提前返回。
    if not items:
        console.print("[yellow][file_transfer] 本地目录为空，未执行上传。[/yellow]")
        return
    # 将所有文件或子目录追加到 scp 参数中。
    for item in items:
        scp_args.append(_format_local_path_for_scp(item))
    # 在参数末尾追加远端目标目录。
    scp_args.append(remote_target)
    # 输出最终命令摘要供排查使用。
    console.print(f"[cyan][file_transfer] 执行命令：{' '.join(shlex.quote(arg) for arg in scp_args)}[/cyan]")
    # 执行 scp 上传过程，若失败将抛出异常。
    subprocess.run(scp_args, check=True)
    # 提醒用户使用 scp 时缺乏增量能力，后续可考虑安装 rsync。
    console.print("[green][file_transfer] scp 上传完成，如需更高性能请在本地安装 rsync。[/green]")


# 定义一个函数用于生成本地结果目录结构。
def make_local_results_dir(results_root: str, instance_label: str, instance_id: str) -> str:
    # 选择实例标签作为目录名，若为空则退回实例 ID。
    label_or_id = instance_label or instance_id or "unknown"
    # 获取当前时间戳并格式化为 YYYYMMDD-HHMMSS。
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    # 构建本地结果目录路径。
    target_dir = Path(results_root).expanduser().resolve() / label_or_id / timestamp
    # 创建目录并允许父级目录自动生成。
    target_dir.mkdir(parents=True, exist_ok=True)
    # 返回目录的字符串路径，供调用方输出或继续使用。
    return str(target_dir)


# 定义一个函数用于在远端生成文件清单。
def generate_remote_manifest(
    user: str,
    host: str,
    remote_dir: str,
    manifest_path: str,
    keyfile: Optional[str] = None,
    pattern: Optional[str] = None,
) -> int:
    # 当配置了过滤模式时为 find 命令准备 -name 片段。
    name_clause = f"-name {shlex.quote(pattern)}" if pattern else ""
    # 构建完整的 find 命令以输出大小与相对路径，并写入清单文件。
    command = (
        f"find {shlex.quote(remote_dir)} -type f {name_clause} -printf '%s\\t%P\\n' "
        f"| sort > {shlex.quote(manifest_path)}"
    )
    # 调用辅助函数在远端执行命令。
    result = _execute_remote(user=user, host=host, command=command, keyfile=keyfile)
    # 若执行失败则输出提示以便排查。
    if result["returncode"] != 0:
        console.print(
            f"[red][file_transfer] 生成远端清单失败，返回码 {result['returncode']}。[/red]"
        )
    # 返回命令退出码供上层判断是否继续。
    return result["returncode"]


# 定义一个内部函数用于执行单次 rsync 下载。
def _run_rsync_download(
    rsync_path: str,
    ssh_command: str,
    remote_target: str,
    local_dir: Path,
    pattern: Optional[str],
) -> None:
    # 初始化 rsync 参数列表，启用压缩、断点续传与进度展示。
    rsync_args = [
        rsync_path,
        "-avz",
        "--partial",
        "--inplace",
        "--progress",
        "-e",
        ssh_command,
    ]
    # 当提供了过滤模式时，使用 include/exclude 组合实现匹配。
    if pattern:
        rsync_args.extend(["--include", "*/", "--include", pattern, "--exclude", "*"])
    # 将远端源路径与本地目标路径追加到参数列表。为了兼容 Windows
    # 平台的 rsync，我们需要将本地路径转换为 /cygdrive/x 形式，避免
    # 诸如 ``E:\`` 这类带冒号的盘符被误判为“远端”参数。
    formatted_local_dir = _format_local_path_for_rsync(local_dir)
    rsync_args.extend([remote_target, f"{formatted_local_dir}/"])
    # 输出命令摘要帮助用户调试。
    console.print(f"[cyan][file_transfer] 执行命令：{' '.join(rsync_args)}[/cyan]")
    # 执行 rsync 并在失败时抛出异常。
    subprocess.run(rsync_args, check=True)


# 定义一个内部函数用于执行单次 scp 下载。
def _run_scp_download(
    user: str,
    host: str,
    remote_dir: str,
    local_dir: Path,
    keyfile: Optional[str],
) -> None:
    # 构造基础的 scp 参数，开启时间戳保留并递归下载。
    scp_args = [
        "scp",
        "-p",
        "-r",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    # 若存在密钥文件则加入 -i 选项。
    if keyfile:
        scp_args.extend(["-i", keyfile])
    # 组合远端源路径，使用 "." 结尾仅复制目录内容。
    remote_source = f"{user}@{host}:{remote_dir.rstrip('/')}/."
    # 将源与目标依次追加。
    scp_args.extend([remote_source, str(local_dir)])
    # 输出命令摘要便于追踪。
    console.print(
        f"[cyan][file_transfer] 执行命令：{' '.join(shlex.quote(arg) for arg in scp_args)}[/cyan]"
    )
    # 执行 scp 并在失败时抛出异常。
    subprocess.run(scp_args, check=True)


# 定义一个函数用于支持重试的下载流程。
def download_with_retry(
    user: str,
    host: str,
    remote_dir: str,
    local_dir: str,
    keyfile: Optional[str] = None,
    pattern: Optional[str] = None,
    retries: int = 3,
    backoff_sec: int = 3,
    preserve: Optional[List[str]] = None,
) -> None:
    # 将本地目录转换为 Path 对象并创建。
    destination = Path(local_dir).expanduser().resolve()
    # 确保本地目录存在，允许幂等调用。
    destination.mkdir(parents=True, exist_ok=True)
    # 获取 rsync 可执行文件路径以决定是否可用。
    rsync_path = shutil.which("rsync") or os.environ.get("RSYNC_PATH")
    # 当提供 preserve 列表时，表示需要在降级模式下保留特定文件（例如清单文件）。
    preserve_set = set(preserve or [])
    # 构建远端目标字符串，末尾保留斜杠以复制目录内容。
    remote_target = f"{user}@{host}:{remote_dir.rstrip('/')}/"
    # 构建 SSH 子命令，供 rsync 的 -e 选项使用。
    ssh_parts = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]
    # 若提供了密钥文件则追加。
    if keyfile:
        ssh_parts.extend(["-i", keyfile])
    # 将 SSH 参数拼接为字符串，保持逐项引用安全。
    ssh_command = " ".join(shlex.quote(part) for part in ssh_parts)
    # 计算允许的最大尝试次数（含首次尝试）。
    max_attempts = max(retries, 0) + 1
    # 逐次尝试下载直到成功或耗尽次数。
    for attempt in range(1, max_attempts + 1):
        try:
            # 当检测到 rsync 可用时优先使用。
            if rsync_path:
                console.print(
                    "[green][file_transfer] 使用 rsync 同步远端结果目录。[/green]"
                )
                _run_rsync_download(
                    rsync_path=rsync_path,
                    ssh_command=ssh_command,
                    remote_target=remote_target,
                    local_dir=destination,
                    pattern=pattern,
                )
            else:
                # 若未检测到 rsync，则降级使用 scp。
                console.print(
                    "[yellow][file_transfer] 未检测到 rsync，降级为 scp -r 回传，过滤将在本地完成。[/yellow]"
                )
                _run_scp_download(
                    user=user,
                    host=host,
                    remote_dir=remote_dir,
                    local_dir=destination,
                    keyfile=keyfile,
                )
            # 下载成功后在过滤模式下清理不匹配的文件。
            if pattern and not rsync_path:
                for root, _, files in os.walk(destination):
                    for filename in files:
                        rel_path = os.path.relpath(
                            Path(root) / filename, destination
                        )
                        if preserve_set and rel_path in preserve_set:
                            continue
                        if not (
                            fnmatch(rel_path, pattern)
                            or fnmatch(os.path.basename(rel_path), pattern)
                        ):
                            os.remove(Path(root) / filename)
            # 成功完成后直接返回函数。
            return
        except (subprocess.CalledProcessError, OSError) as exc:
            # 当达到最大尝试次数时抛出异常。
            if attempt >= max_attempts:
                console.print(
                    f"[red][file_transfer] 下载失败，已达到最大重试次数：{exc}[/red]"
                )
                raise
            # 计算当前退避时长，采用指数退避策略。
            wait_seconds = max(backoff_sec, 1) * (2 ** (attempt - 1))
            # 输出提示信息说明即将进行的重试。
            console.print(
                f"[yellow][file_transfer] 下载失败，第 {attempt} 次重试将在 {wait_seconds} 秒后进行。原因：{exc}[/yellow]"
            )
            # 等待指定的秒数后继续下一次尝试。
            time.sleep(wait_seconds)


# 定义一个函数用于根据清单验证本地文件。
def verify_local_against_manifest(local_dir: str, manifest_path: str) -> Dict[str, object]:
    # 初始化统计结果字典。
    result: Dict[str, object] = {
        "ok": True,
        "missing": [],
        "size_mismatch": [],
        "checked": 0,
    }
    # 将路径对象化便于处理。
    base_path = Path(local_dir)
    manifest_file = Path(manifest_path)
    # 若清单文件不存在则标记失败。
    if not manifest_file.exists():
        result["ok"] = False
        return result
    # 逐行读取清单并验证本地文件。
    with manifest_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            # 去除换行符并跳过空行。
            stripped = line.strip()
            if not stripped:
                continue
            # 尝试拆分大小与相对路径。
            try:
                size_str, relative_path = stripped.split("\t", 1)
                expected_size = int(size_str)
            except ValueError:
                # 若行格式异常则跳过但计为失败。
                result["ok"] = False
                continue
            # 组合本地文件路径。
            local_file = base_path / relative_path
            # 更新已检查计数。
            result["checked"] = int(result["checked"]) + 1
            # 若文件不存在则记录缺失。
            if not local_file.exists():
                result["missing"].append(relative_path)
                result["ok"] = False
                continue
            # 读取实际大小并与清单比对。
            actual_size = local_file.stat().st_size
            if actual_size != expected_size:
                result["size_mismatch"].append(
                    {
                        "path": relative_path,
                        "expected": expected_size,
                        "actual": actual_size,
                    }
                )
                result["ok"] = False
    # 返回最终的校验结果。
    return result


# 定义从远端回传结果目录的主函数。
def fetch_results_from_remote(
    user: str,
    host: str,
    remote_outputs_dir: str,
    local_results_dir: str,
    keyfile: Optional[str] = None,
    pattern: Optional[str] = None,
    retries: int = 3,
    backoff_sec: int = 3,
    verify_manifest: bool = True,
    manifest_name: str = "_manifest.txt",
    remote_project_dir: Optional[str] = None,  # 远端项目根目录，可为空。
    remote_inputs_dir: Optional[str] = None,  # 远端音频目录，可为空。
) -> Dict[str, object]:
    # 初始化返回结构，默认表示未验证。
    summary: Dict[str, object] = {
        "ok": False,
        "local_dir": local_results_dir,
        "verified": False,
        "missing": [],
        "size_mismatch": [],
        "manifest": None,
    }
    # 在回传前同样确保远端目录结构已经创建。
    ensure_remote_io_dirs(
        user=user,
        host=host,
        project_dir=remote_project_dir or "",
        remote_inputs_dir=remote_inputs_dir or "",
        remote_outputs_dir=remote_outputs_dir,
        keyfile=keyfile,
    )
    # 确保本地目录存在。
    Path(local_results_dir).mkdir(parents=True, exist_ok=True)
    # 计算远端与本地的清单路径。
    remote_manifest_path = f"{remote_outputs_dir.rstrip('/')}/{manifest_name}"
    local_manifest_path = Path(local_results_dir) / manifest_name
    # 在开启校验时先生成并下载清单。
    if verify_manifest:
        console.print("[blue][file_transfer] 正在生成远端文件清单……[/blue]")
        manifest_rc = generate_remote_manifest(
            user=user,
            host=host,
            remote_dir=remote_outputs_dir,
            manifest_path=remote_manifest_path,
            keyfile=keyfile,
            pattern=pattern,
        )
        if manifest_rc != 0:
            console.print(
                "[red][file_transfer] 清单生成失败，取消本次回传。[/red]"
            )
            return summary
        console.print("[blue][file_transfer] 正在下载远端清单文件……[/blue]")
        try:
            download_with_retry(
                user=user,
                host=host,
                remote_dir=remote_outputs_dir,
                local_dir=local_results_dir,
                keyfile=keyfile,
                pattern=manifest_name,
                retries=retries,
                backoff_sec=backoff_sec,
                preserve=[manifest_name],
            )
            summary["manifest"] = str(local_manifest_path)
        except (subprocess.CalledProcessError, OSError) as exc:
            console.print(
                f"[red][file_transfer] 下载清单失败：{exc}[/red]"
            )
            return summary
    # 下载远端输出目录。
    console.print("[blue][file_transfer] 开始回传远端结果目录……[/blue]")
    download_with_retry(
        user=user,
        host=host,
        remote_dir=remote_outputs_dir,
        local_dir=local_results_dir,
        keyfile=keyfile,
        pattern=pattern,
        retries=retries,
        backoff_sec=backoff_sec,
        preserve=[manifest_name] if verify_manifest else None,
    )
    # 下载成功后标记成功。
    summary["ok"] = True
    # 在启用清单校验时执行比对。
    if verify_manifest and summary["manifest"]:
        console.print("[blue][file_transfer] 正在校验本地文件与清单……[/blue]")
        verify_result = verify_local_against_manifest(
            local_dir=local_results_dir,
            manifest_path=str(local_manifest_path),
        )
        summary.update(verify_result)
        summary["verified"] = bool(verify_result.get("ok"))
    return summary


# 定义一个可选函数用于在远端轮转日志。
def rotate_remote_log(user: str, host: str, log_path: str, keep: int, keyfile: Optional[str] = None) -> int:
    # 构造 shell 命令，将当前日志重命名并删除多余备份。
    command = (
        "set -euo pipefail; "
        f"LOG={shlex.quote(log_path)}; "
        "if [ -f \"$LOG\" ]; then "
        "DIR=$(dirname \"$LOG\"); "
        "TS=$(date +%Y%m%d-%H%M%S); "
        "mv \"$LOG\" \"$DIR/run-$TS.log\"; "
        "touch \"$LOG\"; "
        "fi; "
        "DIR=$(dirname \"$LOG\"); "
        f"ls -1t \"$DIR\"/run-*.log 2>/dev/null | tail -n +{keep + 1} | while read f; do rm -f \"$f\"; done"
    )
    # 在远端执行命令。
    result = _execute_remote(user=user, host=host, command=command, keyfile=keyfile)
    # 根据返回码打印提示。
    if result["returncode"] == 0:
        console.print("[green][file_transfer] 已完成远端日志轮转。[/green]")
    else:
        console.print("[yellow][file_transfer] 日志轮转命令执行失败或日志不存在。[/yellow]")
    # 返回退出码。
    return result["returncode"]


# 定义一个可选函数用于清空远端输出目录。
def cleanup_remote_outputs(
    user: str,
    host: str,
    outputs_dir: str,
    keyfile: Optional[str] = None,
) -> int:
    # 构造安全的清理命令，兼顾隐藏文件。
    command = (
        "set -euo pipefail; "
        f"DIR={shlex.quote(outputs_dir)}; "
        "if [ -d \"$DIR\" ]; then "
        "shopt -s dotglob nullglob; "
        "rm -rf \"$DIR\"/*; "
        "fi"
    )
    # 调用远端执行函数。
    result = _execute_remote(user=user, host=host, command=command, keyfile=keyfile)
    # 根据返回码打印提示信息。
    if result["returncode"] == 0:
        console.print("[green][file_transfer] 已清空远端 outputs 目录。[/green]")
    else:
        console.print("[yellow][file_transfer] 清理远端 outputs 目录失败或目录不存在。[/yellow]")
    # 返回退出码供调用方处理。
    return result["returncode"]


# 定义用于部署或更新远端仓库的核心函数。
def deploy_repo(
    user: str,
    host: str,
    repo_url: str,
    branch: str,
    project_dir: str,
    keyfile: Optional[str] = None,
    shallow: bool = True,
    with_submodules: bool = True,
    prefer_https: bool = False,
) -> Dict[str, object]:
    # 初始化返回结果中的消息列表，用于记录执行过程。
    messages: List[str] = []
    # 预先构造返回字典的基础字段。
    result_payload: Dict[str, object] = {
        "ok": False,
        "branch": branch,
        "commit": "",
        "project_dir": project_dir,
        "has_submodules": False,
        "used_shallow": False,
        "repo_url": repo_url,
        "messages": messages,
    }
    # 若未提供必要参数，则立即返回失败结果。
    if not repo_url:
        # 记录错误原因。
        messages.append("repo_url 未配置")
        # 返回失败 payload。
        return result_payload
    if not branch:
        # 记录错误原因。
        messages.append("branch 未配置")
        # 返回失败 payload。
        return result_payload
    if not project_dir:
        # 记录错误原因。
        messages.append("project_dir 未配置")
        # 返回失败 payload。
        return result_payload
    # 规范化项目目录路径，避免重复的斜杠。
    normalized_dir = project_dir.rstrip("/")
    # 如果目录最终为空字符串，说明传入的是根目录，直接返回失败。
    if not normalized_dir:
        # 记录错误原因。
        messages.append("project_dir 解析失败")
        # 返回失败 payload。
        return result_payload
    # 在执行 Git 操作前，根据配置决定是否将仓库地址转换为 HTTPS。
    if prefer_https:
        converted = _convert_repo_url_to_https(repo_url)
        if converted and converted != repo_url:
            repo_url = converted
            console.print(
                f"[green][file_transfer] 已将仓库地址转换为 HTTPS：{repo_url}[/green]"
            )
            messages.append(f"使用 HTTPS 克隆仓库：{repo_url}")
    result_payload["repo_url"] = repo_url
    # 在执行 Git 操作前，确保远端已信任仓库所在的 SSH 主机。
    repo_host = _extract_repo_host(repo_url)
    if repo_host:
        console.print(f"[cyan][file_transfer] 确保远端已信任 {repo_host} SSH 指纹。[/cyan]")
        if not _ensure_known_host(user=user, host=host, repo_host=repo_host, keyfile=keyfile):
            warning = f"无法将 {repo_host} 写入 known_hosts，后续 git 操作可能因主机指纹校验失败。"
            console.print(f"[yellow][file_transfer] {warning}[/yellow]")
            messages.append(warning)
    # 定义步骤总数以供进度输出。
    total_steps = 6
    # 第一步：创建项目目录并检测是否已存在 Git 仓库。
    _print_step(1, total_steps, "ensure project_dir")
    ensure_cmd = (
        f"mkdir -p {_quote(normalized_dir)} && "
        f"if [ -d {_quote(normalized_dir)}/.git ]; then echo '__HAS_GIT__=1'; else echo '__HAS_GIT__=0'; fi"
    )
    ensure_result = _execute_remote(user=user, host=host, command=ensure_cmd, keyfile=keyfile)
    if ensure_result["returncode"] != 0:
        # 记录错误信息并返回。
        messages.append("创建项目目录失败，可能是权限不足或 SSH 错误。")
        return result_payload
    has_git = "__HAS_GIT__=1" in str(ensure_result["stdout"])
    # 第二步：根据仓库是否存在执行 clone 或 fetch。
    if has_git:
        # 输出提示说明即将执行 fetch/pull。
        _print_step(2, total_steps, "fetch/pull repository")
        fetch_cmd = (
            f"cd {_quote(normalized_dir)} && git remote -v && git fetch --all --prune"
        )
        fetch_result = _execute_remote(user=user, host=host, command=fetch_cmd, keyfile=keyfile)
        if fetch_result["returncode"] != 0:
            # 记录失败原因并返回。
            messages.append("git fetch 执行失败，请检查网络或访问权限。")
            return result_payload
    else:
        # 输出提示说明即将执行 clone。
        _print_step(2, total_steps, "clone repository")
        clone_parts: List[str] = ["cd", _quote(normalized_dir), "&&", "git", "clone"]
        if shallow:
            # 若启用浅克隆则添加 --depth 参数。
            clone_parts.extend(["--depth", "1"])
        # 添加目标分支参数。
        clone_parts.extend(["-b", _quote(branch), _quote(repo_url), "."])
        clone_cmd = " ".join(clone_parts)
        clone_result = _execute_remote(user=user, host=host, command=clone_cmd, keyfile=keyfile)
        if clone_result["returncode"] != 0:
            # 当目录已存在音频/输出等子目录时，git clone 会因为目录非空而失败。
            fallback = _bootstrap_existing_repo(
                user=user,
                host=host,
                project_dir=normalized_dir,
                repo_url=repo_url,
                branch=branch,
                keyfile=keyfile,
                shallow=shallow,
            )
            if not fallback.get("ok"):
                # 记录失败原因并返回。
                messages.append("git clone 执行失败，请确认仓库地址与分支存在。")
                messages.extend(fallback.get("messages", []))
                return result_payload
            messages.extend(fallback.get("messages", []))
            if shallow:
                result_payload["used_shallow"] = True
            has_git = True
        else:
            # 标记此次操作使用了浅克隆。
            result_payload["used_shallow"] = shallow
            # clone 完成后需要刷新 has_git 状态。
            has_git = True
    # 若仓库仍不存在 .git 目录，则无法继续。
    if not has_git:
        # 记录失败原因。
        messages.append("仓库初始化失败，未检测到 .git 目录。")
        return result_payload
    # 第三步：切换分支并同步最新提交。
    _print_step(3, total_steps, "checkout & pull")
    checkout_cmd = (
        f"cd {_quote(normalized_dir)} && git checkout {_quote(branch)} && "
        f"git pull --ff-only origin {_quote(branch)}"
    )
    checkout_result = _execute_remote(user=user, host=host, command=checkout_cmd, keyfile=keyfile)
    if checkout_result["returncode"] != 0:
        # 记录失败原因并返回。
        messages.append("git checkout 或 git pull 失败，请确认分支存在且本地无冲突。")
        return result_payload
    # 第四步：根据配置更新子模块。
    _print_step(4, total_steps, "update submodules")
    has_submodules = False
    if with_submodules:
        # 先检测是否存在 .gitmodules 文件。
        detect_cmd = (
            f"cd {_quote(normalized_dir)} && "
            f"if [ -f .gitmodules ]; then echo '__HAS_SUBMODULES__=1'; else echo '__HAS_SUBMODULES__=0'; fi"
        )
        detect_result = _execute_remote(user=user, host=host, command=detect_cmd, keyfile=keyfile)
        if detect_result["returncode"] != 0:
            # 如果检测失败则记录信息但不中断流程。
            messages.append("检测子模块时出现错误。")
        else:
            has_submodules = "__HAS_SUBMODULES__=1" in str(detect_result["stdout"])
            if has_submodules:
                update_cmd = (
                    f"cd {_quote(normalized_dir)} && git submodule update --init --recursive"
                )
                update_result = _execute_remote(user=user, host=host, command=update_cmd, keyfile=keyfile)
                if update_result["returncode"] != 0:
                    # 子模块更新失败不会阻断后续流程，但会记录警告。
                    messages.append("子模块更新失败，请在远端手动检查。")
    # 将子模块状态写入返回 payload。
    result_payload["has_submodules"] = has_submodules
    # 第五步：检测并执行 Git LFS 拉取。
    _print_step(5, total_steps, "git lfs pull")
    lfs_cmd = (
        f"cd {_quote(normalized_dir)} && "
        f"if command -v git-lfs >/dev/null 2>&1; then git lfs pull || echo 'git lfs pull failed'; "
        f"else echo 'git-lfs not installed'; fi"
    )
    lfs_result = _execute_remote(user=user, host=host, command=lfs_cmd, keyfile=keyfile)
    if "git-lfs not installed" in str(lfs_result["stdout"]):
        # 如果未安装 git-lfs，则提示用户运行环境部署脚本。
        messages.append("git-lfs 未安装，建议先执行环境部署脚本或手动安装。")
    elif "git lfs pull failed" in str(lfs_result["stdout"]):
        # 若拉取失败则记录警告。
        messages.append("git lfs pull 执行失败，部分大文件可能缺失。")
    # 第六步：输出仓库摘要信息。
    _print_step(6, total_steps, "summarize repository")
    status_cmd = f"cd {_quote(normalized_dir)} && git status --porcelain -b"
    status_result = _execute_remote(user=user, host=host, command=status_cmd, keyfile=keyfile)
    if status_result["returncode"] != 0:
        # 若无法获取状态则返回失败。
        messages.append("git status 执行失败，请检查远端 Git 环境。")
        return result_payload
    commit_cmd = f"cd {_quote(normalized_dir)} && git rev-parse --short HEAD"
    commit_result = _execute_remote(user=user, host=host, command=commit_cmd, keyfile=keyfile)
    if commit_result["returncode"] != 0:
        # 若无法解析 commit 则返回失败。
        messages.append("无法解析当前提交哈希。")
        return result_payload
    # 解析 git status 输出并记录到消息列表，便于用户查看仓库状态。
    status_output = str(status_result["stdout"]).strip()
    if status_output:
        # 将状态信息追加到消息列表。
        messages.append(f"git status:\n{status_output}")
    # 提取 commit 哈希并写入返回 payload。
    commit_hash = str(commit_result["stdout"]).strip().splitlines()[-1] if str(commit_result["stdout"]).strip() else ""
    result_payload["commit"] = commit_hash
    # 若 commit 哈希为空则视为失败。
    if not commit_hash:
        # 记录错误信息。
        messages.append("未能获取当前提交哈希。")
        return result_payload
    # 所有关键步骤执行成功，更新 ok 状态。
    result_payload["ok"] = True
    # 返回最终的结果字典。
    return result_payload


# 定义入口文件验证函数，用于检查 asr_quickstart.py 是否存在并可通过语法检查。
def verify_entry(
    user: str,
    host: str,
    project_dir: str,
    entry_name: str = "asr_quickstart.py",
    keyfile: Optional[str] = None,
) -> Dict[str, object]:
    # 构造入口文件的完整路径，便于向用户展示。
    normalized_dir = project_dir.rstrip("/")
    entry_path = f"{normalized_dir}/{entry_name}" if normalized_dir else entry_name
    # 初始化结果字典。
    verify_payload: Dict[str, object] = {
        "exists": False,
        "py_compiles": False,
        "path": entry_path,
        "messages": [],
    }
    # 第一步：检测文件是否存在。
    exists_cmd = f"if [ -f {_quote(entry_path)} ]; then echo '__ENTRY_EXISTS__=1'; else echo '__ENTRY_EXISTS__=0'; fi"
    exists_result = _execute_remote(user=user, host=host, command=exists_cmd, keyfile=keyfile)
    if exists_result["returncode"] != 0:
        # 若检测命令失败则记录提示并返回。
        verify_payload["messages"].append("无法检测入口文件，请检查路径权限。")
        return verify_payload
    exists_flag = "__ENTRY_EXISTS__=1" in str(exists_result["stdout"])
    verify_payload["exists"] = exists_flag
    if not exists_flag:
        # 文件不存在时直接返回结果，提示用户检查仓库内容。
        verify_payload["messages"].append("入口文件不存在，请确认仓库结构或分支。")
        return verify_payload
    # 第二步：尝试使用 python3 -m py_compile 进行语法检查。
    compile_cmd = (
        f"cd {_quote(normalized_dir)} && python3 -m py_compile {_quote(entry_name)}"
        if normalized_dir
        else f"python3 -m py_compile {_quote(entry_name)}"
    )
    compile_result = _execute_remote(user=user, host=host, command=compile_cmd, keyfile=keyfile)
    if compile_result["returncode"] == 0:
        # 当命令成功时，标记 py_compiles 为 True。
        verify_payload["py_compiles"] = True
    else:
        # 当命令失败时，记录失败信息以提示用户排查。
        verify_payload["messages"].append("python3 -m py_compile 执行失败，请确认远端已安装 Python3 且脚本无语法错误。")
    # 返回验证结果。
    return verify_payload


# 定义一个辅助函数，用于以富文本形式打印部署结果摘要。
def print_deploy_summary(deploy_info: Dict[str, object], verify_info: Dict[str, object]) -> None:
    # 计算入口检查是否通过。
    entry_ok = bool(verify_info.get("exists")) and bool(verify_info.get("py_compiles"))
    # 根据部署与入口检查状态决定主提示颜色。
    summary_color = "green" if deploy_info.get("ok") and entry_ok else "red"
    # 创建表格展示关键信息。
    table = Table(title="远端仓库部署摘要")
    # 添加表头列。
    table.add_column("项目", style="cyan")
    table.add_column("结果", style="magenta")
    # 填充表格数据。
    table.add_row("分支", str(deploy_info.get("branch", "-")))
    table.add_row("提交", str(deploy_info.get("commit", "-")))
    table.add_row("子模块", "✅" if deploy_info.get("has_submodules") else "-" )
    table.add_row("浅克隆", "✅" if deploy_info.get("used_shallow") else "-" )
    table.add_row("入口存在", "✅" if verify_info.get("exists") else "❌")
    table.add_row("入口语法检查", "✅" if verify_info.get("py_compiles") else "❌")
    table.add_row("入口路径", str(verify_info.get("path", "-")))
    # 输出表格与整体状态。
    console.print(table)
    console.print(
        f"[bold {summary_color}]Deployed branch={deploy_info.get('branch', '-')} "
        f"commit={deploy_info.get('commit', '-')} entry={'OK' if entry_ok else 'FAIL'}[/bold {summary_color}]"
    )
    # 如果存在提示信息，则以 JSON 形式输出，方便开发者调试。
    messages = deploy_info.get("messages", [])
    if messages:
        console.print("[blue]附加信息：[/blue]")
        console.print(json.dumps(messages, ensure_ascii=False, indent=2))
    extra = verify_info.get("messages")
    if extra:
        console.print("[blue]入口检查说明：[/blue]")
        console.print(json.dumps(extra, ensure_ascii=False, indent=2))
