#!/usr/bin/env bash
# scripts/ssh_diagnose.sh
# 该脚本用于在远端 VPS 上收集 SSH 服务状态，帮助定位连接问题。

# 遇到任何命令失败即退出，保证诊断步骤不会继续执行错误数据。
set -e

# 打印标题分隔线，提示诊断开始。
echo "=== SSH 远端诊断报告 ==="

# 输出 SSH 服务状态，确认 sshd 是否正在运行。
echo "1. SSH 服务状态:"
systemctl is-active ssh || echo "SSH 服务未运行"

# 打印监听端口信息，确保 sshd 监听预期端口。
echo -e "\n2. 监听端口:"
sudo ss -tlnp | grep sshd || echo "未监听任何端口"

# 查看防火墙状态，判断 22 端口是否可能被阻断。
echo -e "\n3. 防火墙状态:"
sudo ufw status || echo "未启用 ufw 或命令执行失败"

# 检查 sshd 配置中的关键选项，排查登录受限问题。
echo -e "\n4. SSH 登录配置:"
sudo grep -E '^(Port|PermitRootLogin|PasswordAuthentication)' /etc/ssh/sshd_config || echo "无法读取 /etc/ssh/sshd_config"

# 显示当前公网 IP，帮助确认实例可达性。
echo -e "\n5. 当前公网 IP:"
curl -s ifconfig.me || echo "无法检测公网 IP"

# 输出诊断结束提示。
echo "=== 诊断完成 ==="
