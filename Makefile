.PHONY: install test backtest paper report clean lint

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --cov=src --cov-report=term

backtest:
	python scripts/run_backtest.py

paper:
	python scripts/run_paper.py

report:
	python scripts/daily_report.py

analysis:
	python scripts/run_analysis.py $(STOCK)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

lint:
	ruff check src/ tests/
	black --check src/ tests/

format:
	black src/ tests/
	ruff check --fix src/ tests/
