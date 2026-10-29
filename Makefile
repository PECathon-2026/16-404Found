# DevPilot Makefile
.PHONY: install lint format typecheck test web-dev web-build serve demo clean

PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m mypy devpilot/core devpilot/config.py tests

test:
	$(PYTHON) -m pytest -q

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

serve:
	$(PYTHON) -m uvicorn devpilot.api.app:app --reload --port 8000

demo:
	$(PYTHON) -m devpilot.cli demo

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache runs
	find . -type d -name __pycache__ -exec rm -rf {} +
