# VULTRagent

> **新增内容（Round 6）**：新增结果回传目录组织、断点重试与清单校验，支持回传后日志轮转及远端输出清理。
> **新增内容（Round 5）**：新增素材上传、tmux 后台运行 ASR 及实时日志监控，支持 Hugging Face 环境变量注入与 rsync/scp 兼容流程。
> **新增内容（Round 4）**：新增远端仓库部署/更新流程（支持 git-lfs、子模块、入口校验），并保留 Round 3 的一键环境部署与健康检查能力。

## 项目简介与目标
VULTRagent 旨在通过本地命令行工具自动化管理 Vultr VPS，主要用于远程部署与执行语音识别（ASR）任务。本轮构建了基础代码骨架，后续将逐步完善实际功能。

## 功能概览
当前版本提供以下命令行菜单选项：
1. 列出 Vultr 实例（真实 API 调用，支持分页、耗时统计）
2. 选择当前实例并保存（写入 `.state.json`）
3. 查看当前实例详情（实时请求 API）
4. 连接并测试 SSH（占位）
5. 上传本地素材到远端输入目录（支持 rsync，自动降级为 scp）
6. 在 tmux 中后台运行 `asr_quickstart.py`（非交互，支持 Hugging Face 环境变量注入）
7. 实时查看远端日志（`tail -f` 流式转发，支持 Ctrl+C 退出）
8. 回传 ASR 结果到本地（支持目录分组、过滤、重试与清单校验）
9. 停止/清理远端任务（检测 tmux，会话停止、日志轮转与远端 outputs 清理）
10. 一键环境部署/检查（远端脚本，包含健康检查与 Hugging Face 可选登录）
11. 部署/更新 ASR 仓库到远端（支持 clone/pull、子模块、git-lfs、入口检查）
12. 退出

## 文件结构与说明
```
VULTRagent/
├── main.py                  # 命令行入口，加载菜单并调用核心模块
├── core/
│   ├── vultr_api.py         # Vultr API 封装（实例列表、详情、重试逻辑）
│   ├── remote_exec.py       # SSH / tmux 会话控制 / 日志追踪工具集
│   ├── file_transfer.py     # 文件传输与仓库部署逻辑（rsync 优先，scp 降级）
│   ├── remote_bootstrap.py  # 远端初始化与健康检查逻辑
│   └── asr_runner.py        # ASR 命令构建与 tmux 调度封装
├── scripts/
│   └── bootstrap_remote.sh  # 远端一键脚本（幂等部署与健康检查）
├── config.example.yaml      # 配置模板，供用户复制修改
├── requirements.txt         # Python 依赖清单
└── README.md                # 项目说明文档（本文件）
```

远端部署后的项目根目录会额外包含用于音频输入与输出的子目录：

```
/home/ubuntu/asr_program/
├── audio/      # 上传的音频文件
├── output/     # 转写结果输出目录
```

## 安装与运行步骤
1. 克隆仓库到本地：
   ```bash
   git clone <your-repo-url> && cd VULTRagent
   ```
2. （可选）创建并激活虚拟环境：
   ```bash
   python -m venv .venv
   # Linux / macOS
   source .venv/bin/activate
   # Windows PowerShell
   .venv/Scripts/Activate.ps1
   ```
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
4. 准备配置：
   ```bash
   cp config.example.yaml config.yaml
   # 按需编辑 config.yaml
   ```
5. 设置环境变量（确保不要把 Key 写死在代码中）：
   ```bash
   export VULTR_API_KEY="your_api_key"      # Linux / macOS
   setx VULTR_API_KEY "your_api_key"        # Windows（需重新打开终端）
   ```
6. 运行程序：
   ```bash
   python main.py
   ```

## 🔹 rsync 自动检测与安装

- **本地检测**：程序启动时会自动调用 `ensure_local_rsync` 检查本地环境是否存在 `rsync`。若已安装会打印版本信息；若缺失则根据系统类型给出安装指引。对于 Linux 与 macOS，终端会额外提供 `sudo apt update && sudo apt install -y rsync` 的自动安装选项，并实时输出 `[CHECK]`、`[INSTALL]`、`[OK]`、`[FAIL]` 等提示。
- **远端检测**：在确认本地环境后，CLI 会询问是否检测远端 `rsync`。用户可输入远端用户名、主机地址与可选私钥路径；若远端缺少 `rsync`，可在终端输入 `y` 触发自动安装。安装命令为：
  ```bash
  sudo apt-get update -y && sudo apt-get install -y rsync
  ```
  整个流程同样会输出详细的 `[CHECK]`、`[INSTALL]`、`[OK]`、`[FAIL]` 日志，并在成功后再次获取远端版本号以确认安装结果。
