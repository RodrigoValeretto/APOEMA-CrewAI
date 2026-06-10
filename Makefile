.PHONY: install run help clean serve docker docker-up docker-down docker-logs docker-logs-app docker-logs-worker docker-logs-db

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
		$(if $(prefix),--prefix $(prefix))

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

docker-down:
	@echo "Stopping Docker environment..."
	docker compose down

docker-logs:
	@docker compose logs -f

docker-logs-app:
	@docker compose logs -f apoema-app

docker-logs-worker:
	@docker compose logs -f apoema-dramatiq-worker

docker-logs-db:
	@docker compose logs -f apoema-postgres

