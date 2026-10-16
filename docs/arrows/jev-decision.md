# Arrow: jev-decision

Turn one email record into a Jev decisions request, call OpenRouter with one retry, and apply the threshold rule that picks the labels.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 29 specs implemented, annotated in code, and cited by tests.

## References

### HLD
- docs/high-level-design.md (System Design: decision stage)

### LLD
- docs/intent/jev-decision/jev-decision-design.md

### EARS
- docs/intent/jev-decision/jev-decision-specs.md (30 specs)

### Tests
- tests/test_jev_classifier.py (all classes)

### Code
- jev_classifier.py (all)

## Architecture

**Purpose:** Be the only place that knows the shape of a Jev decisions request and the rule that turns its answers into labels. Callers hand in an email record and get back a list of configured label names, or an empty list.

**Key Components:**
1. `build_state` — the email as a named-field object (`from`, `subject`, `date`, `body`) with HTML reduced, URLs cut to host, body capped at 5000 characters; the only place those rules live.
2. `build_questions` / `question_key` — one Noul (yes/no probability) per label plus one Choice across all labels and a `None` option.
3. `validate_labels` — fail-fast checks on the label set; also called by `config.py` at startup.
4. `select_labels` — the pure decision rule: every Noul at or above the label threshold, else the Choice if confident and not `None`.
5. `JevClassifier` — rejects an empty key, holds an `httpx2` client with bearer auth, posts with one retry (honoring a numeric `Retry-After`), parses `answers`, and wraps everything in `classify_email`, which never raises.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| REQ   | DECISION-REQ-001 to DECISION-REQ-009 | 9 | 0 | 0 |
| SEL   | DECISION-SEL-001 to DECISION-SEL-005 | 5 | 0 | 0 |
| HTTP  | DECISION-HTTP-001 to DECISION-HTTP-009 | 9 | 0 | 0 |
| CFG   | DECISION-CFG-001 to DECISION-CFG-006 | 6 | 0 | 0 |
| LOG   | DECISION-LOG-001 | 1 | 0 | 0 |

**Summary:** 30 of 30 active specs implemented; 0 deferred. Every spec is cited by `@spec` annotations in code and in at least one test. Retry on HTTP 500 and 504 (DECISION-HTTP-003) is implemented but only 429, 502, and 503 are exercised by tests.

## Key Findings

1. **Every failure collapses to "no labels"** — `classify_email` (`jev_classifier.py:274-285`) catches `JevRequestError` and returns `[]`. The caller cannot tell a transport outage from a confident "nothing fits", and the agent-runtime segment marks the email processed either way. Accepted under the HLD tenet *classify once over classify eventually*.
2. **Retry is single-shot** — `MAX_ATTEMPTS = 2` (`:38`); the one retry waits a numeric `Retry-After` capped at `MAX_RETRY_AFTER_SECONDS` (60) or the fixed delay (`:210-216`). Backoff across repeated failures is the poll loop's job.
3. **Sole owner of URL reduction and the body cap** — `BODY_MAX_CHARS = 5000` (`jev_classifier.py:36`) and `build_state` (`:55-69`) apply the reduction for every caller; the Gmail client hands over extracted text only.
4. **Pure rule is cleanly separable from transport** — `build_state`, `build_questions`, `select_labels`, and `validate_labels` take and return plain dicts and lists. Tests exercise the HTTP layer through `httpx2.MockTransport` and assert the exact request body.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
_None._

### Nice to Have
_None._
