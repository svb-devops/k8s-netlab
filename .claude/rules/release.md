# 触发条件：用户说"发版"或"打 tag"

**第一步（必须）**：先运行 `skills/pre-release/SKILL.md` 六道质量门，全部通过才能继续。

1. 把 `CHANGELOG.md` 中 `[Unreleased]` 改为新版本号和日期，并在底部补链接
2. 在版本段上方重新插入空的 `## [Unreleased]` 段
3. commit：`release: v<X.Y.Z>`
4. 打 tag 并推送：
   ```bash
   git tag v<X.Y.Z>
   git push
   git push origin v<X.Y.Z> --no-verify
   ```
