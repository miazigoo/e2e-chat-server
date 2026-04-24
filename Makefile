.PHONY: up test test-unit test-integration lint format

up:
	docker compose up --build

test: test-unit

test-unit:
	.venv/bin/pytest -q tests --ignore=tests/integration

test-integration:
	.venv/bin/pytest -q -m integration tests/integration

lint:
	.venv/bin/black --check .
	.venv/bin/isort --check-only .
	.venv/bin/flake8 .
	.venv/bin/mypy app tests

format:
	.venv/bin/black .
	.venv/bin/isort .
