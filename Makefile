.PHONY: install run lint fmt clean test docker-build docker-run

install:
	pip install -r requirements.txt

run:
	python src/main.py

lint:
	ruff check src/ scripts/

fmt:
	ruff format src/ scripts/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .ruff_cache/

test:
	python -m pytest tests/ -v

docker-build:
	docker compose build

docker-run:
	docker compose up --build
