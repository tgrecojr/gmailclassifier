# Agent Runtime — EARS Specs

Prefix `AGENT`. Facets: `CFG` (settings loading and validation), `INIT` (agent construction), `PROC` (per-email policy), `LOOP` (poll loop), `CLI` (entry point).

Status markers: `[x]` observed working in current code, `[ ]` specified but broken or partial, `[D]` explicit non-want.

## Configuration

- [x] **AGENT-CFG-001**: When the configuration module is imported, the agent shall load variables from the environment file in the working directory before resolving any setting.
- [x] **AGENT-CFG-002**: When the configuration module is imported, the agent shall load the label file from `CLASSIFIER_CONFIG_PATH`, defaulting to `classifier_config.json`.
- [x] **AGENT-CFG-003**: If the label file does not exist, then configuration shall raise a file-not-found error naming the path and pointing at `classifier_config.example.json`.
- [x] **AGENT-CFG-004**: If the label file is not valid JSON, then configuration shall raise a value error saying the JSON is invalid.
- [x] **AGENT-CFG-005**: If the label file lacks a `labels` list of non-empty strings, or lacks a `label_descriptions` object mapping names to strings, then configuration shall raise a value error identifying the missing or malformed field.
- [x] **AGENT-CFG-006**: When the label file's shapes are valid, configuration shall run the classifier's label validation (DECISION-CFG-001 to DECISION-CFG-004) so an unrepresentable label set fails at import.
- [x] **AGENT-CFG-007**: When the label file contains keys other than `labels` and `label_descriptions` (such as a legacy `classification_prompt`), configuration shall ignore them.
- [x] **AGENT-CFG-008**: If loading the label file fails for any of the above reasons, then configuration shall print the error and a one-line hint to standard output and re-raise, so the process does not start.
- [x] **AGENT-CFG-009**: The agent shall use `JEV_MODEL` as the model id, falling back to `typesafe/jev-1.13` when the variable is unset or blank.
- [x] **AGENT-CFG-010**: If `JEV_LABEL_THRESHOLD` or `JEV_FALLBACK_CONFIDENCE` is outside [0, 1], or `JEV_TIMEOUT_SECONDS` is outside [1, 600], then configuration shall raise a value error at import stating the variable name, the allowed range, and the value.
- [x] **AGENT-CFG-011**: The agent shall read `JEV_REVIEW_LABEL` with surrounding whitespace removed, treating an unset or blank value as "no review label".
- [x] **AGENT-CFG-012**: The agent shall read the Gmail credentials path (default `credentials.json`) and token path (default `token.json`) from the environment and shall request only the `https://www.googleapis.com/auth/gmail.modify` scope.
- [x] **AGENT-CFG-013**: The agent shall treat `GMAIL_HEADLESS_MODE`, `REMOVE_FROM_INBOX`, and `DRY_RUN` as true only when the value equals `true` case-insensitively, with defaults of false, true, and false respectively.
- [x] **AGENT-CFG-014**: The agent shall read `POLL_INTERVAL_SECONDS` (default 60), `MAX_EMAILS_PER_POLL` (default 10), `STATE_RETENTION_DAYS` (default 30) as integers, `STATE_FILE` (default `.email_state.json`), and `LOG_LEVEL` (default `INFO`) from the environment.
- [x] **AGENT-CFG-015**: The agent shall read `OPENROUTER_API_KEY` from the environment as the bearer token for the decisions endpoint; if it is unset or blank, configuration shall print a hint and raise a value error at import, so the process does not start.

## Startup

