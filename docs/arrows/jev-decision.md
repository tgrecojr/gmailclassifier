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
- docs/intent/jev-decision/jev-decision-specs.md (29 specs)

### Tests
- tests/test_jev_classifier.py (all classes)
- tests/test_llm_utils.py (`TestLogClassificationResult`)

### Code
- jev_classifier.py (all)
- llm_utils.py:76-91 (`log_classification_result`, called only from this segment)

## Architecture

**Purpose:** Be the only place that knows the shape of a Jev decisions request and the rule that turns its answers into labels. Callers hand in an email record and get back a list of configured label names, or an empty list.

**Key Components:**
1. `build_state` — the email as a named-field object (`from`, `subject`, `date`, `body`) with HTML reduced, URLs cut to host, body capped at 5000 characters.
2. `build_questions` / `question_key` — one Noul (yes/no probability) per label plus one Choice across all labels and a `None` option.
3. `validate_labels` — fail-fast checks on the label set; also called by `config.py` at startup.
4. `select_labels` — the pure decision rule: every Noul at or above the label threshold, else the Choice if confident and not `None`.
5. `JevClassifier` — holds an `httpx2` client with bearer auth, posts with one retry, parses `answers`, and wraps everything in `classify_email`, which never raises.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| REQ   | DECISION-REQ-001 to DECISION-REQ-009 | 9 | 0 | 0 |
| SEL   | DECISION-SEL-001 to DECISION-SEL-005 | 5 | 0 | 0 |
| HTTP  | DECISION-HTTP-001 to DECISION-HTTP-009 | 9 | 0 | 0 |
| CFG   | DECISION-CFG-001 to DECISION-CFG-005 | 5 | 0 | 0 |
| LOG   | DECISION-LOG-001 | 1 | 0 | 0 |

**Summary:** 29 of 29 active specs implemented; 0 deferred. Every spec is cited by `@spec` annotations in code and in at least one test. Retry on HTTP 500 and 504 (DECISION-HTTP-003) is implemented but only 429, 502, and 503 are exercised by tests.

## Key Findings

1. **Every failure collapses to "no labels"** — `classify_email` (`jev_classifier.py:244-255`) catches `JevRequestError` and returns `[]`. The caller cannot tell a transport outage from a confident "nothing fits", and the agent-runtime segment marks the email processed either way. Accepted under the HLD tenet *classify once over classify eventually*.
2. **Retry policy is fixed and minimal** — `MAX_ATTEMPTS = 2`, one sleep of `retry_delay_seconds` (default 1.0), `RETRYABLE_STATUSES = {429, 500, 502, 503, 504}` (`:42-43`, `:190-212`). `Retry-After` headers are ignored; there is no backoff or jitter.
3. **Missing API key is not detected here** — the constructor builds `Authorization: Bearer {api_key}` (`:179`) without checking for `None` or empty. A missing key surfaces as HTTP 401 on the first email.
4. **Body cap and text reduction are duplicated with gmail-intake** — `BODY_MAX_CHARS = 5000` (`:41`) and the reduction in `build_state` (`:59-73`) repeat what the Gmail client already did. Both are idempotent. The duplication makes the classifier correct for any caller (the setup-verification probe bypasses the Gmail client), at the cost of two owners for one number.
5. **Booleans count as probabilities** — `_probability` (`:99-100`) accepts anything `isinstance(..., (int, float))`, which includes `bool`. A `noul: true` would read as 1.0. Not observed from the live endpoint; noted as an edge.
6. **Pure rule is cleanly separable from transport** — `build_state`, `build_questions`, `select_labels`, and `validate_labels` take and return plain dicts and lists. Tests exercise the HTTP layer through `httpx2.MockTransport` and assert the exact request body.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
_None._

### Nice to Have
1. Validate `api_key` at construction so a missing key fails at startup rather than on the first email (finding 3).
2. Honor `Retry-After` on 429 (finding 2).
3. Settle one owner for the 5000-character cap with gmail-intake (finding 4; gmail-intake LLD Deferred 9).
4. Reject or coerce boolean `noul` values explicitly (finding 5).
