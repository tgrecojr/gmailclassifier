# Arrow: gmail-intake

Authenticate to Gmail, list unread inbox message ids, fetch messages on request, and extract each one's text.

## Status

**OK** — last audited 2026-10-14 (git SHA `43adeb7ea7982a4e0b108d848355219d2c7f19dc`). All 24 specs implemented and annotated; the two token-script specs are verified by running the script (HLD: verified by running).

## References

### HLD
- docs/high-level-design.md (System Design: intake stage)

### LLD
- docs/intent/gmail-intake/gmail-intake-design.md

### EARS
- docs/intent/gmail-intake/gmail-intake-specs.md (26 specs)

### Tests
- tests/test_gmail_client.py (`TestAuthenticate`, `TestListUnreadIds`, `TestGetUnreadMessages`, `TestGetMessage`, `TestGetMessageBody`)
- tests/test_mail_text.py

### Code
- gmail_client.py:17-222 (`_decode`, `GmailClient.__init__`, `_load_token`, `_save_token`, `_authenticate`, `_run_console_flow`, `list_unread_ids`, `get_unread_messages`, `get_message`, `_walk_parts`, `_get_message_body`)
- mail_text.py (all)
- setup_token.py (operator script that drives the browser OAuth path)

## Architecture

**Purpose:** Be the only place that talks to Gmail on the read side. The agent gets ids first, then flat records (`id`, `subject`, `from`, `date`, `body`, `snippet`) for the ones it asks for, with the body extracted as text (HTML reduced) but not otherwise reduced or capped.

**Key Components:**
1. `GmailClient._authenticate` — loads the JSON token (or a legacy pickled one, rewriting it as JSON), refreshes it, or runs an OAuth flow (browser on port 8080, or console paste-back in headless mode, which requires a TTY), then builds the Gmail v1 service.
2. `GmailClient.list_unread_ids` / `get_message` — list `INBOX` + `UNREAD` ids up to `max_results` (errors propagate); fetch one message in `format="full"` (errors return `None`). `get_unread_messages` composes them for the token script.
3. `GmailClient._get_message_body` — depth-first over nested parts: first `text/plain` with data, else first `text/html` reduced through `strip_html`, else the direct body.
4. `mail_text.strip_html` / `looks_like_html` / `normalize_urls` — pure text helpers; intake uses HTML reduction, jev-decision uses URL reduction.
5. `setup_token.py` — generates a token on a machine with a browser for copying to a headless host.

## Spec Coverage

| Facet | Spec IDs | Implemented | Deferred | Gaps |
|-------|----------|-------------|----------|------|
| AUTH  | INTAKE-AUTH-001 to INTAKE-AUTH-008 | 8 | 0 | 0 |
| FETCH | INTAKE-FETCH-001 to INTAKE-FETCH-007 | 7 | 0 | 0 |
| BODY  | INTAKE-BODY-001 to INTAKE-BODY-005 | 5 | 0 | 0 |
| TEXT  | INTAKE-TEXT-001 to INTAKE-TEXT-006 | 6 | 0 | 0 |

**Summary:** 26 of 26 active specs implemented; 0 deferred. All are cited by `@spec` annotations in code. INTAKE-AUTH-006 and INTAKE-AUTH-007 (`setup_token.py`) are verified by running the script rather than by a test, per the HLD.

## Key Findings

1. **Browser OAuth hardcodes the redirect port** — `gmail_client.py:79` uses `run_local_server(port=8080)`; no requirement depends on the fixed port.
2. **HTML detection needs a structural tag** — `mail_text.py:36-38` matches `html`, `body`, `div`, `p`, `br`, `table`, `tr`, `td`, `span`, `a`, `img`. Inline-only markup such as a lone `<b>` is treated as plain text, by design.

## Work Required

### Must Fix
_None._

### Should Fix
_None._

### Nice to Have
1. Consider `port=0` for the browser OAuth flow (finding 1).
