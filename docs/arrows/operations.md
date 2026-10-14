# Arrow: operations

Verify a deployment's prerequisites, build and publish a signed container image, and keep dependencies scanned and current.

## Status

**MAPPED** — sampled 2026-10-14 (git SHA `08bbc6be6f312e7b4699611f03ec69a733093374`). Segment identified and documented from code; specs not yet verified against code by an audit pass.

## References

### HLD
- docs/high-level-design.md (System Design: delivery)

### LLD
- docs/intent/operations/operations-design.md

### EARS
- docs/intent/operations/operations-specs.md (25 specs)

### Tests
- None. CI workflows are exercised by running; `verify_setup.py` is excluded from coverage and has no unit tests.

### Code
- verify_setup.py
- Dockerfile, docker-compose.yml, .dockerignore
- .github/workflows/test.yml, docker-publish.yml, supply-chain.yml, ghcr-retention.yml
- renovate.json, osv-scanner.toml
- pyproject.toml (`[tool.pytest.ini_options]`, `[tool.coverage.*]`), .flake8

## Architecture

**Purpose:** Get a correct, current, verifiable build of the agent onto a host with as little manual work as possible, and tell the operator before the first run whether the host is ready.

**Key Components:**
1. `verify_setup.py` — pre-flight: Python version, required files, label-file content, API key presence, importable dependencies, and one paid probe of the decisions endpoint.
2. `Dockerfile` — two-stage build on digest-pinned Chainguard Python images; `uv sync --frozen --no-dev` into a venv copied to a distroless runtime; runs as `nonroot`.
3. `docker-compose.yml` — mounts credentials, token, and label config read-only plus a `./data` volume for the ledger.
4. `test.yml` — on pull requests: unit tests with a coverage floor (75% today, 90% intended), flake8, black; an image build without push is intended but absent.
5. `docker-publish.yml` + `supply-chain.yml` — on push to `main`: dependency scans gate a multi-arch build to GHCR, signed with cosign, with SBOM and provenance attestations.
6. `ghcr-retention.yml` — weekly prune of old image versions.
7. `renovate.json` — automerge policy, digest pinning, Chainguard builder/runtime lockstep.

## Spec Coverage

| Facet  | Spec IDs | Implemented | Deferred | Gaps |
|--------|----------|-------------|----------|------|
| IMAGE  | OPS-IMAGE-001 to OPS-IMAGE-006 | 6 | 0 | 0 |
| CI     | OPS-CI-001 to OPS-CI-009 | 6 | 0 | 3 |
| DEPS   | OPS-DEPS-001 to OPS-DEPS-004 | 4 | 0 | 0 |
| VERIFY | OPS-VERIFY-001 to OPS-VERIFY-006 | 6 | 0 | 0 |

**Summary:** 22 of 25 active specs observed implemented; 0 deferred; 3 gaps (OPS-CI-002 floor at 90%, OPS-CI-006 amd64 only, OPS-CI-009 build on pull requests). No `@spec` annotations exist; workflow YAML and Dockerfiles take `# @spec` comments but none are present yet.

## Key Findings

1. **No container health check** — the Dockerfile has no `HEALTHCHECK` and the loop exposes no liveness signal. A hung poll (for example on the alpha decisions endpoint) is indistinguishable from a healthy idle agent to Docker or Compose.
2. **The image is never built on pull requests** — `test.yml` runs tests and lint only; `docker-publish.yml` runs on push to `main`. A Dockerfile regression is discovered after merge.
3. **The runtime Python version is pinned by digest, not by tag** — the Chainguard runtime is `python:latest@sha256:...` (`Dockerfile:24`) while CI installs 3.14 explicitly. Renovate's digest updates will track whatever `latest` becomes; the lockstep group keeps builder and runtime equal but does not hold the minor version.
4. **A dead CI step** — the coverage badge step in `test.yml` is conditioned on `refs/heads/main`, but the workflow runs only on `pull_request`, so the step never executes.
5. **mypy is a dev dependency that nothing runs** — present in `pyproject.toml`, absent from every workflow.
6. **`verify_setup.py` requires a literal environment file** — `verify_setup.py:167` checks that `.env` exists, which fails in deployments that inject environment variables directly (ECS, Kubernetes) even when every variable is set.
7. **`docker-compose.yml` carries an obsolete `version` key** — Compose v2 ignores it with a warning. `GMAIL_HEADLESS_MODE=true` is set in both the Dockerfile and the compose `environment`.
8. **Operator scripts ship in the image** — `COPY *.py` includes `setup_token.py` and `verify_setup.py`. Useful for `docker run ... verify_setup.py`; `setup_token.py` cannot work in a browserless container.
9. **DEPLOYMENT.md drift** — it tells readers to "uncomment the COPY lines in Dockerfile"; no such lines exist. The ECS and Kubernetes sections are templates that nothing in the repository exercises.
10. **The Socket organization is hardcoded** — `supply-chain.yml` passes `--org grecolabs`; the step self-skips when the secret is absent, so forks and bot PRs still pass.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
1. Raise the coverage floor in `test.yml` from 75% to 90% (OPS-CI-002).
2. Drop `linux/arm64` and the QEMU step from `docker-publish.yml` (OPS-CI-006).
3. Build the image without pushing on pull requests (OPS-CI-009, finding 2).
4. Add a container health signal (a heartbeat file touched each poll and checked by `HEALTHCHECK`, or equivalent) so a hung loop is restartable (finding 1). Touching a heartbeat is an agent-runtime change; pause at that boundary.

### Nice to Have
5. Pin the Chainguard runtime to a minor-version tag alongside the digest, or document that `latest` is intended (finding 3).
6. Remove the dead badge step; decide whether mypy runs in CI or leaves the dev dependencies (findings 4, 5).
7. Let `verify_setup.py` accept a set environment without the file (finding 6).
8. Drop the compose `version` key and the duplicated headless variable (finding 7).
9. Fix the DEPLOYMENT.md COPY reference (finding 9).
