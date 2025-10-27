# main.py
# 该脚本是 VULTRagent 项目的入口文件，负责提供一个命令行菜单框架。
# 导入 json 模块以处理状态文件读写。
import json
# 导入 os 模块以便读取环境变量。
import os
# 导入 sys 模块，以便在需要时退出程序。
import sys
# 导入 time 模块用于测量 API 请求耗时。
import time
# 导入 re 模块以便在解析配置时处理 Windows 路径中的反斜杠。
import re
# 导入 string 模块用于处理十六进制字符集合。
import string
# 导入 subprocess 模块以捕获外部命令异常。
import subprocess
# 导入 shlex 模块以在提示命令时进行转义。
import shlex
# 导入 pathlib.Path 以便构建跨平台的文件路径。
from pathlib import Path
# 导入 typing 模块中的 Callable、Dict 和 List 类型用于类型注解。
from typing import Callable, Dict, List, Tuple
# 导入 requests 库以捕获网络请求异常。
import requests
# 导入 typer 库以构建命令行应用。
import typer
# 导入 rich.console 中的 Console 类用于美观的终端输出。
from rich.console import Console
# 导入 rich.table 中的 Table 类用于展示菜单。
from rich.table import Table
# 导入 yaml 库以读取配置模板。
import yaml
# 从 core.vultr_api 模块导入真实的 API 函数。
from core.vultr_api import get_instance_info, list_instances
# 从 core.remote_exec 模块导入 SSH、日志与 tmux 管理函数以及 rsync 安装工具。
from core.remote_exec import (
    run_ssh_command,
    tail_remote_log,
    tail_and_mirror_log,
    stop_tmux_session,
    has_tmux_session,
    install_remote_rsync,
)
# 从 core.env_check 模块导入本地 rsync 检测函数。
from core.env_check import ensure_local_rsync
# 从 core.file_transfer 模块导入文件传输、结果回传与仓库部署函数。
from core.file_transfer import (
    upload_local_to_remote,
    fetch_results_from_remote,
    deploy_repo,
    verify_entry,
    print_deploy_summary,
    make_local_results_dir,
    rotate_remote_log,
    cleanup_remote_outputs,
)
# 从 core.remote_bootstrap 模块导入远端部署与报告函数。
from core.remote_bootstrap import upload_and_bootstrap, print_health_report
# 从 core.asr_runner 模块导入占位函数。
from core.asr_runner import run_asr_job

# 创建 Typer 应用实例，关闭自动补全以保持菜单体验一致。
app = typer.Typer(add_completion=False)
# 创建 Console 实例以用于彩色输出。
console = Console()

# 定义配置文件的默认路径，用户可在同目录下提供 config.yaml 覆盖。
CONFIG_PATH = "config.yaml"
# 定义示例配置文件路径，用于在找不到实际配置时加载示例内容。
CONFIG_EXAMPLE_PATH = "config.example.yaml"

# 定义旧版本中默认使用的远端音频与输出目录，便于自动迁移。
LEGACY_REMOTE_INPUT_DIR = "/home/ubuntu/asr_inputs"
LEGACY_REMOTE_OUTPUT_DIR = "/home/ubuntu/asr_outputs"

# 定义状态文件的路径常量。
STATE_PATH = Path(__file__).resolve().parent / ".state.json"
# 定义 Vultr API 默认基础地址常量。
DEFAULT_API_BASE = "https://api.vultr.com"
# 定义全局缓存用于保存最近一次获取的实例列表。
LAST_INSTANCE_CACHE: List[Dict] = []


# 定义一个函数用于安全读取配置文件。
def _escape_unknown_backslashes(value: str) -> Tuple[str, bool]:
    """修正 YAML 双引号字符串中未转义的反斜杠。"""

    result: List[str] = []
    i = 0
    changed = False
    hex_digits = set(string.hexdigits)

    while i < len(value):
        char = value[i]
        if char != "\\":
            result.append(char)
            i += 1
            continue

        # 处理合法的 YAML 转义序列，保持原样。
        if i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in {'\\', '"', '/', 'b', 'f', 'n', 'r', 't'}:
                result.append("\\")
                result.append(nxt)
                i += 2
                continue
            if nxt == 'x' and i + 3 < len(value) and all(
                ch in hex_digits for ch in value[i + 2 : i + 4]
            ):
                result.append("\\")
                result.append('x')
                result.extend(value[i + 2 : i + 4])
                i += 4
                continue
            if nxt == 'u' and i + 5 < len(value) and all(
                ch in hex_digits for ch in value[i + 2 : i + 6]
            ):
                result.append("\\")
                result.append('u')
                result.extend(value[i + 2 : i + 6])
                i += 6
                continue
            if nxt == 'U' and i + 9 < len(value) and all(
                ch in hex_digits for ch in value[i + 2 : i + 10]
            ):
                result.append("\\")
                result.append('U')
                result.extend(value[i + 2 : i + 10])
                i += 10
                continue

        # 其余情况视为普通反斜杠，需要额外转义。
        result.append("\\\\")
        if i + 1 < len(value):
            result.append(value[i + 1])
            i += 2
        else:
            i += 1
        changed = True

    return "".join(result), changed


def _sanitize_windows_paths(yaml_text: str) -> str:
    """尝试将双引号中的 Windows 路径自动转义。"""

    pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
    changed_any = False

    def repl(match: re.Match) -> str:
        nonlocal changed_any
        original_content = match.group(1)
        corrected, changed = _escape_unknown_backslashes(original_content)
        if changed:
            changed_any = True
            return f'"{corrected}"'
        return match.group(0)

    sanitized = pattern.sub(repl, yaml_text)
    return sanitized if changed_any else yaml_text


