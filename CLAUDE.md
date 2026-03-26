# K8S NetLab — Claude 项目指令

优先级高于全局 `~/.claude/CLAUDE.md`。

## 项目快速上下文

- **用途**：Proxmox 上的 K8s 网络实验平台，供学生做实验
- **服务**：`k8s-netlab.service`，FastAPI，uvicorn port 8000
- **生产地址**：`https://lab.cloudnetops.tech`
- **健康检查**：`curl -s https://lab.cloudnetops.tech/api/health`
- **VMID 范围**：100–199，模板 VM ID = 100（不能删）
- **网络**：vmbr1（172.16.100.0/24）
- **数据**：`data/*.json`（flock 原子读写，不用数据库）
- **测试基线**：256 tests，覆盖率 80%
- **安全门禁**：pre-commit（敏感信息扫描）+ pre-push（8 项安全检查 + pytest），安装：`bash scripts/install-git-hooks.sh`

## 工作流规则（触发时自动执行）

| 场景 | 文件 |
|------|------|
| 修 bug | [rules/bug-fix.md](.claude/rules/bug-fix.md) |
| 加新功能 | [rules/feature.md](.claude/rules/feature.md) |
| 发版 | [rules/release.md](.claude/rules/release.md) |
| 重启服务后 | [rules/deploy.md](.claude/rules/deploy.md) |
| 任何时候 | [rules/constraints.md](.claude/rules/constraints.md) |

## 命令（主动调用）

| 命令 | 用途 |
|------|------|
| `/project:deploy` | 重启服务 + 健康验证 |
| `/project:test` | 全量测试 + 覆盖率 |
| `/project:smoke-test` | 生产端点验证 |
| `/project:new-experiment` | 创建实验文档脚手架 |

## Skills（复杂工作流，Claude 会主动推荐）

| Skill | 触发场景 |
|-------|---------|
| [investigate](.claude/skills/investigate/SKILL.md) | 应用层 bug 根因分析 |
| [debug-vm](.claude/skills/debug-vm/SKILL.md) | VM 创建失败系统排查 |
| [pre-release](.claude/skills/pre-release/SKILL.md) | 发版前六道质量门 |
| [validate-experiment](.claude/skills/validate-experiment/SKILL.md) | 实验文档质量验证 |
