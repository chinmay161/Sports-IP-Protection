.PHONY: up down build logs shell-backend shell-worker migrate test worker-status ps

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build --no-cache

logs:
	docker compose logs -f backend celery-worker celery-beat

shell-backend:
	docker compose exec backend bash

shell-worker:
	docker compose exec celery-worker bash

migrate:
	docker compose exec backend alembic upgrade head

test:
	docker compose exec backend pytest -q tests/

worker-status:
	docker compose exec celery-worker \
	  celery -A app.core.celery inspect registered

ps:
	docker compose ps