- [x] **AGENT-INIT-001**: When the agent is constructed, it shall construct the Jev classifier first and only then the Gmail client (with the configured credentials path, token path, scopes, and headless flag), so an invalid label set or key fails before any OAuth prompt or token refresh.
- [x] **AGENT-INIT-002**: When the agent is constructed, it shall construct the Jev classifier with the configured API key, labels, label descriptions, model, label threshold, fallback confidence, and timeout.
- [x] **AGENT-INIT-003**: When the agent is constructed with dry run off, it shall ensure each configured label exists in Gmail, in configured order, and keep a map from label name to Gmail label id, omitting any label whose creation returned no id.
- [x] **AGENT-INIT-004**: Where a review label is configured and dry run is off, the agent shall ensure the review label exists in Gmail at construction and keep its id.
- [x] **AGENT-INIT-005**: While dry run is on, the agent shall create no Gmail labels at construction and shall use an empty label-id map.
- [x] **AGENT-INIT-006**: When construction completes, the agent shall log the decisions endpoint, model, both thresholds, the review label or `<none>`, whether dry run is on, and the number of ledger entries loaded.

## Per-Email Policy

- [x] **AGENT-PROC-001**: If a fetched email has no `id`, then the agent shall log an error and return false without classifying it.
- [x] **AGENT-PROC-002**: When a fetched email's id is already in the processed ledger, the agent shall log that it is skipping the email and return true without classifying it.
- [x] **AGENT-PROC-003**: When a fetched email is not in the processed ledger, the agent shall classify it with the Jev classifier before any other action.
- [x] **AGENT-PROC-004**: While dry run is on, the agent shall log the labels it would apply (or that it would apply none), mark the email processed in memory only, and return whether any label was predicted, without any Gmail write.
- [x] **AGENT-PROC-005**: When classification yields no labels and a review label id exists, the agent shall add the review label to the email without removing it from the inbox, log a warning, mark the email processed, and return false.
- [x] **AGENT-PROC-006**: When classification yields no labels and no review label id exists, the agent shall log a warning, mark the email processed, and return false.
- [x] **AGENT-PROC-007**: When classification yields labels, the agent shall map each to its Gmail label id from the startup map, dropping names with no id, and if at least one id remains shall add those labels to the email in one call, removing it from the inbox if and only if `REMOVE_FROM_INBOX` is true.
- [x] **AGENT-PROC-008**: When classification yields labels but none maps to a Gmail label id, the agent shall log a warning and apply nothing.
- [x] **AGENT-PROC-009**: After the label step (AGENT-PROC-007 or AGENT-PROC-008) completes without an exception, the agent shall mark the email processed and return true.
- [x] **AGENT-PROC-010**: If an exception escapes any step of processing one email, then the agent shall log the error with the email id, return false, and leave the email out of the processed ledger so the next poll retries it.

## Poll Loop

- [x] **AGENT-LOOP-001**: On each poll cycle, the agent shall prune the ledger, fetch up to `MAX_EMAILS_PER_POLL` unread inbox messages, process each in order, log how many processing calls returned true out of how many were fetched, and sleep `POLL_INTERVAL_SECONDS`.
- [x] **AGENT-LOOP-002**: When a poll cycle fetches no unread messages, the agent shall log at DEBUG and sleep the poll interval.
- [x] **AGENT-LOOP-003**: If an exception escapes a poll cycle, then the agent shall log it and sleep before the next cycle, with the sleep doubling on each consecutive failed cycle from `POLL_INTERVAL_SECONDS` up to ten times `POLL_INTERVAL_SECONDS`, and resetting to `POLL_INTERVAL_SECONDS` after a cycle completes without an exception.
- [x] **AGENT-LOOP-004**: When the poll loop receives a keyboard interrupt, the agent shall stop polling and log that it has stopped.

## Entry Point

- [x] **AGENT-CLI-001**: When started from the command line, the agent shall accept `--log-level` with choices `DEBUG`, `INFO`, `WARNING`, `ERROR`, defaulting to `LOG_LEVEL`, and configure root logging to standard output with timestamp, logger name, level, and message.
- [x] **AGENT-CLI-002**: When started, the agent shall log a banner with the decisions URL, model, both thresholds, configured label names, poll interval, and a dry-run notice when dry run is on, before constructing the agent.
- [x] **AGENT-CLI-003**: When the process receives a keyboard interrupt, it shall exit with status 0; if any other exception escapes startup or the loop, it shall log it with a traceback and exit with status 1.
