COMPOSE  = docker compose
ENV_FILE = .env
CFLAGS   = --env-file $(ENV_FILE)

.PHONY: help setup build up down destroy logs logs-api logs-ui logs-ollama \
        ps health pull-models restart-api restart-ui shell-api shell-ui clean

help:
	@echo ""
	@echo "  Jenkins RCA — BAT.AI"
	@echo "  ─────────────────────────────────────────────"
	@echo "  make setup          Create .env from .env.example"
	@echo "  make build          Build Docker images"
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
	@if [ ! -f $(ENV_FILE) ]; then \
	    cp .env.example $(ENV_FILE); \
	    echo "✅ Created .env — edit it to choose your LLM model."; \
	else \
	    echo "ℹ️  .env already exists."; \
	fi

build: setup
	$(COMPOSE) $(CFLAGS) build --no-cache

up: setup
	$(COMPOSE) $(CFLAGS) up -d
	@echo ""
	@echo "✅ Stack started."
	@echo "   UI       → http://localhost"
	@echo "   API docs → http://localhost/docs"
	@echo "   Health   → http://localhost/api/health"
	@echo ""
	@echo "⏳ Watching model pull (Ctrl+C when done — stack keeps running)…"
	@$(COMPOSE) $(CFLAGS) logs -f ollama-init || true

down:
	$(COMPOSE) $(CFLAGS) down

destroy:
	@echo "⚠️  Deletes ALL containers and downloaded models."
	@read -p "Type 'yes' to confirm: " c && [ "$$c" = "yes" ]
	$(COMPOSE) $(CFLAGS) down -v --remove-orphans
	@echo "🗑️  Done."

logs:         ; $(COMPOSE) $(CFLAGS) logs -f
logs-api:     ; $(COMPOSE) $(CFLAGS) logs -f api
logs-ui:      ; $(COMPOSE) $(CFLAGS) logs -f ui
logs-ollama:  ; $(COMPOSE) $(CFLAGS) logs -f ollama
ps:           ; $(COMPOSE) $(CFLAGS) ps
health:
	@curl -s http://localhost/api/health | python3 -m json.tool \
	    || echo "❌ API not reachable. Is the stack running? (make up)"

pull-models:  ; $(COMPOSE) $(CFLAGS) run --rm ollama-init
restart-api:  ; $(COMPOSE) $(CFLAGS) restart api
restart-ui:   ; $(COMPOSE) $(CFLAGS) restart ui
shell-api:    ; $(COMPOSE) $(CFLAGS) exec api /bin/bash
shell-ui:     ; $(COMPOSE) $(CFLAGS) exec ui /bin/bash
clean:        ; docker image prune -f
