# Klabautermann Makefile
# ======================
# Common development commands

.PHONY: help venv install dev run api tui tui-build test lint type-check format check clean docker-up docker-down docker-logs init-db wipe-db reset-db test-docker-up test-docker-down test-docker-logs test-contracts test-golden test-all-services

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
	@echo "  make api          Start the API server (ws://localhost:8765)"
	@echo "  make tui          Build and run the Rust TUI"
	@echo "  make tui-build    Build the Rust TUI only"
	@echo ""
	@echo "Quality:"
	@echo "  make test         Run all tests"
	@echo "  make test-cov     Run tests with coverage report"
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
	@echo "Test Infrastructure:"
	@echo "  make test-docker-up    Start test Neo4j (port 7688)"
	@echo "  make test-docker-down  Stop test Neo4j"
	@echo "  make test-contracts    Run contract tests"
	@echo "  make test-golden       Run golden scenario E2E tests"
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
	uv run python main.py

api:
	uv run python scripts/start_api.py

tui-build:
	cd tui-rs && cargo build --release

tui: tui-build
	./tui-rs/target/release/klabautermann-tui

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

# === Test Infrastructure ===

test-docker-up:
	docker-compose -f docker-compose.test.yml up -d
	@echo "Test Neo4j starting on port 7688..."
	@echo "Wait for healthy status before running tests"
	@echo "Check status: docker-compose -f docker-compose.test.yml ps"

test-docker-down:
	docker-compose -f docker-compose.test.yml down -v
	@echo "Test infrastructure stopped and volumes removed"

test-docker-logs:
	docker-compose -f docker-compose.test.yml logs -f

test-contracts:
	pytest tests/integration/test_neo4j_contract.py tests/integration/test_graphiti_contract.py -v

test-golden:
	pytest tests/e2e/test_golden_scenarios.py -v -m golden

test-all-services:
	@echo "Starting test infrastructure..."
	docker-compose -f docker-compose.test.yml up -d
	@echo "Waiting for Neo4j to be healthy..."
	@sleep 15
	pytest tests/ -v -m "requires_neo4j or e2e"
	docker-compose -f docker-compose.test.yml down -v

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
