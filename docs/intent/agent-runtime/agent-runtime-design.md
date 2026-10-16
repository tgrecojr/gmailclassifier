---
parent: high-level-design
prefix: AGENT
---

# Agent Runtime

## Context and Design Philosophy

Agent runtime is the policy layer. The other segments are mechanisms: gmail-intake fetches, jev-decision decides, gmail-actions writes, processed-state remembers. This segment chooses the order they run in, the settings they run with, and what happens on each outcome of each email.

Principles:

- **Fail at startup, not at the first email.** Everything that can be validated from configuration alone (the label file, threshold ranges, timeout range) is validated when `config.py` is imported, before Gmail or OpenRouter is touched.
- **Never stop polling.** Any exception inside a poll cycle is logged, the agent sleeps one interval, and tries again. Only an interrupt ends the loop.
- **Classify each message at most once per retention window.** The processed ledger, not Gmail's read state, decides whether a message is sent to Jev. Marking an email processed is this segment's decision; what that means on disk is processed-state's.
- **Dry run touches nothing.** With `DRY_RUN=true` the agent classifies and logs but creates no labels, modifies no messages, and writes no state file.

The segment is `config.py`, `main.py`, and the constructor, label setup, per-email policy, and poll loop of `EmailClassifierAgent`.

## Configuration

`config.py` loads the environment file via `python-dotenv` at import, then resolves every setting into a module constant. Settings fall into two sources: the label set lives in a JSON file because it is structured and not secret; everything else lives in the environment because it is scalar, secret, or deployment-specific.

### Label file

`load_classifier_config(path)` is called at import with `CLASSIFIER_CONFIG_PATH` (default `classifier_config.json`):

| Condition | Result |
|---|---|
| File missing | `FileNotFoundError` naming the path and pointing at `classifier_config.example.json` |
| Invalid JSON | `ValueError("Invalid JSON ...")` |
| No `labels` key, or not a list of non-empty strings | `ValueError` |
| No `label_descriptions` key, or not a dict of strings | `ValueError` explaining that Jev scores descriptions, so every label needs one |
| Shapes valid | jev-decision's `validate_labels` runs (non-empty, every label described, `None` reserved, no key collisions) |
| Extra keys such as the legacy `classification_prompt` | Ignored |

On any of these errors the module prints the error and a one-line hint, then re-raises, so the process exits before constructing anything.

### Environment settings

