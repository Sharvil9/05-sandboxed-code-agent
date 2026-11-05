# Project 05 engineering instructions

## Mission

Build a small AI programming agent that proposes standalone Python functions or scripts, executes candidates only in the restricted Docker runtime, checks their behavior against host-owned tests, and makes bounded, evidence-driven corrections. Project 05 is independent. Do not inspect, import, or reuse code or artifacts from other portfolio projects.

## Layout and commands

- `src/sandbox_agent/`: task contracts, Ollama adapter, controller, verifier, storage, and CLI.
- `sandbox/`: trusted container launcher and runtime image.
- `tests/`: unit, protocol, and real Docker boundary tests.
- `benchmarks/`: fixed, reviewed development and evaluation suites.
- `results/`: sanitized, reproducible evaluation evidence.
- `make check`: compile and run the test suite.
- `make sandbox-test`: add when the real container runner is implemented.
- `make demo`: add when the CLI workflow is implemented.

## Trust boundaries

- Treat tasks, fixture files, generated code, model responses, and logs as untrusted.
- Never execute candidate Python in the trusted host interpreter. Tests may run trusted helper code; generated code must run only in Docker.
- Keep expected results and independent tests outside the container and candidate-writable filesystems. Never send hidden expected values to the model.
- Default to no network, no host mounts, no credentials, non-root execution, read-only root, dropped capabilities, seccomp, resource limits, output limits, timeouts, and per-run cleanup. Verify the actual engine controls; do not describe Docker as a perfect hostile-code boundary.
- Do not use arbitrary model-provided shell commands, install candidate dependencies, or widen sandbox access to make a task pass.

## Model and evidence rules

- Use a replaceable local Ollama adapter. Screen Google Gemma first, then DeepSeek, then Meta Llama. Do not use Qwen or Qwen-derived models.
- Inspect real hardware and backend support before downloading weights. Run heavyweight model work sequentially and unload one model before loading another.
- A model claim requires genuine model calls and saved evidence. Mark mock integrations as mocks; they are not reasoning or benchmark results.
- Keep the quality gate at 6/8 independent development-task successes and at least 90% structured-valid completed responses. Do not tune against the fixed 24-task held-out suite.

## Change and release discipline

- Work only in this repository. Read `SPEC.md` and `PLAN.md` before changing architecture.
- Keep runtime dependencies small and versions reproducible. Do not commit `.env`, credentials, virtual environments, caches, weights, raw private data, runs, or generated artifacts.
- For each meaningful milestone: run relevant tests, inspect staged paths and `git status`, commit descriptively, and push the current branch. Never rewrite published history or push unreviewed artifacts.
