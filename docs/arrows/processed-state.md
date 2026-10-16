# Arrow: processed-state

Persist the ledger of processed email IDs, migrate older file formats, and prune entries past the retention window.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 15 specs implemented, annotated in code, and cited by tests.

## References

### HLD
- docs/high-level-design.md (System Design: processed ledger)

### LLD
- docs/intent/processed-state/processed-state-design.md

### EARS
- docs/intent/processed-state/processed-state-specs.md (16 specs)

### Tests
- tests/test_email_classifier_agent.py (`TestStateTracking`; state assertions in `TestProcessEmail::test_applies_labels_archives_and_saves_state`, `test_exception_does_not_save_state`, and `TestDryRun`)

### Code
- state_store.py (all)
- email_classifier_agent.py:89-129 (`_load_state`, `_cleanup_old_state`, `_save_state`, `_mark_processed`)

## Architecture

**Purpose:** Remember which Gmail message IDs the agent has already handled so an email is classified at most once per retention window, across restarts, without depending on Gmail's read state.

**Key Components:**
1. `state_store.load_state(path)` — reads `{"processed_emails": {id: iso_timestamp}}`; returns `{}` for a missing or unreadable file; migrates a legacy list of IDs by stamping each with the load time.
2. `state_store.save_state(path, processed)` — writes the dict as indented JSON to a temp file and atomically replaces the state file, creating the parent directory; logs and swallows errors.
3. `state_store.retention_cutoff` / `cleanup_old_entries` — drop entries older than now minus the retention days, and entries whose timestamp cannot be parsed or compared.
4. Agent methods — `_load_state` (load then prune), `_cleanup_old_state` (skip when retention is zero or negative), `_mark_processed` (stamp now in UTC and save immediately), `_save_state` (no-op in dry run).

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| FILE  | STATE-FILE-001 to STATE-FILE-009 | 9 | 0 | 0 |
| MARK  | STATE-MARK-001 to STATE-MARK-002 | 2 | 0 | 0 |
| RET   | STATE-RET-001 to STATE-RET-005 | 5 | 0 | 0 |

**Summary:** 16 of 16 active specs implemented; 0 deferred. Every spec is cited by `@spec` annotations in code and in at least one test.

## Key Findings

1. **The ledger records only that an email was handled, not how** — `_mark_processed` (`email_classifier_agent.py:125-127`) stores an ID and a timestamp. A labeled email, one sent to the review label, and one whose classification or label write failed are indistinguishable in the file. This is why the failure-handling questions in jev-decision and gmail-actions cannot be answered by the ledger alone.
2. **Writes are atomic** — `save_state` (`state_store.py:58-66`) writes to `<path>.tmp` and `os.replace`s it over the state file, so a crash mid-write leaves the previous ledger intact.
3. **One write per processed email** — `_mark_processed` saves on every call. With `MAX_EMAILS_PER_POLL` of 10 that is at most 10 writes per poll. Harmless at this scale; it bounds loss to one email on a crash.
4. **A bad state file never stops the agent** — `load_state` (`state_store.py:37-42`) returns `{}` on any exception and logs at ERROR. Stated as design in the docstring.
5. **Timestamp comparison drops anything it cannot compare** — `cleanup_old_entries` (`state_store.py:82-86`) catches `ValueError` and `TypeError`, so a naive timestamp would be pruned as invalid. No version of this project ever wrote naive timestamps (UTC-aware since the store was introduced; the legacy list had none), so this path is defensive.
6. **Retention is applied twice per lifecycle** — once in `_load_state` at startup and once at the top of every poll in `_poll_once` (`email_classifier_agent.py:239`). A retention of zero or less disables both (`:109-110`).
7. **Retention acts on old unread mail, not re-received mail** — Gmail message IDs are unique per message, so a new copy is always new; the effect of expiry is that a message still unread in the inbox after N days is classified again. The README states this.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
_None; the outcome-free ledger (finding 1) is accepted under the HLD tenet *classify once over classify eventually*._

### Nice to Have
_None._
