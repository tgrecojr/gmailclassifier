# Gmail Email Classifier

## Overview

A single long-running agent that polls a Gmail inbox for unread messages, asks Jev (TypeSafe's non-generative decision model, via OpenRouter's decisions endpoint) which of the operator's configured labels fit each one, applies those labels in Gmail, optionally archives, and keeps a local ledger so no message is classified twice within a retention window. One operator, one account, one instance, typically run as a Docker container on a home-lab host.

## Tech Stack

- Language: Python 3.14
- Package manager: uv (`uv.lock` is the source of truth; always `uv sync --frozen`)
- HTTP: httpx2 (synchronous client, `MockTransport` in tests)
- Gmail: google-api-python-client with google-auth-oauthlib
- Model: Jev `typesafe/jev-1.13` via `https://openrouter.ai/api/alpha/decisions`
- Tests: pytest, pytest-cov, pytest-mock; CI coverage floor 90% line coverage
- Lint and format: flake8 (max line 127, max complexity 10), black
- Container: two-stage Chainguard Python build, distroless runtime, nonroot
- CI/CD: GitHub Actions (tests, lint, and a no-push amd64 image build on PR; scan, build, sign, attest, publish to GHCR on push to main); Renovate automerges non-majors

## Commands

- `uv sync --frozen` — install dependencies from the lockfile
- `uv run python verify_setup.py` — pre-flight check (sends one tiny paid decision)
- `uv run python setup_token.py` — mint the Gmail OAuth token on a machine with a browser
- `uv run python main.py [--log-level DEBUG]` — run the agent
- `uv run pytest tests/ -m unit` — run the unit tests (coverage is on by default via pyproject)
- `uv run flake8 . && uv run black --check .` — lint and format check
- `docker compose up -d` — run the published image with mounted credentials and a `./data` volume
- `uv run python scripts/check_coherence.py` — LID arrow coherence check (references, citations, markers, drift, orphans); exits 1 on a hard finding

## Architecture

Six design segments, named for the stage of an email's path they own. See `docs/high-level-design.md` for the whole picture and `docs/intent/<segment>/` for each segment's design and specs.

| Segment | Prefix | Code | Owns |
|---|---|---|---|
| gmail-intake | `INTAKE` | `gmail_client.py` (auth and read side), `mail_text.py`, `setup_token.py` | OAuth, fetching unread mail, body extraction, URL and HTML reduction |
| jev-decision | `DECISION` | `jev_classifier.py` | Jev request shape, one-retry transport, threshold rule, label validation |
| gmail-actions | `ACTIONS` | `gmail_client.py` (write side) | Ensuring labels exist, adding labels, archiving |
| processed-state | `STATE` | `state_store.py`, agent state methods | The processed-id ledger, legacy migration, retention |
| agent-runtime | `AGENT` | `email_classifier_agent.py` (policy and loop), `config.py`, `main.py` | Settings, startup order, per-email policy, dry run, poll loop |
| operations | `OPS` | `verify_setup.py`, `Dockerfile`, compose, `.github/workflows/`, `renovate.json` | Pre-flight, image, CI gate, publish pipeline, dependency policy |

Two files are split across segments on method boundaries: `gmail_client.py` (intake and actions) and `email_classifier_agent.py` (runtime and state).

## Environment Variables

Set in the environment file (never committed; see the example file) or injected by the deployment. Names only:

- `OPENROUTER_API_KEY` — required
- `JEV_MODEL`, `JEV_LABEL_THRESHOLD`, `JEV_FALLBACK_CONFIDENCE`, `JEV_TIMEOUT_SECONDS`, `JEV_REVIEW_LABEL`
- `GMAIL_CREDENTIALS_PATH`, `GMAIL_TOKEN_PATH`, `GMAIL_HEADLESS_MODE`, `REMOVE_FROM_INBOX`
- `CLASSIFIER_CONFIG_PATH` — path to the labels-and-descriptions JSON file
- `POLL_INTERVAL_SECONDS`, `MAX_EMAILS_PER_POLL`, `STATE_FILE`, `STATE_RETENTION_DAYS`, `LOG_LEVEL`, `DRY_RUN`

Files that must never be committed: the environment file, `credentials.json`, `token.json`, `classifier_config.json`, `data/`.

