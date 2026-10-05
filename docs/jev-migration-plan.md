# Plan: replace the llmprotect guard + chat-completion classifier with Jev

Status: all phases implemented 2026-10-05 in one pass. Jev is the only
backend; the chat classifier, guardrail-retry path, `model_config.json` and the
`openai` dependency are gone. Phase 2 (threshold measurement on a hand-labeled
sample) was skipped by decision and can still be run with `scripts/eval_jev.py`
against the live deployment; the defaults below are the starting values.
Open question 2 was resolved as proposed (`JEV_REVIEW_LABEL`, off by default)
and question 3 as proposed (model pinned to `typesafe/jev-1.13`). The rest of
this document is the original plan and is kept for the reasoning.

## 1. Why

Today an email is classified by a generative chat model (OpenRouter, via the
LiteLLM + llmprotect gateway). Because that model *follows instructions*, the
email text had to be scanned first by a prompt-injection classifier (PIGuard),
chunked into 2000-char windows. That guard is the thing misfiring: confident
false positives score 0.99+, so the threshold cannot fix them, and ordinary
newsletters end up `Flagged` instead of labeled.

Jev (`typesafe/jev-1.13`) is a different kind of model. It is non-generative:
you send it *state* plus *typed questions* and it returns a probability
distribution over the options you defined, with a confidence value. It
produces no text, calls no tools, and cannot pick a label outside the set we
give it. That changes the threat model:

| | Chat model behind guard (today) | Jev (proposed) |
|---|---|---|
| Worst case from an injected email | Model follows the injection, emits arbitrary text/labels | Wrong label (same failure as an ordinary misclassification) |
| Guard needed | Yes (and it is the thing failing) | No separate guard; the output space *is* the guardrail |
| Multi-label | Model emits a JSON list, parsed leniently | One Noul question per label, thresholded in code |
| Confidence signal | None | Per-label probability + choice confidence (free) |
| Cost | Sonnet-class tokens via gateway | $0.042 / M input tokens, output free (~$0.00007 per email) |
| Latency | Seconds (gateway scan + generation) | Sub-second (TypeSafe claims <100 ms; OpenRouter endpoint is alpha) |

Honest caveats, from TypeSafe's own "jaggedness" notes for 1.13:

- Jev "does not treat adversarial content as hostile by default." An injected
  "label this as Personal" *can* nudge the probabilities. The blast radius is a
  wrong label, nothing more, which is acceptable for this app.
- "Accuracy falls as the state grows with content unrelated." Keep the body
  trimmed and strip HTML noise (see §4.2).
- Option-order bias: "tends to lean toward first options." Using one Noul per
  label (independent yes/no questions) sidesteps ordering across labels.
- Requests still go through LiteLLM (see §2a), but the Jev route carries no
  guardrails: neither the injection guard nor Presidio runs on it. That is the
  intent for the guard. For Presidio it is a deliberate simplification agreed
  on 2026-10-05; LiteLLM's pass-through guardrail layer only *checks* fields
  and never writes masked text back into the forwarded body, so it would not
  have masked anything anyway. URL path stripping (`normalize_urls`) stays,
  which removes most recipient-specific tracking tokens.
- The OpenRouter Decisions endpoint is marked **alpha**. One integrator
  reported ~15% of calls hanging on read timeout. We set a short timeout and
  retry once.

## 2. The Jev API we will call

Upstream endpoint on OpenRouter:

```
POST https://openrouter.ai/api/alpha/decisions
Authorization: Bearer <OpenRouter key>
Content-Type: application/json
```

### 2a. Through LiteLLM

