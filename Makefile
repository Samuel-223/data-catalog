.PHONY: help install run test cov lint fmt seed migrate up down logs

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## 安装开发依赖
	pip install -r requirements-dev.txt

run: ## 本地启动（SQLite，热重载）
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test: ## 跑全部单元测试
	pytest

cov: ## 跑测试并输出覆盖率
	pytest --cov=app --cov-report=term-missing

lint: ## 代码检查
	ruff check .
	ruff format --check .

fmt: ## 自动格式化
	ruff format .
	ruff check --fix .

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
