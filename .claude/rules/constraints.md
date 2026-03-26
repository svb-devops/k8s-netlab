# 硬性约束（任何情况下不得违反）

- 修 bug 不写回归测试 → **禁止**
- 发版不更新 CHANGELOG → **禁止**
- 部署后不检查日志和 health → **禁止**
- `git reset --hard` 回滚 → **禁止**，必须用 `git revert`
