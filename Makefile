.PHONY: install run help clean serve docker docker-up docker-up-gpu docker-down docker-prune docker-purge docker-logs docker-logs-app docker-logs-worker docker-logs-db

# Default target
help:
	@echo "APOEMA - Available commands:"
	@echo ""
	@echo "  make install                                   Install dependencies (uv sync)"
	@echo "  make run assessment-file=<path>               Run APOEMA (assessment analysis only)"
	@echo "  make run assessment-file=<path> pdf-file=<path>"
	@echo "                                                 Run with PDF plot analysis"
	@echo "  make run assessment-file=<path> png-file=<path> csv-file=<path>"
	@echo "                                                 Run with PNG+CSV plot analysis"
	@echo "  make run exec-mode=crew ...                    Run with Crew execution (default: flow)"
	@echo "  make run model=<model>                         Specify model (e.g., gpt-5-mini or claude-haiku-4.5)"
	@echo "  make run prefix=<string>                       Specify custom prefix for output files"
	@echo "  make serve                                     Run the API server"
	@echo "  make docker                                    Start Docker environment (postgres, rabbitmq, worker, etc.)"
	@echo "  make docker-up                                 Start Docker environment (detached)"
	@echo "  make docker-up-gpu                             Start Docker with NVIDIA GPU (needs nvidia-container-toolkit)"
	@echo "  make docker-down                               Stop containers and remove the network (keeps data volumes)"
	@echo "  make docker-prune                              Reset network: down + remove orphan containers + prune networks (keeps data)"
	@echo "  make docker-purge                              DESTRUCTIVE: down + remove ALL volumes (postgres/ollama/chroma data)"
	@echo "  make help                                      Show this help message"
	@echo "  make clean                                     Clean generated output and cache"
	@echo ""
	@echo "Examples:"
	@echo "  make install"
	@echo "  make run assessment-file=cc_assessment_data.json"
	@echo "  make run assessment-file=cc_assessment_data.json exec-mode=flow"
	@echo "  make run assessment-file=cc_assessment_data.json model=gpt-5-mini"
	@echo "  make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf"
	@echo "  make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf exec-mode=crew"
	@echo "  make run assessment-file=cc_assessment_data.json pdf-file=cc_report.pdf model=claude-haiku-4.5"
	@echo "  make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv"
	@echo "  make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv prefix=plot_analysis"
	@echo "  make run assessment-file=cc_assessment_data.json png-file=plot.png csv-file=data.csv prefix=my_analysis exec-mode=flow"

# Install dependencies using uv
install:
	@echo "Installing dependencies with uv..."
	uv sync
	@echo "✓ Dependencies installed!"

# Run the main script with optional arguments
run:
	@uv run python main.py \
		$(if $(exec-mode),--exec-mode $(exec-mode)) \
		$(if $(assessment-file),--assessment-file $(assessment-file)) \
		$(if $(pdf-file),--pdf-file $(pdf-file)) \
		$(if $(png-file),--png-file $(png-file)) \
		$(if $(csv-file),--csv-file $(csv-file)) \
		$(if $(model),--model $(model)) \
		$(if $(prefix),--prefix $(prefix)) \
		$(if $(fresh),--fresh)

# Clean generated files
clean:
	@echo "Cleaning generated files..."
	rm -rf output/*.md
	rm -rf __pycache__
	rm -rf .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned!"

# Run the API server
serve:
	@echo "Starting API server..."
	uv run python run_api.py

# Docker compose commands
docker:
	@echo "Starting Docker environment..."
	docker compose up --build

docker-up:
	@echo "Starting Docker environment (detached)..."
	docker compose up -d --build

# GPU variant: requires nvidia-container-toolkit + an NVIDIA GPU. Falls back
# to CPU-only if the override is not present.
docker-up-gpu:
	@echo "Starting Docker environment with NVIDIA GPU (detached)..."
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

docker-gpu:
	@echo "Starting Docker environment with NVIDIA GPU..."
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build

docker-down:
	@echo "Stopping Docker environment..."
	docker compose down

# Full network reset WITHOUT touching data. Fixes the "Cannot assign requested
# address" / stale-IP symptom: a worker left in an old apoema_network keeps a
# dead postgres IP. `down` already removes the network, but orphan containers
# (started outside compose, or a previous crashed run) can hold it open, so we
# force-remove the project containers and prune dangling networks. Data lives
# in named volumes (postgres_data, ollama_data, chroma_data, ...) and survives.
docker-prune:
	@echo "Resetting Docker network (containers + networks; data volumes preserved)..."
	docker compose down
	docker rm -f apoema-dramatiq-worker apoema-app apoema-converter-worker apoema-ollama apoema-postgres apoema-rabbitmq apoema-flyway 2>/dev/null || true
	docker network prune -f
	@echo "✓ Network reset done. Bring it back up with: make docker-up-gpu (or make docker-up)"

# DESTRUCTIVE: removes the named data volumes too. Use only to start from a
# blank slate (fresh DB, re-pulled ollama models, re-embedded Chroma index).
docker-purge:
	@echo "⚠️  Purging ALL containers, networks AND data volumes..."
	docker compose down -v
	@echo "✓ Purged. Bring it back up with: make docker-up-gpu (or make docker-up)"

docker-logs:
	@docker compose logs -f

docker-logs-app:
	@docker compose logs -f apoema-app

docker-logs-worker:
	@docker compose logs -f apoema-dramatiq-worker

docker-logs-db:
	@docker compose logs -f apoema-postgres

