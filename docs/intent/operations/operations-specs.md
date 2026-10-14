# Operations — EARS Specs

Prefix `OPS`. Facets: `IMAGE` (container image and compose), `CI` (pull-request gate and publish pipeline), `DEPS` (dependency scanning and Renovate policy), `VERIFY` (pre-flight script).

Status markers: `[x]` observed working in current code, `[ ]` specified but broken or partial, `[D]` explicit non-want.

## Container Image

- [x] **OPS-IMAGE-001**: The container build shall use two stages, a Chainguard Python dev image as builder and a Chainguard Python distroless image as runtime, each pinned by digest.
- [x] **OPS-IMAGE-002**: The builder stage shall install dependencies from the committed lockfile with `uv sync --frozen --no-dev --no-install-project`, compiling bytecode and never downloading a Python, into a venv that the runtime stage copies.
- [x] **OPS-IMAGE-003**: The runtime stage shall run as the `nonroot` user, with `/app` and `/app/data` owned by that user.
- [x] **OPS-IMAGE-004**: The runtime stage shall copy only root-level `*.py` files and the built venv; tests, documentation other than the README, the environment file, credentials, tokens, and Docker files shall be excluded by `.dockerignore`.
- [x] **OPS-IMAGE-005**: The runtime image shall default `GMAIL_HEADLESS_MODE` to `true`, the credentials, token, and label-file paths to `/app/*.json`, and `STATE_FILE` to `/app/data/.email_state.json`, and shall start `python main.py`.
- [x] **OPS-IMAGE-006**: The compose definition shall mount `credentials.json`, `token.json`, and `classifier_config.json` read-only, mount `./data` read-write, load the environment file, and restart the container unless stopped.

## Continuous Integration and Publishing

- [x] **OPS-CI-001**: When a pull request is opened or updated, CI shall install Python 3.14 and the frozen lockfile with uv and run the tests marked `unit` with coverage reported to terminal, XML, and HTML.
- [x] **OPS-CI-002**: If pull-request line coverage is below 90%, then the test job shall fail.
- [x] **OPS-CI-003**: When a pull request is opened or updated, the lint job shall fail on flake8 syntax errors and undefined names (`E9`, `F63`, `F7`, `F82`) and shall report all other flake8 findings without failing.
- [x] **OPS-CI-004**: If `black --check` reports any file that would be reformatted, then the lint job shall fail.
- [x] **OPS-CI-005**: When a commit is pushed to `main`, the publish workflow shall run the supply-chain scan first and shall build the image only if the scan succeeds.
- [x] **OPS-CI-006**: When publishing, CI shall build a `linux/amd64` image (no other architectures) and push it to GHCR tagged `latest` and `main-<short sha>`.
- [x] **OPS-CI-007**: When an image is pushed, CI shall sign its digest with keyless cosign and shall attest an SPDX SBOM and build provenance to the registry.
- [x] **OPS-CI-008**: Every Monday and on manual dispatch, CI shall prune GHCR versions of the image, keeping `latest` and the five most recent tagged versions and deleting untagged versions.
- [x] **OPS-CI-009**: When a pull request is opened or updated, CI shall build the `linux/amd64` image without pushing it, so the build job fails on a Dockerfile or lockfile regression.

## Dependency Scanning and Policy

- [x] **OPS-DEPS-001**: The supply-chain scan shall export the frozen lockfile to a requirements file, run an OSV scan of `uv.lock`, run pip-audit on the exported requirements, and run a Socket Security scan only when its API key secret is present.
- [x] **OPS-DEPS-002**: Renovate shall group minor and patch updates into one pull request, wait three days after release, and automerge them; major updates shall not be automerged and shall carry the `major-update` label.
- [x] **OPS-DEPS-003**: Renovate shall update the Chainguard builder and runtime images together in a single pull request.
- [x] **OPS-DEPS-004**: Renovate shall pin Docker image digests, automerge digest updates at any time, and run lockfile maintenance weekly before 4am on Mondays.

## Pre-flight Verification

- [x] **OPS-VERIFY-001**: When the verification script runs, it shall report failure if the Python version is below 3.14.
- [x] **OPS-VERIFY-002**: When the verification script runs, it shall report whether the environment file, `credentials.json`, and the label file at `CLASSIFIER_CONFIG_PATH` exist, and when the label file exists shall report failure unless it has labels and a non-empty description for each, noting any leftover `classification_prompt` key.
- [x] **OPS-VERIFY-003**: When the verification script runs, it shall report failure if `OPENROUTER_API_KEY` is unset, blank, or a placeholder (contains `xxxx` or equals `your_openrouter_api_key`).
- [x] **OPS-VERIFY-004**: When the verification script runs, it shall report failure for each of `google.auth`, `google_auth_oauthlib`, `googleapiclient`, `httpx2`, and `dotenv` that cannot be imported.
- [x] **OPS-VERIFY-005**: When all dependencies import and an API key is set, the verification script shall send one decision request with a single probe label to the configured model and report success on a valid answer; on HTTP 401 or 403 it shall hint that the key was rejected and on HTTP 402 that the account has no credits.
- [x] **OPS-VERIFY-006**: When every check passes, the verification script shall exit 0 and print the command to start the agent; otherwise it shall exit 1 and point at the README.