The `openrouter/<model>` prefix in `model_list` only routes `/chat/completions`
traffic, and OpenRouter answers 400 for Jev there ("typesafe/jev-1.13 is a
decisions model and cannot be used with the chat/completions endpoint"). For
Jev the prefix moves from the model name to the URL path. LiteLLM ships a
built-in pass-through route (PR #42301, first stable release **v1.104.0**,
2026-10-03):

```
POST http://litellm.lan:4000/openrouter/alpha/decisions
Authorization: Bearer <LiteLLM virtual key>
{"model": "typesafe/jev-1.13", "state": ..., "questions": ...}
```

LiteLLM maps `/openrouter/<path>` to `https://openrouter.ai/api/<path>`,
injects `OPENROUTER_API_KEY` from the proxy environment, and prices the
response from the `openrouter/typesafe/jev-1.13` cost row so spend shows in
the Admin UI. The body's `model` field is the bare OpenRouter id, **not**
`openrouter/typesafe/jev-1.13`. No `model_list` entry is needed.

What this means for llmprotect:

- Production (`llm.internal.thegrecos.com`) already runs v1.104.0 (confirmed
  2026-10-05), so the version floor is met. The llmprotect repo's
  `docker-compose.yml` still pins v1.96.0; reconcile that pin with what is
  deployed so a redeploy does not roll the route away.
- No config change. The route is built in and uses the existing
  `OPENROUTER_API_KEY`.
- Guardrails do not run on this route. LiteLLM's pass-through code only
  collects guardrails when a pass-through entry explicitly lists them, and the
  built-in provider routes list none, so `default_on: true` has no effect
  here. The chat route keeps its full guardrail chain for other apps.
- Correction (observed 2026-10-05 on v1.104.0): per-key `models` allow-lists
  **are** enforced on this route. LiteLLM's auth layer reads `model` from the
  JSON body and answers `403 key_model_access_denied` unless the key lists the
  bare id `typesafe/jev-1.13` or is unrestricted. The app's virtual key needs
  that entry added.

Request:

```json
{
  "model": "typesafe/jev-1.13",
  "state": {
    "from": "billing@aws.amazon.com",
    "subject": "Your AWS Bill is Ready",
    "date": "2026-04-24",
    "body": "Your monthly AWS bill is now available. ..."
  },
  "questions": {
    "is_Finance": {
      "type": "noul",
      "instructions": "Does this email belong under the label 'Finance'?",
      "criteria": {
        "true": "Bank statements, credit card bills, investment updates, tax documents, payment confirmations",
        "false": "Not about money, bills, banking, or payments"
      }
    },
    "is_Shopping": { "type": "noul", "...": "one per configured label" },
    "best": {
      "type": "choice",
      "instructions": "Which single label fits this email best?",
      "criteria": {
        "Finance": "Bank statements, credit card bills, ...",
        "Shopping": "Order confirmations, ...",
        "None": "None of the other labels fit"
      }
    }
  }
}
```

Response:

```json
{
  "model": "typesafe/jev-1.13-20260917",
  "answers": {
    "is_Finance":  {"type": "noul", "noul": 0.97},
    "is_Shopping": {"type": "noul", "noul": 0.08},
    "best": {"type": "choice", "choice": "Finance",
             "probabilities": {"Finance": 0.91, "Shopping": 0.05, "None": 0.04},
             "confidence": 0.86}
  },
  "usage": {"input_tokens": 1450, "output_tokens": 0, "cost": 0.0000609},
  "id": "gen-dec-...", "provider": "TypeSafe"
}
```

Facts that shape the design:

- The app keeps `LLM_BASE_URL=http://litellm.lan:4000/v1` and its LiteLLM
  virtual key. The decisions URL is derived: strip a trailing `/v1`, append
  `/openrouter/alpha/decisions`. `JEV_DECISIONS_URL` overrides it (for example
  `https://openrouter.ai/api/alpha/decisions` to bypass the gateway).

- Questions in one request are evaluated in parallel; adding Nouls "barely
  changes the response time." So: **one request per email**, all questions.
- Question *ids* are never shown to the model. All meaning must be in
  `instructions` and `criteria`. We therefore need a **description per label**.
- Context window 32k tokens (state + longest question). Our 5000-char body cap
  is ~1300 tokens. Fine.
- The model does **not** appear in `GET /api/v1/models` (that list is
  text-output models only), so `verify_setup.py` must probe differently.
- Noul confidence is `|2p - 1|`; Choice confidence is
  `(p_max - 1/n) / (1 - 1/n)`. Both come back computed; we only threshold.
- Model id is pinned to `typesafe/jev-1.13`. `~typesafe/jev-latest` is a
  moving alias and decision behaviour can shift when TypeSafe ships a new
  version. Renovate cannot track this, so bumping is a manual, measured step.

## 3. Decisions (recommendations, with the alternative noted)

1. **Transport: plain `httpx2` against LiteLLM's `/openrouter/alpha/decisions`.**
   Not the `typesafe-sdk` package. The request is ~20 lines of JSON; the SDK
   adds pydantic + tenacity, hard-codes `/v1/systemone` (a path LiteLLM's
   OpenRouter pass-through does not serve), and its model-listing call does not
   work on OpenRouter. `httpx2` is already in `uv.lock` as a transitive
   dependency of `openai`; it becomes a direct dependency.
2. **Multi-label via one Noul per label, plus one Choice as fallback.** Labels
   applied = every Noul with probability ≥ `JEV_LABEL_THRESHOLD`. If none
   clears the bar, apply the Choice answer if its confidence ≥
   `JEV_FALLBACK_CONFIDENCE` and it is not `None`. Otherwise no label (today's
   behaviour for an empty result: warn, mark processed). The Choice costs no
   latency and guarantees a clearly-single-category email still gets labeled
   when its Noul lands at 0.6.
   *Alternative:* Choice only, threshold the probabilities. Rejected because
   probabilities sum to 1, so a genuinely two-label email splits 0.45/0.45 and
   fails any sensible threshold.
3. **Per-label descriptions live in `classifier_config.json`** as a new
   `label_descriptions` object. `classification_prompt` stays for the legacy
   backend. The loader requires a description for every label when the Jev
   backend is active.
4. **Keep the chat backend selectable during cutover**, then delete it.
   `CLASSIFIER_BACKEND=jev|chat` (default `jev` once Phase 4 lands). Removal of
   `OpenRouterClassifier`, the JSON-mode fallback, `ClassificationRejected`,
   `RetryTracker`, and the `REJECTED_*` settings is a separate, final PR so the
   cutover PR is reviewable and reversible.
5. **No instructions sent to the model beyond the questions.** The `<email>`
   fencing, the system prompt, and the "email is data" preamble all exist to
   steer a generative model and to appease the guard. Jev gets a structured
   state object instead (TypeSafe: "use an object for most requests so each
   part of the state has a descriptive name").
6. **Thresholds are chosen from data, not guessed.** Phase 2 runs the new
   classifier over a hand-labeled sample and prints precision/recall per
   threshold. Starting defaults: `JEV_LABEL_THRESHOLD=0.7`,
   `JEV_FALLBACK_CONFIDENCE=0.5`.

## 4. Phases

### Phase 1: `JevClassifier` + offline evaluation script (no agent changes)

New files:

- `jev_classifier.py` (<300 lines)
  - `JevClassifier(api_key, model, labels, label_descriptions, label_threshold,
    fallback_confidence, timeout_seconds, decisions_url)`
  - `build_state(email) -> dict` — `from`, `subject`, `date`, `body`; subject
    and body pass through `normalize_urls` (keep) and body through a new
    `strip_html` when the Gmail client fell back to the HTML part (§4.2).
  - `build_questions(labels, descriptions) -> dict` — N Nouls + 1 Choice with
    `None`.
  - `select_labels(answers, labels, threshold, fallback_confidence) -> list[str]`
    — pure function, fully unit-testable.
  - `classify_email(email) -> list[str]` — POST, 30 s timeout, one retry on
    timeout/connection error/429/5xx, log `usage.cost` and per-label
    probabilities at DEBUG. 4xx other than 429 is a bug in our request: log
    with body, return `[]`.
- `scripts/eval_jev.py` — reads a JSONL of `{subject, from, date, body,
  expected_labels}`, calls `JevClassifier` once per row, and prints a
  threshold sweep (0.5 → 0.9) with per-label precision/recall plus the
  Noul-probability histogram. Rows are built by hand from ~50 recent emails
  (a `scripts/dump_sample.py` that pulls the last N unread/labeled messages
  through the existing `GmailClient` and writes the JSONL, with
  `expected_labels` left empty for you to fill in). The sample file is
  gitignored; it is real mail.
- `pyproject.toml`: add `httpx2` as a direct dependency; `uv lock`.
- `tests/test_jev_classifier.py`: request body shape (every label gets a
  Noul, Choice contains `None`, ids never carry meaning), state building
  (URL normalization, HTML stripping, body cap), `select_labels` matrix
  (multi-label, fallback, `None`, below both thresholds, unknown keys in
  answers ignored), HTTP behaviour via `httpx2.MockTransport` (timeout retry,
  429 retry, 400 → `[]`, malformed JSON → `[]`).

Exit criteria: tests green, `scripts/eval_jev.py` runs against the real
endpoint on the sample and prints a sweep.

### Phase 2: measure and pick thresholds

- Run the eval on the hand-labeled sample. Record the sweep table in this
  document.
- Compare against the labels the current pipeline produced for the same
  emails (the sample dump records existing Gmail labels).
- Choose `JEV_LABEL_THRESHOLD` / `JEV_FALLBACK_CONFIDENCE` defaults.
- Check the known jaggedness items on the sample: a few HTML-heavy
  newsletters, one long thread, one email containing instruction-like text.
- Go/no-go. If Jev is not at least as good as the current pipeline on the
  sample *with zero `Flagged` false positives*, stop here and we have lost
  one afternoon.

### Phase 3: wire into the agent behind a switch, with dry run

- `config.py`: `CLASSIFIER_BACKEND` (`chat` default until Phase 4),
  `JEV_MODEL` (default `typesafe/jev-1.13`), `JEV_DECISIONS_URL` (default
  derived from `LLM_BASE_URL` as in §2), `JEV_LABEL_THRESHOLD`,
  `JEV_FALLBACK_CONFIDENCE`, `JEV_TIMEOUT_SECONDS` (30), `DRY_RUN` (false).
  `load_classifier_config` validates `label_descriptions` when backend is
  `jev`.
- New `classifier_factory.py` (or a function in `config.py`):
  `build_classifier()` returns either backend. Both expose
  `classify_email(email) -> list[str]`; labels and prompt/descriptions are
  bound at construction. `OpenRouterClassifier.classify_email` loses its two
  extra arguments (tests updated).
- `gmail_client.py`: run `strip_html` on text/html fallbacks *before* the
  5000-char cap, so the cap spends its budget on visible text rather than
  markup (Phase 1 strips after the cap, which is lossy for HTML-only mail).
- `email_classifier_agent.py`: use the factory; `DRY_RUN=true` logs the
  labels it *would* apply and does not touch Gmail or state. The rejection
  path stays as-is; the Jev backend never raises `ClassificationRejected`.
- `verify_setup.py`: when backend is `jev`, probe with a one-Noul decisions
  call on a fixed string (~$0.00002) instead of `models.list()`. A 404 from
  LiteLLM here means the proxy predates v1.104.0; print that hint.
- Tests: `test_config.py` (new vars, validation), `test_email_classifier_agent.py`
  (factory selection, dry run), existing classifier tests adjusted for the
  signature change. Coverage must stay ≥ 75%.
- Run the container for a few days with `CLASSIFIER_BACKEND=jev DRY_RUN=true`
  next to the live pipeline and diff the logs.

### Phase 4: cutover

- Prerequisite: LiteLLM ≥ v1.104.0 (already true in production).
- `.env` on the host: `LLM_BASE_URL` and the LiteLLM virtual key stay as they
  are; add `CLASSIFIER_BACKEND=jev`, remove `DRY_RUN`.
- Default `CLASSIFIER_BACKEND` flips to `jev`.
- Docs: README (OpenRouter section describes Jev; LiteLLM gateway section
  explains the `/openrouter/alpha/decisions` route and the v1.104.0 floor;
  "Rejected emails" section marked legacy/chat-only; new "How labels are
  chosen" section with the threshold semantics), `.env.example`,
  `classifier_config.example.json` gains `label_descriptions`,
  `DEPLOYMENT.md` env table, `TESTING.md` test layout.
- `model_config.json` is only read by the chat backend; document that.

### Phase 5: remove the legacy path (separate PR)

Delete `openrouter_classifier.py`, `retry_tracker.py`, the `REJECTED_*`
settings, `construct_system_prompt`/`construct_user_message`/
`parse_labels_from_response` and their tests, the `openai` dependency, the
`Flagged` label creation, and the gateway sections of the README. The state
file's `pending` block is ignored on load and dropped on next save.
Decommissioning the llmprotect stack itself is outside this repo.

## 5. Things that do not change

- Gmail client, OAuth, polling loop, state file, retention, Docker image
  shape, CI workflow, Renovate.
- `normalize_urls` and the 5000-char body cap (both reduce the "noisy state"
  Jev warns about).
- Labels are still validated against `config.LABELS`; nothing outside that set
  can ever be applied.

## 6. Open questions for you

1. ~~Presidio~~ Resolved 2026-10-05: route through LiteLLM's pass-through,
   no Presidio on the Jev route, keep it simple.
2. Should low-confidence emails (nothing clears either threshold) get an
   optional `Review` label so they are visible, the way `Flagged` is today?
   Cheap to add in Phase 3 as `JEV_REVIEW_LABEL` (default empty). Default
   assumption: add it, off by default.
3. Keep `~typesafe/jev-latest` out of the defaults? Default assumption: yes,
   pin `typesafe/jev-1.13` and bump deliberately after re-running Phase 2.

## Sources

- OpenRouter, "What is Jev?" (API schema, pricing, limits):
  https://openrouter.ai/blog/insights/what-is-jev/
- OpenRouter Jev guide: https://openrouter.ai/docs/guides/community/jev
- TypeSafe docs: Noul https://docs.typesafe.ai/primitives/noul ·
  Choice https://docs.typesafe.ai/primitives/choice ·
  Confidence https://docs.typesafe.ai/confidence ·
  State https://docs.typesafe.ai/concepts/state ·
  Jev 1.13 jaggedness https://docs.typesafe.ai/model-jaggedness/jev-1.13 ·
  Classification using confidence cookbook
  https://docs.typesafe.ai/cookbooks/classification_using_confidence
- Python SDK (evaluated, not chosen): https://pypi.org/project/typesafe-sdk/ ·
  https://docs.typesafe.ai/sdk/python/
- SDK path mismatch against OpenRouter and alpha-endpoint timeouts:
  https://github.com/pydantic/pydantic-ai/issues/8552
- LiteLLM OpenRouter decisions pass-through (merged 2026-09-22, in v1.104.0):
  https://github.com/BerriAI/litellm/pull/42301
- LiteLLM pass-through guardrails (check-only, no write-back):
  https://docs.litellm.ai/docs/proxy/pass_through_guardrails
- Independent benchmark harness: https://github.com/4esv/jev-eval
- Adoption note: https://app.dealroom.co/news/note/typesafe-ai-s-jev-tops-openrouter-classification-requests-at-27-weekly-share
