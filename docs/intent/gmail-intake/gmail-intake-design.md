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

The segment is `GmailClient`'s authentication and fetch methods, the shared text-reduction helpers in `llm_utils.py`, and the `setup_token.py` operator script that exercises the browser OAuth path on a machine that has one.

## Authentication

`GmailClient` authenticates in its constructor and holds one Gmail v1 service for its lifetime.

Credential resolution, in order:

1. If a file exists at `token_path`, unpickle it as `google.oauth2.credentials.Credentials`.
2. If the credentials are valid, use them.
3. If they are expired and carry a refresh token, refresh them in place.
4. Otherwise run an installed-app OAuth flow from `credentials_path` with the supplied scopes:
   - **Browser mode** (`headless=False`): `run_local_server(port=8080)` opens the system browser and catches the redirect.
   - **Headless mode** (`headless=True`): print the authorization URL, read the full redirect URL from standard input, and exchange it with `fetch_token(authorization_response=...)`.
5. Whenever step 3 or 4 ran, pickle the resulting credentials back to `token_path`.

The token file is written with `pickle` even though its default name is `token.json`. The file is not JSON and cannot be inspected or edited by hand.

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

Three pure functions in `llm_utils.py`, shared with the jev-decision segment:

- **`normalize_urls(text)`** replaces every `http://` or `https://` URL with its scheme and host (port included). The match stops at whitespace and at `)`, `>`, `]`, so bracketed links keep their closing delimiter. The function is idempotent.
- **`looks_like_html(text)`** is true when the text contains a structural tag: `html`, `body`, `div`, `p`, `br`, `table`, `tr`, `td`, `span`, `a`, or `img`. Inline-only markup such as a lone `<b>` is treated as plain text.
- **`strip_html(text)`** removes comments and whole `script`, `style`, `head`, and `title` blocks; turns `<br>` and the closing tags of `p`, `div`, `tr`, `li`, `h1`–`h6`, and `table` into newlines; removes every remaining tag; unescapes entities; collapses runs of horizontal whitespace to one space and runs of blank lines to one newline. A tag truncated by the body cap (no closing `>`) is left as literal text rather than swallowing what follows.

`llm_utils.py` also holds `log_classification_result`, which is called only by the jev-decision segment and is specified there.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Message selection | `INBOX` and `UNREAD` labels, newest first per Gmail's default ordering | Query string (`is:unread in:inbox`); history API with `startHistoryId` | Label filter is the simplest API call and matches the README's "unread emails in the inbox". History API would avoid re-listing but requires persisted cursors. |
| Fetch format | `format="full"` per message | `metadata` plus a separate body fetch; `raw` and local MIME parsing | One call per message yields headers and decoded parts together; `raw` would require a MIME parser. |
| Body preference | `text/plain` over `text/html` | Always use HTML then strip; concatenate both | Plain text is what the sender wrote for text clients; HTML is a fallback reduced to text so the 5000-char cap is spent on words rather than markup (docstring, `gmail_client.py:175-181`). |
| URL reduction | Scheme and host only, applied before the body cap | Strip query strings only; drop URLs entirely; apply after the cap | Tracking paths add nothing to classification and often encode the recipient; running before the cap keeps link-heavy marketing mail readable (docstrings, `llm_utils.py:20-29`, `gmail_client.py:157-158`). |
| HTML reduction | Regex-based, no dependency | `html.parser`-based extractor; BeautifulSoup; `html2text` | Good enough for classification and avoids a dependency (docstring, `llm_utils.py:53-61`). |
| Body cap | 5000 characters | No cap; cap by tokens; cap at a different length | Inherited from the project's first classifier, a chat LLM reached through a prompt-injection guard and a LiteLLM gateway, where body length drove token cost and context-window risk. Jev is a non-generative decision model with per-email cost near a thousandth of a cent, so the original reason no longer applies. The Jev migration plan judged the cap acceptable (about 1300 tokens against a 32k-token window) rather than necessary; whether a cap still helps accuracy is open (see Deferred 9). The same constant is repeated independently in the jev-decision segment. |
| Token persistence | `pickle` of the `Credentials` object at `token_path` | `Credentials.to_json()` / `from_authorized_user_file()`; keyring | The operator's recollection is that pickle was chosen so the token file is not human-readable. Pickle provides obscurity only, not confidentiality: any Python process can load it and the refresh token inside is fully usable. Google's quickstart samples of the period also used pickle. The path was later renamed to `.json` without changing the format (`.gitignore` still lists `token.pickle`). |
| OAuth flow selection | `headless` flag chooses local server (port 8080) or console paste-back | Always console; detect TTY automatically; device-code flow; `port=0` (any free port) | Containers and servers have no browser, so the operator picks the flow via configuration (README "Headless Mode"). The fixed port 8080 dates from the initial deployment, when the browser flow was used once to mint the first token; no Google-side or deployment requirement depends on it, and a Desktop OAuth client accepts any localhost port. |
| Per-message failure handling | Log and drop the message, keep the batch | Fail the whole poll; retry the message | One unreadable message should not block the rest; the message stays unread and is retried on the next poll because it never reaches the processed ledger. |
| List failure handling | Log and return an empty batch | Raise to the caller | Keeps the polling loop alive; the cost is that a failed poll looks like an empty inbox. |

## Open Questions & Future Decisions

### Resolved
1. ✅ The token is pickled for obscurity only; the operator accepts that this is not confidentiality. Switching to JSON remains Deferred 3.
2. ✅ The 5000-character body cap and port 8080 are inherited conveniences with no dependent requirement (see the Decisions table).

### Deferred
1. Should body extraction descend into nested multipart payloads? Today messages with attachments commonly yield an empty body and classify on the snippet alone.
2. Should a failed list call be surfaced to the agent (exception or sentinel) so a failed poll is logged as failed rather than as "no unread emails"?
3. Should the token be stored as JSON so it matches its filename and can be inspected? Pickle's only benefit is that the file is not readable at a glance; if that matters, file permissions or a secrets store are the real controls. The change is one-way for existing pickled tokens unless both formats are read.
4. Headless mode calls `input()`; in a container with no TTY this raises `EOFError`. Should the client detect the missing TTY and fail with a pointer to `setup_token.py`?
5. DEPLOYMENT.md describes adding `http://localhost:1` as the console-flow redirect URI. The code sets no `redirect_uri`, so the library default applies. Verify what the console flow actually uses and align the doc.
6. URL and HTML reduction run here and again in the jev-decision segment's `build_state`. Both are idempotent. Decide whether one segment should own reduction outright.
7. `llm_utils.py` is a holdover name; nothing in it is LLM-specific. Rename when convenient.
8. `log_classification_result` lives in this segment's file but is behavior of the jev-decision segment. Either move it or accept the cross-segment annotation.
9. Is the 5000-character body cap still wanted under Jev? It was sized for an LLM's token budget. Options: keep as a privacy and payload bound, raise it, or remove it and let the jev-decision segment decide. Whatever is chosen, one segment should own the number.

## References

- `gmail_client.py`, `llm_utils.py`, `setup_token.py`
- `tests/test_gmail_client.py`, `tests/test_llm_utils.py`
- README.md: "Headless Mode", "What is sent to the model, and why no injection guard is needed"
- DEPLOYMENT.md: "Headless OAuth Setup"
- Downstream consumer: `docs/intent/jev-decision/jev-decision-design.md` (`build_state`)
- Google Gmail API: `users.messages.list`, `users.messages.get`
