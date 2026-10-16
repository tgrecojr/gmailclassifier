---
parent: high-level-design
prefix: INTAKE
---

# Gmail Intake

## Context and Design Philosophy

Gmail intake is the read side of the agent's Gmail boundary. It authenticates once per process, lists unread inbox message ids on demand, fetches the messages the caller asks for, and hands each one downstream as a flat record whose body is the message's text: plain text when the sender provided it, otherwise HTML reduced to its visible text.

Three principles shape it:

- **Extract, do not reduce.** Intake turns MIME into text and nothing more. Cutting URLs to their host and capping the body are the classifier's concerns (jev-decision, `build_state`), so there is one owner for those rules.
- **Ids before bodies.** Listing and fetching are separate calls so the agent can consult its ledger between them and never download a message it has already handled.
- **A bad message never stops the poll; a bad poll is a failed poll.** A single message that cannot be fetched is skipped with a logged error and seen again next cycle. A list call that fails raises, so the agent counts the cycle as failed and backs off instead of mistaking it for an empty inbox.

The segment is `GmailClient`'s authentication, listing, fetch, and body-extraction methods, the shared HTML-and-URL helpers in `mail_text.py`, and the `setup_token.py` operator script that exercises the browser OAuth path on a machine that has one.

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

## Listing and Fetching

Two calls, used separately by the agent and together by `setup_token.py`:

- **`list_unread_ids(max_results)`** lists messages with `labelIds=["INBOX", "UNREAD"]` and `maxResults=max_results` and returns their ids, newest first. A Gmail `HttpError` propagates.
- **`get_message(msg_id)`** calls `messages.get(format="full")` and builds a record, or returns `None` after logging if the fetch raised `HttpError`.
- **`get_unread_messages(max_results)`** composes the two, omitting messages whose fetch returned `None`. The token setup script uses it to confirm the connection.

Record shape delivered to the caller:

| Field | Source | Default when absent |
|---|---|---|
| `id` | message id | always present |
| `subject` | `Subject` header (case-insensitive) | `"No Subject"` |
| `from` | `From` header | `"Unknown"` |
| `date` | `Date` header | `"Unknown"` |
| `body` | see Body Extraction; untruncated, URLs untouched | `""` |
| `snippet` | Gmail's `snippet` field | `""` |

## Body Extraction

`_get_message_body(payload)`:

- **Payload has `parts`:** walk them depth-first, descending into nested multiparts (`multipart/mixed` wrapping `multipart/alternative` is the common shape when attachments are present). The first `text/plain` part with data wins at any depth. If none exists, the first `text/html` part with data, reduced with `strip_html`.
- **Payload has no `parts`:** decode `payload.body.data` directly; if `payload.mimeType` is `text/html`, reduce it.
- **Neither:** return `""`.

Part data is URL-safe base64 and is decoded as UTF-8. HTML is reduced here because markup is MIME detail, not message content; URL reduction and the length cap are not applied here.

## Text Reduction

Three pure functions in `mail_text.py`. Intake uses `strip_html` (and `looks_like_html` indirectly through the classifier); the jev-decision segment applies `normalize_urls` and the body cap when it builds the request.

