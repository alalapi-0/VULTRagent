#!/usr/bin/env bash
# 声明脚本解释器并保证在 Bash 环境中运行。

# 开启严格模式以便在出现错误时尽早失败，同时防止未定义变量被使用。
set -euo pipefail

# 定义一个辅助函数用于输出标准化的状态行，供上层程序解析。
log_status() {
  # 该函数期望传入三个参数：检查名称、状态和值得展示的消息。
  local name="$1"
  local state="$2"
  local message="$3"
  # 使用统一格式打印状态，方便远端 Python 客户端解析。
  printf 'STATUS:%s:%s:%s\n' "$name" "$state" "$message"
}

# 记录整体执行状态，默认为 OK，如果后续步骤失败会被置为 FAIL。
OVERALL_STATUS="OK"

# 定义需要安装的核心依赖列表，满足 Round 3 中列出的要求。
REQUIRED_PACKAGES=(
  git
  git-lfs
  python3
  python3-venv
  python3-pip
  tmux
  rsync
  ffmpeg
  libavcodec-extra
  curl
  ca-certificates
)

# 允许通过环境变量覆盖包管理器命令，默认使用 apt-get。
PKG_MANAGER_COMMAND=${PKG_MANAGER_COMMAND:-"apt-get"}

# 如果系统存在 sudo 并且当前命令非 root，则自动在前面加上 sudo。
if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
  # 通过 sudo 执行包管理器命令以获得必要权限。
  PKG_MANAGER_COMMAND="sudo ${PKG_MANAGER_COMMAND}"
fi

# 更新包索引，确保后续安装能够获取最新的软件版本。
DEBIAN_FRONTEND=noninteractive eval "$PKG_MANAGER_COMMAND update -y"

# 安装所需依赖软件包，若已安装则该命令不会破坏系统状态。
DEBIAN_FRONTEND=noninteractive eval "$PKG_MANAGER_COMMAND install -y ${REQUIRED_PACKAGES[*]}"

# 初始化 git lfs，以确保仓库能够正确处理大文件。
git lfs install >/dev/null 2>&1 || true

# 从环境变量读取需要创建的目录路径，若未提供则留空。
BASE_DIR=${BASE_DIR:-""}
PROJECT_DIR=${PROJECT_DIR:-""}
INPUTS_DIR=${INPUTS_DIR:-""}
OUTPUTS_DIR=${OUTPUTS_DIR:-""}
MODELS_DIR=${MODELS_DIR:-""}
LOG_FILE=${LOG_FILE:-""}

# 基于配置初始化音频目录变量，优先使用 inputs_dir 值。
AUDIO_DIR="$INPUTS_DIR"
# 若 inputs_dir 留空但提供了 project_dir，则在项目目录下派生 audio 子目录。
if [ -z "$AUDIO_DIR" ] && [ -n "$PROJECT_DIR" ]; then
  AUDIO_DIR="${PROJECT_DIR%/}/audio"
fi
# 基于配置初始化输出目录变量，优先使用 outputs_dir 值。
OUTPUT_DIR="$OUTPUTS_DIR"
# 若 outputs_dir 留空但提供了 project_dir，则在项目目录下派生 output 子目录。
if [ -z "$OUTPUT_DIR" ] && [ -n "$PROJECT_DIR" ]; then
  OUTPUT_DIR="${PROJECT_DIR%/}/output"
fi

# 组装一个目录数组以便统一创建。
DIRECTORIES_TO_CREATE=()

# 如果基础目录非空则加入创建列表。
if [ -n "$BASE_DIR" ]; then
  DIRECTORIES_TO_CREATE+=("$BASE_DIR")
fi

# 将其他目录逐一加入创建列表。
if [ -n "$PROJECT_DIR" ]; then
  DIRECTORIES_TO_CREATE+=("$PROJECT_DIR")
fi
if [ -n "$INPUTS_DIR" ]; then
  DIRECTORIES_TO_CREATE+=("$INPUTS_DIR")
fi
if [ -n "$OUTPUTS_DIR" ]; then
  DIRECTORIES_TO_CREATE+=("$OUTPUTS_DIR")
fi
if [ -n "$MODELS_DIR" ]; then
  DIRECTORIES_TO_CREATE+=("$MODELS_DIR")
fi

# 如果提供了日志文件路径，则确保其父目录存在。
if [ -n "$LOG_FILE" ]; then
  DIRECTORIES_TO_CREATE+=("$(dirname "$LOG_FILE")")
fi

# 遍历所有需要创建的目录并设置权限为 755，保持幂等。
for directory in "${DIRECTORIES_TO_CREATE[@]}"; do
  # 使用 mkdir -p 避免重复创建时报错。
  mkdir -p "$directory"
  # 设置权限为 755，满足大多数服务的访问需求。
  chmod 755 "$directory" || true
done

# 当配置了项目目录时再额外执行一次确保其存在，避免派生目录时失败。
if [ -n "$PROJECT_DIR" ]; then
  mkdir -p "$PROJECT_DIR"
