# Arrow: operations

Verify a deployment's prerequisites, build and publish a signed container image, and keep dependencies scanned and current.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 25 specs implemented and annotated; verified by CI runs and by running the verify script (HLD: verified by running).

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
1. `verify_setup.py` — pre-flight: Python version, credentials and label files, label-file content, API key presence, importable dependencies, and one paid probe of the decisions endpoint.
2. `Dockerfile` — two-stage build on digest-pinned Chainguard Python images; `uv sync --frozen --no-dev` into a venv copied to a distroless runtime; runs as `nonroot`.
3. `docker-compose.yml` — mounts credentials, token, and label config read-only plus a `./data` volume for the ledger.
4. `test.yml` — on pull requests: unit tests with a 90% coverage floor, flake8, black, and an amd64 image build without push.
5. `docker-publish.yml` + `supply-chain.yml` — on push to `main`: dependency scans gate a multi-arch build to GHCR, signed with cosign, with SBOM and provenance attestations.
6. `ghcr-retention.yml` — weekly prune of old image versions.
7. `renovate.json` — automerge policy, digest pinning, Chainguard builder/runtime lockstep.

## Spec Coverage

| Facet  | Spec IDs | Implemented | Deferred | Gaps |
|--------|----------|-------------|----------|------|
| IMAGE  | OPS-IMAGE-001 to OPS-IMAGE-006 | 6 | 0 | 0 |
| CI     | OPS-CI-001 to OPS-CI-009 | 9 | 0 | 0 |
| DEPS   | OPS-DEPS-001 to OPS-DEPS-004 | 4 | 0 | 0 |
| VERIFY | OPS-VERIFY-001 to OPS-VERIFY-006 | 6 | 0 | 0 |

**Summary:** 25 of 25 active specs implemented; 0 deferred. The Dockerfile, compose file, all four workflows, and `verify_setup.py` carry `@spec` comments. OPS-DEPS-002 to OPS-DEPS-004 live in `renovate.json`, which cannot carry comments, and are cited from the LLD only. No operations spec has a unit test: CI, IMAGE, and DEPS specs are verified by the workflows running on every pull request and push to `main`; VERIFY specs by running the script. This is the accepted convention per the HLD. No `@spec` annotations exist; workflow YAML and Dockerfiles take `# @spec` comments but none are present yet.

## Key Findings

1. **No container health check, by decision** — the loop exposes no liveness signal. Docker and Compose would not restart an unhealthy container anyway, so a `HEALTHCHECK` is deferred until a hung loop is actually observed.
2. **The runtime Python version is held by digest, not by tag** — Chainguard's public images publish only `latest`; the digest pin and the Renovate lockstep group hold builder and runtime together. Intended.
3. **The Socket organization is hardcoded** — `supply-chain.yml` passes `--org grecolabs`; the step self-skips when the secret is absent, so forks and bot PRs still pass.
4. **Operator scripts ship in the image** — `COPY *.py` includes `setup_token.py` and `verify_setup.py`. Kept: `verify_setup.py` in the image is useful and `setup_token.py` is harmless.

## Work Required

### Must Fix
_None._

### Should Fix
_None._

### Nice to Have
_None._
