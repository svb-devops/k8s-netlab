根据用户提供的实验编号和标题，从模板创建新实验文档。

1. 读取模板：`docs/experiments/template.md`
2. 读取现有实验文件，了解编号和格式规范
3. 按照模板结构创建 `docs/experiments/<NN>-<slug>.md`
   - 编号两位数字补零（如 12 → `12-xxx`）
   - slug 用小写 + 连字符，不用下划线
4. 填写标题、难度、时长、实验目标，其余内容留占位符 `TODO`
5. 告知用户文件路径，提示下一步填充内容

如用户未提供编号或标题，先询问。

文件创建后推荐 → 运行 `skills/validate-experiment.md` 验证文档质量