## LID
- Mode: Full
- Version: 1.3.0

## Linked-Intent Development (MANDATORY)

**Consult the `linked-intent-dev` skill for ALL code changes.** All changes flow through the arrow of intent in one direction:

```
HLD → LLDs → EARS → Tests → Code
```

- **New features and refactors**: full six-phase workflow (HLD check → LLD check/draft → EARS → intent-narrowing edge audit → tests-first → code).
- **Bug fixes**: walk the arrow like any other change — find where behavior diverged from intent and cascade from there. No short-circuit.
- **If unsure**: use the full workflow.

Stop after each phase for user review. **Docs carry current intent, written to be read cold** — write each doc as if authored fresh today, from current intent alone: no narration of how it changed, no meaning that needs the conversation that produced it, no rebuttals to questions only a past discussion raised. Rationale, considered alternatives, and constraints a fresh author would independently write stay; record rejected alternatives and why in the LLD's Decisions & Alternatives table, not as asides in body prose.

**Memory vs. intent.** Before saving durable project knowledge to agent or tool memory, test whether it is project *intent* — would a fresh agent, in any tool, next session, need it to build this system correctly? If yes, record it in the arrow (HLD / LLD / EARS / decision doc), which travels and cascades — not in private, per-tool memory, where intent escapes the arrow. Knowledge about the user or how they like to work stays in memory.

### Navigation

| What you need | Where to look |
|---|---|
| High-level design | `docs/high-level-design.md` |
| Design tree (sub-HLDs, LLDs, their specs) | `docs/intent/` — one folder per node |
| EARS specs | beside each design doc as `{node}-specs.md` in the node's folder under `docs/intent/` |
| Decision docs | `docs/decisions/` (project-level) and `docs/intent/<segment>/decisions/` |
| Arrow of intent overlay | `docs/arrows/index.yaml` and per-segment docs in `docs/arrows/` |

### Terminology

- **HLD**: High-Level Design — single project-level doc at `docs/high-level-design.md`.
- **LLD**: Low-Level Design — detailed component design doc in `docs/intent/`. The design layer is a recursive tree: the root is the HLD, leaf LLDs own EARS, and a component deep enough to outgrow one doc becomes a sub-HLD (HLD-shaped, owns no EARS) with children beneath it. "HLD" and "LLD" are roles by position; depth-2 (one HLD over flat leaf LLDs) is the default.
- **EARS**: Easy Approach to Requirements Syntax — structured one-line requirements beside each design doc as `{node}-specs.md` in the node's folder under `docs/intent/`. IDs are path-concatenated — the root-to-leaf path of the owning segment plus a number — so a prefix grep gathers a subtree. Markers: `[x]` implemented, `[ ]` active gap, `[D]` deferred.
- **Arrow**: the unidirectional chain from vision to code (HLD → LLDs → EARS → Tests → Code). Strictly a DAG of intent.
- **Arrow segment**: the territory owned by one leaf LLD — the LLD itself plus the specs, tests, and code that cite its EARS IDs. The boundary is the leaf prefix. Within-segment cascade is free; across-segment cascade pauses.
- **Cascade**: propagating a change downstream through the arrow so adjacent levels stay coherent.

### Code annotations

Annotate code and tests with `@spec` comments citing EARS IDs:

```
# @spec INTAKE-FETCH-001, INTAKE-FETCH-002
```

Place the annotation at the *entry point of the behavior's implementation graph* — the topmost function or module owning the specified behavior, not every helper. When a behavior spans multiple subsystems, annotate at the entry point in each subsystem. Tests follow the same rule: annotate the test that directly exercises the spec, not every inner assertion. In YAML workflows and the Dockerfile, use `# @spec OPS-...` comments.

## LID Tooling

Declared project-local scripts that LID skills invoke instead of their in-prompt fallbacks. The listed script is authoritative for the deterministic checks it performs.

- **Coherence check**: `scripts/check_coherence.py` — run with `uv run python scripts/check_coherence.py`. Checks reference coherence (arrow-doc paths, spec IDs, line ranges), code and test citations per spec, `[ ]` markers, reverse orphans and unannotated tests, and orphan docs or code files. Exit status 1 on a hard finding. Specs verified by running rather than by unit tests (see the HLD) show up only in the informational coverage section.