fi
# 如果计算出了音频目录，则创建并保持幂等。
if [ -n "$AUDIO_DIR" ]; then
  mkdir -p "$AUDIO_DIR"
fi
# 如果计算出了输出目录，则创建并保持幂等。
if [ -n "$OUTPUT_DIR" ]; then
  mkdir -p "$OUTPUT_DIR"
fi
# 若音频或输出目录存在，则将所有权调整为 ubuntu 用户，避免权限问题。
if [ -n "$AUDIO_DIR" ] || [ -n "$OUTPUT_DIR" ]; then
  chown -R ubuntu:ubuntu ${AUDIO_DIR:+"$AUDIO_DIR"} ${OUTPUT_DIR:+"$OUTPUT_DIR"} || true
fi
# 若两个目录均计算成功，则输出提示便于日志检索。
if [ -n "$AUDIO_DIR" ] && [ -n "$OUTPUT_DIR" ]; then
  echo "[OK] Created directories: $AUDIO_DIR, $OUTPUT_DIR"
fi

# 准备处理 Hugging Face 登录相关的环境变量。
PERSIST_HF_LOGIN=${PERSIST_HF_LOGIN:-"false"}
HF_TOKEN_FROM_AGENT=${HF_TOKEN_FROM_AGENT:-""}
HF_HOME=${HF_HOME:-""}
SET_HF_GIT_CREDENTIAL=${SET_HF_GIT_CREDENTIAL:-"true"}
HF_TOKEN=${HF_TOKEN:-""}

# 如果远端环境尚未定义 HF_TOKEN，而配置中提供了 token，则自动补充该变量。
if [ -z "$HF_TOKEN" ] && [ -n "$HF_TOKEN_FROM_AGENT" ]; then
  HF_TOKEN="$HF_TOKEN_FROM_AGENT"
fi

# 将 HF_TOKEN 导出到后续流程，便于健康检查或其他脚本复用。
if [ -n "$HF_TOKEN" ]; then
  export HF_TOKEN
fi

# 记录 Hugging Face 登录状态，默认值为 SKIPPED。
HF_LOGIN_STATUS="SKIPPED"
HF_LOGIN_MESSAGE="未开启持久化登录或缺少 token"

# 当启用了持久化登录并且提供了 token 时，尝试执行 CLI 登录。
if [ "${PERSIST_HF_LOGIN,,}" = "true" ] && [ -n "$HF_TOKEN_FROM_AGENT" ]; then
  # 安装 huggingface_hub[cli] 以获得 huggingface-cli 命令。
  python3 -m pip install --upgrade --quiet "huggingface_hub[cli]" || true
  # 根据可用命令选择兼容的新旧 CLI 调用方式。
  if command -v hf >/dev/null 2>&1; then
    HF_LOGIN_CMD=(hf auth login)
  elif command -v huggingface-cli >/dev/null 2>&1; then
    HF_LOGIN_CMD=(huggingface-cli login)
  else
    HF_LOGIN_STATUS="FAIL"
    HF_LOGIN_MESSAGE="未找到 Hugging Face CLI"
    OVERALL_STATUS="FAIL"
  fi
  # 拼接登录命令及可选参数（避免使用已弃用的 --yes 标志）。
  if [ "$HF_LOGIN_STATUS" != "FAIL" ]; then
    HF_LOGIN_CMD+=(--token "$HF_TOKEN_FROM_AGENT")
    if [ "${SET_HF_GIT_CREDENTIAL,,}" = "true" ]; then
      HF_LOGIN_CMD+=(--add-to-git-credential)
    fi
    # 尝试使用提供的 token 进行登录，并捕获成功或失败信息。
    if "${HF_LOGIN_CMD[@]}" >/tmp/hf_login.log 2>&1; then
      HF_LOGIN_STATUS="OK"
      HF_LOGIN_MESSAGE="CLI 登录成功"
    else
      HF_LOGIN_STATUS="FAIL"
      HF_LOGIN_MESSAGE="CLI 登录失败，请检查 token"
      OVERALL_STATUS="FAIL"
    fi
  fi
  # 输出 CLI 登录日志内容以便调试（安全起见仅在失败时打印）。
  if [ "$HF_LOGIN_STATUS" = "FAIL" ]; then
    cat /tmp/hf_login.log || true
  fi
fi

# 记录 HF_TOKEN 的可用性，方便上层在健康检查报告中观察状态。
if [ -n "$HF_TOKEN" ]; then
  log_status "HF_TOKEN" "OK" "HF_TOKEN 已配置"
else
  log_status "HF_TOKEN" "SKIPPED" "未提供 HF_TOKEN"
fi

# 检查音频目录是否创建成功，如失败则标记整体状态。
if [ -n "$AUDIO_DIR" ]; then
  if [ -d "$AUDIO_DIR" ]; then
    log_status "AUDIO_DIR" "OK" "$AUDIO_DIR 存在"
  else
    log_status "AUDIO_DIR" "FAIL" "$AUDIO_DIR 不存在"
    OVERALL_STATUS="FAIL"
  fi