def _load_yaml_file(path: str) -> Dict:
    """读取 YAML 文件并在必要时自动修正 Windows 路径反斜杠。"""

    with open(path, "r", encoding="utf-8") as handle:
        yaml_text = handle.read()

    try:
        return yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        sanitized = _sanitize_windows_paths(yaml_text)
        if sanitized != yaml_text:
            try:
                data = yaml.safe_load(sanitized) or {}
            except yaml.YAMLError as inner_exc:
                raise RuntimeError(
                    "配置文件包含未转义的反斜杠且自动修正失败，请将 Windows 路径使用单引号或双反斜杠书写。"
                ) from inner_exc
            console.print(
                "[yellow]检测到 config.yaml 中的 Windows 路径缺少转义，已在运行时自动修正。"
                "建议将路径使用单引号包裹或写成双反斜杠以避免该提示。[/yellow]"
            )
            return data
        raise RuntimeError(
            "解析配置文件失败，请检查 YAML 语法是否正确。"
        ) from exc


def _normalize_remote_paths(config_data: Dict) -> None:
    """将旧版本的远端路径配置迁移到新的 asr_program 目录结构。"""

    if not config_data:
        return

    remote_conf = config_data.setdefault("remote", {})
    project_dir = (remote_conf.get("project_dir", "") or "").strip()
    project_dir = project_dir.rstrip("/")
    derived_inputs = f"{project_dir}/audio" if project_dir else ""
    derived_outputs = f"{project_dir}/output" if project_dir else ""

    inputs_dir = (remote_conf.get("inputs_dir") or "").strip()
    outputs_dir = (remote_conf.get("outputs_dir") or "").strip()

    changed = False

    if derived_inputs and inputs_dir in {"", LEGACY_REMOTE_INPUT_DIR}:
        remote_conf["inputs_dir"] = derived_inputs
        inputs_dir = derived_inputs
        changed = True

    if derived_outputs and outputs_dir in {"", LEGACY_REMOTE_OUTPUT_DIR}:
        remote_conf["outputs_dir"] = derived_outputs
        outputs_dir = derived_outputs
        changed = True

    asr_conf = config_data.setdefault("asr", {})
    asr_args = asr_conf.setdefault("args", {})

    if inputs_dir and asr_args.get("input_dir") in {None, "", LEGACY_REMOTE_INPUT_DIR}:
        asr_args["input_dir"] = inputs_dir
        changed = True

    if outputs_dir and asr_args.get("output_dir") in {None, "", LEGACY_REMOTE_OUTPUT_DIR}:
        asr_args["output_dir"] = outputs_dir
        changed = True

    if changed:
        console.print(
            "[yellow]检测到旧版目录配置，已自动迁移到 /home/ubuntu/asr_program/audio 与 /home/ubuntu/asr_program/output。[/yellow]"
        )


def load_configuration() -> Dict:
    # 该函数尝试读取真实配置文件，否则回退到示例配置。
    if os.path.exists(CONFIG_PATH):
        config_data = _load_yaml_file(CONFIG_PATH)
        _normalize_remote_paths(config_data)
        return config_data

    # 如果真实配置不存在，则读取示例配置提醒用户。
    config_data = _load_yaml_file(CONFIG_EXAMPLE_PATH)
    _normalize_remote_paths(config_data)
    console.print("[yellow]未找到 config.yaml，使用示例配置运行占位菜单。[/yellow]")
    return config_data

# 定义一个函数用于获取 Vultr API Key。
def fetch_vultr_api_key() -> str:
    # 通过环境变量获取 API Key，符合安全要求。
    api_key = os.environ.get("VULTR_API_KEY", "")
    # 如果未配置 API Key，则打印警告。
    if not api_key:
        console.print("[red]警告：未检测到 VULTR_API_KEY 环境变量，部分功能仅为占位演示。[/red]")
    # 返回 API Key（可能为空字符串）。
    return api_key

# 定义辅助函数以从配置中解析 Vultr API 基础地址。
def resolve_api_base(config: Dict) -> str:
    # 尝试从配置中读取自定义的 API 地址。
    return config.get("vultr", {}).get("api_base", DEFAULT_API_BASE)


# 定义辅助函数将实例列表缓存到全局变量。
def cache_instances(instances: List[Dict]) -> None:
    # 首先清空现有缓存内容。
    LAST_INSTANCE_CACHE.clear()
    # 将新的实例逐个追加到缓存中。
    LAST_INSTANCE_CACHE.extend(instances)


# 定义辅助函数从磁盘读取状态文件。
def load_state() -> Dict:
    # 如果状态文件不存在则抛出 FileNotFoundError。
    if not STATE_PATH.exists():
        raise FileNotFoundError("state file not found")
    # 打开状态文件并读取 JSON 内容。
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        # 使用 json.load 解析文件并返回状态字典。
        return json.load(handle)


# 定义辅助函数将状态写入磁盘。
def save_state(state: Dict) -> None:
    # 使用 with 语句安全地写入 JSON 文件。
    with STATE_PATH.open("w", encoding="utf-8") as handle:
        # 使用 json.dump 将状态内容写入磁盘。
        json.dump(state, handle, ensure_ascii=False, indent=2)


