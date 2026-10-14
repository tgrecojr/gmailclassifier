# Arrow: gmail-actions

Create Gmail labels and modify messages: add label IDs, optionally archive.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 7 specs implemented, annotated in code, and cited by tests.

## References

### HLD
- docs/high-level-design.md (System Design: actions stage)

### LLD
- docs/intent/gmail-actions/gmail-actions-design.md

### EARS
- docs/intent/gmail-actions/gmail-actions-specs.md (7 specs)

### Tests
- tests/test_gmail_client.py (`TestCreateLabelIfNotExists`, `TestAddLabelsToMessage`)

### Code
- gmail_client.py:229-303 (`create_label_if_not_exists`, `add_labels_to_message`)

## Architecture

**Purpose:** Be the only place that writes to Gmail. Callers pass label names to ensure and label IDs to apply; this segment turns them into `users.labels.create` and `users.messages.modify` calls and never raises.

**Key Components:**
1. `create_label_if_not_exists(name)` — lists the account's labels, returns the id of an exact-name match, otherwise creates the label with show/show visibility and returns the new id. Returns `None` on any Gmail API error.
2. `add_labels_to_message(msg_id, label_ids, remove_from_inbox)` — one `modify` call adding the ids and, when asked, removing `INBOX` in the same request.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| LABEL | ACTIONS-LABEL-001 to ACTIONS-LABEL-003 | 3 | 0 | 0 |
| MSG   | ACTIONS-MSG-001 to ACTIONS-MSG-003, ACTIONS-MSG-006 | 4 | 0 | 0 |

**Summary:** 7 of 7 active specs implemented; 0 deferred. Every spec is cited by a `@spec` annotation in code and in at least one test. No `@spec` annotations exist yet in code or tests.

## Key Findings

1. **Write failures are invisible to the caller** — `add_labels_to_message` (`gmail_client.py:280-281`) logs the `HttpError` and returns `None` either way. The agent-runtime segment marks the email processed after calling it, so a failed label write leaves the message unlabeled, in the inbox, and never retried.
2. **Label lookup is exact and case-sensitive** — `gmail_client.py:223-224` compares `label["name"] == label_name`. Gmail treats label names as case-insensitively unique, so a config label `finance` alongside an existing Gmail label `Finance` would miss the match, attempt a create, receive a conflict error, and return `None`. Not verified against the live API; inferred from Gmail's documented behavior.
3. **One list call per configured label at startup** — `create_label_if_not_exists` fetches the whole label list on every call (`:220`). With N labels that is N list calls at startup. Harmless at home-lab label counts.
4. **Archive is folded into the label write** — `remove_from_inbox=True` adds `removeLabelIds: ["INBOX"]` to the same `modify` request (`:267-269`), so labeling and archiving are one atomic round trip.
5. **Labeled mail stays unread** — nothing in the agent's path removes `UNREAD`. The README relies on this: "each email is only classified once, even if it remains unread in your inbox."

## Work Required

### Must Fix
_None._

### Should Fix
_None; the swallowed-write behavior (finding 1) is accepted under the HLD tenet *classify once over classify eventually*._

### Nice to Have
1. Match label names case-insensitively, or document that config labels must match Gmail's casing exactly (finding 2).
2. Fetch the label list once and reuse it across the startup loop (finding 3).
