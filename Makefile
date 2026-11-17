.PHONY: help install run test cov lint fmt sec keygen token audit-report seed migrate up down logs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## 安装开发依赖
	pip install -r requirements-dev.txt

PY ?= python3

run: ## 本地启动（SQLite，热重载）
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

local: ## 本地启动（先杀掉占用端口的旧进程，再起服务）
	./scripts/start-local.sh

stop: ## 停掉本地服务（按端口找进程）
	./scripts/stop-local.sh

keyctl: ## 密钥管理（keyctl ARGS="create --role viewer --label demo --days 30"）
	$(PY) -m app.core.keyring $(ARGS)

test: ## 跑全部单元测试
	$(PY) -m pytest

cov: ## 跑测试并输出覆盖率
	$(PY) -m pytest --cov=app --cov-report=term-missing

lint: ## 代码检查
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt: ## 自动格式化
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

sec: ## Linux/容器安全基线检查（有 FAIL 则退出码 1）
	$(PY) security/linux_security_check.py --json security/linux_result.json

keygen: ## 生成 API Key：make keygen ROLE=admin
	$(PY) -m app.core.security $(or $(ROLE),editor)

token: ## 本地 OIDC 测试 token：make token ROLE=admin
	python scripts/dev_token.py $(or $(ROLE),admin)

audit-report: ## 审计报表（默认读 AUDIT_LOG_PATH 或 audit.jsonl）
	./scripts/audit_report.sh -f $(or $(AUDIT_LOG),audit.jsonl)

seed: ## 灌入演示数据（2 数据源 / 5 表 / 18 字段 / 3 规则）
	python scripts/seed_demo.py

migrate: ## 执行数据库迁移到最新版本
	alembic upgrade head

up: ## 启动 docker compose（api + postgres）
	docker compose up -d --build

down: ## 停止 compose
	docker compose down

logs: ## 查看 api 日志
	docker compose logs -f api
