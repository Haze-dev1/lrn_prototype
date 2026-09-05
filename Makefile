# LRN developer commands.
# Every target runs against the containerised topology unless it is explicitly a local target.

COMPOSE      := docker compose
COMPOSE_PROD := docker compose -f docker-compose.yml

.PHONY: help
help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

# --- Environment -------------------------------------------------------------------------
.PHONY: env
env: ## Create .env from .env.example if it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env — set real secrets before deploying anywhere.")

# --- Stack -------------------------------------------------------------------------------
.PHONY: up
up: env ## Build and start the full stack
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop the stack, preserving database volumes
	$(COMPOSE) down

.PHONY: reset
reset: ## Stop the stack and DELETE all data volumes
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Follow logs for all services
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Show service status and health
	$(COMPOSE) ps

.PHONY: prod-up
prod-up: ## Build and start the production topology (excludes the dev override)
	$(COMPOSE_PROD) up -d --build

# --- Database ----------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply all pending migrations
	$(COMPOSE) exec api alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="add attempts table"
	$(COMPOSE) exec api alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: ## Revert the most recent migration
	$(COMPOSE) exec api alembic downgrade -1

.PHONY: seed
seed: ## Load the authored question bank (idempotent; safe to re-run)
	$(COMPOSE) exec api python -m scripts.seed_questions

.PHONY: seed-check
seed-check: ## Validate the question bank content without writing anything
	$(COMPOSE) exec api python -m scripts.seed_questions --dry-run

.PHONY: benchmark
benchmark: ## Run the grading benchmark against the configured provider
	$(COMPOSE) exec api python -m scripts.run_grading_benchmark

.PHONY: psql
psql: ## Open a psql shell on the application database
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-lrn} -d $${POSTGRES_DB:-lrn}

# --- Quality gates -----------------------------------------------------------------------
.PHONY: test
test: test-api test-web ## Run all tests

.PHONY: test-api
test-api: ## Run backend tests (database-backed tests need `make up`)
	@set -a; . ./.env; set +a; cd backend && \
	  DATABASE_URL="postgresql+psycopg://$$POSTGRES_USER:$$POSTGRES_PASSWORD@localhost:5432/$${POSTGRES_DB}_test" \
	  REDIS_URL="redis://localhost:6379/1" \
	  uv run pytest -q

.PHONY: test-web
test-web: ## Run frontend tests
	cd web && npm test

.PHONY: lint
lint: ## Lint backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd web && npm run lint

.PHONY: format
format: ## Auto-format backend and frontend
	cd backend && uv run ruff check --fix . && uv run ruff format .

.PHONY: typecheck
typecheck: ## Typecheck backend and frontend
	cd backend && uv run mypy core commons
	cd web && npm run typecheck

.PHONY: check
check: lint typecheck test ## Run every quality gate
