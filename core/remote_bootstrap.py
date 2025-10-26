# core/remote_bootstrap.py
# 该模块负责上传远端引导脚本、执行并解析健康检查结果。

# 导入 json 模块以在解析输出时使用（例如调试时序列化）。
import json
# 导入 os 模块用于在上传后清理临时文件。
import os
# 导入 pathlib.Path 用于处理跨平台的文件路径。
from pathlib import Path
# 导入 re 模块用于匹配脚本输出中的状态行。
import re
# 导入 shlex 模块用于安全地构建 shell 命令。
import shlex
# 导入 tempfile 模块以便在上传前生成临时文件。
import tempfile
# 导入 typing 模块中的 Dict 类型用于类型注解。
from typing import Dict

# 导入 rich.console 中的 Console 以美化终端输出。
from rich.console import Console
# 导入 rich.table 中的 Table 用于以表格形式展示报告。
from rich.table import Table

# 从 core.remote_exec 模块导入封装好的 ssh/scp 函数。
from core.remote_exec import run_ssh_command, scp_upload

# 创建一个 Console 实例供本模块复用。
console = Console()

# 预编译一个正则表达式用于解析脚本输出的状态行。
STATUS_PATTERN = re.compile(r"^STATUS:([^:]+):([^:]+):(.*)$")

# 定义一个辅助函数，用于验证并获取配置中的远端路径信息。
def _extract_remote_paths(config: Dict) -> Dict[str, str]:
    # 尝试获取 remote 配置段，如果不存在则返回空字典。
    remote_conf = config.get("remote", {}) if config else {}
    # 构造一个包含所有需要路径的字典，缺省值为空字符串。
    return {
        "BASE_DIR": remote_conf.get("base_dir", ""),
        "PROJECT_DIR": remote_conf.get("project_dir", ""),
        "INPUTS_DIR": remote_conf.get("inputs_dir", ""),
        "OUTPUTS_DIR": remote_conf.get("outputs_dir", ""),
        "MODELS_DIR": remote_conf.get("models_dir", ""),
        "LOG_FILE": remote_conf.get("log_file", ""),
    }

# 定义一个辅助函数，用于解析 Hugging Face 相关配置。
def _extract_hf_config(config: Dict) -> Dict[str, str]:
    # 读取 huggingface 配置段，若不存在则回退为空字典。
    hf_conf = config.get("huggingface", {}) if config else {}
    # 组装需要传递给远端脚本的环境变量。
    return {
        "PERSIST_HF_LOGIN": "true" if hf_conf.get("persist_login", False) else "false",
        "HF_TOKEN_FROM_AGENT": hf_conf.get("token", ""),
        "HF_HOME": hf_conf.get("hf_home", ""),
        "SET_HF_GIT_CREDENTIAL": "true" if hf_conf.get("set_git_credential", True) else "false",
    }

# 定义一个辅助函数，用于将环境变量字典转换为安全的字符串键值。
def _sanitize_env_values(env: Dict[str, str]) -> Dict[str, str]:
    # 创建一个新的字典以避免修改原始数据。
    sanitized: Dict[str, str] = {}
    # 遍历所有环境变量键值对。
    for key, value in env.items():
        # 对于字符串值，直接转为字符串；若为 None 则跳过。
        if value is not None:
            sanitized[key] = str(value)
    # 返回处理后的字典。
    return sanitized

# 定义一个辅助函数，用于屏蔽敏感字段并用于日志输出。
def _mask_sensitive(env: Dict[str, str]) -> Dict[str, str]:
    # 创建一个副本以免影响原始字典。
    masked = dict(env)
    # 如果包含 HF token，则仅保留长度信息。
    if masked.get("HF_TOKEN_FROM_AGENT"):
        masked["HF_TOKEN_FROM_AGENT"] = "***MASKED***"
    # 返回处理后的字典。
    return masked

