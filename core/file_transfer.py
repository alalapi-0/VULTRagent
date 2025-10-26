# core/file_transfer.py
# 该模块负责处理文件上传、结果下载以及 Round 4 要求的远端仓库部署逻辑。
# 导入 json 模块用于在调试时格式化输出内容。
import json
# 导入 shlex 模块以确保在构建 shell 命令时进行安全转义。
import shlex
# 导入 subprocess 模块以执行本地外部命令（rsync 或 scp）。
import subprocess
# 导入 shutil 模块以检测 rsync 是否可用。
import shutil
# 导入 pathlib.Path 以处理本地路径的展开与校验。
from pathlib import Path
# 导入 typing 模块中的 Dict、List、Optional 以完善类型注解。
from typing import Dict, List, Optional

# 导入 rich.console.Console 以便在终端呈现彩色输出。
from rich.console import Console
# 导入 rich.table.Table 以便在总结阶段生成信息表格。
from rich.table import Table

# 从 core.remote_exec 模块导入 run_ssh_command 函数以执行远端命令。
from core.remote_exec import run_ssh_command

# 创建全局 Console 实例，便于在本模块中统一输出日志。
console = Console()


# 定义一个辅助函数，用于安全地将路径或参数转换为 shell 可接受的形式。
def _quote(value: str) -> str:
    # 通过 shlex.quote 处理可能包含空格或特殊字符的值。
    return shlex.quote(value)


# 定义一个辅助函数，用于构造带 bash -lc 的远端命令并执行。
def _execute_remote(user: str, host: str, command: str, keyfile: Optional[str]) -> Dict[str, object]:
    # 先拼接 bash -lc 包装层，保证能够执行复合命令。
    wrapped = f"bash -lc {_quote(command)}"
    # 调用 run_ssh_command 执行远端指令，并捕获输出与返回码。
    result = run_ssh_command(host=host, user=user, keyfile=keyfile, command=wrapped)
    # 将执行结果组装成统一的字典格式，便于后续处理。
    return {"returncode": result.returncode, "stdout": result.stdout, "args": result.args}


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
    rsync_path = shutil.which("rsync")
    # 统一构造远端目标字符串，确保以斜杠结尾表示目录。
    remote_target = f"{user}@{host}:{remote_inputs_dir.rstrip('/')}/"
    # 构造 SSH 选项字符串，用于 rsync -e 传递。
    ssh_parts = ["ssh", "-o", "BatchMode=yes"]
    # 如果提供了密钥文件，则追加 -i 选项。
    if keyfile:
        ssh_parts.extend(["-i", keyfile])
    # 将 SSH 命令拼接成字符串，并对每个片段进行 shell 转义。
    ssh_command = " ".join(shlex.quote(part) for part in ssh_parts)
    # 当检测到 rsync 可用时优先使用，以获得增量与进度显示能力。
    if rsync_path:
        console.print("[green][file_transfer] 检测到 rsync，使用 rsync -avz --progress 进行同步。[/green]")
        # 构造 rsync 参数列表，确保末尾带有斜杠以复制目录内容。
        rsync_args = [
            rsync_path,
            "-avz",
            "--progress",
            "-e",
            ssh_command,
            f"{str(local_dir)}/",
            remote_target,
        ]
        # 输出命令摘要以便用户复现，密钥路径不会包含敏感信息。
        console.print(f"[cyan][file_transfer] 执行命令：{' '.join(rsync_args)}[/cyan]")
        # 启动 rsync 并在失败时抛出异常，由调用方捕获并提示。
        subprocess.run(rsync_args, check=True)
        # 成功后告知用户上传完成。
        console.print("[green][file_transfer] rsync 上传完成。[/green]")
        return
    # 若 rsync 不可用则打印降级提示。
    console.print("[yellow][file_transfer] 未检测到 rsync，降级使用 scp -r 批量上传，性能较差。[/yellow]")
    # 构建 scp 参数，保留时间戳并递归复制。
    scp_args = ["scp", "-p", "-r"]
    # 若配置了密钥文件则同样传递给 scp。
    if keyfile:
        scp_args.extend(["-i", keyfile])
    # 获取待上传目录中的所有项目，确保多文件复制到同一目标。
    items = sorted(local_dir.iterdir())
    # 当目录为空时提示用户并提前返回。
    if not items:
        console.print("[yellow][file_transfer] 本地目录为空，未执行上传。[/yellow]")
        return
    # 将所有文件或子目录追加到 scp 参数中。
    for item in items:
        scp_args.append(str(item))
    # 在参数末尾追加远端目标目录。
    scp_args.append(remote_target)
    # 输出最终命令摘要供排查使用。
    console.print(f"[cyan][file_transfer] 执行命令：{' '.join(shlex.quote(arg) for arg in scp_args)}[/cyan]")
    # 执行 scp 上传过程，若失败将抛出异常。
    subprocess.run(scp_args, check=True)
    # 提醒用户使用 scp 时缺乏增量能力，后续可考虑安装 rsync。
    console.print("[green][file_transfer] scp 上传完成，如需更高性能请在本地安装 rsync。[/green]")


# 定义从远端下载结果的占位函数（后续轮次会补全真实逻辑）。
def fetch_results_from_remote(remote_path: str, local_path: str) -> None:
    # 目前功能尚未实现，打印提示以便调试。
    console.print(f"[yellow][file_transfer] fetch_results_from_remote 占位调用 remote={remote_path}, local={local_path}[/yellow]")


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
            # 记录失败原因并返回。
            messages.append("git clone 执行失败，请确认仓库地址与分支存在。")
            return result_payload
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