- **`normalize_urls(text)`** replaces every `http://` or `https://` URL with its scheme and host (port included). The match stops at whitespace and at `)`, `>`, `]`, so bracketed links keep their closing delimiter. The function is idempotent.
- **`looks_like_html(text)`** is true when the text contains a structural tag: `html`, `body`, `div`, `p`, `br`, `table`, `tr`, `td`, `span`, `a`, or `img`. Inline-only markup such as a lone `<b>` is treated as plain text.
- **`strip_html(text)`** removes comments and whole `script`, `style`, `head`, and `title` blocks; turns `<br>` and the closing tags of `p`, `div`, `tr`, `li`, `h1`–`h6`, and `table` into newlines; removes every remaining tag; unescapes entities; collapses runs of horizontal whitespace to one space and runs of blank lines to one newline. A tag truncated by the body cap (no closing `>`) is left as literal text rather than swallowing what follows.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Message selection | `INBOX` and `UNREAD` labels, listed as ids, newest first per Gmail's default ordering | Query string (`is:unread in:inbox`); history API with `startHistoryId` | Label filter is the simplest API call and matches the README's "unread emails in the inbox". Listing ids separately from fetching lets the agent skip mail already in its ledger. History API would avoid re-listing but requires persisted cursors. |
| Fetch format | `format="full"` per message | `metadata` plus a separate body fetch; `raw` and local MIME parsing | One call per message yields headers and decoded parts together; `raw` would require a MIME parser. |
| Body preference | `text/plain` at any depth over `text/html` at any depth | Top-level parts only; always use HTML then strip; concatenate both | Plain text is what the sender wrote for text clients. Attachments wrap the text parts in a nested `multipart/alternative`, so a top-level-only search returned an empty body for exactly the mail most likely to matter. HTML is a fallback reduced to text because markup is MIME detail. |
| URL reduction and body cap | Not applied here; owned by jev-decision's `build_state` | Reduce and cap in the Gmail client as well | One owner for one rule. The classifier applies them to every caller, including the setup-verification probe, and TypeSafe's accuracy guidance is the reason they exist, which is the classifier's concern. |
| HTML reduction | Regex-based, no dependency | `html.parser`-based extractor; BeautifulSoup; `html2text` | Good enough for classification and avoids a dependency (docstring, `mail_text.py:53-61`). |
| Token persistence | JSON via `Credentials.to_json()` / `from_authorized_user_file()`; a legacy pickled token is read once and rewritten | Keep pickle; keyring | The file matches its `.json` name and can be inspected. Pickle offered obscurity only, not confidentiality; file permissions are the real control. The one-time pickle read keeps existing deployments working without a manual step. |
| OAuth flow selection | `headless` flag chooses local server (port 8080) or console paste-back; console mode refuses to start without a TTY | Always console; detect TTY automatically; device-code flow; `port=0` (any free port) | Containers and servers have no browser, so the operator picks the flow via configuration (README "Headless Mode"). A container started without a terminal would otherwise die on `input()` with a bare `EOFError`; failing early with a pointer to `setup_token.py` is the useful behavior. The fixed port 8080 dates from the initial deployment; no Google-side or deployment requirement depends on it. |
| Per-message failure handling | Log and return `None`; the agent skips the message this cycle | Fail the whole poll; retry the message | One unreadable message should not block the rest; because it never reaches the ledger it is retried on the next poll. |
| List failure handling | Let the `HttpError` propagate | Log and return an empty batch | The agent's loop treats an exception as a failed cycle and backs off; returning an empty list made an outage look like an empty inbox. |

## Open Questions & Future Decisions

### Resolved
1. ✅ The token is stored as JSON. A pickled token written by an earlier version is read once and rewritten; pickle's only benefit was obscurity, which is not confidentiality.
2. ✅ The 5000-character body cap and port 8080 are inherited conveniences with no dependent requirement (see the Decisions table).
3. ✅ Headless mode without a TTY fails immediately with a message naming `setup_token.py` instead of dying on `input()`.
4. ✅ The documented console-flow redirect URI (`http://localhost:1`) was unverified against the code and has been removed from DEPLOYMENT.md; the supported path is minting the token with `setup_token.py` and copying it.
5. ✅ `llm_utils.py` is now `mail_text.py`; `log_classification_result` moved to `jev_classifier.py`, the only caller.
6. ✅ Body extraction descends into nested multiparts, so mail with attachments classifies on its text rather than on the snippet.
7. ✅ A failed list call raises; the agent counts the cycle as failed and backs off.
8. ✅ Intake no longer reduces URLs or caps the body; jev-decision owns both, keeping 5000 characters as the cap.
9. ✅ Ids are listed before bodies are fetched, so the agent can skip ledger entries without downloading them.

### Deferred
_None._

## References

- `gmail_client.py`, `mail_text.py`, `setup_token.py`
- `tests/test_gmail_client.py`, `tests/test_mail_text.py`
- README.md: "Headless Mode", "What is sent to the model, and why no injection guard is needed"
- DEPLOYMENT.md: "Headless OAuth Setup"
- Downstream consumer: `docs/intent/jev-decision/jev-decision-design.md` (`build_state`)
- Google Gmail API: `users.messages.list`, `users.messages.get`
