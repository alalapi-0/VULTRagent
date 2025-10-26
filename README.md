# VULTRagent

> **新增内容（Round 1）**：创建项目骨架、命令行主菜单框架、核心模块占位实现与配置模板。

## 项目简介与目标
VULTRagent 旨在通过本地命令行工具自动化管理 Vultr VPS，主要用于远程部署与执行语音识别（ASR）任务。本轮构建了基础代码骨架，后续将逐步完善实际功能。

## 功能概览
当前版本提供以下命令行菜单选项（均为占位实现，用于后续扩展）：
1. 列出 Vultr 实例
2. 连接并测试 SSH
3. 一键环境部署/检查（远端）
4. 部署/更新 ASR 仓库到远端
5. 上传本地素材到远端输入目录
6. 在 tmux 中后台运行 `asr_quickstart.py`
7. 实时查看远端日志
8. 回传 ASR 结果到本地
9. 停止/清理远端任务
10. 退出

## 文件结构与说明
```
VULTRagent/
├── main.py                  # 命令行入口，加载菜单并调用核心模块
├── core/
│   ├── vultr_api.py         # Vultr API 占位逻辑
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
   python main.py menu
   ```

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
- **Round 2**：补充配置加载、日志系统与基础错误处理。
- **Round 3**：实现 `bootstrap_remote.sh` 与远端初始化流程。
- **Round 4**：完善 Vultr API 调用与实例管理。
- **Round 5**：实现 SSH 执行、文件传输与 tmux 作业管理。
- **Round 6**：整合 ASR 运行流程，支持实时日志回传。
- **Round 7**：增加结果回传与清理策略、完成功能测试。
