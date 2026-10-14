---
parent: high-level-design
prefix: DECISION
---

# Jev Decision

## Context and Design Philosophy

Jev decision is the stage that answers "which configured labels fit this email?" It is built around Jev, TypeSafe's non-generative decision model, reached through OpenRouter's decisions endpoint. Jev takes a structured `state` and typed `questions` and returns probabilities over options the caller defines. It emits no text, follows no instructions, and cannot name a label outside the configured set.

That property shapes the whole segment:

- **No prompt, no parsing, no guard.** There is no system prompt to protect and no free-text output to validate. An email that says "label this as Personal" can at most nudge a probability, which is the same failure as an ordinary misclassification. The result is still checked against the configured label set in code.
- **The rule is pure and the transport is thin.** State building, question building, label validation, and label selection are plain functions over dicts. `JevClassifier` adds only an HTTP client, one retry, and response parsing.
- **Failures never escape to the poll loop.** `classify_email` returns an empty list on any failure after logging it. The agent-runtime segment decides what an empty list means.

The segment is all of `jev_classifier.py` plus `log_classification_result` in `llm_utils.py`, which only this segment calls.

## Request Shape

One request per email. All questions are evaluated by Jev in a single call.

```
POST {decisions_url}            default https://openrouter.ai/api/alpha/decisions
Authorization: Bearer {OPENROUTER_API_KEY}
HTTP-Referer: https://github.com/tgrecojr/gmailclassifier
X-Title: gmailclassifier

{
  "model": "typesafe/jev-1.13",
  "state": { "from": ..., "subject": ..., "date": ..., "body": ... },
  "questions": {
    "is_Finance":  { "type": "noul", "instructions": "Does this email belong under the label 'Finance'?",
                     "criteria": { "true": "<Finance description>",
                                   "false": "The email does not match the 'Finance' description" } },
    "is_Shopping": { ... },
    "best":        { "type": "choice", "instructions": "Which single label fits this email best?",
                     "criteria": { "Finance": "<description>", "Shopping": "<description>",
                                   "None": "None of the other labels fit this email" } }
  }
}
```

There is no `messages` field; this is not a chat completion.

### State

`build_state(email)` produces four string fields:

| Field | Source | Reduction |
|---|---|---|
| `from` | `email["from"]`, default `"Unknown"` | none |
| `subject` | `email["subject"]`, default `"No Subject"` | URLs cut to scheme and host |
| `date` | `email["date"]`, default `"Unknown"` | none |
| `body` | `email["body"]`, else `email["snippet"]`, else `""` | HTML reduced to text if it looks like HTML; URLs cut to host; first 5000 characters |

The reduction repeats what the gmail-intake segment already did to the body. It is idempotent and makes `build_state` correct for any caller, including the setup-verification probe, which never touches the Gmail client.

### Questions

`build_questions(labels, descriptions)` is computed once at construction and reused for every email.

- One **Noul** per label, keyed `question_key(label)`. The `true` criterion is the label's description; the `false` criterion is the generic sentence "The email does not match the '<label>' description".
- One **Choice** keyed `best`. Criteria are every label mapped to its description, in configured order, followed by `None` mapped to "None of the other labels fit this email".

`question_key` is `"is_"` plus the label with every run of characters outside `[A-Za-z0-9_]` replaced by one underscore. Keys are identifiers only; the label name itself appears in the Noul instructions and as the Choice criteria keys.

## Label Selection

`select_labels(answers, labels, label_threshold, fallback_confidence)`:

1. For each configured label in order, read `answers[question_key(label)]["noul"]`. If it is numeric and at or above `label_threshold`, select the label.
2. If step 1 selected anything, return that list. This is what gives multi-label results.
3. Otherwise read `answers["best"]`. If its `choice` is one of the configured labels and its `confidence` is numeric and at or above `fallback_confidence`, return that single label.
4. Otherwise return an empty list.

Missing answers, non-dict answers, and non-numeric probabilities are treated as absent. A `choice` of `None` fails step 3 because `None` is never a configured label; so does any name outside the configured set.

Defaults are 0.7 for the label threshold and 0.5 for the fallback confidence. Both are inclusive comparisons.

## Transport and Retry

