# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |

## Reporting a Vulnerability

**请勿通过公开 GitHub Issue 报告安全漏洞。**

通过邮箱报告：**cxtcyang@gmail.com**，或提交私有的 [GitHub Security Advisory](https://github.com/svb-devops/k8s-netlab/security/advisories/new)（仅维护者可见）。

请包含：
- 漏洞描述及潜在影响
- 复现步骤
- 受影响版本
- 建议修复方案（可选）

**响应时间承诺：**
- 24 小时内确认收到
- 72 小时内完成初步评估
- 7 天内完成修复（视严重程度可能延长，会同步进展）

## Known Security Design Decisions

以下是已评审确认的合理设计，不是漏洞：

| 规则 | 说明 |
|------|------|
| `B104`（`0.0.0.0` 绑定） | 服务监听所有接口，外部暴露由 Cloudflare Tunnel 处理，不直接对公网开放端口 |
| `B108`（`/tmp/labgen-linux-sandboxes` 等硬编码临时目录） | 路径来自内部配置常量，非用户输入，用于路径边界校验而非临时文件创建 |
| `B507`（SSH `AutoAddPolicy`，`backend/websocket.py`） | 面向 Proxmox 内网隔离的实验 VM（vmbr1/172.16.100.0/24），host key 校验对该场景无实际意义。**如未来任何组件需要连接公网/不受信主机，必须改为 `RejectPolicy` 并预置已知 host key** |
| `B604`（`shell="bash"` 关键字误报，`backend/labgen/linux_template.py`） | `shell` 是函数参数名而非 `subprocess(shell=True)`，bandit 按参数名字符串匹配触发的误报 |

## 依赖安全

依赖版本锁定在 `requirements.lock`（`pip-compile` 生成），CI 用 `pip install --require-hashes` 安装防供应链攻击。`make audit` 跑 `pip-audit` 检查已知 CVE，发现即升级——最近一次全面升级见 CHANGELOG `[Unreleased]` 中的 `fix(security)` 记录。