| Setting | Default | Parsing |
|---|---|---|
| `OPENROUTER_API_KEY` | none | stripped string; unset or blank fails at import with a printed hint |
| `JEV_MODEL` | `typesafe/jev-1.13` | blank falls back to default |
| `JEV_LABEL_THRESHOLD` | 0.7 | float, must be in [0, 1] |
| `JEV_FALLBACK_CONFIDENCE` | 0.5 | float, must be in [0, 1] |
| `JEV_TIMEOUT_SECONDS` | 30 | float, must be in [1, 600] |
| `JEV_REVIEW_LABEL` | empty (off) | stripped string |
| `GMAIL_CREDENTIALS_PATH` | `credentials.json` | string |
| `GMAIL_TOKEN_PATH` | `token.json` | string |
| `GMAIL_SCOPES` | `gmail.modify` only | fixed, not configurable |
| `GMAIL_HEADLESS_MODE` | false | boolean: `true`/`1`/`yes`/`on` or `false`/`0`/`no`/`off`, case-insensitive; anything else fails at import |
| `REMOVE_FROM_INBOX` | true | same boolean rule |
| `DRY_RUN` | false | same boolean rule |
| `POLL_INTERVAL_SECONDS` | 60 | integer, must be in [1, 86400] |
| `MAX_EMAILS_PER_POLL` | 10 | integer, must be in [1, 500] (Gmail's list maximum) |
| `STATE_FILE` | `.email_state.json` | string |
| `STATE_RETENTION_DAYS` | 30 | integer, must be in [0, 3650]; zero disables pruning |
| `LOG_LEVEL` | `INFO` | string; CLI flag overrides |

An out-of-range or non-numeric value raises a `ValueError` naming the variable and the allowed range at import; an unrecognized boolean spelling does the same, listing the accepted spellings.

## Startup

`EmailClassifierAgent.__init__`, in order:

1. Read `DRY_RUN`.
2. Construct `JevClassifier` with the API key, labels, descriptions, model, both thresholds, and timeout. Label and key validation run inside; nothing is sent. Building it first means bad configuration fails before any Gmail interaction.
3. Construct `GmailClient` with the credential and token paths, scopes, and headless flag. Authentication happens here, including any OAuth prompt or token refresh.
4. Ensure Gmail labels: in dry run, none are created and the name-to-id map is empty. Otherwise each configured label is ensured in order and its id kept; a label whose creation failed is left out of the map.
5. Where `JEV_REVIEW_LABEL` is set and dry run is off, ensure that label too and keep its id.
6. Load the ledger and prune it (processed-state).
7. Log a summary: endpoint, model, thresholds, review label, dry-run flag, and ledger size.

## Per-Email Policy

`process_email(email) -> bool` is called once per fetched message:

```
no id                      → log error, return False
id in ledger               → log skip, return True
classify → predicted labels
dry run                    → log "would apply", mark processed (memory only), return True
no labels                  → unlabeled path (mark processed), return True
labels → ids via the startup map (names with no id are dropped)
  some ids                 → add labels, archive iff REMOVE_FROM_INBOX
  no ids                   → warn, apply nothing
mark processed, return True
any exception              → log, return False, NOT marked processed
```

The unlabeled path (`_handle_unlabeled`): if a review label id exists, add it to the message without removing it from the inbox and warn; otherwise just warn. Either way mark the email processed.

Two consequences follow from this shape:

- **An outage looks like "nothing fits".** jev-decision returns an empty list on any endpoint failure and gmail-actions returns nothing on a failed write. Both land on a "mark processed" line. An email caught in a transient failure is therefore never retried within its retention window. The README documents the Jev half of this ("a second failure yields no labels and the email is marked processed").
- **Only bugs get retried.** The exception path is the one route that leaves an email unmarked for the next poll. By design every expected failure is caught below this layer, so in practice it is reached only by programming errors.

The boolean return means *handled*: `True` whenever the email ends up in the ledger (labeled, sent to review, left unlabeled, already processed, or dry run), `False` only when it could not be handled and will be seen again (no id, or an unexpected exception). The poll summary reports handled and failed counts from it.

## Poll Loop

`run_continuous()` repeats until interrupted:

1. Prune the in-memory ledger (processed-state).
2. List up to `MAX_EMAILS_PER_POLL` unread inbox message ids (gmail-intake) and drop the ones already in the ledger, logging how many were skipped.
3. If nothing is left, log at DEBUG. Otherwise fetch each remaining message in full (a fetch that returns nothing is left for the next poll), call `process_email` on each, and log "Handled N of M emails (K failed)".
4. Sleep `POLL_INTERVAL_SECONDS`.

Any exception escaping a cycle is logged at ERROR and followed by a sleep before the next cycle. The sleep backs off exponentially across consecutive failed cycles: the poll interval, doubled per further failure, capped at ten times the interval (`MAX_BACKOFF_MULTIPLIER`), and reset to the plain interval after a cycle completes. One cycle (prune, fetch, process, log) is `_poll_once`; `run_continuous` owns the sleep and failure count.

On entry, `run_continuous` installs a SIGTERM handler that raises `KeyboardInterrupt`, so `docker stop` and Ctrl-C end the loop the same way. The interrupt is caught by a handler around the whole loop, so it ends the loop cleanly whether it arrives during a cycle or during either sleep, and the agent logs that it stopped.

The ledger is consulted between listing and fetching, so a message that stays unread in the inbox after processing costs one id in a list response per poll and is never downloaded again. `process_email` checks the ledger a second time as a guard.

## Entry Point

`main.py`:

- Parses `--log-level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`), defaulting to `LOG_LEVEL`.
- Configures root logging to stdout as `time - logger - level - message`.
- Logs a banner: decisions URL, model, both thresholds, label names, poll interval, and a dry-run notice when on.
- Constructs the agent and runs the loop. `KeyboardInterrupt` (also raised for SIGTERM by the loop's handler) exits 0; any other exception is logged with traceback and exits 1.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Outcome of "no labels" or a swallowed failure | Mark processed; leave in inbox; optionally apply the review label | Leave unmarked and retry next poll; retry a bounded number of times with backoff | An earlier design retried rejected emails on a bounded backoff schedule and tracked attempts in the state file; it was removed with the injection guard because Jev has no rejection path. Today's rule is the simplest that guarantees no email is sent to Jev twice. The cost, that transient failures permanently skip mail, is accepted under the HLD tenet *classify once over classify eventually* and documented (README "Error Handling"). |
| Review label handling | Added without archiving, so the email stays visible | Archive with the review label; no review label | Unlabeled mail should stay where a human will see it rather than be silently marked processed (config comment, `config.py:93-94`; README). |
| Archive on label | Default `REMOVE_FROM_INBOX=true`; one `modify` call does both | Never archive; archive in a second call | The point of labeling is to clear the inbox; the operator can keep mail in the inbox by setting the flag off (README "Archive After Labeling"). |
| Dry run | Classify and log; no Gmail writes; no state writes; remember in memory | Dry run that still writes state; no dry run | Lets the operator try new labels, descriptions, or thresholds against real mail with zero side effects, without re-classifying the same messages every cycle (README "Dry run"; comment, `email_classifier_agent.py:151-152`). |
| Retry surface | Only an unexpected exception leaves an email unprocessed | Also leave unprocessed on endpoint or write failure | Bugs should not poison the ledger with entries for mail that was never handled; expected failures are handled by the lower segments' own rules. |
| Config evaluation | Module constants computed at import, fail-fast | Lazy config object; a settings class validated in `main` | Constants are the simplest thing to read everywhere; import-time failure guarantees nothing runs on bad config. Tests pay for it with a conftest hook. |
| Label set location | JSON file; everything else in the environment | Everything in the environment; everything in one YAML | Labels and descriptions are structured text that an operator edits and may want to version; secrets and scalars belong in the environment (README "Customizing Labels"). |
| Float setting ranges | Thresholds in [0, 1], timeout in [1, 600], checked at import | Accept any float; clamp silently | A threshold outside [0, 1] can never fire or always fires; failing at startup with the range in the message is clearer than odd behavior later (`tests/test_config.py::test_out_of_range_values_fail_fast`). |
| Gmail scope | `gmail.modify` only, fixed | `gmail.readonly` plus `gmail.labels`; full `mail.google.com`; configurable | `modify` is the narrowest scope that can both read messages and change their labels; making it configurable invites broader grants by mistake. |
| Label creation timing | All configured labels ensured at startup, ids cached for the process | Create on first use; look up on every write | Labels are created at startup if missing (README "Workflow"); a cached map makes the per-email path one `modify` call with no lookups. |
| Error backoff in the loop | Exponential backoff on consecutive failed cycles: the sleep doubles from the poll interval up to ten times the interval, and resets after a successful cycle | Sleep the normal interval every time (today's code); immediate retry | A failing dependency (Gmail or OpenRouter down) should be hit less often the longer it stays down, not every interval. Ten times the interval caps the wait at ten minutes with the default 60-second poll. |
| Logging destination | stdout, configurable level, CLI flag over environment | File logging; structured JSON | Logs are written to the console so containers and systemd capture them natively (README "Logging"). |
| Concurrency | One synchronous loop, one instance | Threads per message; multiple replicas | Multiple instances would race on the same unread mail and the ledger; raise `MAX_EMAILS_PER_POLL` instead (DEPLOYMENT "Scaling Considerations"). |
| Boolean parsing | `true`/`1`/`yes`/`on` and `false`/`0`/`no`/`off`, case-insensitive; anything else fails at import | Only the literal `true`; accept anything non-empty as true | The common spellings all work, and a typo such as `DRY_RUN=maybe` stops the agent with a message instead of silently running live. |
| Integer settings | Parsed with the same ranged, named error as the floats; ranges 1 to 86400 s, 1 to 500 per poll, 0 to 3650 days | Bare `int()` | A non-numeric or absurd value should fail at import with the variable name, not with a bare traceback or a loop that never sleeps. 500 is Gmail's list maximum; 0 days keeps the documented "never prune" meaning. |
| Shutdown signals | SIGTERM is translated to `KeyboardInterrupt`; one handler around the loop | Ignore SIGTERM (process dies wherever it is); a stop flag polled between sleeps | `docker stop` sends SIGTERM; translating it reuses the Ctrl-C path, and wrapping the whole loop means an interrupt during the failure-path sleep also ends cleanly. The state file is written atomically, so even an untranslated kill cannot corrupt it. |

## Open Questions & Future Decisions

### Resolved
1. ✅ **Mark-processed policy on failure.** An email whose Jev call or label write failed is marked processed, left in the inbox (under the review label when configured), and not retried within the retention window. Settled by the HLD tenet *classify once over classify eventually*: no email is ever sent to Jev twice, at the accepted cost that a transient outage skips mail. Reversing this would require jev-decision to distinguish failure from "no labels", gmail-actions to report write failures, and possibly processed-state to record an outcome per entry.
2. ✅ A blank `OPENROUTER_API_KEY` fails at import with a printed hint, and the classifier is constructed before the Gmail client, so no configuration error ever reaches an OAuth prompt.
3. ✅ `process_email` returns "handled"; the poll summary reports handled and failed counts.
4. ✅ SIGTERM ends the loop like Ctrl-C, and an interrupt during any sleep ends it cleanly with the "stopped" log.
5. ✅ Ids are listed first and filtered against the ledger before any full fetch; already-processed unread mail is no longer re-downloaded each poll.
6. ✅ Integer settings are ranged and named in their errors; boolean settings accept the common spellings and reject anything else at import.

### Deferred
_None._

## References

- `email_classifier_agent.py:13-80, 119-256`, `config.py`, `main.py`
- `tests/test_email_classifier_agent.py`, `tests/test_config.py`, `tests/conftest.py`
- README.md: "Jev Configuration", "How labels are chosen", "Usage", "Configuration", "Error Handling", "Logging"
- DEPLOYMENT.md: "Scaling Considerations"
- Mechanisms this segment orchestrates: `docs/intent/gmail-intake/`, `docs/intent/jev-decision/`, `docs/intent/gmail-actions/`, `docs/intent/processed-state/`
- Removed bounded-retry design, for the history of Resolved 1: commit `35bff18` (feat: retry emails rejected with 400 on a bounded backoff schedule, #153), removed in `d4b1ed1` (#171)
