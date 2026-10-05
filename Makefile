.PHONY: demo test stop reset-demo

demo:
	docker compose up --build

test:
	cd backend && pytest

stop:
	docker compose down

reset-demo:
	docker compose down -v
	docker compose up --build
