#!/usr/bin/env bash
# 声明脚本使用 Bash 解释器执行，确保在远端 Ubuntu 环境中兼容。

# 开启严格模式：-e 遇到错误即退出，-u 禁止使用未定义变量，-o pipefail 保证管道失败被捕获。
set -euo pipefail

# 输出脚本开始执行的信息，便于日志排查。
echo "[INFO] 启动远端环境检查与安装流程。"

# ==========================================================
# 检查并安装 rsync（确保文件同步功能正常）
# ==========================================================
# 打印正在检查 rsync 的提示。
echo "[CHECK] rsync ..."
# 使用 command -v 检测 rsync 是否存在。
if ! command -v rsync &>/dev/null; then
    # 当未检测到 rsync 时输出警告。
    echo "[WARN] 远端未检测到 rsync。"
    # 询问用户是否需要自动安装 rsync。
    read -p "是否自动安装 rsync？(y/n): " choice
    # 判断用户输入是否为 y 或 Y。
    if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
        # 提示开始安装 rsync。
        echo "[INSTALL] 开始安装 rsync..."
        # 依次执行 apt-get update 与 apt-get install。
        if sudo apt-get update && sudo apt-get install -y rsync; then
            # 安装成功后打印 rsync 版本信息。
            echo "[OK] rsync 安装成功：$(rsync --version | head -n1)"
        else
            # 当安装失败时输出错误信息并退出。
            echo "[FAIL] rsync 安装失败，请检查 apt 源配置。" >&2
            exit 1
        fi
    else
        # 当用户选择不安装时给出跳过提示。
        echo "[SKIP] 用户取消安装 rsync。程序可能无法同步文件。"
    fi
else
    # 当检测到 rsync 已安装时打印版本信息。
    echo "[OK] rsync 已安装：$(rsync --version | head -n1)"
fi

# 输出脚本结束信息，表示检查流程完成。
echo "[INFO] 远端环境检查流程结束。"
