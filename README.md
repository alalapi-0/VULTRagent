# VULTRagent

> **新增内容（Round 4）**：新增远端仓库部署/更新流程（支持 git-lfs、子模块、入口校验），并保留 Round 3 的一键环境部署与健康检查能力。

## 项目简介与目标
VULTRagent 旨在通过本地命令行工具自动化管理 Vultr VPS，主要用于远程部署与执行语音识别（ASR）任务。本轮构建了基础代码骨架，后续将逐步完善实际功能。

## 功能概览
当前版本提供以下命令行菜单选项：
1. 列出 Vultr 实例（真实 API 调用，支持分页、耗时统计）
2. 选择当前实例并保存（写入 `.state.json`）
3. 查看当前实例详情（实时请求 API）
4. 连接并测试 SSH（占位）
5. 一键环境部署/检查（远端脚本，包含健康检查与 Hugging Face 可选登录）
6. 部署/更新 ASR 仓库到远端（支持 clone/pull、子模块、git-lfs、入口检查）
7. 上传本地素材到远端输入目录（占位）
8. 在 tmux 中后台运行 `asr_quickstart.py`（占位）
9. 实时查看远端日志（占位）
10. 回传 ASR 结果到本地（占位）
11. 停止/清理远端任务（占位）
12. 退出

## 文件结构与说明
```
VULTRagent/
├── main.py                  # 命令行入口，加载菜单并调用核心模块
├── core/
│   ├── vultr_api.py         # Vultr API 封装（实例列表、详情、重试逻辑）
│   ├── remote_exec.py       # SSH / 文件上传封装与后续扩展占位
│   ├── file_transfer.py     # 文件传输与仓库部署占位逻辑
│   ├── remote_bootstrap.py  # 远端初始化与健康检查逻辑
│   └── asr_runner.py        # ASR 任务执行占位逻辑
├── scripts/
│   └── bootstrap_remote.sh  # 远端一键脚本（幂等部署与健康检查）
├── config.example.yaml      # 配置模板，供用户复制修改
├── requirements.txt         # Python 依赖清单
└── README.md                # 项目说明文档（本文件）
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
- `asr`：ASR 启动脚本与参数占位。
- `transfer`：回传结果时的匹配模式。
- `huggingface`：Round 3 新增，用于控制 token 注入与 CLI 登录行为。

## 一键远端环境部署/检查
菜单项 **5. 一键环境部署/检查** 会自动执行以下流程：

1. 将本地 `scripts/bootstrap_remote.sh` 上传到远端 `/tmp/vultragentsvc_bootstrap.sh`（路径可在 `remote.bootstrap_tmp_path` 中自定义）。
2. 通过 `ssh` 注入配置中的远端目录、日志路径、Hugging Face 选项等环境变量。
3. 在远端执行脚本，完成以下任务：
   - 更新包索引并安装 `git`、`git-lfs`、`python3`、`pip`、`tmux`、`rsync`、`ffmpeg`、`curl`、`ca-certificates` 等依赖；
   - 初始化 Git LFS；
   - 创建 `base_dir`、`project_dir`、`inputs_dir`、`outputs_dir`、`models_dir` 及日志目录；
   - 可选执行 Hugging Face CLI 持久登录；
   - 运行健康检查：输出 Python、pip、tmux、ffmpeg、git、磁盘空间及网络连通性状态。

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

若部署成功且入口脚本通过 `python3 -m py_compile` 校验，界面会提示接下来可执行的菜单 7（上传素材）与菜单 8（tmux 后台运行）。

**常见问题与排查**：

- `Host key verification failed`：首次连接新主机时请先在本地 `ssh` 一次或使用 `ssh-keyscan` 添加指纹；
- `Permission denied (publickey)`：确认 `ssh.user`、`ssh.keyfile` 与远端授权匹配，并保证 Windows/WSL 下的密钥权限正确；
- `fatal: Remote branch <name> not found`：确认 `git.branch` 与仓库实际分支一致；
- `git lfs pull failed` 或 `git-lfs: command not found`：请重新执行菜单 5 或在远端运行 `git lfs install` 后再次尝试部署。

## Hugging Face 配置与安全
`config.example.yaml` 中新增的 `huggingface` 段落支持两种工作模式：

- **持久登录（`persist_login: true`）**：菜单 5 会在远端安装 `huggingface_hub[cli]` 并执行 `huggingface-cli login`，可选写入 Git Credential Helper，适合长期运行的部署。登录日志仅在失败时输出。
- **运行时注入（`persist_login: false`）**：脚本不会在远端保存凭据。后续轮次（Round 5）会通过环境变量在执行 ASR 时临时注入 token。

安全建议：

- 不要将真实 token 写入仓库。请在 `config.yaml` 中手工填入，并确保 `.gitignore` 已屏蔽该文件。
- 若怀疑 token 泄露，请立即在 Hugging Face 账户页面撤销，并生成新的访问令牌。
- 当远端机器需要共享或回收时，执行 `huggingface-cli logout` 或清理 `~/.cache/huggingface`，以免凭据残留。

## 下一步开发计划
- **Round 2**：已实现 Vultr 实例管理与 API 错误处理基础能力。
- **Round 3**：已实现 `bootstrap_remote.sh`、远端环境健康检查与 Hugging Face 登录集成。
- **Round 4**：实现远端仓库部署/更新与入口校验。
- **Round 5**：实现 SSH 执行、文件传输与 tmux 作业管理。
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
