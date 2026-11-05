.PHONY: up down logs migrate test lint backend-dev worker-dev web-dev

up:            ## Build and start the full stack
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f api worker
migrate:
	docker compose run --rm migrate
test:          ## Backend tests (SQLite) inside Docker
	docker build -t faceless-backend-test --target test backend && docker run --rm faceless-backend-test
lint:
	cd backend && ruff check app tests
	cd frontend && npm run lint && npx tsc --noEmit
backend-dev:
	cd backend && uvicorn app.main:app --reload
worker-dev:
	cd backend && arq app.workers.worker.WorkerSettings --watch app
web-dev:
	cd frontend && npm run dev
