"""core/env_check.py
该模块负责检测并引导安装本地 rsync，确保文件同步能力可用。
"""

# 导入 os 模块用于在运行时调整 PATH 环境变量。
import os
# 导入 platform 模块用于判断当前操作系统类型。
import platform
# 导入 shutil 模块以便使用 which 函数查找可执行文件。
import shutil
# 导入 subprocess 模块用于执行系统安装命令。
import subprocess
# 导入 pathlib.Path 用于跨平台处理本地路径。
from pathlib import Path
# 从 core.remote_exec 模块导入 install_remote_rsync 以便其他模块可直接复用。
from core.remote_exec import install_remote_rsync

# 定义 cwRsync 的官方下载地址，用于在 Windows 环境下自动拉取 rsync。
_CWRSYNC_ZIP_URL = "https://www.itefix.net/dl/cwRsync_6.2.1_x64_free.zip"


def _run_commands(commands):
    """依次执行命令列表，只要有一个失败就返回 False。"""

    for command in commands:
        try:
            subprocess.run(command, check=True)
        except Exception as exc:  # noqa: BLE001 - 需要捕获所有异常以输出原因
            print(f"[FAIL] 执行 {' '.join(command)} 失败：{exc}")
            return False
    return True


def _find_rsync_in_directory(base_dir: Path) -> Path:
    """在指定目录下递归查找 rsync.exe。"""

    for candidate in base_dir.rglob("rsync.exe"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("rsync.exe not found")


def _ensure_windows_rsync_via_cmd() -> bool:
    """使用 cmd + PowerShell 下载并解压 cwRsync，返回是否成功。"""

    download_root = Path.home() / "cwrsync"
    download_root.mkdir(parents=True, exist_ok=True)
    zip_path = download_root / "cwrsync.zip"
    zip_path_str = str(zip_path)
    download_root_str = str(download_root)

    try:
        existing = _find_rsync_in_directory(download_root)
    except FileNotFoundError:
        existing = None

    if existing:
        os.environ["PATH"] = (
            f"{existing.parent}{os.pathsep}{os.environ.get('PATH', '')}"
        )
        if shutil.which("rsync"):
            print(f"[OK] 已检测到本地 cwRsync：{existing.parent}")
            return True

    print("[INFO] 尝试通过 cmd 下载 cwRsync 以获取 rsync 支持……")

    download_cmd = (
        "powershell -NoProfile -ExecutionPolicy Bypass "
        f"-Command \"Invoke-WebRequest -Uri '{_CWRSYNC_ZIP_URL}' -OutFile '{zip_path_str}'\""
    )
    extract_cmd = (
        "powershell -NoProfile -ExecutionPolicy Bypass "
        f"-Command \"Expand-Archive -LiteralPath '{zip_path_str}' -DestinationPath '{download_root_str}' -Force\""
    )

    try:
        subprocess.run(["cmd", "/c", download_cmd], check=True)
        subprocess.run(["cmd", "/c", extract_cmd], check=True)
    except Exception as exc:
        print(f"[FAIL] 调用 cmd 下载或解压 cwRsync 失败：{exc}")
        return False
    finally:
        try:
            if zip_path.exists():
                zip_path.unlink()
        except OSError:
            pass

    try:
        rsync_exe = _find_rsync_in_directory(download_root)
    except FileNotFoundError:
        print("[FAIL] 下载完成后仍未找到 rsync.exe，请检查网络或手动安装。")
        return False

    os.environ["PATH"] = (
        f"{rsync_exe.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    detected = shutil.which("rsync")
    if detected:
        print(f"[OK] 已通过 cwRsync 安装 rsync：{detected}")
        print(
            "[INFO] 当前进程已临时更新 PATH，建议将目录添加到系统 PATH 以便后续使用。"
        )
        return True

    print("[FAIL] 虽已下载 cwRsync，但未能在 PATH 中找到 rsync，请手动检查。")
    return False


def _install_windows_rsync_via_package_managers() -> bool:
    """尝试使用已安装的包管理器在 Windows 上安装 rsync。"""

    installers = [
        (
            "Chocolatey",
            "choco",
            [["choco", "install", "-y", "rsync"]],
        ),
        (
            "Scoop",
            "scoop",
            [["scoop", "install", "rsync"]],
        ),
        (
            "Winget",
            "winget",
            [["winget", "install", "-e", "--id", "cwRsync.cwRsync"]],
        ),
    ]

    for name, executable, commands in installers:
        if not shutil.which(executable):
            continue
        print(f"[INFO] 检测到 {name}，尝试安装 rsync …")
        if not _run_commands(commands):
            continue
        if shutil.which("rsync"):
            print(f"[OK] 已通过 {name} 安装 rsync。")
            return True
        print(f"[WARN] 使用 {name} 安装后仍未在 PATH 中找到 rsync。")
    return False


def _install_unix_rsync_automatically() -> bool:
    """在类 Unix 平台上尽力通过包管理器安装 rsync。"""

    manager_commands = [
        (
            "apt",
            "apt",
            [
                ["sudo", "apt", "update", "-y"],
                ["sudo", "apt", "install", "-y", "rsync"],
            ],
        ),
        (
            "apt-get",
            "apt-get",
            [
                ["sudo", "apt-get", "update", "-y"],
                ["sudo", "apt-get", "install", "-y", "rsync"],
            ],
        ),
        (
            "yum",
            "yum",
            [["sudo", "yum", "install", "-y", "rsync"]],
        ),
        (
            "dnf",
            "dnf",
            [["sudo", "dnf", "install", "-y", "rsync"]],
        ),
        (
            "pacman",
            "pacman",
            [["sudo", "pacman", "-Sy", "--noconfirm", "rsync"]],
        ),
        (
            "apk",
            "apk",
            [["sudo", "apk", "add", "rsync"]],
        ),
        (
            "brew",
            "brew",
            [["brew", "install", "rsync"]],
        ),
    ]

    for name, executable, commands in manager_commands:
        if not shutil.which(executable):
            continue
        print(f"[INFO] 检测到包管理器 {name}，尝试安装 rsync …")
        if not _run_commands(commands):
            continue
        if shutil.which("rsync"):
            print(f"[OK] 已通过 {name} 安装 rsync。")
            return True
        print(f"[WARN] 使用 {name} 安装后仍未在 PATH 中找到 rsync。")
    return False


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

    if "windows" in system_name:
        # Windows 环境下尝试通过 cmd 自动下载 cwRsync。
        if _ensure_windows_rsync_via_cmd():
            return True
        # 如果下载 cwRsync 失败，则尝试使用常见包管理器安装。
        if _install_windows_rsync_via_package_managers():
            return True
        print("请根据系统类型安装 rsync：")
        print("  - 备用方案 1: 安装 Git for Windows 并在 Git Bash 中使用 rsync；")
        print("  - 备用方案 2: 安装 WSL (Ubuntu)，并运行: sudo apt install -y rsync")
        return False

    # 针对非 Windows 平台自动尝试使用包管理器安装。
    if _install_unix_rsync_automatically():
        return True

    print("请根据系统类型安装 rsync：")
    if "darwin" in system_name:
        # 针对 macOS 给出 Homebrew 安装方式。
        print("  - macOS: 使用 Homebrew 安装 → brew install rsync")
    else:
        # 默认提示 Linux 用户通过 apt 安装。
        print("  - Linux: 运行 → sudo apt update && sudo apt install -y rsync")

    if interactive:
        print("[WARN] 自动安装未成功，请手动执行上述命令后重启程序。")
    return False


__all__ = ["ensure_local_rsync", "install_remote_rsync"]
