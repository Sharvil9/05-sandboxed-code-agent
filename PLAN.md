# Project 05 implementation plan

- [x] Bootstrap the correct independent repository and publish the project-specific trust, scope, and evidence rules.
- [ ] Verify the Docker engine and implement the restricted runner before enabling model-generated execution.
- [ ] Exercise real negative sandbox cases: forbidden mounts/files, denied networking, timeout, process/resource limits, output cap, and cleanup.
- [ ] Add the typed execution contract, deterministic tool interface, verifier, and meaningful unit/integration tests.
- [ ] Add the local Ollama adapter with model digest checks and strict structured response parsing.
- [ ] Implement task state, bounded correction, duplicate-candidate detection, artifact storage, and CLI.
- [ ] Run genuine model screening on the eight fixed development tasks; diagnose failures by stage and preserve all results.
- [ ] Freeze a qualifying model/configuration only if it meets the unchanged 6/8 and 90% gates; otherwise report the blocker and retain the best honest result.
- [ ] Run the fixed 24-task suite once with one-attempt baseline and bounded correction; publish the complete comparison.
- [ ] Document verified setup for macOS Docker Desktop and the actual security limits. MacBook-specific validation remains separate from cloud Linux validation.

Each meaningful milestone must pass its relevant checks, be reviewed for safe staged paths, and be committed and pushed. Do not run the 24-task suite for tuning.
