---
description: 重启 k8s-netlab 服务，然后按 `.claude/rules/deploy.md` 执行部署后强制检查。
disable-model-invocation: true
---

重启 k8s-netlab 服务，然后按 `.claude/rules/deploy.md` 执行部署后强制检查。

```bash
systemctl restart k8s-netlab
```

部署成功后推荐 → `/project:smoke-test` 验证核心端点
部署前发版检查 → 先运行 `skills/pre-release/SKILL.md`
