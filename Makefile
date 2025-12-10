.PHONY: help install install-dev backend frontend start stop clean test lint format

# Default values
DB_USER ?= $(shell whoami)
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 8080
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

backend: ## Start FastAPI backend server
	@echo "Starting backend on http://localhost:$(BACKEND_PORT)"
	@echo "API docs: http://localhost:$(BACKEND_PORT)/docs"
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	uvicorn main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

backend-prod: ## Start FastAPI backend server in production mode
	@echo "Starting backend in production mode on http://localhost:$(BACKEND_PORT)"
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	uvicorn main:app --host 0.0.0.0 --port $(BACKEND_PORT) --workers 4

frontend: ## Start frontend HTTP server
	@echo "Starting frontend on http://localhost:$(FRONTEND_PORT)"
	@echo "Open http://localhost:$(FRONTEND_PORT) in your browser"
	cd frontend && $(PYTHON) server.py $(FRONTEND_PORT)

start: ## Start both backend and frontend (requires two terminals)
	@echo "To start both services, run:"
	@echo "  Terminal 1: make backend"
	@echo "  Terminal 2: make frontend"
	@echo ""
	@echo "Or use: make backend & make frontend"

test: ## Run tests
	. $(VENV)/bin/activate && pytest

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
	@echo "Run 'make frontend' to start the frontend server"

db-test: ## Test database connection
	@export DB_USER=$(DB_USER) && \
	. $(VENV)/bin/activate && \
	python -c "from services.database import get_db_connection; conn = get_db_connection(); print('✓ Database connection successful'); conn.close()"

api-test: ## Test API endpoint (requires backend to be running)
	@echo "Testing API endpoint..."
	@curl -s http://localhost:$(BACKEND_PORT)/api/v1/routes/bre10 | python -m json.tool | head -20

