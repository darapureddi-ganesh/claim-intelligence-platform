.PHONY: install dev run test lint migrate seed deploy redeploy models

run:  ## ClaimSaathi Cloud Run app locally (http://localhost:8080)
	uvicorn src.platform.app:app --reload --port 8080

models:  ## List Google AI models your key/project can call
	python scripts/list_models.py

deploy:  ## First-time Google Cloud setup + deploy (needs PROJECT_ID, GEMINI_API_KEY)
	./deploy/setup.sh

redeploy:
	gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION=$${REGION:-asia-south1}

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