- **功能依赖**：`rsync` 是上传、下载以及日志镜像的核心工具。本地与远端任一侧缺失都会导致文件同步能力受限，因此建议首次运行程序时完成上述检查流程。

## 配置与环境变量
- `VULTR_API_KEY`：必须设置，用于通过 Vultr API 进行身份验证。建议使用环境变量而非写入代码；Windows 可使用 `setx` 永久写入，Linux/macOS 推荐在 `~/.bashrc` 或 `~/.zshrc` 中 export。
- `config.yaml`（可选）：配置文件可覆盖默认 API 地址（`vultr.api_base`），以及 SSH/远端路径等占位项。如果缺失将自动读取 `config.example.yaml` 并提示用户。

## 实例管理
1. 运行 `python main.py` 后进入主菜单。
2. 选择 **1. 列出 Vultr 实例**，程序会调用 `/v2/instances` 接口并显示带行号的表格，同时在表格下方展示实例总数与 API 耗时，例如：
   ```
   ┏━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┓
   ┃ 行号 ┃ 实例 ID             ┃ 标签  ┃ 主 IP ┃ 状态 ┃ 电源 ┃ 区域 ┃ 计划 ┃
   ┣━━━━╋━━━━━━━━━━━━━━━━━━╋━━━━━━━╋━━━━━━━━╋━━━━━━╋━━━━━━╋━━━━━━╋━━━━━━┫
   ┃ 1  ┃ 12345678-...      ┃ demo ┃ 1.2.3.4 ┃ active ┃ running ┃ lax  ┃ vc2-1c-1gb ┃
   ┗━━━━┻━━━━━━━━━━━━━━━━━━┻━━━━━━━┻━━━━━━━━┻━━━━━━┻━━━━━━┻━━━━━━┻━━━━━━┛
   共 1 个实例，API 耗时 0.42 秒
   ```
3. 选择 **2. 选择当前实例并保存**，输入行号后会将实例 ID、IP、标签写入项目根目录的 `.state.json`，终端会提示“已保存到 .state.json”。
4. 选择 **3. 查看当前实例详情**，程序会读取 `.state.json` 并调用 `/v2/instances/{id}` 返回完整字段，最终以表格形式展示包括 `region`、`plan`、`os`、`vcpu_count` 等信息。
5. 如果 `.state.json` 不存在或损坏，菜单会提示重新执行步骤 2。

## 依赖说明
- Python 3.9+
- `requests`：后续与 Vultr API 的 HTTP 交互
- `PyYAML`：加载 YAML 配置文件
- `typer[all]`：构建 CLI 与交互式菜单
- `rich`：美化终端输出

跨平台兼容性说明：
- SSH 连接：在 Linux/macOS 下可使用内置 `ssh`，在 Windows 推荐使用 `OpenSSH`（Windows 10 及以上自带）或 `PuTTY`。确保已将私钥添加至 `ssh-agent`。
- 文件同步：推荐使用 `rsync`（Linux/macOS）或 `rsync` for Windows（可通过 WSL 或 cwRsync 安装）；也可以使用 `scp` 作为替代方案。

## 配置文件说明
请复制 `config.example.yaml` 为 `config.yaml` 并根据实际环境修改：
- `vultr`：API 基础地址等配置。
- `ssh`：默认用户与密钥配置，留空 keyfile 时走 `ssh-agent`。
- `remote`：远端目录、日志路径、tmux 会话名等。
- `git`：ASR 项目的 Git 仓库地址与默认分支。
- `asr`：包含 `entry`、`python_bin`、`non_interactive`、`args`（含 `extra` 数组）等字段，用于拼装非交互命令。
- `transfer`：上传目录（`upload_local_dir`）、回传过滤（`download_glob`）、结果根目录（`results_root`）、重试参数（`retries` / `retry_backoff_sec`）与清单配置（`verify_manifest`、`manifest_name`）。
- `cleanup`：控制回传后的远端清理，例如 `rotate_remote_logs`、`keep_log_backups` 与 `remove_remote_outputs`。
- `huggingface`：Round 3 新增，用于控制 token 注入与 CLI 登录行为。