# 定义一个函数用于列出 Vultr 实例并展示表格。
def handle_list_instances(config: Dict) -> None:
    # 解析 Vultr API 基础地址。
    api_base = resolve_api_base(config)
    # 记录开始时间以计算请求耗时。
    start_time = time.perf_counter()
    try:
        # 调用 list_instances 获取实例列表。
        instances = list_instances(api_base)
    except ValueError:
        # 捕获缺少 API 密钥的情况并向用户提示。
        console.print("[red]未检测到 VULTR_API_KEY，请先设置环境变量后再试。[/red]")
        return
    except requests.RequestException as exc:
        # 捕获 requests 层面的网络错误。
        console.print(f"[red]网络请求失败：{exc}[/red]")
        return
    except RuntimeError as exc:
        # 捕获 API 返回的错误并输出具体信息。
        console.print(f"[red]列出实例失败：{exc}[/red]")
        return
    # 计算请求耗时。
    duration = time.perf_counter() - start_time
    # 将成功获取的实例列表写入缓存。
    cache_instances(instances)
    # 创建 Rich 表格展示信息。
    table = Table(title="Vultr 实例列表")
    # 添加行号列帮助用户选择实例。
    table.add_column("行号", justify="right", style="cyan")
    # 添加实例 ID 列。
    table.add_column("实例 ID", style="magenta")
    # 添加标签列。
    table.add_column("标签")
    # 添加主 IP 列。
    table.add_column("主 IP")
    # 添加状态列。
    table.add_column("状态")
    # 添加电源状态列。
    table.add_column("电源")
    # 添加区域列。
    table.add_column("区域")
    # 添加计划列。
    table.add_column("计划")
    # 遍历实例列表并逐行写入表格。
    for index, instance in enumerate(instances, start=1):
        table.add_row(
            str(index),
            instance.get("id", "-"),
            instance.get("label", "-"),
            instance.get("main_ip", "-"),
            instance.get("status", "-"),
            instance.get("power_status", "-"),
            instance.get("region", "-"),
            instance.get("plan", "-"),
        )
    # 打印表格。
    console.print(table)
    # 在表格下方输出实例总数和 API 耗时。
    console.print(f"[bold blue]共 {len(instances)} 个实例，API 耗时 {duration:.2f} 秒[/bold blue]")


# 定义函数用于选择实例并保存到状态文件。
def handle_select_instance(config: Dict) -> None:
    # 如果缓存为空则尝试重新列出实例。
    if not LAST_INSTANCE_CACHE:
        console.print("[yellow]当前没有实例缓存，正在尝试获取列表……[/yellow]")
        handle_list_instances(config)
        # 如果再次尝试后仍然没有数据则直接返回。
        if not LAST_INSTANCE_CACHE:
            return
    # 提示用户输入要选择的行号。
    choice = typer.prompt("请输入要选择的实例行号")
    try:
        # 将输入转换为整数索引。
        index = int(choice)
    except ValueError:
        # 如果输入无法转换为整数则提示错误。
        console.print("[red]请输入有效的数字行号。[/red]")
        return
    # 将行号转换为列表索引。
    if index < 1 or index > len(LAST_INSTANCE_CACHE):
        # 当索引越界时提示用户。
        console.print("[red]行号超出范围，请先使用菜单 1 查看最新列表。[/red]")
        return
    # 根据索引获取目标实例。
    instance = LAST_INSTANCE_CACHE[index - 1]
    # 构造需要持久化的状态数据。
    state_payload = {
        "instance_id": instance.get("id", ""),
        "ip": instance.get("main_ip", ""),
        "label": instance.get("label", ""),
    }
    try:
        # 将状态写入磁盘。
        save_state(state_payload)
    except OSError as exc:
        # 捕获文件写入异常并提示用户。
        console.print(f"[red]写入 .state.json 失败：{exc}[/red]")
        return
    # 输出成功提示并强调状态文件已经更新。
    console.print("[bold green]已保存到 .state.json[/bold green]")
    # 同时打印当前选择的实例信息供用户确认。
    console.print(f"当前实例：{state_payload['label']} ({state_payload['instance_id']}) @ {state_payload['ip']}")


# 定义函数用于查看当前实例详情。
def handle_show_instance_details(config: Dict) -> None:
    try:
        # 尝试从状态文件读取当前实例信息。
        state = load_state()
    except FileNotFoundError:
        # 状态文件不存在时给出指引。
        console.print("[red]尚未选择实例，请先使用菜单 2 进行选择。[/red]")
        return
    except json.JSONDecodeError:
        # 状态文件损坏时提示用户重新选择。
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 从状态中提取实例 ID。
    instance_id = state.get("instance_id")
    # 如果没有实例 ID 则提示用户。
    if not instance_id:
        console.print("[red]状态文件缺少 instance_id，请重新选择实例。[/red]")
        return
    # 解析 Vultr API 基础地址。
    api_base = resolve_api_base(config)
    try:
        # 调用 get_instance_info 获取实例详情。
        instance_info = get_instance_info(api_base, instance_id)
    except ValueError:
        # 当缺少 API Key 时提醒用户设置环境变量。
        console.print("[red]未检测到 VULTR_API_KEY，请先设置环境变量后再试。[/red]")
        return
    except requests.RequestException as exc:
        # 捕获网络错误并输出提示。
        console.print(f"[red]网络请求失败：{exc}[/red]")
        return
    except RuntimeError as exc:
        # 捕获 API 错误并提示用户。
        console.print(f"[red]获取实例详情失败：{exc}[/red]")
        return
    # 创建表格展示实例详情。
    detail_table = Table(title=f"实例详情 - {instance_info.get('label', instance_id)}")
    # 添加字段列。
    detail_table.add_column("字段", style="cyan")
    # 添加值列。
    detail_table.add_column("值", style="magenta")
    # 定义需要展示的字段顺序列表。
    display_fields = [
        "id",
        "label",
        "main_ip",
        "region",
        "plan",
        "os",
        "status",
        "power_status",
        "ram",
        "disk",
        "vcpu_count",
        "created_at",
    ]
    # 遍历字段列表并添加到表格中。
    for field in display_fields:
        detail_table.add_row(field, str(instance_info.get(field, "-")))
    # 打印实例详情表格。
    console.print(detail_table)

