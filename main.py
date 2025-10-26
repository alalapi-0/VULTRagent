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
# 导入 subprocess 模块以捕获外部命令异常。
import subprocess
# 导入 pathlib.Path 以便构建跨平台的文件路径。
from pathlib import Path
# 导入 typing 模块中的 Callable、Dict 和 List 类型用于类型注解。
from typing import Callable, Dict, List
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
# 从 core.remote_exec 模块导入占位函数。
from core.remote_exec import run_ssh_command, start_remote_job_in_tmux, tail_remote_log
# 从 core.file_transfer 模块导入占位函数。
from core.file_transfer import upload_local_to_remote, fetch_results_from_remote, deploy_repo
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

# 定义状态文件的路径常量。
STATE_PATH = Path(__file__).resolve().parent / ".state.json"
# 定义 Vultr API 默认基础地址常量。
DEFAULT_API_BASE = "https://api.vultr.com"
# 定义全局缓存用于保存最近一次获取的实例列表。
LAST_INSTANCE_CACHE: List[Dict] = []


# 定义一个函数用于安全读取配置文件。
def load_configuration() -> Dict:
    # 该函数尝试读取真实配置文件，否则回退到示例配置。
    config_data: Dict = {}
    # 判断 config.yaml 是否存在。
    if os.path.exists(CONFIG_PATH):
        # 如果存在则读取并解析 YAML 内容。
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            # 使用 yaml.safe_load 将 YAML 内容转换为字典。
            config_data = yaml.safe_load(config_file) or {}
    else:
        # 如果真实配置不存在，则读取示例配置提醒用户。
        with open(CONFIG_EXAMPLE_PATH, "r", encoding="utf-8") as example_file:
            config_data = yaml.safe_load(example_file) or {}
            # 输出提示告知用户当前使用示例配置。
            console.print("[yellow]未找到 config.yaml，使用示例配置运行占位菜单。[/yellow]")
    # 返回配置字典。
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
    # 调用 run_ssh_command 占位函数，传入示例参数。
    run_ssh_command(host=config.get("ssh", {}).get("host", "example.com"),
                    command="echo 'test'")

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
    # 从状态信息中提取远端 IP 地址。
    ip_address = state.get("ip", "")
    # 如果没有 IP 地址则无法继续操作。
    if not ip_address:
        console.print("[red]状态文件缺少远端 IP 地址，请重新选择实例。[/red]")
        return
    # 读取 ssh 配置段，获取用户名与密钥路径。
    ssh_conf = config.get("ssh", {}) if config else {}
    # 获取远端登录用户名。
    ssh_user = ssh_conf.get("user", "")
    # 如果未配置用户名则提示用户补全配置。
    if not ssh_user:
        console.print("[red]配置文件缺少 ssh.user，请先更新 config.yaml。[/red]")
        return
    # 解析私钥路径，允许留空以使用默认凭据。
    ssh_key = ssh_conf.get("keyfile", "")
    # 如果用户提供了私钥路径，则展开 ~ 以获得绝对路径。
    ssh_key_path = str(Path(ssh_key).expanduser()) if ssh_key else ""
    # 构造本地脚本路径并确保其存在。
    local_script_path = Path(__file__).resolve().parent / "scripts" / "bootstrap_remote.sh"
    # 设置远端临时脚本路径，可通过配置覆盖，默认位于 /tmp。
    remote_tmp_path = config.get("remote", {}).get("bootstrap_tmp_path", "/tmp/vultragentsvc_bootstrap.sh")
    # 在终端提示用户正在执行的操作。
    console.print(f"[blue]正在将部署脚本上传到 {ip_address} …[/blue]")
    try:
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
    # 调用 deploy_repo 占位函数。
    deploy_repo(config)

# 定义上传素材到远端的函数。
def handle_upload_materials(config: Dict) -> None:
    # 调用 upload_local_to_remote 占位函数。
    upload_local_to_remote(local_path="./samples", remote_path=config.get("remote", {}).get("inputs_dir", ""))

# 定义在 tmux 中后台运行 ASR 的函数。
def handle_run_asr_tmux(config: Dict) -> None:
    # 调用 start_remote_job_in_tmux 占位函数。
    start_remote_job_in_tmux(session_name=config.get("remote", {}).get("tmux_session", "default"),
                             command="python asr_quickstart.py")

# 定义实时查看远端日志的函数。
def handle_tail_logs(config: Dict) -> None:
    # 调用 tail_remote_log 占位函数。
    tail_remote_log(log_file=config.get("remote", {}).get("log_file", ""))

# 定义回传 ASR 结果的函数。
def handle_fetch_results(config: Dict) -> None:
    # 调用 fetch_results_from_remote 占位函数。
    fetch_results_from_remote(remote_path=config.get("remote", {}).get("outputs_dir", ""),
                              local_path="./outputs")

# 定义停止或清理远端任务的函数。
def handle_cleanup_remote(config: Dict) -> None:
    # 目前清理功能尚未实现，此处给出占位提示。
    console.print("[yellow]清理功能将在后续版本中提供。[/yellow]")

# 定义直接运行 ASR 任务的函数。
def handle_run_asr(config: Dict) -> None:
    # 调用 run_asr_job 占位函数。
    run_asr_job(config)

# 建立菜单选项与处理函数的映射。
MENU_ACTIONS: Dict[str, Dict[str, Callable[[Dict], None]]] = {
    # 每个键为用户输入的序号，值为包含描述和处理函数的字典。
    "1": {"label": "列出 Vultr 实例", "handler": handle_list_instances},
    "2": {"label": "选择当前实例并保存", "handler": handle_select_instance},
    "3": {"label": "查看当前实例详情", "handler": handle_show_instance_details},
    "4": {"label": "连接并测试 SSH", "handler": handle_test_ssh},
    "5": {"label": "一键环境部署/检查（远端）", "handler": handle_remote_bootstrap},
    "6": {"label": "部署/更新 ASR 仓库到远端", "handler": handle_deploy_repo},
    "7": {"label": "上传本地素材到远端输入目录", "handler": handle_upload_materials},
    "8": {"label": "在 tmux 中后台运行 asr_quickstart.py", "handler": handle_run_asr_tmux},
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
    # 当没有额外命令行参数时直接进入交互式菜单，满足 "python main.py" 启动要求。
    if len(sys.argv) == 1:
        # 直接调用交互式菜单。
        interactive_menu()
    else:
        # 若带有参数则交由 Typer 处理，保持灵活性。
        app()