## 结果回传与目录组织（Round 6）

菜单 **8. 回传 ASR 结果到本地** 会将远端 `remote.outputs_dir` 中的识别产物整理到本地 `transfer.results_root` 目录下，结构如下：

```
./results/<实例标签或 ID>/<YYYYMMDD-HHMMSS>/
├── _manifest.txt          # 可选：远端生成的文件清单
└── ...                    # 真实的 ASR 输出文件（按原始层级保留）
```

- **目录命名规则**：优先使用实例标签作为一级目录，若为空则回退到实例 ID；二级目录使用 UTC 时间戳，方便多轮回传并行存档。
- **过滤策略**：`transfer.download_glob` 支持使用 `*.json`、`*.txt` 等模式，仅回传匹配的文件；留空或删除该字段时，表示全量回传目录内容。
- **重试与退避**：`transfer.retries` 控制失败后的最大重试次数，`transfer.retry_backoff_sec` 为基础等待秒数，每次重试成倍增加。例如默认配置下可能出现：
  ```
  [yellow][file_transfer] 下载失败，第 1 次重试将在 3 秒后进行。原因：...[/yellow]
  [yellow][file_transfer] 下载失败，第 2 次重试将在 6 秒后进行。原因：...[/yellow]
  ```
  当达到最大次数仍失败时，CLI 会提示检查网络、磁盘空间或 SSH 权限。
