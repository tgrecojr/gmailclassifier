# Arrow: agent-runtime

Load settings, wire the Gmail client and Jev classifier, poll on an interval, and decide per email what to do: label and archive, send to review, dry-run, or skip.

## Status

**MAPPED** — sampled 2026-10-14 (git SHA `08bbc6be6f312e7b4699611f03ec69a733093374`). Segment identified and documented from code; specs not yet verified against code by an audit pass.

## References

### HLD
- docs/high-level-design.md (System Design: orchestration and policy)

### LLD
- docs/intent/agent-runtime/agent-runtime-design.md

### EARS
- docs/intent/agent-runtime/agent-runtime-specs.md (37 specs)

### Tests
- tests/test_email_classifier_agent.py (`TestEmailClassifierAgentInit`, `TestProcessEmail`, `TestDryRun`, `TestRunContinuous`)
- tests/test_config.py
- tests/conftest.py (throwaway label config so `config` can import)

### Code
- email_classifier_agent.py:13-80, 119-256 (`__init__`, `_initialize_labels`, `process_email`, `_handle_unlabeled`, `run_continuous`)
- config.py (all)
- main.py (all)

## Architecture

**Purpose:** Own the policy. Every other segment is a mechanism (fetch, decide, write, remember); this one decides the order, the defaults, and what happens on each outcome.

**Key Components:**
1. `config.py` — reads the environment file and `classifier_config.json` at import, validates shapes and ranges, and exposes module-level constants. A bad config stops the process before anything else runs.
2. `EmailClassifierAgent.__init__` — constructs the Gmail client (which authenticates), the Jev classifier, ensures Gmail labels exist, and loads the ledger.
3. `process_email` — the per-email policy: skip if in ledger; classify; dry-run short-circuit; unlabeled path; label and archive; mark processed.
4. `run_continuous` / `_poll_once` — the poll loop: prune ledger, fetch, process, sleep; survives any exception by sleeping with exponential backoff and retrying.
5. `main.py` — CLI flag for log level, stdout logging, startup banner, exit codes.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| CFG   | AGENT-CFG-001 to AGENT-CFG-014 | 14 | 0 | 0 |
| INIT  | AGENT-INIT-001 to AGENT-INIT-006 | 6 | 0 | 0 |
| PROC  | AGENT-PROC-001 to AGENT-PROC-010 | 10 | 0 | 0 |
| LOOP  | AGENT-LOOP-001 to AGENT-LOOP-004 | 4 | 0 | 0 |
| CLI   | AGENT-CLI-001 to AGENT-CLI-003 | 3 | 0 | 0 |

**Summary:** 37 of 37 active specs implemented; 0 deferred. The LOOP specs are annotated in code and tests; CFG, INIT, PROC, and CLI are not yet. No `@spec` annotations exist yet in code or tests. `main.py` is excluded from coverage and the CLI specs have no automated tests.

## Key Findings

1. **"Processed" means "never send to Jev again", regardless of outcome** — `process_email` marks an email processed after a successful label write (`email_classifier_agent.py:183`), after a review-label write or no-label result (`:207`), after a label write whose ids all failed to resolve (`:178-183`), and in dry run (`:153`). Because jev-decision swallows endpoint failures into "no labels" and gmail-actions swallows write failures, a transient outage in either results in the email being marked processed and never retried. The only path that leaves an email for the next poll is an unexpected exception (`:186-188`). Accepted under the HLD tenet *classify once over classify eventually*; the matching questions in jev-decision, gmail-actions, and processed-state are resolved the same way.
2. **The return value and the poll summary disagree with the ledger** — `process_email` returns `False` for an email it handled via the unlabeled path (`:158`) but `True` for one that was already processed (`:140`) or whose predicted labels had no ids (`:184`). The loop's "Processed N out of M" line (`:238-240`) therefore undercounts handled mail.
3. **The ledger is checked after the full message is fetched** — gmail-intake downloads every listed message in `format="full"` before `process_email` consults the ledger (`:138`). Mail that stays unread in the inbox after processing (unlabeled mail, or everything when `REMOVE_FROM_INBOX=false`) is re-downloaded every poll until it is read or expires from the list window.
4. **No SIGTERM handling** — only `KeyboardInterrupt` (SIGINT) is caught (`:246-248`, `main.py:71-73`). `docker stop` sends SIGTERM, which Python does not translate, so the process dies wherever it is, possibly mid-`save_state`.
5. **Startup order is Gmail first, Jev second** — `__init__` authenticates to Gmail (`:20-25`) before constructing the classifier (`:27-35`). A missing or bad OpenRouter key is not detected at startup at all; it surfaces as HTTP 401 on the first email.
6. **Config is evaluated at import** — `config.py:71-78` loads and validates the label file when the module is imported, printing and re-raising on failure. Tests need `conftest.py` to point `CLASSIFIER_CONFIG_PATH` at a temp file before collection.
7. **Boolean settings accept only the literal `true`** — `config.py:101-102, 112` compare `.lower() == "true"`. `yes`, `1`, and `on` are silently false.
8. **A leftover environment variable** — `main.py:32` sets `ANONYMIZED_TELEMETRY=false`. Nothing in the project reads it; it belonged to a removed dependency.
9. **Integer settings have no guard** — `POLL_INTERVAL_SECONDS`, `MAX_EMAILS_PER_POLL`, `STATE_RETENTION_DAYS` go straight through `int()` (`config.py:105-108`); a non-numeric value fails at import with a bare `ValueError`, unlike the `JEV_*` floats which get a ranged message.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
1. Handle SIGTERM so container stops are graceful (finding 4).

### Nice to Have
2. Make `process_email`'s return value mean "handled" consistently, or report counts by outcome (finding 2).
3. Check the ledger before fetching full message bodies, which needs gmail-intake to expose ids before details (finding 3; cascades into gmail-intake).
4. Validate `OPENROUTER_API_KEY` presence at startup (finding 5).
5. Remove the `ANONYMIZED_TELEMETRY` leftover (finding 8).
6. Range-check or at least message-wrap the integer settings (finding 9).
