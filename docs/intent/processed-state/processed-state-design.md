---
parent: high-level-design
prefix: STATE
---

# Processed State

## Context and Design Philosophy

The processed-state ledger is how the agent knows it has already dealt with a message. Gmail's own read state is not used for this: labeled mail is deliberately left unread so the operator still sees it as new, and an email that received no label stays in the inbox. Without a ledger, every poll would re-send the same unread messages to Jev.

Principles:

- **Never block the agent on its own bookkeeping.** A missing, corrupt, or unwritable state file is logged and treated as empty. The worst outcome is reclassifying messages that are still unread, which costs a Jev call each and nothing else.
- **Bounded growth.** Entries expire after a configurable number of days so the file does not grow forever on a long-running deployment.
- **Forward-compatible loading.** Older file layouts are read and rewritten in the current layout on the next save.

The segment is `state_store.py` and the four state methods of `EmailClassifierAgent`. The agent-runtime segment decides *when* to mark an email processed; this segment owns what that means and how it persists.

## File Layout

```json
{
  "processed_emails": {
    "<gmail message id>": "<ISO 8601 timestamp, UTC, timezone-aware>",
    ...
  }
}
```

Default path is `.email_state.json` in the working directory, overridden by the `STATE_FILE` setting; the container image sets it to `/app/data/.email_state.json` so a volume can hold it across restarts.

Only `processed_emails` is read or written. Any other top-level key is ignored on load and absent after the next save. Earlier versions wrote a `pending_retries` block for a since-removed guardrail retry feature; it is dropped this way.

## Loading

`load_state(path)` returns a dict of id to timestamp:

| File state | Result | Log |
|---|---|---|
| Missing | `{}` | INFO "starting fresh" |
| Unreadable or invalid JSON | `{}` | ERROR with the exception |
| `processed_emails` is a list (legacy) | every id stamped with the load time | INFO "Migrating state" |
| `processed_emails` is a dict | that dict | none |
| `processed_emails` is anything else or absent | `{}` | none |

The agent's `_load_state` calls `load_state` and then applies retention pruning before the first poll.

## Marking and Saving

`_mark_processed(email_id)` records `datetime.now(UTC).isoformat()` under the id and saves immediately. There is one write per processed email, so a crash loses at most the email in flight.

`save_state(path, processed)` creates the parent directory if needed and writes `{"processed_emails": processed}` as indented JSON. Any exception is logged at ERROR and swallowed. The write is a plain open-and-dump; it is not atomic.

`_save_state` is a no-op while dry run is on. Dry-run entries live in memory only, so repeated polls within one dry-run process do not reclassify the same messages, and a fresh process starts clean.

## Retention

`retention_cutoff(days)` is now in UTC minus `days`. `cleanup_old_entries(processed, cutoff, days)` keeps entries whose parsed timestamp is at or after the cutoff and drops the rest. An entry whose timestamp cannot be parsed (`ValueError`) or compared (`TypeError`, as a naive datetime against an aware cutoff would raise) is dropped with a WARNING. When anything was removed, the count is logged at INFO.

`_cleanup_old_state` wraps this with one rule: a retention of zero or less disables pruning entirely and returns the ledger unchanged.

Pruning runs at startup (inside `_load_state`) and at the top of every poll cycle (called from `run_continuous`). The default retention is 30 days.

The practical effect of expiry: a message that is still unread in the inbox after the retention window will be classified again. A newly received message always has a new Gmail id and is unaffected by retention.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Storage | One JSON file | SQLite; Gmail label as the marker; no persistence | Single-user deployment with at most a few thousand entries; a JSON file is inspectable, needs no dependency, and mounts as a volume trivially. |
| Entry shape | Map of id to ISO timestamp | List of ids; map of id to outcome record | Timestamps make retention possible; the list form could not expire entries (docstring, `state_store.py:4-12`). Recording an outcome per entry has no consumer while every outcome is final; see Resolved 1. |
| Legacy handling | Read the list form and stamp each id with the load time; ignore unknown keys; rewrite in current form on save | Refuse old files; one-off migration script | Operators should never have to touch the file by hand; a load-time migration with a fresh stamp is the least surprising choice, at the cost of resetting those entries' age (docstring, `state_store.py:10-12`). |
| Failure behavior on load | Return empty and continue | Stop the agent; back up and continue | A bad state file must never stop the agent; reclassifying still-unread mail is a tolerable cost (docstring, `state_store.py:29-30`). |
| Save cadence | After every processed email | Once per poll; on shutdown | Bounds loss to one email on a crash; write volume is trivial at ten emails per poll. |
| Write atomicity | Plain open and dump | Temp file and rename | Atomicity was never considered. The consequence of a torn write is an empty ledger and reclassification of still-unread mail, not persistent corruption. Whether to switch to temp-and-rename is Deferred 1. |
| Timestamp form | Timezone-aware UTC ISO 8601 | Naive local time; epoch seconds | Unambiguous across hosts and containers; `fromisoformat` round-trips it. |
| Retention trigger | At startup and at the top of every poll | Startup only; a timer | Old entries are removed when the agent starts and periodically during each poll cycle (README "State Retention"). |
| Retention disable | Zero or negative days keeps everything | A separate boolean | Set `STATE_RETENTION_DAYS=0` to keep all entries forever (README). |
| Invalid timestamps | Drop the entry with a warning | Keep it forever; stop | Unreadable timestamps cannot be aged, so the entry is treated as expired (docstring, `state_store.py:73-74`). |
| Dry run | Never write; remember in memory only | Write to a separate dry-run file | Dry run must leave Gmail and disk untouched while still not reclassifying the same poll's messages every cycle (README "Dry run"; comment, `email_classifier_agent.py:151-152`). |

## Open Questions & Future Decisions

### Resolved
1. ✅ Ledger entries record only that an email was handled, not how. Under the HLD tenet *classify once over classify eventually*, every outcome ends with the id in the ledger and none is retried, so a per-entry outcome has no consumer. Recording one would only matter if that tenet were reversed.

### Deferred
1. Should saves be atomic (write to a temp file, then rename) so a crash mid-write cannot reset the ledger?
2. Is one write per email still the right cadence, or should the agent save once per poll?
3. The README's retention example ("if you receive the same email again after 30 days") describes a case that cannot happen; the real effect is on old messages still unread in the inbox. Correct the README.

## References

- `state_store.py`, `email_classifier_agent.py:82-117`
- `tests/test_email_classifier_agent.py::TestStateTracking`
- README.md: "State Persistence", "State Retention"
- Deployment: `Dockerfile` (`STATE_FILE=/app/data/.email_state.json`), `docker-compose.yml` (`./data` volume)
- Policy owner for when an email is marked processed: `docs/intent/agent-runtime/agent-runtime-design.md`
