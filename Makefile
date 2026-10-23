SHELL := /bin/bash
COMPOSE := docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory
CELL := uv run --project apps/cell
PYTEST := $(CELL) pytest

.PHONY: help doctor bootstrap up down clean logs smoke test arch-test lint fmt secrets ci

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

doctor: ## Check the local toolchain (node, pnpm, uv, python 3.12, docker)
	@bash scripts/doctor.sh

bootstrap: ## Install JS + Python dependencies and git hooks
	pnpm install
	$(CELL) sync --all-groups
	@uvx pre-commit install
	@echo "bootstrap: dependencies installed, pre-commit hooks active"

up: ## Start the factory dev stack
	$(COMPOSE) up -d --build
	@bash scripts/wait-healthy.sh

down: ## Stop the stack, keep volumes
	$(COMPOSE) down

clean: ## Stop the stack and delete volumes
	$(COMPOSE) down -v

logs: ## Tail stack logs
	$(COMPOSE) logs -f --tail=100

smoke: ## Health-check every service in the stack
	@bash scripts/smoke.sh

test: ## Unit tests (Python cell + architecture, then JS workspaces)
	$(PYTEST) -c apps/cell/pyproject.toml apps/cell/tests infra/architecture-tests
	pnpm -r --if-present test

arch-test: ## Enforce architecture boundaries (UI-free cell, route allowlist)
	$(PYTEST) -c apps/cell/pyproject.toml infra/architecture-tests

lint: ## Lint Python, format-check TypeScript, typecheck
	$(CELL) ruff check apps/cell infra/architecture-tests
	pnpm exec prettier --check "apps/{control-plane,web}/**/*.{ts,tsx,css,json,html}" "packages/{shared-types,test-fixtures}/**/*.{ts,js,mjs,json,css,html}"
	pnpm -r --if-present typecheck

fmt: ## Format Python and TypeScript
	$(CELL) ruff format apps/cell infra/architecture-tests
	pnpm exec prettier --write "apps/{control-plane,web}/**/*.{ts,tsx,css,json,md}" "packages/{shared-types,test-fixtures}/**/*.{ts,json,md}"

secrets: ## Seed dev-only secrets into the local Vault (values never touch disk)
	@bash scripts/seed-secrets.sh

ci: lint test arch-test ## What CI enforces locally
