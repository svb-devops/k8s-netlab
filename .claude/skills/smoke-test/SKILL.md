---
name: smoke-test
description: |
  对生产服务运行冒烟测试，验证核心端点可用。
  触发场景：重启服务后、发版后、部署后验证生产可用性。
user-invocable: true
allowed-tools: Bash
---

# smoke-test

**触发时机**：`systemctl restart k8s-netlab` 后、发版后、怀疑服务异常时。

---

## 执行

```bash
bash scripts/smoke_test.sh
```

端点定义维护在 `scripts/smoke_test.sh`，此处不重复列举（避免双重维护导致不一致）。

---

## 解读结果

- 全部通过 → 服务正常
- `/api/health` 失败 → 服务未启动或端口不通，检查：
  ```bash
  systemctl status k8s-netlab
  journalctl -u k8s-netlab -p err --since "5 minutes ago" --no-pager
  ```
- `/api/auth/me` 失败 → session/auth 模块异常，检查 `backend/auth.py`
- `/api/experiments` 失败 → 实验文档路径异常，检查 `data/` 目录权限

---

## 下一步推荐

- 全部通过 → 部署完成
- 有失败 → 用 `skills/investigate/SKILL.md` 定位根因