- **清单生成与校验**：`transfer.verify_manifest` 为 `true` 时，会先在远端生成 `manifest_name`（默认 `_manifest.txt`），内容为 `大小\t相对路径`。该清单为轻量级一致性校验，不包含哈希或加密签名，但足以在断点重试后快速确认文件完整性。
- **Windows 兼容性**：若本地缺少 `rsync`，工具会自动降级为 `scp -r` 下载，再根据 `download_glob` 在本地二次筛选。由于 `scp` 无法原生 include/exclude，请注意下载体积可能增大。推荐：
  - **WSL**：在 Windows 启用 WSL，并在子系统中 `sudo apt install rsync`。
  - **cwRsync**：安装 [cwRsync](https://www.itefix.net/cwrsync) 后在 PowerShell 中调用 `rsync`。若无法安装，请接受 `scp` 降级并关注 README 的差异说明。

回传成功后，若 `cleanup.rotate_remote_logs` 或 `cleanup.remove_remote_outputs` 为 `true`，系统会自动执行相应的远端清理操作，避免日志膨胀或输出目录堆积。日志轮转后的文件名为 `run-YYYYMMDD-HHMMSS.log`，并按照 `keep_log_backups` 保留最近若干份。

## 停止与清理

菜单 **9. 停止/清理远端任务** 提供一键收尾能力，适用于一次 ASR 任务结束后的善后流程：

- **检测并停止 tmux 会话**：先通过 `tmux has-session` 判断会话是否存在，存在时调用 `tmux kill-session` 停止后台任务；若会话不存在，会在终端给出提示。
- **日志轮转**：当 `cleanup.rotate_remote_logs=true` 且配置了 `remote.log_file` 时，当前日志会被重命名为 `run-YYYYMMDD-HHMMSS.log`，随后重新创建空日志文件，并按时间顺序保留最近 `cleanup.keep_log_backups` 份，其余自动删除。
- **远端输出清理**：`cleanup.remove_remote_outputs=true` 时会清空 `remote.outputs_dir` 内的文件（包括隐藏文件），适合下一轮任务前的归零操作。该步骤默认关闭，建议在确认结果已成功回传后再开启。

运行该菜单后，终端会汇总执行的动作，并提示后续可重新上传素材或直接退出。

## 一键远端环境部署/检查
菜单项 **5. 一键环境部署/检查（远端）** 会自动执行以下流程：

1. 将本地 `scripts/bootstrap_remote.sh` 上传到远端 `/tmp/vultragentsvc_bootstrap.sh`（路径可在 `remote.bootstrap_tmp_path` 中自定义）。
2. 通过 `ssh` 注入配置中的远端目录、日志路径、Hugging Face 选项等环境变量。
3. 在远端执行脚本，完成以下任务：
   - 更新包索引并安装 `git`、`git-lfs`、`python3`、`pip`、`tmux`、`rsync`、`ffmpeg`、`curl`、`ca-certificates` 等依赖；
   - 初始化 Git LFS；
   - 创建 `base_dir`、`project_dir`、`inputs_dir`、`outputs_dir`、`models_dir` 及日志目录；
   - 自动派生并创建 `/home/ubuntu/asr_program/audio` 与 `/home/ubuntu/asr_program/output`，并将所有权调整为 `ubuntu:ubuntu`；
   - 可选执行 Hugging Face CLI 持久登录；
   - 运行健康检查：输出 Python、pip、tmux、ffmpeg、git、磁盘空间及网络连通性状态。

部署脚本与文件同步流程会在必要时输出 `[OK] Created directories: ...`，健康检查表格也新增 `AUDIO_DIR` 与 `OUTPUT_DIR` 行以确认目录是否存在；若缺失会直接标记为失败。

脚本采用 `set -euo pipefail` 并保证幂等，多次执行不会破坏现有配置。部署完成后，终端会展示类似如下的状态汇总：

```
STATUS:PYTHON:OK:Python 3.10.12
STATUS:PIP:OK:pip 23.1.2 from /usr/lib/python3/dist-packages/pip
STATUS:FFMPEG:OK:ffmpeg version 5.1.2-...
STATUS:NETWORK:FAIL:网络检测失败
STATUS:OVERALL:FAIL:环境部署与检查完成
```

`print_health_report` 会对上述状态进行解析并以彩色表格展示，清晰标记 ✅/❌。若某一步骤失败，可根据提示在远端手动排查后再次执行菜单 5，脚本会在已有基础上补齐缺失依赖。

## 远端仓库部署（Round 4）

菜单项 **6. 部署/更新 ASR 仓库到远端** 现已接入真实逻辑，推荐流程如下：

- **前置条件**：
  - 已通过菜单 2 选择目标实例，`.state.json` 中包含 `ip` 等字段；
  - 已执行菜单 5 或确认远端已安装 `git`、`git-lfs`、`python3` 等依赖；
  - 本地可通过 `ssh user@host`（Windows 建议使用 WSL 或安装 OpenSSH 客户端）。
- **关键配置项**（位于 `config.yaml`）：
  - `git.repo_url`：支持 SSH（推荐部署密钥）或 HTTPS；
  - `git.branch`：目标分支名，若不存在将提示 `branch not found`；
  - `git.prefer_https`：当值为 `true` 时会将 SSH 地址自动转换为 HTTPS，适合公共仓库或缺少 SSH 密钥的场景；
  - `remote.project_dir`：远端部署目录，脚本会自动创建并切换至该目录。
- **兼容性与安全建议**：
  - 使用 SSH 克隆时建议为目标仓库配置只读 Deploy Key；
  - 使用 HTTPS 克隆时需确保远端已配置 `git-credential`（可与 Hugging Face 的 `--add-to-git-credential` 说明相同处理）；
  - 若仓库包含子模块，确保主仓库与子模块均可访问；
  - 安装 `git-lfs` 后记得执行 `git lfs install`（菜单 5 会自动处理），否则大文件无法同步。

运行菜单 6 后，终端会按照 `[1/6] ensure project_dir` → `[6/6] summarize repository` 的顺序输出步骤，并实时转发远端 `git` 日志。示例输出：

```
[1/6] ensure project_dir
[2/6] fetch/pull repository
...
[6/6] summarize repository
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ 项目         ┃ 结果           ┃
┣━━━━━━━━━━━━━━╋━━━━━━━━━━━━━━━━┫
┃ 分支         ┃ main           ┃
┃ 提交         ┃ a1b2c3d        ┃
┃ 子模块       ┃ -              ┃
┃ 浅克隆       ┃ ✅             ┃
┃ 入口存在     ┃ ✅             ┃
┃ 入口语法检查 ┃ ✅             ┃
┃ 入口路径     ┃ /home/ubuntu/asr_program/asr_quickstart.py ┃
┗━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━┛
Deployed branch=main commit=a1b2c3d entry=OK
```

若部署成功且入口脚本通过 `python3 -m py_compile` 校验，界面会提示接下来可执行的菜单 8（上传素材）与菜单 7（tmux 后台运行）。

**常见问题与排查**：

- `Host key verification failed`：首次连接新主机时请先在本地 `ssh` 一次或使用 `ssh-keyscan` 添加指纹；
- `Permission denied (publickey)`：确认 `ssh.user`、`ssh.keyfile` 与远端授权匹配，并保证 Windows/WSL 下的密钥权限正确；
- `fatal: Remote branch <name> not found`：确认 `git.branch` 与仓库实际分支一致；
- `git lfs pull failed` 或 `git-lfs: command not found`：请重新执行菜单 5 或在远端运行 `git lfs install` 后再次尝试部署。

## 上传素材与运行 ASR（Round 5）

### 前置条件

- 已执行菜单 2 选择目标实例，`.state.json` 中包含 `ip` 等字段；
- 已通过菜单 6 部署/更新 ASR 仓库，确认入口脚本存在且可编译；
- 已运行菜单 5（或手动完成环境部署），确保远端安装了 `tmux`、`rsync`（可选）与 Python 运行环境；
- `config.yaml` 中补全 `ssh`、`remote`、`transfer`、`asr` 与 `huggingface` 配置。

### 菜单 8：上传本地素材到远端输入目录

1. 默认会将 `transfer.upload_local_dir`（示例为 `./materials`）下的全部文件与子目录同步到远端 `remote.inputs_dir`。若目录不存在，程序会自动创建。
2. 优先调用 `rsync -avz --progress`，可增量同步并展示进度；若本地缺少 `rsync`，则自动降级为 `scp -r`，速度较慢且无法增量，请在 README 的“常见问题”中了解差异。
3. Windows 用户可通过以下方式获得 `rsync`：
   - **WSL**：在 Windows 11/10 上启用 WSL，并在 Ubuntu 子系统中运行 `sudo apt install rsync`；
   - **cwRsync**：安装 [cwRsync](https://www.itefix.net/cwrsync) 并在 PowerShell 中调用 `rsync`；若遇到权限问题，可改用默认的 `scp` 降级模式。
4. 上传成功后终端会提示统计命令，例如：
  ```bash
  ssh -i ~/.ssh/id_rsa ubuntu@203.0.113.10 'find /home/ubuntu/asr_program/audio -type f | wc -l'
   ```
   该命令可在远端统计素材数量，验证是否传输完整。

### 菜单 7：在 tmux 中后台运行 ASR

- 程序会根据 `config.yaml` 拼装非交互命令，参数映射如下：

  | 配置项 | 命令行参数 |
  | --- | --- |
  | `asr.python_bin` | Python 可执行文件（默认 `python3`） |
  | `asr.entry` | 入口脚本路径（相对 `remote.project_dir` 或绝对路径） |
  | `asr.args.input_dir` | `--input` |
  | `asr.args.output_dir` | `--output` |
  | `asr.args.models_dir` | `--models-dir` |
  | `asr.args.model` | `--model` |
  | `asr.args.extra` | 追加到命令末尾的自定义参数 |

- 示例：
  ```bash
  python3 /home/ubuntu/asr_program/asr_quickstart.py \
    --input "/home/ubuntu/asr_program/audio" \
    --output "/home/ubuntu/asr_program/output" \
    --models-dir "/home/ubuntu/.cache/asrprogram/models" \
    --model "large-v3"
  ```
- 典型日志片段（通过菜单 9 观察）：
  ```text
  [2024-05-01 12:34:56] Downloading model large-v3...
  [2024-05-01 12:35:10] Loaded model in 14.2s
  [2024-05-01 12:35:12] Processing /home/ubuntu/asr_program/audio/demo.wav
  [2024-05-01 12:35:45] Saved transcript to /home/ubuntu/asr_program/output/demo.json
  ```
- 若 `asr.non_interactive` 为 `false`，CLI 会提示当前脚本仍需交互输入，建议在上游仓库改造为 `argparse` 或使用 `expect` 等工具封装后再接入。
- Hugging Face 变量注入逻辑：
  - `huggingface.persist_login = true`：注入 `HF_HOME`（若配置）与 `HF_TOKEN`（若提供 token），依赖远端已持久登录；
  - `huggingface.persist_login = false`：临时注入 `HF_TOKEN`、`HUGGINGFACE_HUB_TOKEN` 与 `HF_HOME`，执行完毕后凭据不会落盘。
  CLI 会在终端打印环境变量摘要，带 `token`/`secret`/`key` 的值会自动打码为 `***`。
- 启动成功后可通过 `tmux ls` 在远端确认会话存在，日志将写入 `remote.log_file` 并可重复追加。

### 菜单 9：实时日志监控

- 程序通过 `ssh ... tail -n +1 -f <log_file>` 将远端日志逐行转发到本地，适用于监控模型下载、转录进度等输出；
- 终端明确提示“按 Ctrl+C 结束”，中断后命令会返回退出码 130 并继续保留 tmux 会话；
- 查看结束后终端会提示执行菜单 10 回传 ASR 结果，此步骤会按实例标签与时间戳创建本地目录并自动执行重试与清单校验。

### 常见问题

- `tmux: command not found`：说明远端缺少 tmux，请先执行菜单 5（或手动运行 `scripts/bootstrap_remote.sh`）重新部署环境；
- `Permission denied`：检查 `ssh.user`、`ssh.keyfile`、远端目录权限及 `chmod`；如使用 WSL/cwRsync，确保密钥权限遵循 OpenSSH 限制；
- 日志文件为空：确认入口脚本路径正确、命令参数无误；必要时在远端手动执行 README 中的示例命令，或检查 Hugging Face 下载是否因 token 失效而失败；
- Hugging Face 模式差异：`persist_login=true` 适合长期节点，登录一次即可；`persist_login=false` 更安全，每次注入临时 token。若需撤销令牌，请访问 [Hugging Face Access Tokens](https://huggingface.co/settings/tokens) 删除旧 token 并更新 `config.yaml`。
- `rsync` 降级说明：当本地没有 `rsync` 时自动使用 `scp -r`，缺乏增量同步能力；建议尽快安装 `rsync` 以缩短素材同步时间。

## Hugging Face 配置与安全
`config.example.yaml` 中新增的 `huggingface` 段落支持两种工作模式：

- **持久登录（`persist_login: true`）**：菜单 5 会在远端安装 `huggingface_hub[cli]` 并执行 `huggingface-cli login`，可选写入 Git Credential Helper，适合长期运行的部署。登录日志仅在失败时输出。
- **运行时注入（`persist_login: false`）**：菜单 7 在启动 tmux 任务时临时注入 `HF_TOKEN`、`HUGGINGFACE_HUB_TOKEN` 与 `HF_HOME`，执行结束后不会在远端留下凭据。

安全建议：

- 不要将真实 token 写入仓库。请在 `config.yaml` 中手工填入，并确保 `.gitignore` 已屏蔽该文件。
- 若怀疑 token 泄露，请立即在 Hugging Face 账户页面撤销，并生成新的访问令牌。
- 当远端机器需要共享或回收时，执行 `huggingface-cli logout` 或清理 `~/.cache/huggingface`，以免凭据残留。

## 下一步开发计划
- **Round 2**：已实现 Vultr 实例管理与 API 错误处理基础能力。
- **Round 3**：已实现 `bootstrap_remote.sh`、远端环境健康检查与 Hugging Face 登录集成。
- **Round 4**：实现远端仓库部署/更新与入口校验。
- **Round 5**：实现素材上传、tmux 后台运行 ASR 与实时日志监控。
- **Round 6**：整合 ASR 运行流程，支持实时日志回传。
- **Round 7**：增加结果回传与清理策略、完成功能测试。

## 常见错误
- **401 Unauthorized**：API Key 无效或未设置。请确认环境变量 `VULTR_API_KEY`，在 macOS/Linux 下使用 `export`，在 Windows PowerShell 下使用 `setx` 并重新打开终端。
- **429 Too Many Requests**：触发 Vultr 限流。程序会自动指数退避重试，若仍失败请稍后再试或减少频繁操作。
- **请求超时或网络错误**：可能是网络不稳定或 Vultr API 暂时不可用。请检查网络连通性并重试；必要时可在配置中自定义代理或稍后再访问。
- **Permission denied (publickey)**：远端拒绝 SSH 连接。请确认 config.yaml 中的 `ssh.user` 与 `ssh.keyfile` 设置正确，并确保私钥已添加到 `ssh-agent` 或配置了 `~/.ssh/config`。
- **git-lfs: command not found**：请重新执行菜单 5 或在远端手动运行 `git lfs install`，以初始化 Git LFS 环境。
- **tmux: failed to connect to server**：通常是 tmux 尚未安装或缺少权限。运行菜单 5 后会自动安装；若仍失败，可检查 `$HOME/.tmux` 权限并执行 `tmux kill-server`。
- **ffmpeg/网络检测失败**：远端脚本会标记为 FAIL。请确认系统包源可访问，并检查网络策略（如需代理可在 `.bashrc` 中设置），然后重新运行菜单 5。
