# Sandboxed Code Agent

A local-model Python coding agent that generates a candidate, runs it in a restricted Docker container, checks it against host-owned tests, and makes a small number of evidence-driven repairs. Generated programs never run in the trusted host Python interpreter.

The project is being rebuilt in milestones. The initial repository contains the project scope and trust-boundary specification; the Docker runner is the first implementation milestone. No model score or security guarantee is claimed until the corresponding real checks run.

## Requirements

- Python 3.11 or newer
- Docker Engine with Linux containers, cgroups v2, seccomp, and support for resource limits; on macOS use Docker Desktop
- Ollama only for genuine local-model generation (it is not required for sandbox-only checks)

## Setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Commands

```sh
make check
make sandbox-test
```

`make sandbox-test` builds the digest-pinned runtime image and executes controlled integration checks against the local Docker engine. It does not download or invoke a model. See [PLAN.md](PLAN.md) for current progress and [SPEC.md](SPEC.md) for the trust model and acceptance criteria.

The runner refuses to execute candidates unless its in-container probe confirms the configured resource limits are effective. `make sandbox-test` exits nonzero when that readiness gate fails. The current cloud Docker engine does not delegate those cgroup limits, so candidate execution remains blocked here; the exact measurements are recorded in [PLAN.md](PLAN.md).

## Security boundary

The intended runtime disables networking and host mounts, uses a non-root identity with reduced privileges, and enforces time, memory, CPU, process, and output limits. Docker still shares a kernel with its host. This local developer project is not a hardened multi-tenant code-execution service.
