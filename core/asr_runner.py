# core/asr_runner.py
# 该模块用于封装 ASR 任务执行逻辑，包括命令构建与 tmux 调度。
# 导入 shlex 模块以便在拼接命令时进行安全转义。
import shlex
# 导入 typing 模块中的 Dict、Optional 类型用于类型注解。
from typing import Dict, Optional

# 导入 rich.console.Console 以提供彩色终端输出。
from rich.console import Console

# 从 core.remote_exec 模块导入 tmux 启动函数。
from core.remote_exec import start_remote_job_in_tmux

# 创建 Console 实例用于输出提示信息。
console = Console()


# 定义辅助函数，用于根据配置生成完整的 ASR 启动命令。
def build_asr_command(
    python_bin: str,
    project_dir: str,
    entry: str,
    args_cfg: Dict[str, object],
    non_interactive: bool,
) -> str:
    # 如果入口脚本不是绝对路径，则拼接项目目录形成完整路径。
    entry_path = entry if entry.startswith("/") else f"{project_dir.rstrip('/')}/{entry}"
    # 构造命令的初始部分，包括 Python 可执行文件与入口脚本。
    command_parts = [shlex.quote(python_bin or "python3"), shlex.quote(entry_path)]
    # 定义常见参数与命令行选项的映射表。
    flag_map = {
        "input_dir": "--input",
        "output_dir": "--output",
        "models_dir": "--models-dir",
        "model": "--model",
    }
    # 遍历映射表，将配置中的值转换为命令行参数。
    for key, flag in flag_map.items():
        value = args_cfg.get(key)
        if value:
            command_parts.extend([flag, shlex.quote(str(value))])
    # 处理额外参数列表，允许用户自定义更多 CLI 选项。
    extra_args = args_cfg.get("extra", []) or []
    for item in extra_args:
        command_parts.append(shlex.quote(str(item)))
    # 如果脚本仍然是交互式的，则提示用户在 README 中查看改造建议。
    if not non_interactive:
        console.print("[yellow][asr_runner] 当前入口脚本标记为需要交互，请在 README 查阅改造建议后再执行。[/yellow]")
    # 将所有片段通过空格拼接成最终命令字符串。
    return " ".join(command_parts)


# 定义主函数，根据配置在 tmux 中启动 ASR 任务。
def run_asr_job(
    user: str,
    host: str,
    keyfile: Optional[str],
    cfg: Dict[str, object],
) -> int:
    # 解析远端相关配置，获取 tmux 会话、日志路径与项目目录。
    remote_cfg = cfg.get("remote", {}) if cfg else {}
    tmux_session = remote_cfg.get("tmux_session", "vultragentsvc")
    log_file = remote_cfg.get("log_file", "")
    project_dir = remote_cfg.get("project_dir", "")
    # 若缺少项目目录或日志路径，则无法继续。
    if not project_dir or not log_file:
        console.print("[red][asr_runner] 配置缺少 remote.project_dir 或 remote.log_file。[/red]")
        return 1
    # 解析 ASR 配置，获取入口脚本、Python 解释器及参数列表。
    asr_cfg = cfg.get("asr", {}) if cfg else {}
    entry = asr_cfg.get("entry", "asr_quickstart.py")
    python_bin = asr_cfg.get("python_bin", "python3")
    args_cfg = asr_cfg.get("args", {}) or {}
    non_interactive = asr_cfg.get("non_interactive", True)
    # 调用辅助函数构建命令字符串。
    command = build_asr_command(python_bin, project_dir, entry, args_cfg, non_interactive)
    # 解析 Hugging Face 配置，决定注入哪些环境变量。
    hf_cfg = cfg.get("huggingface", {}) if cfg else {}
    env_vars: Dict[str, str] = {}
    hf_home = hf_cfg.get("hf_home", "")
    if hf_home:
        env_vars["HF_HOME"] = hf_home
    persist_login = hf_cfg.get("persist_login", True)
    if not persist_login:
        token = hf_cfg.get("token", "")
        if token:
            env_vars["HUGGINGFACE_HUB_TOKEN"] = token
        else:
            console.print("[yellow][asr_runner] 未提供 Hugging Face token，可能无法下载模型。[/yellow]")
    # 输出环境变量注入摘要，敏感值替换为 ***。
    if env_vars:
        redacted = []
        for key, value in env_vars.items():
            if any(marker in key.lower() for marker in ["token", "secret", "key"]):
                redacted.append(f"{key}=***")
            else:
                redacted.append(f"{key}={value}")
        console.print(f"[blue][asr_runner] 将注入环境变量：{', '.join(redacted)}[/blue]")
    else:
        console.print("[blue][asr_runner] 未注入额外环境变量，沿用远端持久凭据。[/blue]")
    # 提示用户即将启动 tmux 会话以及日志存放路径。
    console.print(f"[blue][asr_runner] 即将在 {host} 的 tmux 会话 {tmux_session} 中运行命令。[/blue]")
    console.print(f"[blue][asr_runner] 日志将追加到 {log_file}，请通过菜单 7 查看。[/blue]")
    # 调用核心函数启动 tmux 作业，并返回其退出码。
    return start_remote_job_in_tmux(
        user=user,
        host=host,
        cmd=command,
        session=tmux_session,
        log_file=log_file,
        keyfile=keyfile,
        env_vars=env_vars,
    )
