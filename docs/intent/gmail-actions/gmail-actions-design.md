---
parent: high-level-design
prefix: ACTIONS
---

# Gmail Actions

## Context and Design Philosophy

Gmail actions is the write side of the agent's Gmail boundary. Everything the agent changes in a mailbox goes through two methods on `GmailClient`: ensure a label exists, and add labels to a message, optionally archiving it in the same call.

Two principles shape it:

- **Writes are idempotent from the caller's point of view.** Ensuring a label that already exists returns its id; adding a label a message already has is a no-op in Gmail. The agent can repeat any action safely.
- **A failed write never raises.** Every method catches the Gmail API's `HttpError`, logs it, and returns. The poll loop stays alive. The cost is that the caller cannot tell a failed write from a successful one.

The segment shares `GmailClient` and its authenticated service with the gmail-intake segment, which owns authentication.

## Ensuring Labels

`create_label_if_not_exists(label_name) -> label_id | None`:

1. List all labels for the account.
2. If a label's `name` equals `label_name` case-insensitively (`casefold`), return its `id`.
3. Otherwise create a label with `labelListVisibility: labelShow` and `messageListVisibility: show` and return the new `id`.
4. On `HttpError` from either call, log and return `None`.

Matching is case-insensitive because Gmail treats label names as case-insensitively unique: a configured `finance` finds an existing `Finance` instead of attempting a create that Gmail would reject.

The agent-runtime segment calls this once per configured label at startup, plus once for the optional review label, and keeps the returned ids in a name-to-id map for the life of the process.

Label names are flat. Nested Gmail labels (`Parent/Child`) are outside this segment's scope; no parent is created and no name is checked for `/`.

## Modifying Messages

The message method is a single `users.messages.modify` call on `userId="me"`:

| Method | `addLabelIds` | `removeLabelIds` | Caller in the agent |
|---|---|---|---|
| `add_labels_to_message(id, ids, remove_from_inbox=False)` | the given ids | `["INBOX"]` when `remove_from_inbox` is true | `process_email`, `_handle_unlabeled` |

Adding labels and archiving happen in one request, so a message is never observed labeled-but-in-inbox or archived-but-unlabeled.

Nothing on the agent's path removes `UNREAD`. Labeled mail stays unread so the operator still sees it as new; the processed-email ledger, not the read state, is what prevents reclassification.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Label creation | List, match by exact name, create only if absent | Create unconditionally and treat the conflict error as "exists"; cache the label list across calls | Gmail's create call is not idempotent (a duplicate name is rejected), so a lookup first is the simplest safe path. |
| New-label visibility | `labelShow` in the label list, `show` in the message list | Hidden labels; `labelShowIfUnread` | Labels the agent applies are meant to be browsed by the operator, so they should appear in the sidebar and on messages. |
| Archive mechanism | Fold `removeLabelIds: ["INBOX"]` into the label-adding `modify` call when asked | A separate `archive_message` call after labeling | One round trip and one atomic change; the message is never half-updated. |
| Read state | Leave `UNREAD` untouched | Mark read after labeling | The operator should still see classified mail as new; the processed ledger, not read state, prevents reprocessing (README "State Persistence"). |
| Failure surface | Catch `HttpError`, log, return `None` or nothing | Raise to the caller; return a success flag | Keeps the poll loop alive without try/except in the agent. The cost, that the agent marks a message processed after a failed write, is accepted under the HLD tenet *classify once over classify eventually*. |
| Name matching | Case-insensitive (`casefold`) | Exact, case-sensitive | Gmail's own uniqueness rule is case-insensitive; matching the same way means a casing difference in the config never produces a failed create and a dropped label. |
| Message-mutation surface | One method, `add_labels_to_message` | Also `mark_as_read` and `archive_message` as standalone calls | Archiving happens inside the label write and the agent never marks mail read, so standalone methods had no caller; dead surface invites a caller that would contradict the read-state decision above. |

## Open Questions & Future Decisions

### Resolved
1. ✅ Nested labels (`Parent/Child`) are not supported and never were intended. Configured label names are flat; `create_label_if_not_exists` creates no parents. A configured name containing `/` is not rejected today and would fail at creation if its parent did not exist.
2. ✅ `mark_as_read` and `archive_message` were removed along with their tests. Nothing called them and the design never marks mail read.
3. ✅ Label names match case-insensitively, as Gmail itself treats them.
4. ✅ A label deleted in Gmail mid-run makes later writes with its id fail until the agent restarts; accepted, restart is the fix at this scale.
5. ✅ A failed label write is logged and swallowed; the agent-runtime segment marks the email processed regardless, per the HLD tenet *classify once over classify eventually*. Reporting failure to the caller would only matter if that tenet were reversed.

### Deferred
_None._

## References

- `gmail_client.py:200-275`
- `tests/test_gmail_client.py` (label and modify test classes)
- README.md: "Archive After Labeling (Remove from Inbox)", "State Persistence"
- Shared client and authentication: `docs/intent/gmail-intake/gmail-intake-design.md`
- Caller: `docs/intent/agent-runtime/agent-runtime-design.md` (`_initialize_labels`, `process_email`, `_handle_unlabeled`)
- Gmail API: `users.labels.list`, `users.labels.create`, `users.messages.modify`
