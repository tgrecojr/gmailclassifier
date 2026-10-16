# Arrow: agent-runtime

Load settings, wire the Gmail client and Jev classifier, poll on an interval, and decide per email what to do: label and archive, send to review, dry-run, or skip.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 38 specs implemented and annotated; the CLI and import-time specs are verified by running (HLD: verified by running).

## References

### HLD
- docs/high-level-design.md (System Design: orchestration and policy)

### LLD
- docs/intent/agent-runtime/agent-runtime-design.md

### EARS
- docs/intent/agent-runtime/agent-runtime-specs.md (39 specs)

### Tests
- tests/test_email_classifier_agent.py (`TestEmailClassifierAgentInit`, `TestProcessEmail`, `TestDryRun`, `TestRunContinuous`)
- tests/test_config.py
- tests/conftest.py (throwaway label config so `config` can import)

### Code
- email_classifier_agent.py:17-88, 131-283 (`__init__`, `_initialize_labels`, `process_email`, `_handle_unlabeled`, `run_continuous`)
- config.py (all)
- main.py (all)

## Architecture

**Purpose:** Own the policy. Every other segment is a mechanism (fetch, decide, write, remember); this one decides the order, the defaults, and what happens on each outcome.

**Key Components:**
1. `config.py` — reads the environment file and `classifier_config.json` at import, validates shapes, ranges, and boolean spellings, and exposes module-level constants. A bad config stops the process before anything else runs.
2. `EmailClassifierAgent.__init__` — constructs the Jev classifier (configuration-only, fails fast), then the Gmail client (which authenticates), ensures Gmail labels exist, and loads the ledger.
3. `process_email` — the per-email policy: skip if in ledger; classify; dry-run short-circuit; unlabeled path; label and archive; mark processed.
4. `run_continuous` / `_poll_once` — the poll loop: prune ledger, fetch, process, sleep; survives any exception by sleeping with exponential backoff and retrying; SIGTERM and Ctrl-C end it cleanly.
5. `main.py` — CLI flag for log level, stdout logging, startup banner, exit codes.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| CFG   | AGENT-CFG-001 to AGENT-CFG-015 | 15 | 0 | 0 |
| INIT  | AGENT-INIT-001 to AGENT-INIT-006 | 6 | 0 | 0 |
| PROC  | AGENT-PROC-001 to AGENT-PROC-010 | 10 | 0 | 0 |
| LOOP  | AGENT-LOOP-001 to AGENT-LOOP-005 | 5 | 0 | 0 |
| CLI   | AGENT-CLI-001 to AGENT-CLI-003 | 3 | 0 | 0 |

**Summary:** 39 of 39 active specs implemented; 0 deferred. All are cited by `@spec` annotations in code. AGENT-CFG-001, AGENT-CFG-008, AGENT-CFG-012 (import-time behaviors of `config.py`), AGENT-INIT-006 (startup log line), and AGENT-CLI-001 to AGENT-CLI-003 (`main.py`) are verified by running rather than by a test, per the HLD. No `@spec` annotations exist yet in code or tests. `main.py` is excluded from coverage and the CLI specs have no automated tests.

## Key Findings

1. **"Processed" means "never send to Jev again", regardless of outcome** — `process_email` marks an email processed after a successful label write (`email_classifier_agent.py:200`), after a review-label write or no-label result (`:225`), after a label write whose ids all failed to resolve, and in dry run (`:170`). Because jev-decision swallows endpoint failures into "no labels" and gmail-actions swallows write failures, a transient outage in either results in the email being marked processed and never retried. The only path that leaves an email for the next poll is an unexpected exception (`:203`). Accepted under the HLD tenet *classify once over classify eventually*; the matching questions in jev-decision, gmail-actions, and processed-state are resolved the same way.
2. **The ledger is checked after the full message is fetched** — gmail-intake downloads every listed message in `format="full"` before `process_email` consults the ledger (`:155`). Mail that stays unread in the inbox after processing (unlabeled mail, or everything when `REMOVE_FROM_INBOX=false`) is re-downloaded every poll until it is read or expires from the list window.
3. **Config is evaluated at import** — `config.py:107-31` loads and validates the label file when the module is imported, printing and re-raising on failure. Tests need `conftest.py` to point `CLASSIFIER_CONFIG_PATH` at a temp file and set a dummy API key before collection.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
_None._

### Nice to Have
1. Check the ledger before fetching full message bodies, which needs gmail-intake to expose ids before details (finding 2; cascades into gmail-intake).