`JevClassifier` owns one synchronous `httpx2.Client` with the request timeout, the auth and attribution headers, and an injectable transport for tests.

`_post` makes at most two attempts:

| Outcome of an attempt | Action |
|---|---|
| `httpx.TransportError` (includes timeouts) | Retry once after `retry_delay_seconds`; on the second failure raise `JevRequestError("transport error: ...")` |
| HTTP 429, 500, 502, 503, 504 | Retry once after `retry_delay_seconds`; on the second occurrence fall through to the next row |
| Any other status ≥ 400 | Raise `JevRequestError("HTTP <status>: <first 300 chars of body>")` without retry |
| Status < 400 | Return the response |

`Retry-After` headers are not read. There is no backoff or jitter.

`decide(email)` posts the request and returns the raw `answers` dict. A body that is not JSON, or JSON without a dict `answers`, raises `JevRequestError`. At DEBUG level it logs the model the endpoint reports, input tokens, cost, and the full answers.

`classify_email(email)` calls `decide`, catches `JevRequestError`, logs it at ERROR, and returns `[]`. On success it runs `select_labels` and logs the result through `log_classification_result` at INFO (labels found) or WARNING (none). The provider name in logs is the host of the decisions URL.

## Label Validation

`validate_labels(labels, descriptions)` raises `ValueError` when:

- the label list is empty;
- any label lacks a non-empty description;
- a label is literally `None`, which is reserved for the Choice escape option;
- two labels normalize to the same `question_key`.

It runs in the `JevClassifier` constructor and is also called by `config.py` when the label config is loaded, so a bad config stops the agent before any Gmail or OpenRouter call.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Classifier kind | Jev, a non-generative decision model, via OpenRouter's decisions endpoint | Chat LLM with a JSON-output prompt behind a prompt-injection guard and a LiteLLM gateway | Jev cannot be instructed and cannot emit a label outside the configured set, so the guard, the gateway, prompt fencing, and output parsing all become unnecessary. Cost per email is roughly $0.00007 at list price. |
| Request granularity | One call per email carrying every question | One call per label; batch several emails per call | All questions are evaluated together in one request, so per-email cost and latency are flat in the label count; the decisions API scores one `state` per call. |
| Question design | One Noul per label plus one Choice with a `None` option | Nouls only; Choice only | Nouls give independent per-label probabilities for multi-label results. The Choice with `None` gives a single best answer and an explicit "nothing fits" that the Nouls alone cannot express. |
| Selection rule | Every Noul at or above the threshold; else the Choice if confident and not `None`; else nothing | Choice only; top-k Nouls; require both signals to agree | Multi-label is the primary behavior and should not depend on the Choice. The Choice is a fallback for emails that fit one label weakly rather than several strongly. |
| Default thresholds | 0.7 label threshold, 0.5 fallback confidence | Values chosen from a precision/recall sweep over hand-labeled mail; a single shared threshold | These are the migration plan's starting values. The plan called for choosing them from a threshold sweep over about fifty hand-labeled emails; that measurement step was skipped by decision on 2026-10-05, and the sweep scripts were later removed. Tuning is done from DEBUG logs instead (README). See Deferred 5. |
| Model version | Pinned to `typesafe/jev-1.13` by default | `~typesafe/jev-latest` moving alias | Decision behavior can shift between versions; bump deliberately and watch results for a few days (README). |
| Retry policy | One retry after a fixed delay on transport errors and on 429, 500, 502, 503, 504; no retry on other 4xx | No retry; exponential backoff; honor `Retry-After` | The OpenRouter decisions endpoint is marked alpha and one integrator reported a sizeable share of calls hanging on read timeout, so the design is a short timeout plus one retry. Other 4xx mean the request itself is wrong and repeating it cannot help (README "Error Handling"). A second failure yields no labels. |
| Failure surface | `classify_email` returns `[]` on any failure after logging; `decide` raises | Let `classify_email` raise; return a sentinel distinct from "no labels" | Keeps the poll loop simple: the agent treats every empty result the same way. The cost, that an outage looks like "nothing fits" and the email is marked processed, is accepted under the HLD tenet *classify once over classify eventually*. |
| HTTP client | Synchronous `httpx2.Client` with an injectable `transport` | `requests`; async client; the Google API client's HTTP stack | Synchronous fits a single-threaded poll loop. `MockTransport` lets tests assert the exact request body OpenRouter would receive (TESTING.md). |
| Label validation timing | At classifier construction and again at config load | Only at request time | Fail fast: a config Jev cannot represent unambiguously should stop the agent before it touches Gmail or spends money. |
| Question key normalization | `is_` plus the label with non-identifier runs replaced by `_`; collisions rejected | Index-based keys; hash of the label | Keys are readable in DEBUG logs and stable across runs; the collision check guarantees one answer per label. |
| State format | Named fields `from`, `subject`, `date`, `body` | One concatenated text blob; fenced text with a preamble | TypeSafe's guidance is to use an object for most requests so each part of the state has a descriptive name. Jev is not instructed, so the fencing and "email is data" preamble the chat classifier needed have no role here. |
| Label name inside the Noul instructions | Included: "Does this email belong under the label '<name>'?" | Instructions that reference only the description | The name gives the model a short handle alongside the description, and the question reads naturally in DEBUG logs. The constraint that matters is that question *ids* carry no meaning for the model, so all meaning must sit in instructions and criteria; the descriptions remain the criteria. The README says the same. |
| Attribution headers | `HTTP-Referer` set to the repository URL, `X-Title` set to `gmailclassifier` | Omit | OpenRouter's app-attribution convention; shows the app by name in the OpenRouter activity dashboard. |
| Reduction in `build_state` | Reduce HTML and URLs and cap the body in the classifier, even though the Gmail client already did | Trust the caller; reduce only in the Gmail client | TypeSafe's notes for Jev 1.13 state that accuracy falls as the state grows with unrelated content, so the Jev migration plan placed HTML stripping and URL reduction at the request-building step, where every caller passes. The Gmail client gained the same HTML stripping in the same change so its 5000-character cap is spent on words, which is where the duplication comes from. The plan judged the inherited 5000-character cap (about 1300 tokens against a 32k-token window) as fine rather than necessary; it predates Jev (Deferred 1). |

