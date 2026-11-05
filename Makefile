PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install check test

install:
	$(PYTHON) -m pip install -e '.[dev]'

check:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m pytest -q

test:
	$(PYTHON) -m pytest -q
