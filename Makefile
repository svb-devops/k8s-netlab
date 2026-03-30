.PHONY: help test test-unit lint format format-check typecheck security audit dev install-hooks

help:
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-20s %s\n", $$1, $$2}'

test: ## 全量测试（覆盖率 ≥90%）
	source venv/bin/activate && pytest tests/ -x -q --tb=short --cov=backend --cov-report=term-missing --cov-fail-under=90

test-unit: ## 仅静态单元测试（不需要 Proxmox）
	source venv/bin/activate && pytest tests/ -x -q -m "not vm" --tb=short

lint: ## ruff 检查
	source venv/bin/activate && ruff check backend/

format: ## black 格式化
	source venv/bin/activate && black backend/ tests/

format-check: ## black 格式检查（不修改）
	source venv/bin/activate && black --check backend/ tests/

typecheck: ## mypy 类型检查
	source venv/bin/activate && mypy backend/ --ignore-missing-imports --warn-return-any --check-untyped-defs --no-error-summary

security: ## bandit 安全扫描
	source venv/bin/activate && bandit -r backend/ -lll

audit: ## pip-audit CVE 检查
	source venv/bin/activate && pip-audit --ignore-vuln CVE-2026-4539 --ignore-vuln PYSEC-2023-228 --ignore-vuln CVE-2025-8869 --ignore-vuln CVE-2026-1703 --ignore-vuln PYSEC-2025-49 --ignore-vuln CVE-2024-6345

dev: ## 启动开发服务器（port 8000）
	source venv/bin/activate && uvicorn backend.main:app --reload --port 8000

install-hooks: ## 安装 git hooks（pre-commit + pre-push）
	bash scripts/install-git-hooks.sh
