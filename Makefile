.PHONY: up down build logs restart clean migrate migrate-create test-backend shell-backend shell-db init

# Docker commands
up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

logs:
	docker-compose logs -f

restart:
	docker-compose restart

clean:
	docker-compose down -v
	rm -rf backend/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} +

# Database commands
migrate:
	docker-compose exec backend alembic upgrade head

migrate-create:
	@read -p "Enter migration name: " name; \
	docker-compose exec backend alembic revision --autogenerate -m "$$name"

migrate-downgrade:
	docker-compose exec backend alembic downgrade -1

# Testing commands
test-backend:
	docker-compose exec backend pytest

test-backend-cov:
	docker-compose exec backend pytest --cov=app --cov-report=html

# Shell access
shell-backend:
	docker-compose exec backend bash

shell-db:
	docker-compose exec db mysql -u mysterymixclub -p mysterymixclub

# Initialization
init:
	@echo "Initializing Mystery Mix Club..."
	@echo "1. Creating .env file from .env.example..."
	@if [ ! -f backend/.env ]; then \
		cp backend/.env.example backend/.env; \
		echo "Created backend/.env - please update with your configuration"; \
	else \
		echo "backend/.env already exists"; \
	fi
	@echo "2. Building Docker containers..."
	@make build
	@echo "3. Starting containers..."
	@make up
	@echo "4. Waiting for database to be ready..."
	@sleep 10
	@echo "5. Running migrations..."
	@make migrate
	@echo ""
	@echo "Setup complete! Your API is running at http://localhost:8000"
	@echo "API docs available at http://localhost:8000/docs"

# Help
help:
	@echo "Available commands:"
	@echo "  make up              - Start all containers"
	@echo "  make down            - Stop all containers"
	@echo "  make build           - Build Docker images"
	@echo "  make logs            - View container logs"
	@echo "  make restart         - Restart containers"
	@echo "  make clean           - Stop containers and remove volumes"
	@echo "  make migrate         - Run database migrations"
	@echo "  make migrate-create  - Create a new migration"
	@echo "  make test-backend    - Run backend tests"
	@echo "  make shell-backend   - Open bash shell in backend container"
	@echo "  make shell-db        - Open MySQL shell"
	@echo "  make init            - Initialize the project (first time setup)"
