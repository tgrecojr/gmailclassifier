# Arrow: processed-state

Persist the ledger of processed email IDs, migrate older file formats, and prune entries past the retention window.

## Status

**MAPPED** — sampled 2026-10-14 (git SHA `08bbc6be6f312e7b4699611f03ec69a733093374`). Segment identified and documented from code; specs not yet verified against code by an audit pass.

## References

### HLD
- docs/high-level-design.md (System Design: processed ledger)

### LLD
- docs/intent/processed-state/processed-state-design.md

### EARS
- docs/intent/processed-state/processed-state-specs.md (15 specs)

### Tests
- tests/test_email_classifier_agent.py (`TestStateTracking`; state assertions in `TestProcessEmail::test_applies_labels_archives_and_saves_state`, `test_exception_does_not_save_state`, and `TestDryRun`)

### Code
- state_store.py (all)
- email_classifier_agent.py:82-117 (`_load_state`, `_cleanup_old_state`, `_save_state`, `_mark_processed`)

## Architecture

**Purpose:** Remember which Gmail message IDs the agent has already handled so an email is classified at most once per retention window, across restarts, without depending on Gmail's read state.

**Key Components:**
1. `state_store.load_state(path)` — reads `{"processed_emails": {id: iso_timestamp}}`; returns `{}` for a missing or unreadable file; migrates a legacy list of IDs by stamping each with the load time.
2. `state_store.save_state(path, processed)` — writes the dict as indented JSON, creating the parent directory; logs and swallows errors.
3. `state_store.retention_cutoff` / `cleanup_old_entries` — drop entries older than now minus the retention days, and entries whose timestamp cannot be parsed or compared.
4. Agent methods — `_load_state` (load then prune), `_cleanup_old_state` (skip when retention is zero or negative), `_mark_processed` (stamp now in UTC and save immediately), `_save_state` (no-op in dry run).

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| FILE  | STATE-FILE-001 to STATE-FILE-008 | 8 | 0 | 0 |
| MARK  | STATE-MARK-001 to STATE-MARK-002 | 2 | 0 | 0 |
| RET   | STATE-RET-001 to STATE-RET-005 | 5 | 0 | 0 |

**Summary:** 15 of 15 active specs observed implemented; 0 deferred. No `@spec` annotations exist yet in code or tests.

## Key Findings

1. **The ledger records only that an email was handled, not how** — `_mark_processed` (`email_classifier_agent.py:115-117`) stores an ID and a timestamp. A labeled email, one sent to the review label, and one whose classification or label write failed are indistinguishable in the file. This is why the failure-handling questions in jev-decision and gmail-actions cannot be answered by the ledger alone.
2. **Writes are not atomic** — `save_state` (`state_store.py:58-59`) opens the file for writing and dumps into it. A crash mid-write leaves a truncated file; the next load treats it as unreadable and starts empty, so every unread message still in the inbox is reclassified and relabeled. Benign for labels, which are idempotent, but it costs one Jev call per message.
3. **One write per processed email** — `_mark_processed` saves on every call. With `MAX_EMAILS_PER_POLL` of 10 that is at most 10 writes per poll. Harmless at this scale; it bounds loss to one email on a crash.
4. **A bad state file never stops the agent** — `load_state` (`state_store.py:36-41`) returns `{}` on any exception and logs at ERROR. Stated as design in the docstring.
5. **Timestamp comparison drops anything it cannot compare** — `cleanup_old_entries` (`state_store.py:79-82`) catches `ValueError` and `TypeError`, so a naive timestamp would be pruned as invalid. No version of this project ever wrote naive timestamps (UTC-aware since the store was introduced; the legacy list had none), so this path is defensive.
6. **Retention is applied twice per lifecycle** — once in `_load_state` at startup and once at the top of every poll in `run_continuous` (`email_classifier_agent.py:222`). A retention of zero or less disables both (`:101-102`).
7. **README's retention example describes the wrong case** — it says a re-received email would be reprocessed after N days. Gmail message IDs are unique per message, so a new copy is always new. The real effect is that an old message still unread in the inbox after N days is classified again.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
_None; the outcome-free ledger (finding 1) is accepted under the HLD tenet *classify once over classify eventually*._

### Nice to Have
1. Write the state file atomically (temp file then rename) so a crash cannot reset the ledger (finding 2).
2. Correct the README's retention example (finding 7).
