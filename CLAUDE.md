# K8S NetLab — Claude 项目指令

本文件约束 Claude 在此项目中的行为。优先级高于全局 CLAUDE.md 中的通用规则。

---

## 修 Bug 标准流程（每次必须完整执行）

1. **定位根因**，不猜测，先读代码
2. **写回归测试**（先写测试复现 bug，再修代码）
3. **修代码**，确保新测试通过
4. **更新 CHANGELOG.md** 的 `[Unreleased]` 段，追加一行 `- fix: <描述>`
5. **commit**，message 格式：`fix: <描述> — 补回归测试防止重现`
6. **push**（pre-push hook 自动跑全量测试）
7. **push 后查一次错误日志**：
   ```bash
   journalctl -u k8s-netlab -p err --since "5 minutes ago" --no-pager
   ```

---

## 加新功能标准流程

1. **实现功能**
2. **补测试**（新功能必须有对应测试，覆盖率不得低于当前水平）
3. **更新 CHANGELOG.md** 的 `[Unreleased]` 段，追加一行 `- feat: <描述>`
4. **commit + push**

---

## 发版流程（用户明确说"发版"或"打 tag"时执行）

1. 把 `CHANGELOG.md` 中 `[Unreleased]` 改为新版本号和日期，并在底部补链接
2. 在 `[Unreleased]` 上方重新插入空的 `## [Unreleased]` 段
3. commit：`release: v<X.Y.Z>`
4. 打 tag 并推送：
   ```bash
   git tag v<X.Y.Z>
   git push
   git push origin v<X.Y.Z> --no-verify
   ```

---

## 部署后强制检查

每次 `systemctl restart k8s-netlab` 后，必须执行：

```bash
sleep 3
curl -s https://lab.cloudnetops.tech/api/health
journalctl -u k8s-netlab -p err --since "2 minutes ago" --no-pager
```

两项都通过才算部署完成。

---

## 不允许的行为

- 修 bug 不写回归测试
- 发版不更新 CHANGELOG
- 部署后不检查日志和 health
- 直接 `git reset --hard` 回滚（应用 `git revert`）
