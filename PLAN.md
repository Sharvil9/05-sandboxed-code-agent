# Project 05 implementation plan

- [x] Bootstrap the correct independent repository and publish the project-specific trust, scope, and evidence rules.
- [x] Implement a local-Unix-socket Docker runner, bounded execution protocol, pinned runtime image, configuration inspection, cleanup, and an in-container readiness probe.
- [ ] Complete sandbox milestone on an engine with effective limits. The current cloud engine stores the requested Docker limits in container configuration but exposes `memory.max=8589934592`, `memory.swap.max=max`, `pids.max=max`, and `cpu.max=200000 100000` inside the container (8 GiB, unlimited swap/processes, and 2 CPUs). The trusted probe rejects it before candidate code runs.
- [ ] Exercise real negative sandbox cases on a ready engine: forbidden mounts/files, denied networking, timeout, process/resource limits, output cap, and cleanup.
- [ ] Add the typed execution contract, deterministic tool interface, verifier, and meaningful unit/integration tests.
- [ ] Add the local Ollama adapter with model digest checks and strict structured response parsing.
- [ ] Implement task state, bounded correction, duplicate-candidate detection, artifact storage, and CLI.
- [ ] Run genuine model screening on the eight fixed development tasks; diagnose failures by stage and preserve all results.
- [ ] Freeze a qualifying model/configuration only if it meets the unchanged 6/8 and 90% gates; otherwise report the blocker and retain the best honest result.
- [ ] Run the fixed 24-task suite once with one-attempt baseline and bounded correction; publish the complete comparison.
- [ ] Document verified setup for macOS Docker Desktop and the actual security limits. MacBook-specific validation remains separate from cloud Linux validation.

Current execution readiness is **blocked** in this environment. `make sandbox-test` builds the runtime, then exits nonzero at its required readiness gate (1 pass, 1 readiness failure, 9 candidate-execution tests skipped). The trusted fail-closed test confirms no candidate sentinel output and verifies container cleanup. Do not run a model or claim sandbox execution is verified until the gate and boundary tests pass on a supported engine.

Each meaningful milestone must pass its relevant checks, be reviewed for safe staged paths, and be committed and pushed. Do not run the 24-task suite for tuning.