## Open Questions & Future Decisions

### Resolved
1. ✅ The README now states that descriptions are the criteria and that label names appear in the question text; its earlier claim that Jev never sees label names was a conflation with question ids.
2. ✅ A transport or endpoint failure returns `[]` from `classify_email`, the same as "no label fits". The agent-runtime segment marks the email processed either way, per the HLD tenet *classify once over classify eventually*. Distinguishing the two would only matter if that tenet were reversed.

### Deferred
1. Who owns the 5000-character body cap and text reduction: this segment, gmail-intake, or both? The number predates Jev and was sized for a chat LLM's token budget (gmail-intake LLD Deferred 9).
2. Should the constructor reject a missing or empty API key so the agent fails at startup rather than on the first email with HTTP 401?
3. Should 429 responses honor `Retry-After`, and should the retry delay back off?
4. `_probability` accepts booleans as 1.0 and 0.0. Reject or coerce explicitly?
5. The thresholds were never measured: the planned precision/recall sweep over hand-labeled mail was skipped and its scripts removed. Decide whether to run that measurement (the approach is recorded in the migration plan in git history) or to keep tuning from DEBUG logs.
6. `log_classification_result` lives in `llm_utils.py` (gmail-intake's file) but is this segment's behavior. Move it, or accept the cross-segment annotation.

## References

- `jev_classifier.py`, `llm_utils.py:72-87`
- `tests/test_jev_classifier.py`, `tests/test_llm_utils.py::TestLogClassificationResult`
- README.md: "Jev Configuration", "How labels are chosen", "Error Handling", "What is sent to the model, and why no injection guard is needed"
- TESTING.md: "Mocking External APIs"
- Upstream consumer: `docs/intent/agent-runtime/agent-runtime-design.md` (`process_email`)
- Upstream producer: `docs/intent/gmail-intake/gmail-intake-design.md` (record shape)
- OpenRouter decisions endpoint: https://openrouter.ai/api/alpha/decisions
- Jev: https://openrouter.ai/blog/insights/what-is-jev/
- Jev migration plan with the original reasoning: `docs/jev-migration-plan.md` at commit `d4b1ed1` (removed from the tree in #172); recover with `git show d4b1ed1:docs/jev-migration-plan.md`