# 定义处理 SSH 测试的函数。
def handle_test_ssh(config: Dict) -> None:
    # 若未加载配置文件，则无法执行 SSH 测试。
    if not config:
        console.print("[red]未加载配置文件，请先创建 config.yaml。[/red]")
        return

    ssh_conf = config.get("ssh", {}) if config else {}
    ssh_user = ssh_conf.get("user", "")
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请补全后再试。[/red]")
        return

    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""

    target_host = ""
    host_source = ""

    try:
        state = load_state()
    except FileNotFoundError:
        state = {}
    except json.JSONDecodeError:
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return

    if state:
        target_host = state.get("ip", "")
        if target_host:
            host_source = ".state.json"

    if not target_host:
        target_host = ssh_conf.get("host", "")
        if target_host:
            host_source = "配置文件 ssh.host"

    if not target_host:
        console.print(
            "[red]无法确定 SSH 目标主机。请先使用菜单 2 保存实例，或在 config.yaml 中配置 ssh.host。[/red]"
        )
        return

    test_command = (
        ssh_conf.get("test_command")
        or "echo '✅ SSH 连接正常'; whoami; hostname; uptime"
    )
    remote_command = f"bash -lc {shlex.quote(test_command)}"

    source_display = host_source or "未知"
    console.print(
        f"[blue]正在测试 SSH 连接：{ssh_user}@{target_host}（来源：{source_display}）[/blue]"
    )
    if ssh_key_path:
        console.print(f"[blue]使用私钥：{ssh_key_path}[/blue]")
    console.print(f"[blue]执行命令：{test_command}[/blue]")

    try:
        result = run_ssh_command(
            host=target_host,
            user=ssh_user,
            keyfile=ssh_key_path or None,
            command=remote_command,
        )
    except OSError as exc:
        console.print(f"[red]执行 ssh 命令失败：{exc}[/red]")
        return

    if result.returncode == 0:
        console.print("[green]✅ SSH 测试成功。[/green]")
    else:
        console.print(f"[red]❌ SSH 测试失败，返回码 {result.returncode}。[/red]")
        console.print("[yellow]请检查 IP、用户名、私钥路径以及安全组设置后重试。[/yellow]")

# 定义运行远端环境部署的函数。
def handle_remote_bootstrap(config: Dict) -> None:
    # 首先尝试读取状态文件，获取当前选择的实例信息。
    try:
        state = load_state()
    except FileNotFoundError:
        # 若状态文件不存在，则提醒用户先选择实例。
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        # 当状态文件格式损坏时提醒用户重新选择。
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 从状态信息中提取远端 IP 地址，允许通过环境变量覆盖。
    ip_address = state.get("ip", "")
    env_host = os.environ.get("VULTR_REMOTE_HOST", "").strip()
    if env_host:
        ip_address = env_host
    # 如果没有 IP 地址则无法继续操作。
    if not ip_address:
        console.print(
            "[red]无法确定远端 IP 地址，请先在菜单 2 保存实例或设置 VULTR_REMOTE_HOST 环境变量。[/red]"
        )
        return
    # 读取 ssh 配置段，获取用户名与密钥路径。
    ssh_conf = config.get("ssh", {}) if config else {}
    # 获取远端登录用户名。
    ssh_user = ssh_conf.get("user", "") or os.environ.get("VULTR_REMOTE_USER", "").strip()
    # 如果未配置用户名则提示用户补全配置。
    if not ssh_user:
        console.print(
            "[red]缺少远端登录用户名，请在 config.yaml 配置 ssh.user 或设置 VULTR_REMOTE_USER 环境变量。[/red]"
        )
        return
    # 解析私钥路径，允许留空以使用默认凭据。
    ssh_key = ssh_conf.get("keyfile", "") or os.environ.get("VULTR_REMOTE_KEYFILE", "")
    # 如果用户提供了私钥路径，则展开 ~ 以获得绝对路径。
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 构造本地脚本路径并确保其存在。
    local_script_path = Path(__file__).resolve().parent / "scripts" / "bootstrap_remote.sh"
    # 设置远端临时脚本路径，可通过配置覆盖，默认位于 /tmp。
    remote_tmp_path = config.get("remote", {}).get("bootstrap_tmp_path", "/tmp/vultragentsvc_bootstrap.sh")
    # 在终端提示用户正在执行的操作。
    console.print(f"[blue]正在将部署脚本上传到 {ip_address} …[/blue]")
    try:
        # 在部署脚本之前确保远端 rsync 已就绪。
        install_remote_rsync(
            user=ssh_user,
            host=ip_address,
            keyfile=ssh_key_path or None,
        )
        # 调用核心函数上传脚本并执行远端部署流程。
        report = upload_and_bootstrap(
            user=ssh_user,
            host=ip_address,
            keyfile=ssh_key_path,
            local_script_path=str(local_script_path),
            remote_tmp_path=remote_tmp_path,
            config=config,
        )
    except FileNotFoundError as exc:
        # 当脚本缺失时向用户输出明确的错误提示。
        console.print(f"[red]远端部署脚本缺失：{exc}[/red]")
        return
    except subprocess.CalledProcessError as exc:
        # 捕获 scp/ssh 运行失败的情况，并展示返回码。
        console.print(f"[red]远端命令执行失败：{exc}[/red]")
        return
    except OSError as exc:
        # 捕获底层系统错误，例如 ssh 命令不可用等。
        console.print(f"[red]执行远端部署时出现系统错误：{exc}[/red]")
        return
    # 调用打印函数展示远端健康检查报告。
    print_health_report(report)

