# Arrow: gmail-intake

Authenticate to Gmail, fetch unread inbox messages, and reduce each one to the text that carries classification signal.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 24 specs implemented and annotated; the two token-script specs are verified by running the script (HLD: verified by running).

## References

### HLD
- docs/high-level-design.md (System Design: intake stage)

### LLD
- docs/intent/gmail-intake/gmail-intake-design.md

### EARS
- docs/intent/gmail-intake/gmail-intake-specs.md (24 specs)

### Tests
- tests/test_gmail_client.py (`TestAuthenticate`, `TestGetUnreadMessages`, `TestGetMessageDetails`, `TestGetMessageBody`)
- tests/test_mail_text.py

### Code
- gmail_client.py:17-227 (`_decode`, `GmailClient.__init__`, `_load_token`, `_save_token`, `_authenticate`, `_run_console_flow`, `get_unread_messages`, `_get_message_details`, `_get_message_body`)
- mail_text.py (all)
- setup_token.py (operator script that drives the browser OAuth path)

## Architecture

**Purpose:** Be the only place that talks to Gmail on the read side. Everything downstream receives a flat dict (`id`, `subject`, `from`, `date`, `body`, `snippet`) with the body already reduced to visible text, URLs cut to scheme and host, and capped at 5000 characters.

**Key Components:**
1. `GmailClient._authenticate` — loads the JSON token (or a legacy pickled one, rewriting it as JSON), refreshes it, or runs an OAuth flow (browser on port 8080, or console paste-back in headless mode, which requires a TTY), then builds the Gmail v1 service.
2. `GmailClient.get_unread_messages` — lists `INBOX` + `UNREAD` up to `max_results`, fetches each in `format="full"`, drops any whose detail fetch fails.
3. `GmailClient._get_message_body` — prefers a top-level `text/plain` part; falls back to `text/html` reduced through `strip_html`; falls back to the direct body.
4. `mail_text.normalize_urls` / `strip_html` / `looks_like_html` — pure text reduction shared with the jev-decision segment.
5. `setup_token.py` — generates a token on a machine with a browser for copying to a headless host.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| AUTH  | INTAKE-AUTH-001 to INTAKE-AUTH-007 | 7 | 0 | 0 |
| FETCH | INTAKE-FETCH-001 to INTAKE-FETCH-006 | 6 | 0 | 0 |
| BODY  | INTAKE-BODY-001 to INTAKE-BODY-005 | 5 | 0 | 0 |
| TEXT  | INTAKE-TEXT-001 to INTAKE-TEXT-006 | 6 | 0 | 0 |

**Summary:** 24 of 24 active specs implemented; 0 deferred. All are cited by `@spec` annotations in code. INTAKE-AUTH-006 and INTAKE-AUTH-007 (`setup_token.py`) are verified by running the script rather than by a test, per the HLD.

## Key Findings

1. **Body extraction only inspects top-level MIME parts** — `gmail_client.py:213` iterates `payload["parts"]` one level deep. A `multipart/mixed` wrapping a `multipart/alternative` (common with attachments) yields an empty body; the jev-decision segment then falls back to Gmail's `snippet`.
2. **URL reduction runs before the 5000-character cap on purpose** — `gmail_client.py:186-193`. The jev-decision segment repeats both URL reduction and HTML stripping in `build_state`; both are idempotent, so this is redundancy rather than a defect.
3. **A failed list call silently skips the whole poll** — `gmail_client.py:158` logs and returns `[]` on `HttpError`, which the agent cannot distinguish from "no unread mail".
4. **Browser OAuth hardcodes the redirect port** — `gmail_client.py:79` uses `run_local_server(port=8080)`; no requirement depends on the fixed port.
5. **HTML detection needs a structural tag** — `mail_text.py:36-38` matches `html`, `body`, `div`, `p`, `br`, `table`, `tr`, `td`, `span`, `a`, `img`. Inline-only markup such as a lone `<b>` is treated as plain text, by design.

## Work Required

### Must Fix
_None identified during mapping._

### Should Fix
1. Descend into nested multipart payloads so bodies with attachments are not lost (finding 1).
2. Distinguish "Gmail list failed" from "no unread mail" so the agent can log the poll as failed rather than quiet (finding 3).

### Nice to Have
3. Revisit the 5000-character body cap: it was sized for a chat LLM's token budget before the Jev rewrite and is duplicated in jev-decision (LLD Deferred 4).
4. Consider `port=0` for the browser OAuth flow (finding 4).
