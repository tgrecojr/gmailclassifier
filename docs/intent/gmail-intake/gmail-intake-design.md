---
parent: high-level-design
prefix: INTAKE
---

# Gmail Intake

## Context and Design Philosophy

Gmail intake is the read side of the agent's Gmail boundary. It authenticates once per process, pulls unread inbox messages on demand, and hands each one downstream as a flat record whose body has already been reduced to the text that carries classification signal.

Two principles shape it:

- **Reduce before anything leaves the process.** Tracking-link paths and HTML markup are noise to a classifier and often identify the recipient. They are stripped here, before the body is capped, so the cap is spent on words rather than tokens or tags.
- **A bad message never stops the poll.** Any single message that cannot be fetched is dropped from the batch with a logged error. The caller always gets a list.

The segment is `GmailClient`'s authentication and fetch methods, the shared text-reduction helpers in `mail_text.py`, and the `setup_token.py` operator script that exercises the browser OAuth path on a machine that has one.

## Authentication

`GmailClient` authenticates in its constructor and holds one Gmail v1 service for its lifetime.

Credential resolution, in order:

1. If a file exists at `token_path`, load it. The agent writes the token as JSON (`Credentials.to_json`), read back with `Credentials.from_authorized_user_file`. A file that is not JSON is read as the pickled `Credentials` object earlier versions wrote; it is rewritten as JSON in step 5.
2. If the credentials are valid, use them.
3. If they are expired and carry a refresh token, refresh them in place.
4. Otherwise run an installed-app OAuth flow from `credentials_path` with the supplied scopes:
   - **Browser mode** (`headless=False`): `run_local_server(port=8080)` opens the system browser and catches the redirect.
   - **Headless mode** (`headless=True`): requires an interactive terminal. If standard input is not a TTY the client raises immediately with a message naming `setup_token.py`. Otherwise it prints the authorization URL, reads the full redirect URL from standard input, and exchanges it with `fetch_token(authorization_response=...)`.
5. Whenever step 3 or 4 ran, or the token was read from the legacy pickle form, write the credentials to `token_path` as JSON.

`setup_token.py` is the recommended way to produce the token for a headless deployment: it checks that `credentials_path` exists, offers to back up any existing token to `<token_path>.backup`, constructs a `GmailClient` in browser mode, and confirms the result by fetching one unread message.

## Fetching Unread Messages

`get_unread_messages(max_results)`:

1. Lists messages with `labelIds=["INBOX", "UNREAD"]` and `maxResults=max_results`.
2. For each id, calls `messages.get(format="full")` and builds a record.
3. Skips any message whose detail fetch raised `HttpError`.
4. Returns the list, or an empty list if the list call itself raised `HttpError`.

Record shape delivered to the caller:

| Field | Source | Default when absent |
|---|---|---|
| `id` | message id | always present |
| `subject` | `Subject` header (case-insensitive) | `"No Subject"` |
| `from` | `From` header | `"Unknown"` |
| `date` | `Date` header | `"Unknown"` |
| `body` | see Body Extraction, then URL-reduced, then cut to 5000 chars | `""` |
| `snippet` | Gmail's `snippet` field | `""` |

An empty list is returned both when the inbox has no unread mail and when the list call failed. The two cases are distinguished only by log level (info versus error).

## Body Extraction

`_get_message_body(payload)` is applied to the top-level payload only:

- **Payload has `parts`:** take the first `text/plain` part that has `body.data`. If none does, take the first `text/html` part with data and reduce it with `strip_html`.
- **Payload has no `parts`:** decode `payload.body.data` directly; if `payload.mimeType` is `text/html`, reduce it.
- **Neither:** return `""`.

Part data is URL-safe base64 and is decoded as UTF-8.

Only one level of `parts` is examined. A `multipart/mixed` message that wraps a `multipart/alternative` (the common shape when attachments are present) has no top-level text part and yields an empty body; the downstream jev-decision segment then falls back to `snippet`.

## Text Reduction

Three pure functions in `mail_text.py`, shared with the jev-decision segment:

