PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: install check test sandbox-image sandbox-test

install:
	$(PYTHON) -m pip install -e '.[dev]'

check:
	$(PYTHON) -m compileall -q src tests sandbox
	$(PYTHON) -m pytest -q -m 'not sandbox'

test:
	$(PYTHON) -m pytest -q

sandbox-image:
	docker build --file sandbox/Dockerfile --tag sandbox-agent-runtime:local .

sandbox-test: sandbox-image
	SANDBOX_REQUIRE_READY=1 $(PYTHON) -m pytest -q -m sandbox
