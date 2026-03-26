---
description: 对生产服务运行冒烟测试，验证核心端点可用。
---

对生产服务运行冒烟测试，验证核心端点可用。

```bash
bash scripts/smoke_test.sh
```

报告每个端点的通过 / 失败状态。如有失败，说明具体端点和返回内容。

端点失败时推荐 → `skills/investigate/SKILL.md` 查应用层，或 `skills/debug-vm/SKILL.md` 查基础设施
