# main.py
# 该脚本是 VULTRagent 项目的入口文件，负责提供一个命令行菜单框架。
# 导入 os 模块以便读取环境变量。
import os
# 导入 sys 模块，以便在需要时退出程序。
import sys
# 导入 typing 模块中的 Callable 和 Dict 类型用于类型注解。
from typing import Callable, Dict
# 导入 typer 库以构建命令行应用。
import typer
# 导入 rich.console 中的 Console 类用于美观的终端输出。
from rich.console import Console
# 导入 rich.table 中的 Table 类用于展示菜单。
from rich.table import Table
# 导入 yaml 库以读取配置模板。
import yaml
# 从 core.vultr_api 模块导入占位函数。
from core.vultr_api import list_instances
# 从 core.remote_exec 模块导入占位函数。
from core.remote_exec import run_ssh_command, start_remote_job_in_tmux, tail_remote_log
# 从 core.file_transfer 模块导入占位函数。
from core.file_transfer import upload_local_to_remote, fetch_results_from_remote, deploy_repo
# 从 core.remote_bootstrap 模块导入占位函数。
from core.remote_bootstrap import run_bootstrap, check_health
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

# 定义菜单项的处理函数，每个函数调用 core 模块中的占位函数。
def handle_list_instances(config: Dict) -> None:
    # 调用 list_instances 函数并显示返回的示例数据。
    instances = list_instances()
    # 使用 rich.Table 展示结果。
    table = Table(title="Vultr 实例列表(示例)")
    # 添加列定义。
    table.add_column("实例 ID")
    table.add_column("名称")
    table.add_column("状态")
    # 遍历示例实例并添加到表格中。
    for instance in instances:
        table.add_row(instance.get("id", "-"), instance.get("name", "-"), instance.get("status", "-"))
    # 输出表格到控制台。
    console.print(table)

# 定义处理 SSH 测试的函数。
def handle_test_ssh(config: Dict) -> None:
    # 调用 run_ssh_command 占位函数，传入示例参数。
    run_ssh_command(host=config.get("ssh", {}).get("host", "example.com"),
                    command="echo 'test'")

# 定义运行远端环境部署的函数。
def handle_remote_bootstrap(config: Dict) -> None:
    # 调用 run_bootstrap 占位函数。
    run_bootstrap(config)

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
    # 调用 check_health 占位函数以演示未来的清理流程。
    check_health(config)

# 定义直接运行 ASR 任务的函数。
def handle_run_asr(config: Dict) -> None:
    # 调用 run_asr_job 占位函数。
    run_asr_job(config)

# 建立菜单选项与处理函数的映射。
MENU_ACTIONS: Dict[str, Dict[str, Callable[[Dict], None]]] = {
    # 每个键为用户输入的序号，值为包含描述和处理函数的字典。
    "1": {"label": "列出 Vultr 实例", "handler": handle_list_instances},
    "2": {"label": "连接并测试 SSH", "handler": handle_test_ssh},
    "3": {"label": "一键环境部署/检查（远端）", "handler": handle_remote_bootstrap},
    "4": {"label": "部署/更新 ASR 仓库到远端", "handler": handle_deploy_repo},
    "5": {"label": "上传本地素材到远端输入目录", "handler": handle_upload_materials},
    "6": {"label": "在 tmux 中后台运行 asr_quickstart.py", "handler": handle_run_asr_tmux},
    "7": {"label": "实时查看远端日志", "handler": handle_tail_logs},
    "8": {"label": "回传 ASR 结果到本地", "handler": handle_fetch_results},
    "9": {"label": "停止/清理远端任务", "handler": handle_cleanup_remote},
    "10": {"label": "退出", "handler": lambda config: sys.exit(0)},  # 使用匿名函数统一出口逻辑。
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
        choice = typer.prompt("请输入操作序号", default="10")
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
