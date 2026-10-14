---
parent: high-level-design
prefix: OPS
---

# Operations

## Context and Design Philosophy

Operations covers everything that gets the agent from a commit to a running, trustworthy process on a host: the pre-flight check an operator runs before the first start, the container image, the CI gate on pull requests, the publish pipeline on `main`, and the dependency policy that keeps all of it current without hand work.

Principles:

- **Merge means ship.** A push to `main` produces a published, signed, multi-architecture image with attestations. There is no separate release step.
- **Current by default.** Renovate automerges every non-major update after a short stability window; humans review only majors. Lockfile maintenance runs weekly.
- **Nothing secret in the image.** Credentials, the OAuth token, the label file, and the environment are mounted or injected at run time. The image contains code and dependencies only.
- **Tell the operator before spending money or time.** `verify_setup.py` checks the host and sends exactly one tiny paid decision so a bad key or empty account is found before the loop starts.

## Pre-flight: `verify_setup.py`

Runs five numbered check groups and prints a pass/fail line for each:

1. **Python version** at least 3.14.
2. **Required files**: the environment file, `credentials.json`, and the label file at `CLASSIFIER_CONFIG_PATH`. When the label file is present it is also opened: it must have labels and a description for every label; a leftover `classification_prompt` key earns a note that it can be removed.
3. **Environment**: `OPENROUTER_API_KEY` is set and is not a placeholder (contains `xxxx` or equals `your_openrouter_api_key`).
4. **Dependencies**: `google.auth`, `google_auth_oauthlib`, `googleapiclient`, `httpx2`, and `dotenv` import.
5. **Decisions endpoint**: when dependencies import, construct a `JevClassifier` with one probe label and send one decision (about $0.00002). On failure, HTTP 401 or 403 earns a hint that the key was rejected, 402 that the account has no credits.

Exit 0 with the run command when every check passes; otherwise exit 1 with a pointer to the README.

The environment-file check is a file-existence test. Deployments that inject variables without a file fail check 2 even when every variable is present.

## Container Image

Two stages, both on Chainguard Python images pinned by digest:

| Stage | Base | Does |
|---|---|---|
| builder | `cgr.dev/chainguard/python:latest-dev` | copies `uv` from the pinned `ghcr.io/astral-sh/uv` image; `uv sync --frozen --no-dev --no-install-project` into `/app/.venv` with bytecode compiled and Python downloads disabled; creates `/app/data`; chowns `/app` to `nonroot` |
| runtime | `cgr.dev/chainguard/python:latest` | copies the venv and data dir from the builder; copies root-level `*.py`; sets `PATH` to the venv and container defaults for the Gmail paths, headless mode, label file path, and state file; `CMD ["python", "main.py"]` |

Container defaults: `GMAIL_CREDENTIALS_PATH=/app/credentials.json`, `GMAIL_TOKEN_PATH=/app/token.json`, `GMAIL_HEADLESS_MODE=true`, `CLASSIFIER_CONFIG_PATH=/app/classifier_config.json`, `STATE_FILE=/app/data/.email_state.json`.

The runtime image is distroless: no shell, no package manager. The process runs as the image's `nonroot` user. There is no `HEALTHCHECK`.

`.dockerignore` excludes the environment file, credentials, token, tests, documentation other than the README, Docker files, caches, and agent tooling directories. Because the Dockerfile copies `*.py`, the two operator scripts are present in the image.

`docker-compose.yml` runs the image with `restart: unless-stopped`, mounts `credentials.json`, `token.json`, and `classifier_config.json` read-only, mounts `./data` read-write for the ledger, loads the environment file, sets `GMAIL_HEADLESS_MODE=true` and `LOG_LEVEL=INFO`, and declares CPU and memory limits under `deploy.resources`. The file carries a `version: '3.8'` key that Compose v2 ignores.

## Pull-Request Gate: `test.yml`

Two jobs on every pull request today, with a third intended:

