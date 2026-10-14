# Jev Decision — EARS Specs

Prefix `DECISION`. Facets: `REQ` (state and question building, request shape), `SEL` (label selection rule), `HTTP` (transport, retry, response parsing), `CFG` (label validation), `LOG` (result logging).

Status markers: `[x]` observed working in current code, `[ ]` specified but broken or partial, `[D]` explicit non-want.

## Request Building

- [x] **DECISION-REQ-001**: When building the Jev state for an email record, the classifier shall produce exactly four string fields: `from`, `subject`, `date`, and `body`.
- [x] **DECISION-REQ-002**: When building the Jev state, the classifier shall take the body from the record's `body` field, else its `snippet` field, else an empty string.
- [x] **DECISION-REQ-003**: When building the Jev state and the body looks like HTML (contains a structural tag), the classifier shall reduce it to visible text before further processing.
- [x] **DECISION-REQ-004**: When building the Jev state, the classifier shall reduce URLs in the subject and body to scheme and host and then cut the body to its first 5000 characters.
- [x] **DECISION-REQ-005**: When building the Jev state and the record lacks `from`, `subject`, or `date`, the classifier shall substitute `Unknown`, `No Subject`, and `Unknown` respectively.
- [x] **DECISION-REQ-006**: For each configured label, the classifier shall build one Noul question keyed `is_<normalized label>` whose instructions name the label, whose `true` criterion is the label's description, and whose `false` criterion is the sentence "The email does not match the '<label>' description".
- [x] **DECISION-REQ-007**: The classifier shall build one Choice question keyed `best` whose criteria map every configured label, in configured order, to its description, followed by `None` mapped to "None of the other labels fit this email".
- [x] **DECISION-REQ-008**: When normalizing a label into a question key, the classifier shall prefix `is_` and replace every run of characters outside `A-Z`, `a-z`, `0-9`, and `_` with a single underscore.
- [x] **DECISION-REQ-009**: When sending a decision request, the classifier shall POST a JSON body containing exactly `model`, `state`, and `questions` (no `messages` field) with an `Authorization: Bearer <API key>` header, an `HTTP-Referer` header set to the repository URL, and an `X-Title` header set to `gmailclassifier`.

## Label Selection

- [x] **DECISION-SEL-001**: When selecting labels from Jev answers, the classifier shall select every configured label whose Noul probability is numeric and at or above the label threshold, preserving configured order.
- [x] **DECISION-SEL-002**: When no Noul reaches the label threshold, the classifier shall select the Choice answer's label if that label is one of the configured labels and the Choice confidence is numeric and at or above the fallback confidence.
- [x] **DECISION-SEL-003**: When no Noul reaches the label threshold and the Choice answer is `None`, is below the fallback confidence, or names a label outside the configured set, the classifier shall select no labels.
- [x] **DECISION-SEL-004**: When a Jev answer is missing, is not an object, or carries a non-numeric probability or confidence, the classifier shall treat that answer as absent rather than failing.
- [x] **DECISION-SEL-005**: The classifier shall apply the label threshold and fallback confidence it was constructed with (defaults 0.7 and 0.5) to every selection.

## Transport and Response

- [x] **DECISION-HTTP-001**: The classifier shall apply its configured timeout (default 30 seconds) to every decision request.
- [x] **DECISION-HTTP-002**: If a decision request fails with a transport error (including a timeout), then the classifier shall wait the configured retry delay and retry once; if the retry also fails, it shall raise a request error from `decide`.
- [x] **DECISION-HTTP-003**: If a decision request returns HTTP 429, 500, 502, 503, or 504, then the classifier shall wait the configured retry delay and retry once before treating a repeated status as a failure.
- [x] **DECISION-HTTP-004**: If a decision request returns any other HTTP status of 400 or above, then the classifier shall raise a request error carrying the status and the first 300 characters of the response body, without retrying.
- [x] **DECISION-HTTP-005**: If a decision response body is not valid JSON, then the classifier shall raise a request error from `decide`.
- [x] **DECISION-HTTP-006**: If a decision response lacks an `answers` object, then the classifier shall raise a request error from `decide`.
- [x] **DECISION-HTTP-007**: When a decision response is valid, `decide` shall return the raw `answers` object and log the reported model, input tokens, cost, and answers at DEBUG level.
- [x] **DECISION-HTTP-008**: If `decide` raises a request error, then `classify_email` shall log the error at ERROR level and return an empty label list.
- [x] **DECISION-HTTP-009**: The classifier shall default to model `typesafe/jev-1.13` and to the decisions URL `https://openrouter.ai/api/alpha/decisions` when neither is supplied.

## Label Validation

- [x] **DECISION-CFG-001**: If the configured label list is empty, then label validation shall raise a value error.
- [x] **DECISION-CFG-002**: If any configured label lacks a non-empty description, then label validation shall raise a value error naming the labels missing descriptions.
- [x] **DECISION-CFG-003**: If a configured label is literally `None`, then label validation shall raise a value error (the name is reserved for the Choice escape option).
- [x] **DECISION-CFG-004**: If two configured labels normalize to the same question key, then label validation shall raise a value error.
- [x] **DECISION-CFG-005**: When a classifier is constructed, it shall run label validation before building questions or an HTTP client, so an invalid label set fails at construction.

## Result Logging

- [x] **DECISION-LOG-001**: When `classify_email` completes a selection, the classifier shall log the provider host, the first 50 characters of the subject (`No Subject` when the record has none), and the selected labels at INFO level, or a "no labels predicted" message at WARNING level when none were selected.
