# Project 05 specification

## Product scope

This project accepts a natural-language request for a small Python function or script, asks a local language model for structured candidate code, runs it only in an isolated Docker container, compares actual behavior with trusted deterministic tests, and optionally asks the model for bounded corrections based on concise failure evidence. It returns code only as verified when the independent verifier passes.

Supported first tasks: algorithms, small data transformations, CSV/JSON processing, and dependency-light command-line scripts. No package installation, arbitrary network access, production filesystems, credentials, GUI automation, or multi-file projects.

## Components

- Task controller: validates task size, contracts, files, and budgets; coordinates a state machine and bounded attempts.
- Model adapter: local Ollama chat API, structured `{code: ...}` response, pinned model digest, bounded prompts/timeouts, no model-provided tool execution.
- Sandbox runner: Docker local engine; a fresh restricted container for each execution; no host mounts, network, credentials, or privileged access.
- Trusted launcher: materializes bounded fixtures, runs candidate code inside the container, emits bounded observations. It never receives expected values.
- Verifier: keeps provided and independent cases host-owned, runs candidates through the sandbox, compares types and outputs, classifies failures, and never imports candidate code on the host.
- Correction loop: gives the model original task, candidate, and bounded provided-case diagnostics; caps attempts and time; stops on duplicate candidates or infrastructure failure.
- Artifact store and CLI: atomic local run records and a small `doctor`, `run`, and fixed-suite `evaluate` interface.

## Execution boundary

Use a prebuilt, digest-pinned Python runtime image. Require Linux, cgroups v2, seccomp, and observable memory, CPU, and PID limits. Run as a fixed non-root UID with read-only root filesystem, small `noexec,nosuid,nodev` tmpfs work areas, no network, no bind mounts, no devices, all capabilities dropped, no-new-privileges, default seccomp, equal memory/swap caps, CPU quota, PID cap, file-descriptor cap, output cap, and timeout. Verify container configuration before start and launcher identity/cgroup settings before executing candidate code. Remove each container and verify cleanup.

This is defense in depth for bounded local tasks, not a hardened multi-tenant service. Docker shares the host kernel; kernel/daemon vulnerabilities, denial of service outside observable limits, and host compromise remain risks. Require macOS users to use Docker Desktop's Linux VM; verify the actual Docker engine before running tasks.

## Model selection and evaluation

Use local inference where possible through Ollama. Compare actual model-specific instruction following, structured-output validity, task accuracy, correction success, latency, token counts, and memory. Keep family priority Gemma, DeepSeek, then Llama; exclude Qwen. Do not select a model from parameter count or vendor claims alone.

The fixed eight-task development suite supports diagnosis and selection. Preserve a quality gate of at least 6/8 independent final passes and 90% structured-valid completed model calls. Only after a model/configuration passes and is frozen may the fixed 24-task evaluation compare one-attempt baseline with bounded correction. Hidden cases never enter prompts. Report every task and infrastructure failure.

## Acceptance criteria

1. A user can submit a bounded natural-language Python task and optional JSON tests/fixtures.
2. A genuine supported local model generates code through a structured adapter.
3. Candidate execution occurs only in a tested restricted container.
4. Host-owned tests verify behavior; exit code alone never implies success.
5. Observed failures can produce targeted, bounded correction attempts.
6. State, candidates, execution output, test outcomes, and final result are persisted without exposing hidden expectations.
7. Fixed evaluation reports first-pass/final success, correction effectiveness, latency, resource use, and safety tests honestly.
8. Unsupported tasks and unresolved failures stop clearly; unverified code is never reported as verified.
