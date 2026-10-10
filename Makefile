.PHONY: dev test lint migrate seed demo stop reset-demo logs

dev:
	docker compose up --build

test:
	cd backend && ../.venv/bin/python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=85

lint:
	cd backend && ../.venv/bin/python -m ruff check . && ../.venv/bin/python -m mypy app && ../.venv/bin/python -m bandit -q -r app

migrate:
	cd backend && DATABASE_URL=$${DATABASE_URL:-sqlite+aiosqlite:///./teeka_yatra.db} ../.venv/bin/alembic upgrade head

seed:
	cd backend && DATABASE_URL=$${DATABASE_URL:-sqlite+aiosqlite:///./teeka_yatra.db} ../.venv/bin/python -m app.seed

demo:
	docker compose up --build -d
	@echo "Waiting for API health..."
	@for i in $$(seq 1 60); do \
		if curl -fsS http://localhost:8000/health >/dev/null; then \
			echo "Demo ready: API http://localhost:8000/docs  Frontend http://localhost:5173"; \
			exit 0; \
		fi; \
		sleep 2; \
	done; \
	echo "API did not become healthy in time. Run 'make logs' for details."; \
	exit 1

stop:
	docker compose down

reset-demo:
	docker compose down -v
	$(MAKE) demo

logs:
	docker compose logs -f api frontend worker
