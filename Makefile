VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help install dev deps doctor test run clean

help: ## show this help
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t18

install: $(VENV) ## create the venv and install m3talist
	@$(PIP) install -q -e .
	@echo "installed: $(VENV)/bin/m3talist"
	@$(MAKE) --no-print-directory doctor

dev: $(VENV) ## install with the test dependencies
	@$(PIP) install -q -e '.[dev]'

deps: ## install ffmpeg and fpcalc with the system package manager
	@scripts/deps.sh install

doctor: ## report which external tools are present
	@scripts/deps.sh check

test: dev ## run the test suite
	@$(PY) -m pytest -q

run: ## start the web terminal on http://127.0.0.1:8420
	@$(PY) -m m3talist serve

clean: ## remove the venv and build artefacts
	rm -rf $(VENV) build dist *.egg-info .pytest_cache
	find . -name __pycache__ -prune -exec rm -rf {} +

$(VENV):
	python3 -m venv $(VENV)
	@$(PIP) install -q --upgrade pip