# 定义主要函数：上传脚本并在远端执行，返回检查报告。
def upload_and_bootstrap(user: str, host: str, keyfile: str,
                         local_script_path: str, remote_tmp_path: str,
                         config: Dict) -> Dict:
    # 将本地脚本路径转换为 Path 对象以便校验存在性。
    script_path = Path(local_script_path)
    # 如果脚本不存在则抛出异常，指导用户检查仓库完整性。
    if not script_path.exists():
        raise FileNotFoundError(f"脚本不存在: {script_path}")
    # 构造返回结构并先记录上传状态。
    report: Dict = {"upload": {"status": "PENDING", "message": ""},
                    "execution": {"status": "PENDING", "message": ""},
                    "checks": {}}
    # 为了确保远端可以使用 Bash 正确执行脚本，需要保证换行符为 LF。
    # 在 Windows 环境下，仓库文件可能被签出为 CRLF，这会导致远端 bash
    # 出现 `$'\r': command not found` 报错。为此在上传前将脚本内容写入
    # 一个临时文件，并强制使用 Unix 换行符保存。
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", newline="\n") as temp_file:
        temp_file.write(script_path.read_text(encoding="utf-8"))
        temp_path = temp_file.name

    try:
        # 调用 scp_upload 将临时脚本复制到远端指定路径。
        scp_upload(temp_path, remote_tmp_path, host, user=user, keyfile=keyfile or None)
    finally:
        # 无论上传是否成功，都尝试删除临时文件以避免残留。
        try:
            os.unlink(temp_path)
        except OSError:
            pass
    # 更新上传状态为成功。
    report["upload"] = {"status": "OK", "message": "脚本已上传"}
    # 合并远端目录配置与 Hugging Face 配置以构建环境变量字典。
    env_vars = _sanitize_env_values({**_extract_remote_paths(config), **_extract_hf_config(config)})
    # 构建远端命令，使用 bash 执行上传好的脚本并保留可执行权限。
    remote_command = f"bash {shlex.quote(remote_tmp_path)}"
    # 使用 run_ssh_command 执行脚本，并实时打印输出。
    result = run_ssh_command(host, remote_command, user=user, keyfile=keyfile or None, env=env_vars)
    # 根据退出码更新执行状态。
    exec_status = "OK" if result.returncode == 0 else "FAIL"
    report["execution"] = {"status": exec_status, "message": f"退出码 {result.returncode}"}
    # 遍历脚本输出，解析所有符合 STATUS 格式的行。
    for raw_line in result.stdout.splitlines():
        # 使用正则表达式匹配状态信息。
        match = STATUS_PATTERN.match(raw_line.strip())
        # 如果匹配成功，则提取名称、状态和详细信息。
        if match:
            name, state, message = match.groups()
            # 将解析结果写入报告中。
            report["checks"][name] = {"status": state, "message": message}
    # 将已屏蔽敏感信息的环境变量附加到报告中，方便调试。
    report["environment"] = _mask_sensitive(env_vars)
    # 返回最终的报告字典。
    return report

# 定义一个辅助函数，将状态字符串转换为直观的图标。
def _status_icon(status: str) -> str:
    # 将状态转换为大写以便统一比较。
    normalized = (status or "").upper()
    # 根据状态返回不同的 emoji。
    if normalized == "OK":
        return "✅"
    if normalized == "SKIPPED":
        return "⚪"
    return "❌"

# 定义打印健康检查报告的函数。
def print_health_report(report: Dict) -> None:
    # 首先输出上传与执行阶段的概览信息。
    console.print("[bold]远端脚本上传状态：[/bold]" + report.get("upload", {}).get("status", "UNKNOWN"))
    console.print("[bold]远端脚本执行状态：[/bold]" + report.get("execution", {}).get("status", "UNKNOWN"))
    # 创建表格用于展示各项检查结果。
    table = Table(title="远端健康检查报告")
    # 添加列：项目名称、状态与说明。
    table.add_column("检查项", style="cyan")
    table.add_column("状态", style="magenta")
    table.add_column("详情", style="green")
    # 遍历所有解析到的检查结果。
    for name, payload in report.get("checks", {}).items():
        # 提取状态与消息并加入表格。
        status = payload.get("status", "UNKNOWN")
        message = payload.get("message", "")
        table.add_row(name, f"{_status_icon(status)} {status}", message)
    # 输出表格。
    console.print(table)
    # 如果报告中包含环境信息，则打印屏蔽后的变量供调试。
    if "environment" in report:
        console.print("[dim]传递的环境变量：" + json.dumps(report["environment"], ensure_ascii=False))
    # 最后给出下一步提示，便于用户继续操作。
    console.print("[bold blue]下一步建议执行：4. 部署/更新 ASR 仓库。[/bold blue]")
