# Klabautermann Makefile
# ======================
# Common development commands

.PHONY: help venv install dev run test lint type-check format check clean docker-up docker-down docker-logs init-db wipe-db reset-db

# Default target
help:
	@echo "Klabautermann Development Commands"
	@echo "=================================="
	@echo ""
	@echo "Setup:"
	@echo "  make venv         Create virtual environment (uv)"
	@echo "  make install      Install production dependencies"
	@echo "  make dev          Install development dependencies"
	@echo ""
	@echo "Run:"
	@echo "  make run          Start the CLI"
	@echo ""
	@echo "Quality:"
	@echo "  make test         Run all tests"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make type-check   Run type checker (mypy)"
	@echo "  make format       Format code (ruff format)"
	@echo "  make check        Run all quality checks"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up    Start Docker services"
	@echo "  make docker-down  Stop Docker services"
	@echo "  make docker-logs  Follow Docker logs"
	@echo ""
	@echo "Database:"
	@echo "  make init-db      Initialize Neo4j schema"
	@echo ""
	@echo "Utility:"
	@echo "  make clean        Remove build artifacts"

# === Setup ===

venv:
	uv venv

install:
	uv pip install -r requirements.txt

dev:
	uv pip install -r requirements-dev.txt
	pre-commit install

# === Run ===

run:
	python main.py

# === Quality ===

test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v -m unit

test-integration:
	pytest tests/integration/ -v -m integration

test-e2e:
	pytest tests/e2e/ -v -m e2e

test-cov:
	pytest tests/ --cov=src/klabautermann --cov-report=html --cov-report=term

lint:
	ruff check src/ tests/

type-check:
	mypy src/klabautermann/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

check: lint type-check test
	@echo "All checks passed!"

# === Docker ===

docker-up:
	docker compose up -d
	@echo "Services starting..."
	@echo "Neo4j Browser: http://localhost:7474"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-rebuild:
	docker compose build --no-cache
	docker compose up -d

# === Database ===

init-db:
	python scripts/init_database.py

wipe-db:
	@echo "Wiping all data from Neo4j..."
	docker compose exec neo4j cypher-shell -u neo4j -p klabautermann "MATCH (n) DETACH DELETE n"
	@echo "Done. Run 'make init-db' to recreate schema."

reset-db: wipe-db init-db
	@echo "Database reset complete."

# === Utility ===

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
