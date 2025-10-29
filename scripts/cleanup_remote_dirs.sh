#!/usr/bin/env bash
#
# 通过 SSH 清理远端 ASR 程序目录下的临时文件。
#
# 使用示例：
#   scripts/cleanup_remote_dirs.sh ubuntu@198.13.46.63
#   scripts/cleanup_remote_dirs.sh -i ~/.ssh/id_rsa ubuntu@198.13.46.63
#   scripts/cleanup_remote_dirs.sh --dry-run ubuntu@198.13.46.63
#
# 默认会清空以下目录中的所有文件：
#   /home/ubuntu/asr_program/audio
#   /home/ubuntu/asr_program/output
# 仅会删除目录中的内容，不会移除目录本身。

set -euo pipefail

usage() {
  cat <<'USAGE'
用法：cleanup_remote_dirs.sh [选项] <user@host>

必选参数：
  user@host         SSH 目标，例如 ubuntu@198.13.46.63

可选参数：
  -i, --identity    指定私钥文件（透传给 ssh 的 -i 参数）
  -p, --port        指定 SSH 端口（默认 22）
  --dry-run         仅列出将要删除的文件，不执行删除
  -h, --help        显示本帮助信息并退出
USAGE
}

if ! command -v ssh >/dev/null 2>&1; then
  echo "[ERROR] 本地未找到 ssh 命令，请先安装 OpenSSH 客户端。" >&2
  exit 1
fi

TARGET=""
SSH_OPTS=()
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--identity)
      if [[ $# -lt 2 ]]; then
        echo "[ERROR] --identity 需要一个参数。" >&2
        exit 1
      fi
      SSH_OPTS+=("-i" "$2")
      shift 2
      ;;
    -p|--port)
      if [[ $# -lt 2 ]]; then
        echo "[ERROR] --port 需要一个参数。" >&2
        exit 1
      fi
      SSH_OPTS+=("-p" "$2")
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "[ERROR] 未知参数：$1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -z "$TARGET" ]]; then
        TARGET="$1"
        shift
      else
        echo "[ERROR] 多余的位置参数：$1" >&2
        usage >&2
        exit 1
      fi
      ;;
  esac
done

if [[ -z "$TARGET" && $# -gt 0 ]]; then
  TARGET="$1"
  shift
fi

if [[ -z "$TARGET" ]]; then
  echo "[ERROR] 请提供 SSH 目标 (user@host)。" >&2
  usage >&2
  exit 1
fi

if [[ $# -gt 0 ]]; then
  echo "[ERROR] 收到多余的参数：$*" >&2
  usage >&2
  exit 1
fi

# 如需调整目标目录，请确保同时更新下方 heredoc 中的 remote_dirs 数组。
REMOTE_DIRS=(
  /home/ubuntu/asr_program/audio
  /home/ubuntu/asr_program/output
)

printf '[INFO] 正在连接 %s 并清理以下目录：\n' "$TARGET"
for dir in "${REMOTE_DIRS[@]}"; do
  printf '  - %s\n' "$dir"
done

if [[ "$DRY_RUN" == "1" ]]; then
  printf '[INFO] 已启用 dry-run 模式，远端仅会列出即将删除的条目。\n'
fi

ssh "${SSH_OPTS[@]}" "$TARGET" "DRY_RUN=${DRY_RUN} bash -s" <<'EOF_REMOTE'
set -euo pipefail
DRY_RUN="${DRY_RUN}"
remote_dirs=(
  /home/ubuntu/asr_program/audio
  /home/ubuntu/asr_program/output
)
for dir in "${remote_dirs[@]}"; do
  if [ ! -d "$dir" ]; then
    printf "[SKIP] 目录不存在：%s\n" "$dir"
    continue
  fi
  if [ "$DRY_RUN" = "1" ]; then
    printf "[DRY-RUN] 将会删除 %s 内的以下条目：\n" "$dir"
    find "$dir" -mindepth 1 -maxdepth 1 -print | sed "s/^/  /"
  else
    printf "[CLEAN] 正在删除目录 %s 内的所有内容...\n" "$dir"
    find "$dir" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    printf "[DONE] 已清理目录：%s\n" "$dir"
  fi
done
EOF_REMOTE

