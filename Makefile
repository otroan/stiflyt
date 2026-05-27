.PHONY: help install install-dev backend backend-noreload backend-prod frontend signs signs-build mcp clean test lint format perf-test

# Default values
DB_USER ?= $(shell whoami)
BACKEND_PORT ?= 8001
SIGNS_PORT ?= 5174
VENV ?= venv
PYTHON ?= python3

help: ## Show this help message
	@echo "Stiflyt Makefile Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install project dependencies
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install --upgrade pip && pip install -e .

install-dev: ## Install project with dev dependencies
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && pip install --upgrade pip && pip install -e ".[dev]"

backend: ## Start FastAPI backend server (with reload). Use Ctrl+C twice to stop.
	@echo "Starting backend on http://localhost:$(BACKEND_PORT)"
	@echo "API docs: http://localhost:$(BACKEND_PORT)/docs"
	@echo "Tip: With --reload you may need to press Ctrl+C twice to stop."
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	uvicorn main:app --reload --host 127.0.0.1 --port $(BACKEND_PORT)

backend-noreload: ## Start backend without reload; single Ctrl+C stops the server
	@echo "Starting backend (no reload) on http://localhost:$(BACKEND_PORT)"
	@echo "API docs: http://localhost:$(BACKEND_PORT)/docs"
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	uvicorn main:app --host 127.0.0.1 --port $(BACKEND_PORT)

backend-prod: ## Start FastAPI backend server in production mode
	@echo "Starting backend in production mode on http://localhost:$(BACKEND_PORT)"
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	uvicorn main:app --host 127.0.0.1 --port $(BACKEND_PORT) --workers 4

mcp: ## Start Stiflyt MCP server (stdio). For Cursor MCP; backend should be running on BACKEND_PORT.
	@echo "Starting MCP server (stdio). Backend should be at http://localhost:$(BACKEND_PORT)."
	@echo "Use Ctrl+C to stop."
	@export STIFLYT_BASE_URL=$${STIFLYT_BASE_URL:-http://localhost:$(BACKEND_PORT)} && \
	. $(VENV)/bin/activate && stiflyt-mcp

frontend: ## Start changeset editor frontend (React/Vite, port 3000)
	@echo "Starting changeset editor frontend on http://localhost:3000"
	@echo "Backend should be running on http://127.0.0.1:$(BACKEND_PORT)"
	@if ! curl -s http://127.0.0.1:$(BACKEND_PORT)/health > /dev/null 2>&1; then \
		echo "⚠️  WARNING: Backend does not appear to be running on port $(BACKEND_PORT)"; \
		echo "   Run 'make backend' in another terminal first"; \
		echo ""; \
	fi
	@cd changeset_editor/frontend && \
	if [ ! -d node_modules ]; then \
		echo "Installing dependencies..."; \
		npm install; \
	fi && \
	npm run dev

signs: ## Start the Breheimen signs_app (React/Vite, port 5174 by default)
	@echo "Starting signs_app on http://localhost:$(SIGNS_PORT)"
	@echo "Backend should be running on http://127.0.0.1:$(BACKEND_PORT)"
	@if ! curl -s http://127.0.0.1:$(BACKEND_PORT)/health > /dev/null 2>&1; then \
		echo "⚠️  WARNING: Backend does not appear to be running on port $(BACKEND_PORT)"; \
		echo "   Run 'make backend' in another terminal first"; \
		echo ""; \
	fi
	@cd signs_app && \
	if [ ! -d node_modules ]; then \
		echo "Installing dependencies..."; \
		npm install; \
	fi && \
	node_modules/.bin/vite --port $(SIGNS_PORT)

signs-build: ## Build the signs_app for production (dist/ in signs_app/)
	@cd signs_app && \
	if [ ! -d node_modules ]; then npm install; fi && \
	node_modules/.bin/vite build

test: ## Run backend tests
	. $(VENV)/bin/activate && pytest

test-frontend: ## Run frontend tests
	@echo "Running frontend tests..."
	@cd changeset_editor/frontend && \
	if [ ! -d node_modules ]; then \
		echo "Installing dependencies..."; \
		npm install; \
	fi && \
	npm run test:run

test-frontend-coverage: ## Run frontend tests with coverage
	@echo "Running frontend tests with coverage..."
	@cd changeset_editor/frontend && \
	if [ ! -d node_modules ]; then \
		echo "Installing dependencies..."; \
		npm install; \
	fi && \
	npm run test:coverage

test-all: test test-frontend ## Run all tests (backend + frontend)

perf-test: ## Run performance tests against API
	@echo "Running performance tests..."
	@echo "Make sure the backend is running: make backend"
	. $(VENV)/bin/activate && $(PYTHON) scripts/performance_test.py --url http://localhost:$(BACKEND_PORT)

lint: ## Run linter
	. $(VENV)/bin/activate && flake8 api services main.py

format: ## Format code with black
	. $(VENV)/bin/activate && black api services main.py scripts/*.py

check: ## Run linting and formatting checks
	. $(VENV)/bin/activate && flake8 api services main.py && black --check api services main.py scripts/*.py

clean: ## Clean temporary files and caches
	find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -r {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -r {} + 2>/dev/null || true
	rm -rf .coverage htmlcov dist build

clean-venv: ## Remove virtual environment
	rm -rf $(VENV)

clean-all: clean clean-venv ## Clean everything including venv

setup: install-dev ## Setup development environment
	@echo "Development environment setup complete!"
	@echo "Run 'make backend' to start the API server"
	@echo "Run 'make frontend' to start the changeset editor frontend"

sync-route-errata: ## Apply data/route_errata.yaml into the ops errata tables (bootstrap/restore; OVERWRITES DB)
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	$(PYTHON) scripts/apply_route_errata.py

dump-route-errata: ## Export the ops errata tables to data/route_errata.yaml (regular workflow; DB is source of truth)
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	$(PYTHON) scripts/dump_route_errata.py

db-test: ## Test database connection
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	python -c "from services.database import get_db_connection; conn = get_db_connection(); print('✓ Database connection successful'); conn.close()"

db-migrate-changeset: ## Run changeset editor database migrations
	@echo "Running changeset editor migrations..."
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	python scripts/run_changeset_migration.py

api-test: ## Test API endpoint (requires backend to be running)
	@echo "Testing API endpoint..."
	@curl -s http://localhost:$(BACKEND_PORT)/api/v1/routes/bre10 | python -m json.tool | head -20

analyze-query: ## Analyze query performance and check indexes
	@echo "Analyzing query performance..."
	. $(VENV)/bin/activate && python scripts/analyze_query_performance.py