- **test**: `astral-sh/setup-uv` with lock-keyed cache; `uv python install 3.14`; `uv sync --frozen`; `pytest tests/ -m unit` with coverage to terminal, XML, and HTML; upload to Codecov (non-fatal); upload the HTML report as an artifact; fail if XML line coverage is below the floor. The design sets the floor at 90%; the workflow today enforces 75%. A badge-generation step is conditioned on the `main` ref and never runs here.
- **lint**: flake8 twice, first failing the job on syntax errors and undefined names only (`E9,F63,F7,F82`), then reporting everything else at `--max-complexity=10 --max-line-length=127` with exit-zero; then `black --check --diff`.

Intended but not yet present: a **build** job that builds the image for `linux/amd64` without pushing, so Dockerfile and lockfile regressions fail the pull request.

Only tests marked `unit` run. `integration` and `slow` markers are declared in `pyproject.toml` with no tests behind them. `mypy` is a dev dependency and is not run.

## Publish Pipeline: `docker-publish.yml` and `supply-chain.yml`

On push to `main`:

1. **Supply chain** (reusable workflow): `uv export --frozen` to a requirements file; Socket Security scan when `SOCKET_SECURITY_API_KEY` is present (skipped otherwise, so bot-authored PRs that lack secrets still pass); OSV scan of `uv.lock` (allowlist in `osv-scanner.toml`, currently empty); pip-audit of the exported requirements.
2. **Build and push** (needs step 1): Buildx; log in to GHCR with the workflow token; tags `latest` and `main-<sha>`; build `linux/amd64` with GitHub Actions cache; push. The workflow today also sets up QEMU and builds `linux/arm64`; the design drops both.
3. **Sign and attest**: cosign keyless signature on the pushed digest; SPDX SBOM generated by `anchore/sbom-action` and attested with `actions/attest`; build provenance attested with `actions/attest-build-provenance`; both pushed to the registry.

`ghcr-retention.yml` runs every Monday (and on demand): keep `latest` plus the five most recent tagged versions, delete untagged versions.

## Dependency Policy: `renovate.json`

