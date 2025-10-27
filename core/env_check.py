"""core/env_check.py
该模块负责检测并引导安装本地 rsync，确保文件同步能力可用。
"""

# 导入 platform 模块用于判断当前操作系统类型。
import platform
# 导入 shutil 模块以便使用 which 函数查找可执行文件。
import shutil
# 导入 subprocess 模块用于执行系统安装命令。
import subprocess
# 从 core.remote_exec 模块导入 install_remote_rsync 以便其他模块可直接复用。
from core.remote_exec import install_remote_rsync


def ensure_local_rsync(interactive: bool = True) -> bool:
    """检测本地 rsync 是否可用并在必要时引导安装。

    参数:
        interactive: 当为 True 时允许在终端内交互式执行自动安装。

    返回:
        bool: 若最终存在可用的 rsync 命令则返回 True，否则为 False。
    """

    # 使用 shutil.which 查找 rsync 可执行文件路径。
    rsync_path = shutil.which("rsync")
    # 如果找到了路径，则尝试输出版本信息。
    if rsync_path:
        try:
            # 调用 rsync --version 并截取第一行以展示核心版本号。
            version_output = subprocess.check_output(["rsync", "--version"], text=True)
            version_line = version_output.splitlines()[0]
            print(f"[OK] 本地 rsync 已安装: {version_line}")
        except Exception:
            # 读取版本失败时提示用户但仍认为命令存在。
            print("[WARN] 无法读取 rsync 版本，但命令存在。")
        # 返回 True 表示 rsync 已安装。
        return True

    # 未找到 rsync 时输出警告与可能影响的功能。
    print("\n[WARN] 本地未检测到 rsync，部分功能（上传/下载/日志镜像）可能无法使用。")
    # 使用 platform.system 获取操作系统名称并转换为小写以统一比较。
    system_name = platform.system().lower()
    # 提示用户根据系统类型安装 rsync。
    print("请根据系统类型安装 rsync：")
    if "windows" in system_name:
        # 针对 Windows 平台提供两种安装建议。
        print("  - 方法 1（推荐）: 安装 Git for Windows，自带 rsync 命令；")
        print("  - 方法 2: 安装 WSL (Ubuntu)，并运行: sudo apt install -y rsync")
    elif "darwin" in system_name:
        # 针对 macOS 给出 Homebrew 安装方式。
        print("  - macOS: 使用 Homebrew 安装 → brew install rsync")
    else:
        # 默认提示 Linux 用户通过 apt 安装。
        print("  - Linux: 运行 → sudo apt update && sudo apt install -y rsync")

    # 当允许交互且系统非 Windows 时，提供自动安装选项。
    if interactive and "windows" not in system_name:
        try:
            # 询问用户是否需要自动安装。
            choice = input("\n是否自动为本地安装 rsync？(y/n): ").strip().lower()
        except EOFError:
            # 当输入不可用时视为取消安装。
            choice = "n"
        if choice == "y":
            try:
                # 运行 sudo apt update 刷新软件源。
                subprocess.run(["sudo", "apt", "update", "-y"], check=True)
                # 安装 rsync 软件包。
                subprocess.run(["sudo", "apt", "install", "-y", "rsync"], check=True)
                # 安装成功后提示用户。
                print("[OK] 已成功安装 rsync。")
                return True
            except Exception as exc:
                # 捕获安装过程中出现的异常并提示失败原因。
                print(f"[FAIL] 自动安装失败：{exc}")
    # 未能成功安装时返回 False。
    return False


__all__ = ["ensure_local_rsync", "install_remote_rsync"]
