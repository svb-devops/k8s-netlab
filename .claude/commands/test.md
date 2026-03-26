运行完整测试套件并报告结果。

```bash
source venv/bin/activate && pytest tests/ -x -q --tb=short --cov=backend --cov-report=term-missing
```

完成后报告：
- 通过 / 失败数量
- 覆盖率（必须 ≥ 75%，当前目标 80%）
- 如有失败，列出失败的测试名称和错误摘要