- Semantic commits, dependency dashboard, no rate limiting, New York timezone, runs weeknights and weekends.
- Pin Docker digests. Digest updates automerge at any time with no release-age wait.
- Minor and patch updates are grouped into one PR, wait 3 days after release, and automerge (branch automerge for Docker).
- Major updates are never automerged and are labeled `major-update`.
- The Chainguard builder and runtime images are grouped so they always move in one PR and the venv built on one matches the Python in the other.
- Lockfile maintenance runs before 4am on Mondays. Vulnerability alerts are enabled and labeled `security`.
- A rule for common infrastructure images (`postgres`, `nginx`, and others) with a 1-day age is present and matches nothing in this repository.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Base images | Chainguard Python, distroless runtime, digest-pinned, builder and runtime moved together | `python:slim`; Alpine; a single-stage image | Minimal attack surface and no shell in the runtime; the lockstep Renovate group exists so the venv copied from the builder always matches the runtime Python (`renovate.json` rule description). |
| Dependency install | `uv sync --frozen --no-dev --no-install-project` from the committed lockfile, bytecode compiled | `pip install -r requirements.txt`; installing the project as a package | The lockfile is the source of truth and Renovate maintains it; `--frozen` guarantees the image matches it exactly; no dev tools in the runtime; precompiled bytecode shortens startup. |
| Runtime user | `nonroot` | root | Least privilege; the process needs only to read mounted files and write `/app/data`. |
| Secrets and config delivery | Read-only volume mounts and environment injection; nothing baked into the image | Build credentials and config into the image | Credentials and tokens must never be in a shippable artifact; the label file could be baked but is mounted for consistency (DEPLOYMENT "Security Best Practices"). |
| Health check | None | `HEALTHCHECK` on a heartbeat file; an HTTP liveness endpoint | Never considered. Distroless images have no shell for a conventional check and the loop exposes no signal. Adding one is Deferred 1. |
| Publish trigger | Every push to `main`, gated by the supply-chain scan | Tagged releases; manual dispatch | One operator, one deployment: the newest `main` is the release. Scans run first so a vulnerable lockfile cannot ship. |
| Image trust | Keyless cosign signature plus SBOM and provenance attestations | Unsigned images; key-based signing | Verifiable images with no key to manage; GitHub's OIDC identity is the signer. |
| Architectures | `linux/amd64` only | amd64 and arm64 (today's workflow) | The agent runs on one x86 host; the arm64 build and the QEMU step it needs add CI time for an image nobody pulls. The workflow still builds both; dropping arm64 is pending (OPS-CI-006 is an active gap). |
| Image retention | Keep `latest` and five tagged versions, delete untagged, weekly | Keep everything; keep by age | Bounds registry storage while leaving enough history to roll back a few merges. |
| Renovate posture | Automerge non-majors after 3 days; majors need review; digests immediately | Review everything; automerge everything | Non-major updates on a small single-user service are low risk and high volume; majors can need migration work (rule descriptions in `renovate.json`). |
| Coverage floor | 90% line coverage on pull requests | 75% (today's workflow); no floor; a floor at the current 95% | The suite sits at about 96%, so 75% would let a quarter of the code lose its tests before CI noticed. 90% leaves room for ordinary churn while catching a real drop. The workflow still enforces 75%; raising it is pending (OPS-CI-002 is an active gap). |
| Lint severity | flake8 fails only on syntax errors and undefined names; style findings are advisory; black is enforced | Fail on every flake8 finding | Formatting is objective and black decides it; style warnings are informative (workflow comments, `test.yml`). |
| PR gate scope | Tests, lint, and an image build without push | Tests and lint only (today's workflow) | Not building on pull requests was an oversight. A Dockerfile or lockfile regression should fail the PR, not the first push to `main` (OPS-CI-009 is an active gap). |
| Pre-flight probe | Send one real decision request | Only check that the key is non-empty; list models | Jev does not appear in OpenRouter's text-model listing, so the only end-to-end proof is a real decision; it costs about $0.00002 (docstring, `verify_setup.py:105`). |

## Open Questions & Future Decisions

### Resolved
1. ✅ Build for `linux/amd64` only; the deployment has no ARM hosts.
2. ✅ Raise the pull-request coverage floor from 75% to 90%.
3. ✅ Build the image (without pushing) on pull requests.

### Deferred
1. Add a liveness signal and `HEALTHCHECK` so a hung poll is restarted. The signal (for example a heartbeat file touched each cycle) would be an agent-runtime change.
2. Pin the Chainguard runtime to a minor-version tag alongside the digest, or record that tracking `latest` is intended.
3. Remove the badge step that never runs. Decide whether `mypy` should run in CI or leave the dev dependencies.
4. Let `verify_setup.py` pass when variables are set without an environment file.
5. Drop the obsolete compose `version` key and the headless variable duplicated between Dockerfile and compose.
6. DEPLOYMENT.md refers to Dockerfile COPY lines that do not exist, and its ECS and Kubernetes sections are untested templates. Correct or trim.
7. Should `setup_token.py` be excluded from the image, since it cannot run without a browser?
8. The Renovate rule for `postgres`, `nginx`, and similar images matches nothing here; remove or keep as shared policy.

## References

- `verify_setup.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`
- `.github/workflows/test.yml`, `docker-publish.yml`, `supply-chain.yml`, `ghcr-retention.yml`
- `renovate.json`, `osv-scanner.toml`, `.flake8`, `pyproject.toml`
- README.md: "Docker Deployment"; DEPLOYMENT.md; TESTING.md: "Continuous Integration"
- Consumers of the container defaults: `docs/intent/agent-runtime/agent-runtime-design.md` (Configuration)