fi
# 检查输出目录是否创建成功，如失败则标记整体状态。
if [ -n "$OUTPUT_DIR" ]; then
  if [ -d "$OUTPUT_DIR" ]; then
    log_status "OUTPUT_DIR" "OK" "$OUTPUT_DIR 存在"
  else
    log_status "OUTPUT_DIR" "FAIL" "$OUTPUT_DIR 不存在"
    OVERALL_STATUS="FAIL"
  fi
fi

# 如果指定了 HF_HOME，则确保目录存在并将其写入 ~/.bashrc。
if [ -n "$HF_HOME" ]; then
  mkdir -p "$HF_HOME"
  if ! grep -q "^export HF_HOME=" "$HOME/.bashrc" 2>/dev/null; then
    echo "export HF_HOME=\"$HF_HOME\"" >> "$HOME/.bashrc"
  fi
  export HF_HOME
fi

# 输出 Hugging Face 登录状态供上层解析。
log_status "HF_LOGIN" "$HF_LOGIN_STATUS" "$HF_LOGIN_MESSAGE"

# 依次执行健康检查命令，并记录结果到状态列表中。
PYTHON_VERSION_OUTPUT="$(python3 --version 2>&1)" || PYTHON_VERSION_OUTPUT="python3 不可用"
if [[ "${PYTHON_VERSION_OUTPUT,,}" == python* ]]; then
  log_status "PYTHON" "OK" "$PYTHON_VERSION_OUTPUT"
else
  log_status "PYTHON" "FAIL" "$PYTHON_VERSION_OUTPUT"
  OVERALL_STATUS="FAIL"
fi

PIP_VERSION_OUTPUT="$(pip3 --version 2>&1)" || PIP_VERSION_OUTPUT="pip3 不可用"
if [[ "$PIP_VERSION_OUTPUT" == pip* ]]; then
  log_status "PIP" "OK" "$PIP_VERSION_OUTPUT"
else
  log_status "PIP" "FAIL" "$PIP_VERSION_OUTPUT"
  OVERALL_STATUS="FAIL"
fi

TMUX_VERSION_OUTPUT="$(tmux -V 2>&1)" || TMUX_VERSION_OUTPUT="tmux 不可用"
if [[ "$TMUX_VERSION_OUTPUT" == tmux* ]]; then
  log_status "TMUX" "OK" "$TMUX_VERSION_OUTPUT"
else
  log_status "TMUX" "FAIL" "$TMUX_VERSION_OUTPUT"
  OVERALL_STATUS="FAIL"
fi

FFMPEG_VERSION_OUTPUT="$(ffmpeg -version 2>&1 | head -n1)" || FFMPEG_VERSION_OUTPUT="ffmpeg 不可用"
if [[ "$FFMPEG_VERSION_OUTPUT" == ffmpeg* ]]; then
  log_status "FFMPEG" "OK" "$FFMPEG_VERSION_OUTPUT"
else
  log_status "FFMPEG" "FAIL" "$FFMPEG_VERSION_OUTPUT"
  OVERALL_STATUS="FAIL"
fi

FFMPEG_AAC_CODEC_LINE="$(ffmpeg -hide_banner -codecs 2>/dev/null | grep -E '\bDE[A-Z.]*\s+aac\b' || true)"
if [ -n "$FFMPEG_AAC_CODEC_LINE" ]; then
  log_status "FFMPEG_AAC" "OK" "检测到 AAC 解码器：$FFMPEG_AAC_CODEC_LINE"
else
  log_status "FFMPEG_AAC" "FAIL" "未检测到 AAC 解码器，已安装 libavcodec-extra"
  OVERALL_STATUS="FAIL"
fi

# 检查 git 与 git-lfs 命令是否存在，并打印部分环境信息。
if command -v git >/dev/null 2>&1; then
  log_status "GIT" "OK" "$(command -v git)"
else
  log_status "GIT" "FAIL" "git 命令缺失"
  OVERALL_STATUS="FAIL"
fi

git lfs env | head -n3 || true

# 打印磁盘使用情况，便于了解剩余空间。
df -h / | head -n2 || true

# 进行网络连通性检测，优先使用 ping github，如失败再尝试访问 Hugging Face。
if ping -c 1 github.com >/dev/null 2>&1; then
  log_status "NETWORK" "OK" "github.com 可达"
else
  if curl -sSf https://huggingface.co >/dev/null 2>&1; then
    log_status "NETWORK" "OK" "huggingface.co 可达"
  else
    log_status "NETWORK" "FAIL" "网络检测失败"
    OVERALL_STATUS="FAIL"
  fi
fi

# 输出整体执行状态，便于上层判断流程是否顺利。
log_status "OVERALL" "$OVERALL_STATUS" "环境部署与检查完成"