# 定义部署 ASR 仓库的函数。
def handle_deploy_repo(config: Dict) -> None:
    # 在执行部署前尝试读取状态文件，确保已经选择实例。
    try:
        # 尝试解析 .state.json 获取目标实例信息。
        state = load_state()
    except FileNotFoundError:
        # 当状态文件不存在时提示用户先执行菜单 2。
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        # 当状态文件内容损坏时提示用户重新选择实例。
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 从状态中获取远端 IP 地址。
    ip_address = state.get("ip", "")
    # 如果缺少 IP 信息则无法继续部署。
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 读取 SSH 配置段，用于构造远端登录凭据。
    ssh_conf = config.get("ssh", {}) if config else {}
    # 获取远端用户名。
    ssh_user = ssh_conf.get("user", "")
    # 若用户名缺失则提醒用户补全配置。
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请先更新 config.yaml。[/red]")
        return
    # 解析私钥路径，允许使用默认 ssh-agent。
    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 读取 Git 配置以获取仓库地址与分支。
    git_conf = config.get("git", {}) if config else {}
    repo_url = git_conf.get("repo_url", "")
    branch = git_conf.get("branch", "")
    prefer_https_raw = git_conf.get("prefer_https", False)
    if isinstance(prefer_https_raw, str):
        prefer_https = prefer_https_raw.strip().lower() in {"1", "true", "yes", "on"}
    else:
        prefer_https = bool(prefer_https_raw)
    # 校验仓库地址是否配置。
    if not repo_url:
        console.print("[red]配置文件缺少 git.repo_url，无法执行部署。[/red]")
        return
    # 校验分支是否配置。
    if not branch:
        console.print("[red]配置文件缺少 git.branch，无法执行部署。[/red]")
        return
    # 读取远端项目目录。
    remote_conf = config.get("remote", {}) if config else {}
    project_dir = remote_conf.get("project_dir", "")
    if not project_dir:
        console.print("[red]配置文件缺少 remote.project_dir，无法执行部署。[/red]")
        return
    # 解析入口脚本名称，默认使用 asr_quickstart.py。
    entry_name = config.get("asr", {}).get("entry", "asr_quickstart.py")
    # 在终端输出部署起始提示。
    console.print(f"[blue]即将部署仓库到 {ip_address}:{project_dir}，分支 {branch}。[/blue]")
    try:
        # 调用核心函数执行远端仓库部署。
        deploy_info = deploy_repo(
            user=ssh_user,
            host=ip_address,
            repo_url=repo_url,
            branch=branch,
            project_dir=project_dir,
            keyfile=ssh_key_path or None,
            prefer_https=prefer_https,
        )
    except OSError as exc:
        # 捕获本地执行 ssh/git 命令时的系统错误。
        console.print(f"[red]执行远端部署时出现系统错误：{exc}[/red]")
        return
    # 根据部署结果决定是否继续校验入口文件。
    if deploy_info.get("ok"):
        try:
            # 仓库部署成功后验证入口脚本。
            verify_info = verify_entry(
                user=ssh_user,
                host=ip_address,
                project_dir=project_dir,
                entry_name=entry_name or "asr_quickstart.py",
                keyfile=ssh_key_path or None,
            )
        except OSError as exc:
            # 捕获执行验证时可能出现的 ssh 错误。
            console.print(f"[red]入口检查失败：{exc}[/red]")
            verify_info = {
                "exists": False,
                "py_compiles": False,
                "path": f"{project_dir.rstrip('/')}/{entry_name}",
                "messages": ["入口校验时发生 ssh 错误。"],
            }
    else:
        # 若部署失败则构造占位的入口检查结果。
        verify_info = {
            "exists": False,
            "py_compiles": False,
            "path": f"{project_dir.rstrip('/')}/{entry_name}",
            "messages": ["仓库部署未完成，未执行入口检查。"],
        }
    # 打印部署摘要信息，包含分支、提交与入口校验结果。
    print_deploy_summary(deploy_info, verify_info)
    # 根据综合状态给出下一步建议。
    entry_ok = bool(verify_info.get("exists")) and bool(verify_info.get("py_compiles"))
    if deploy_info.get("ok") and entry_ok:
        console.print("[green]✅ 仓库部署完成，可继续执行：[/green]")
        console.print("  • 菜单 8：上传本地素材到远端输入目录。")
        console.print("  • 菜单 7：在 tmux 中后台运行 asr_quickstart.py。")
    else:
        console.print("[red]❌ 部署或入口检查未通过，请检查上述输出并重试。[/red]")
        console.print("[yellow]常见问题：确认 SSH 凭据、仓库分支与入口文件路径是否正确；如提示 python3 缺失，请先运行菜单 5 进行环境部署。[/yellow]")

# 定义上传素材到远端的函数。
def handle_upload_materials(config: Dict) -> None:
    # 在执行前检查配置是否存在。
    if not config:
        console.print("[red]未加载配置文件，请先创建 config.yaml。[/red]")
        return
    try:
        # 读取状态文件获取当前实例信息。
        state = load_state()
    except FileNotFoundError:
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 提取远端 IP 地址。
    ip_address = state.get("ip", "")
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 解析 SSH 配置获取用户名与私钥。
    ssh_conf = config.get("ssh", {})
    ssh_user = ssh_conf.get("user", "")
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请补全后重试。[/red]")
        return
    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 获取远端 inputs 目录配置。
    remote_conf = config.get("remote", {})
    inputs_dir = remote_conf.get("inputs_dir", "")
    project_dir = remote_conf.get("project_dir", "")
    outputs_dir = remote_conf.get("outputs_dir", "")
    if not inputs_dir:
        console.print("[red]配置文件缺少 remote.inputs_dir，无法确定上传目标。[/red]")
        return
    # 获取本地素材目录配置。
    transfer_conf = config.get("transfer", {})
    local_dir = transfer_conf.get("upload_local_dir", "") or "./materials"
    # 输出上传摘要信息。
    console.print(f"[blue]即将把 {local_dir} 上传到 {ssh_user}@{ip_address}:{inputs_dir}。[/blue]")
    try:
        # 调用核心函数执行上传。
        upload_local_to_remote(
            local_path=local_dir,
            user=ssh_user,
            host=ip_address,
            remote_inputs_dir=inputs_dir,
            keyfile=ssh_key_path or None,
            remote_project_dir=project_dir,
            remote_outputs_dir=outputs_dir,
        )
    except (FileNotFoundError, NotADirectoryError) as exc:
        console.print(f"[red]上传失败：{exc}[/red]")
        return
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]上传过程中命令失败，退出码 {exc.returncode}。[/red]")
        return
    except RuntimeError as exc:
        console.print(f"[red]上传失败：{exc}[/red]")
        return
    # 上传成功后给出下一步建议与远端统计命令。
    console.print("[green]✅ 上传完成，可继续执行菜单 7 启动 ASR。[/green]")
    ssh_hint = "ssh"
    if ssh_key_path:
        ssh_hint += f" -i {shlex.quote(ssh_key_path)}"
    remote_find = f"find {shlex.quote(inputs_dir)} -type f | wc -l"
    ssh_hint += f" {ssh_user}@{ip_address} \"{remote_find}\""
    console.print(f"[blue]可选统计命令：{ssh_hint}[/blue]")

