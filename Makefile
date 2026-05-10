# ─────────────────────────────────────────────────────────────────────────────
# Log-RCA  |  Makefile
#
# Docker Compose automatically reads .env from the current directory,
# so no --env-file flag is needed.
# ─────────────────────────────────────────────────────────────────────────────

COMPOSE = docker compose
# Faster rebuilds: layer cache + pip wheel cache (requires BuildKit — default on Docker Desktop / recent Engine)
export DOCKER_BUILDKIT := 1

.PHONY: help setup build build-nocache build-ui build-ui-nocache up down destroy \
        logs logs-api logs-ui logs-ollama \
        ps health pull-models \
        restart-api restart-ui \
        shell-api shell-ui clean

help:
	@echo ""
	@echo "  Log-RCA"
	@echo "  ─────────────────────────────────────────────"
	@echo "  make setup          Create .env from .env.example"
	@echo "  make build          Build all images (uses Docker layer cache)"
	@echo "  make build-nocache  Build all images from scratch (--no-cache)"
	@echo "  make build-ui       Rebuild UI (cached) + up -d ui"
	@echo "  make build-ui-nocache  Rebuild UI --no-cache + up -d ui"
	@echo "  make up             Start stack + pull models"
	@echo "  make down           Stop (keep volumes)"
	@echo "  make destroy        Stop + DELETE volumes ⚠️"
	@echo ""
	@echo "  make logs           All logs"
	@echo "  make logs-api       API logs"
	@echo "  make logs-ui        UI logs"
	@echo "  make logs-ollama    Ollama logs"
	@echo "  make ps             Container status"
	@echo "  make health         API health check"
	@echo ""
	@echo "  make pull-models    Re-pull after changing LLM_MODEL"
	@echo "  make restart-api    Restart API"
	@echo "  make restart-ui     Restart UI"
	@echo "  make shell-api      Shell in API container"
	@echo "  make shell-ui       Shell in UI container"
	@echo "  make clean          Prune dangling images"
	@echo ""

setup:
	@if [ ! -f .env ]; then \
	    cp .env.example .env; \
	    echo "✅ Created .env — edit it to choose your LLM model."; \
	else \
	    echo "ℹ️  .env already exists."; \
	fi

build: setup
	$(COMPOSE) build

build-nocache: setup
	$(COMPOSE) build --no-cache

build-ui:
	$(COMPOSE) build ui
	$(COMPOSE) up -d ui

build-ui-nocache:
	$(COMPOSE) build --no-cache ui
	$(COMPOSE) up -d ui

up: setup
	$(COMPOSE) up -d
	@echo ""
	@echo "✅ Stack started."
	@echo "   UI       → http://localhost"
	@echo "   API docs → http://localhost/docs"
	@echo "   Health   → http://localhost/api/health"
	@echo ""
	@echo "⏳ Watching model pull (Ctrl+C when done — stack keeps running)…"
	@$(COMPOSE) logs -f ollama-init || true

down:
	$(COMPOSE) down

destroy:
	@echo "⚠️  Deletes ALL containers and downloaded models."
	@read -p "Type 'yes' to confirm: " c && [ "$$c" = "yes" ]
	$(COMPOSE) down -v --remove-orphans
	@echo "🗑️  Done."

logs:         ; $(COMPOSE) logs -f
logs-api:     ; $(COMPOSE) logs -f api
logs-ui:      ; $(COMPOSE) logs -f ui
logs-ollama:  ; $(COMPOSE) logs -f ollama
ps:           ; $(COMPOSE) ps
health:
	@curl -s http://localhost/api/health | python3 -m json.tool \
	    || echo "❌ API not reachable. Is the stack running? (make up)"

pull-models:  ; $(COMPOSE) run --rm ollama-init
restart-api:  ; $(COMPOSE) restart api
restart-ui:   ; $(COMPOSE) restart ui
shell-api:    ; $(COMPOSE) exec api /bin/bash
shell-ui:     ; $(COMPOSE) exec ui /bin/bash
clean:        ; docker image prune -f