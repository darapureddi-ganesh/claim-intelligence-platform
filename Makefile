.PHONY: install dev test lint migrate seed

install:
	pip install -e ".[dev]"
	python -m spacy download en_core_web_sm

dev:
	docker-compose up -d postgres redis
	uvicorn src.claimiq.main:app --reload --port 8000 &
	uvicorn src.policylens.main:app --reload --port 8001

test:
	pytest tests/ -v --cov=src --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff format src/ tests/

migrate:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(MSG)"

seed:
	python scripts/seed_adjusters.py
	python scripts/seed_policy_graph.py

docker-up:
	docker-compose up --build -d

docker-down:
	docker-compose down -v