# 定义在 tmux 中后台运行 ASR 的函数。
def handle_run_asr_tmux(config: Dict) -> None:
    # 校验配置是否加载。
    if not config:
        console.print("[red]未加载配置文件，请先创建 config.yaml。[/red]")
        return
    try:
        # 从状态文件中读取当前实例信息。
        state = load_state()
    except FileNotFoundError:
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 解析远端 IP 地址。
    ip_address = state.get("ip", "")
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 解析 SSH 用户名与密钥。
    ssh_conf = config.get("ssh", {})
    ssh_user = ssh_conf.get("user", "")
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请补全后重试。[/red]")
        return
    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 输出启动摘要。
    console.print(f"[blue]即将在 {ip_address} 的 tmux 中运行 ASR 任务。[/blue]")
    try:
        # 调用核心函数启动 tmux 后台任务。
        result_code = run_asr_job(
            user=ssh_user,
            host=ip_address,
            keyfile=ssh_key_path or None,
            cfg=config,
        )
    except OSError as exc:
        console.print(f"[red]执行远端命令时出现系统错误：{exc}[/red]")
        return
    # 根据返回码输出提示。
    if result_code == 0:
        console.print("[green]✅ 已启动 ASR 任务，请继续使用菜单 9 查看实时日志。[/green]")
    else:
        console.print(f"[red]❌ ASR 任务启动失败，返回码 {result_code}。请检查上述输出。[/red]")

# 定义实时查看远端日志的函数。
def handle_tail_logs(config: Dict) -> None:
    # 校验配置是否加载。
    if not config:
        console.print("[red]未加载配置文件，请先创建 config.yaml。[/red]")
        return
    try:
        # 读取状态文件获取当前实例。
        state = load_state()
    except FileNotFoundError:
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 获取远端 IP。
    ip_address = state.get("ip", "")
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 获取 SSH 配置。
    ssh_conf = config.get("ssh", {})
    ssh_user = ssh_conf.get("user", "")
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请补全后重试。[/red]")
        return
    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 获取日志文件路径。
    remote_conf = config.get("remote", {})
    log_file = remote_conf.get("log_file", "")
    if not log_file:
        console.print("[red]配置文件缺少 remote.log_file，无法查看日志。[/red]")
        return
    # 解析本地日志镜像配置。
    logging_conf = config.get("logging", {}) if config else {}
    mirror_on_view = logging_conf.get("mirror_on_view", True)
    local_root = logging_conf.get("local_root", "./logs")
    local_filename = logging_conf.get("filename", "run.log")
    mirror_interval = logging_conf.get("mirror_interval_sec", 3)
    try:
        mirror_interval_value = int(mirror_interval)
    except (TypeError, ValueError):
        mirror_interval_value = 3
    # 提示用户正在连接并展示日志位置。
    console.print(f"[blue]开始实时查看 {ip_address}:{log_file}，按 Ctrl+C 结束。[/blue]")
    try:
        if mirror_on_view:
            # 当启用镜像时，调用增强函数同步日志到本地。
            exit_code = tail_and_mirror_log(
                user=ssh_user,
                host=ip_address,
                remote_log=log_file,
                local_log_dir=local_root,
                local_filename=local_filename,
                keyfile=ssh_key_path or None,
                mirror_interval_sec=mirror_interval_value,
            )
        else:
            # 否则退回到轻量版 tail。
            exit_code = tail_remote_log(
                user=ssh_user,
                host=ip_address,
                log_path=log_file,
                keyfile=ssh_key_path or None,
            )
    except OSError as exc:
        console.print(f"[red]查看日志时发生系统错误：{exc}[/red]")
        return
    # 根据退出码提供后续操作建议。
    if exit_code == 0:
        console.print("[green]✅ 日志查看结束，可继续执行菜单 10 回传结果。[/green]")
    else:
        console.print(f"[yellow]日志查看结束，退出码 {exit_code}。可根据需要执行菜单 10 回传结果。[/yellow]")

