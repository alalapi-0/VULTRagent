# VULTRagent

> **新增内容（Round 2）**：接入 Vultr API，实现实例列表、实例选择持久化与详情查看，并补充环境变量与常见错误说明。

## 项目简介与目标
VULTRagent 旨在通过本地命令行工具自动化管理 Vultr VPS，主要用于远程部署与执行语音识别（ASR）任务。本轮构建了基础代码骨架，后续将逐步完善实际功能。

## 功能概览
当前版本提供以下命令行菜单选项：
1. 列出 Vultr 实例（真实 API 调用，支持分页、耗时统计）
2. 选择当前实例并保存（写入 `.state.json`）
3. 查看当前实例详情（实时请求 API）
4. 连接并测试 SSH（占位）
5. 一键环境部署/检查（远端，占位）
6. 部署/更新 ASR 仓库到远端（占位）
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
│   ├── remote_exec.py       # SSH / tmux / 日志操作占位逻辑
│   ├── file_transfer.py     # 文件传输与仓库部署占位逻辑
│   ├── remote_bootstrap.py  # 远端初始化与健康检查占位逻辑
│   └── asr_runner.py        # ASR 任务执行占位逻辑
├── scripts/
│   └── bootstrap_remote.sh  # 远端一键脚本（占位，Round 3 实现）
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

## 下一步开发计划
- **Round 2**：已实现 Vultr 实例管理与 API 错误处理基础能力。
- **Round 3**：实现 `bootstrap_remote.sh` 与远端初始化流程。
- **Round 4**：完善 Vultr API 调用与实例管理。
- **Round 5**：实现 SSH 执行、文件传输与 tmux 作业管理。
- **Round 6**：整合 ASR 运行流程，支持实时日志回传。
- **Round 7**：增加结果回传与清理策略、完成功能测试。

## 常见错误
- **401 Unauthorized**：API Key 无效或未设置。请确认环境变量 `VULTR_API_KEY`，在 macOS/Linux 下使用 `export`，在 Windows PowerShell 下使用 `setx` 并重新打开终端。
- **429 Too Many Requests**：触发 Vultr 限流。程序会自动指数退避重试，若仍失败请稍后再试或减少频繁操作。
- **请求超时或网络错误**：可能是网络不稳定或 Vultr API 暂时不可用。请检查网络连通性并重试；必要时可在配置中自定义代理或稍后再访问。