- **`normalize_urls(text)`** replaces every `http://` or `https://` URL with its scheme and host (port included). The match stops at whitespace and at `)`, `>`, `]`, so bracketed links keep their closing delimiter. The function is idempotent.
- **`looks_like_html(text)`** is true when the text contains a structural tag: `html`, `body`, `div`, `p`, `br`, `table`, `tr`, `td`, `span`, `a`, or `img`. Inline-only markup such as a lone `<b>` is treated as plain text.
- **`strip_html(text)`** removes comments and whole `script`, `style`, `head`, and `title` blocks; turns `<br>` and the closing tags of `p`, `div`, `tr`, `li`, `h1`–`h6`, and `table` into newlines; removes every remaining tag; unescapes entities; collapses runs of horizontal whitespace to one space and runs of blank lines to one newline. A tag truncated by the body cap (no closing `>`) is left as literal text rather than swallowing what follows.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Message selection | `INBOX` and `UNREAD` labels, newest first per Gmail's default ordering | Query string (`is:unread in:inbox`); history API with `startHistoryId` | Label filter is the simplest API call and matches the README's "unread emails in the inbox". History API would avoid re-listing but requires persisted cursors. |
| Fetch format | `format="full"` per message | `metadata` plus a separate body fetch; `raw` and local MIME parsing | One call per message yields headers and decoded parts together; `raw` would require a MIME parser. |
| Body preference | `text/plain` over `text/html` | Always use HTML then strip; concatenate both | Plain text is what the sender wrote for text clients; HTML is a fallback reduced to text so the 5000-char cap is spent on words rather than markup (docstring, `gmail_client.py:175-181`). |
| URL reduction | Scheme and host only, applied before the body cap | Strip query strings only; drop URLs entirely; apply after the cap | Tracking paths add nothing to classification and often encode the recipient; running before the cap keeps link-heavy marketing mail readable (docstrings, `mail_text.py:20-29`, `gmail_client.py:157-158`). |
| HTML reduction | Regex-based, no dependency | `html.parser`-based extractor; BeautifulSoup; `html2text` | Good enough for classification and avoids a dependency (docstring, `mail_text.py:53-61`). |
| Body cap | 5000 characters | No cap; cap by tokens; cap at a different length | Inherited from the project's first classifier, a chat LLM reached through a prompt-injection guard and a LiteLLM gateway, where body length drove token cost and context-window risk. Jev is a non-generative decision model with per-email cost near a thousandth of a cent, so the original reason no longer applies. The Jev migration plan judged the cap acceptable (about 1300 tokens against a 32k-token window) rather than necessary; whether a cap still helps accuracy is open (see Deferred 4). The same constant is repeated independently in the jev-decision segment. |
| Token persistence | JSON via `Credentials.to_json()` / `from_authorized_user_file()`; a legacy pickled token is read once and rewritten | Keep pickle; keyring | The file matches its `.json` name and can be inspected. Pickle offered obscurity only, not confidentiality; file permissions are the real control. The one-time pickle read keeps existing deployments working without a manual step. |
| OAuth flow selection | `headless` flag chooses local server (port 8080) or console paste-back; console mode refuses to start without a TTY | Always console; detect TTY automatically; device-code flow; `port=0` (any free port) | Containers and servers have no browser, so the operator picks the flow via configuration (README "Headless Mode"). A container started without a terminal would otherwise die on `input()` with a bare `EOFError`; failing early with a pointer to `setup_token.py` is the useful behavior. The fixed port 8080 dates from the initial deployment; no Google-side or deployment requirement depends on it. |
| Per-message failure handling | Log and drop the message, keep the batch | Fail the whole poll; retry the message | One unreadable message should not block the rest; the message stays unread and is retried on the next poll because it never reaches the processed ledger. |
| List failure handling | Log and return an empty batch | Raise to the caller | Keeps the polling loop alive; the cost is that a failed poll looks like an empty inbox. |

## Open Questions & Future Decisions

### Resolved
1. ✅ The token is stored as JSON. A pickled token written by an earlier version is read once and rewritten; pickle's only benefit was obscurity, which is not confidentiality.
2. ✅ The 5000-character body cap and port 8080 are inherited conveniences with no dependent requirement (see the Decisions table).
3. ✅ Headless mode without a TTY fails immediately with a message naming `setup_token.py` instead of dying on `input()`.
4. ✅ The documented console-flow redirect URI (`http://localhost:1`) was unverified against the code and has been removed from DEPLOYMENT.md; the supported path is minting the token with `setup_token.py` and copying it.
5. ✅ `llm_utils.py` is now `mail_text.py`; `log_classification_result` moved to `jev_classifier.py`, the only caller.

### Deferred
1. Should body extraction descend into nested multipart payloads? Today messages with attachments commonly yield an empty body and classify on the snippet alone.
2. Should a failed list call be surfaced to the agent (exception or sentinel) so a failed poll is logged as failed rather than as "no unread emails"?
3. URL and HTML reduction run here and again in the jev-decision segment's `build_state`. Both are idempotent. Decide whether one segment should own reduction outright.
4. Is the 5000-character body cap still wanted under Jev? It was sized for an LLM's token budget. Options: keep as a privacy and payload bound, raise it, or remove it and let the jev-decision segment decide. Whatever is chosen, one segment should own the number.

## References

- `gmail_client.py`, `mail_text.py`, `setup_token.py`
- `tests/test_gmail_client.py`, `tests/test_mail_text.py`
- README.md: "Headless Mode", "What is sent to the model, and why no injection guard is needed"
- DEPLOYMENT.md: "Headless OAuth Setup"
- Downstream consumer: `docs/intent/jev-decision/jev-decision-design.md` (`build_state`)
- Google Gmail API: `users.messages.list`, `users.messages.get`