# 定义回传 ASR 结果的函数。
def handle_fetch_results(config: Dict) -> None:
    # 若未加载配置文件则无法继续操作。
    if not config:
        console.print("[red]未加载配置文件，请先创建 config.yaml。[/red]")
        return
    try:
        # 读取状态文件以确定目标实例。
        state = load_state()
    except FileNotFoundError:
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 提取实例信息以用于目录组织与输出提示。
    instance_label = state.get("label", "")
    instance_id = state.get("instance_id", "")
    ip_address = state.get("ip", "")
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 解析 SSH 登录配置。
    ssh_conf = config.get("ssh", {})
    ssh_user = ssh_conf.get("user", "")
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请补全后再试。[/red]")
        return
    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 解析远端结果目录。
    remote_conf = config.get("remote", {})
    outputs_dir = remote_conf.get("outputs_dir", "")
    project_dir = remote_conf.get("project_dir", "")
    inputs_dir = remote_conf.get("inputs_dir", "")
    if not outputs_dir:
        console.print("[red]配置文件缺少 remote.outputs_dir，无法回传结果。[/red]")
        return
    # 读取传输相关配置，提供合理的默认值。
    transfer_conf = config.get("transfer", {})
    results_root = transfer_conf.get("results_root", "./results")
    download_glob = (transfer_conf.get("download_glob") or "").strip() or None
    retries = transfer_conf.get("retries", 3)
    backoff = transfer_conf.get("retry_backoff_sec", 3)
    verify_manifest = transfer_conf.get("verify_manifest", True)
    manifest_name = transfer_conf.get("manifest_name", "_manifest.txt")
    # 将数值型配置转换为整数，并处理潜在异常。
    try:
        retries = int(retries)
    except (TypeError, ValueError):
        retries = 3
    try:
        backoff = int(backoff)
    except (TypeError, ValueError):
        backoff = 3
    # 构建本地结果目录并展示路径。
    local_results_dir = make_local_results_dir(
        results_root=results_root,
        instance_label=instance_label,
        instance_id=instance_id,
    )
    console.print(
        f"[blue]即将从 {ip_address}:{outputs_dir} 回传结果到 {local_results_dir}。[/blue]"
    )
    if download_glob:
        console.print(
            f"[blue]仅会下载符合模式 {download_glob} 的文件。[/blue]"
        )
    # 调用核心函数执行回传与重试逻辑。
    try:
        result = fetch_results_from_remote(
            user=ssh_user,
            host=ip_address,
            remote_outputs_dir=outputs_dir,
            local_results_dir=local_results_dir,
            keyfile=ssh_key_path or None,
            pattern=download_glob,
            retries=max(retries, 0),
            backoff_sec=max(backoff, 1),
            verify_manifest=bool(verify_manifest),
            manifest_name=manifest_name,
            remote_project_dir=project_dir,
            remote_inputs_dir=inputs_dir,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        console.print(f"[red]回传过程中发生错误：{exc}[/red]")
        console.print("[yellow]请检查网络连通性、磁盘空间与 SSH 权限后重试。[/yellow]")
        return
    # 输出汇总信息，包含目录、校验结果与缺失统计。
    if result.get("ok"):
        console.print("[green]✅ 结果回传完成。[/green]")
    else:
        console.print("[yellow]⚠️ 回传完成，但清单校验存在异常。[/yellow]")
    console.print(f"[cyan]本地结果目录：{result.get('local_dir')}[/cyan]")
    if result.get("manifest"):
        console.print(f"[cyan]本地清单文件：{result.get('manifest')}[/cyan]")
    if bool(verify_manifest):
        if result.get("verified"):
            console.print("[green]清单校验：通过。[/green]")
        else:
            missing_count = len(result.get("missing", []))
            mismatch_count = len(result.get("size_mismatch", []))
            console.print(
                f"[yellow]清单校验未通过，缺失 {missing_count} 个文件，大小不匹配 {mismatch_count} 个。[/yellow]"
            )
            if missing_count:
                console.print(f"[yellow]缺失文件示例：{result.get('missing')[:5]}[/yellow]")
            if mismatch_count:
                console.print(
                    f"[yellow]大小不一致示例：{result.get('size_mismatch')[:3]}[/yellow]"
                )
    # 根据配置执行可选的清理动作。
    cleanup_conf = config.get("cleanup", {})
    if result.get("ok"):
        if cleanup_conf.get("rotate_remote_logs"):
            log_file = remote_conf.get("log_file", "")
            keep_logs = cleanup_conf.get("keep_log_backups", 5)
            try:
                keep_logs = int(keep_logs)
            except (TypeError, ValueError):
                keep_logs = 5
            if log_file:
                rotate_remote_log(
                    user=ssh_user,
                    host=ip_address,
                    log_path=log_file,
                    keep=max(keep_logs, 1),
                    keyfile=ssh_key_path or None,
                )
            else:
                console.print("[yellow]未配置 remote.log_file，跳过日志轮转。[/yellow]")
        if cleanup_conf.get("remove_remote_outputs"):
            cleanup_remote_outputs(
                user=ssh_user,
                host=ip_address,
                outputs_dir=outputs_dir,
                keyfile=ssh_key_path or None,
            )
    else:
        console.print("[yellow]检测到回传存在异常，已跳过远端清理操作。[/yellow]")
    # 给出下一步建议。
    console.print("[blue]可继续执行菜单 11 停止远端任务或查看结果目录。[/blue]")

# 定义停止或清理远端任务的函数。
def handle_cleanup_remote(config: Dict) -> None:
    # 校验配置是否加载。
    if not config:
        console.print("[red]未加载配置文件，请先创建 config.yaml。[/red]")
        return
    try:
        # 尝试读取状态文件获取当前实例信息。
        state = load_state()
    except FileNotFoundError:
        console.print("[red]尚未选择实例，请先使用菜单 2 保存目标实例。[/red]")
        return
    except json.JSONDecodeError:
        console.print("[red].state.json 内容无效，请重新选择实例。[/red]")
        return
    # 解析基础信息以便输出提示。
    ip_address = state.get("ip", "")
    instance_label = state.get("label", state.get("instance_id", ""))
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 解析 SSH 配置。
    ssh_conf = config.get("ssh", {})
    ssh_user = ssh_conf.get("user", "")
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请补全后再试。[/red]")
        return
    ssh_key = ssh_conf.get("keyfile", "")
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 读取远端目录与 tmux 配置。
    remote_conf = config.get("remote", {})
    session_name = remote_conf.get("tmux_session", "")
    log_file = remote_conf.get("log_file", "")
    outputs_dir = remote_conf.get("outputs_dir", "")
    cleanup_conf = config.get("cleanup", {})
    console.print(
        f"[blue]正在处理 {instance_label} ({ip_address}) 的后台任务与清理操作。[/blue]"
    )
    # 如果配置了 tmux 会话，则先检测并尝试停止。
    if session_name:
        exists = has_tmux_session(
            user=ssh_user,
            host=ip_address,
            session=session_name,
            keyfile=ssh_key_path or None,
        )
        if exists:
            stop_tmux_session(
                user=ssh_user,
                host=ip_address,
                session=session_name,
                keyfile=ssh_key_path or None,
            )
    else:
        console.print("[yellow]未配置 remote.tmux_session，跳过 tmux 停止步骤。[/yellow]")
    # 根据配置执行日志轮转。
    if cleanup_conf.get("rotate_remote_logs"):
        keep_logs = cleanup_conf.get("keep_log_backups", 5)
        try:
            keep_logs = int(keep_logs)
        except (TypeError, ValueError):
            keep_logs = 5
        if log_file:
            rotate_remote_log(
                user=ssh_user,
                host=ip_address,
                log_path=log_file,
                keep=max(keep_logs, 1),
                keyfile=ssh_key_path or None,
            )
        else:
            console.print("[yellow]未配置 remote.log_file，跳过日志轮转。[/yellow]")
    # 根据配置执行 outputs 目录清理。
    if cleanup_conf.get("remove_remote_outputs"):
        if outputs_dir:
            cleanup_remote_outputs(
                user=ssh_user,
                host=ip_address,
                outputs_dir=outputs_dir,
                keyfile=ssh_key_path or None,
            )
        else:
            console.print("[yellow]未配置 remote.outputs_dir，跳过远端输出清理。[/yellow]")
    # 输出总结信息。
    console.print("[blue]清理流程结束，可根据需要重新运行 ASR 或退出程序。[/blue]")

# 建立菜单选项与处理函数的映射。
MENU_ACTIONS: Dict[str, Dict[str, Callable[[Dict], None]]] = {
    # 每个键为用户输入的序号，值为包含描述和处理函数的字典。
    "1": {"label": "列出 Vultr 实例", "handler": handle_list_instances},
    "2": {"label": "选择当前实例并保存", "handler": handle_select_instance},
    "3": {"label": "查看当前实例详情", "handler": handle_show_instance_details},
    "4": {"label": "连接并测试 SSH", "handler": handle_test_ssh},
    "5": {"label": "一键环境部署/检查（远端）", "handler": handle_remote_bootstrap},
    "6": {"label": "部署/更新 ASR 仓库到远端", "handler": handle_deploy_repo},
    "7": {"label": "在 tmux 中后台运行 asr_quickstart.py", "handler": handle_run_asr_tmux},
    "8": {"label": "上传本地素材到远端输入目录", "handler": handle_upload_materials},
    "9": {"label": "实时查看远端日志", "handler": handle_tail_logs},
    "10": {"label": "回传 ASR 结果到本地", "handler": handle_fetch_results},
    "11": {"label": "停止/清理远端任务", "handler": handle_cleanup_remote},
    "12": {"label": "退出", "handler": lambda config: sys.exit(0)},  # 使用匿名函数统一出口逻辑。
}

# 定义打印菜单的函数。
def render_menu() -> None:
    # 创建一个表格用于展示菜单项。
    table = Table(title="VULTRagent 主菜单")
    # 添加序号列。
    table.add_column("序号", style="cyan", justify="center")
    # 添加操作描述列。
    table.add_column("操作", style="magenta")
    # 遍历 MENU_ACTIONS 并将每项加入表格。
    for key, info in MENU_ACTIONS.items():
        table.add_row(key, info["label"])
    # 输出表格。
    console.print(table)

# 定义主循环函数，用于交互式处理用户输入。
def interactive_menu() -> None:
    # 读取配置数据。
    config = load_configuration()
    # 获取 Vultr API Key。
    fetch_vultr_api_key()
    # 进入无限循环直到用户选择退出。
    while True:
        # 每次循环先渲染菜单。
        render_menu()
        # 提示用户输入操作序号。
        choice = typer.prompt("请输入操作序号", default="12")
        # 根据输入查找对应的菜单项。
        action_info = MENU_ACTIONS.get(choice)
        # 如果找到了有效的操作。
        if action_info:
            # 调用对应的处理函数。
            action_info["handler"](config)
        else:
            # 如果输入无效则提示用户。
            console.print(f"[red]无效的选项: {choice}，请重新输入。[/red]")

# 使用 Typer 的命令装饰器将 interactive_menu 暴露为 CLI 命令。
@app.command()
def menu() -> None:
    # Typer 命令函数，仅调用 interactive_menu 启动菜单。
    interactive_menu()

# 如果脚本作为主程序运行，则根据参数决定如何启动。
if __name__ == "__main__":
    # 在程序入口处提示用户进行环境检测。
    print("\n=== 环境检测阶段 ===")
    # 调用 ensure_local_rsync 检测本地 rsync 是否可用。
    if not ensure_local_rsync(interactive=True):
        # 当本地缺少 rsync 时给出警告提示。
        print("[WARN] 本地 rsync 未就绪，请确认安装后重启程序。")
    # 当没有额外命令行参数时直接进入交互式菜单，满足 "python main.py" 启动要求。
    if len(sys.argv) == 1:
        # 直接调用交互式菜单。
        interactive_menu()
    else:
        # 若带有参数则交由 Typer 处理，保持灵活性。
        app()
