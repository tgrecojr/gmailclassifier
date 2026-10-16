# Gmail Intake — EARS Specs

Prefix `INTAKE`. Facets: `AUTH` (credential resolution and the token script), `FETCH` (listing and per-message records), `BODY` (MIME body extraction), `TEXT` (shared text reduction in `mail_text.py`).

Status markers: `[x]` observed working in current code, `[ ]` specified but broken or partial, `[D]` explicit non-want.

## Authentication

- [x] **INTAKE-AUTH-001**: When a file exists at the configured Gmail token path, the Gmail client shall load credentials from it, reading the JSON form this agent writes and, failing that, the pickle form written by earlier versions, and if they are valid shall use them without prompting.
- [x] **INTAKE-AUTH-002**: When loaded Gmail credentials are expired and carry a refresh token, the Gmail client shall refresh them before building the Gmail service.
- [x] **INTAKE-AUTH-003**: When no valid Gmail credentials can be loaded or refreshed and headless mode is off, the Gmail client shall run the installed-app OAuth flow from the configured credentials file with a local redirect server on port 8080.
- [x] **INTAKE-AUTH-004**: When no valid Gmail credentials can be loaded or refreshed and headless mode is on, the Gmail client shall print the authorization URL, read the full redirect URL from standard input, and exchange it for credentials.
- [x] **INTAKE-AUTH-005**: When Gmail credentials are obtained, refreshed, or were read from a legacy pickle file, the Gmail client shall persist them to the configured token path as JSON before building the Gmail service.
- [x] **INTAKE-AUTH-006**: When the token setup script is run and a token file already exists, the script shall ask for confirmation and, on yes, rename the existing token to `<token path>.backup` before starting a browser-mode OAuth flow.
- [x] **INTAKE-AUTH-007**: If the token setup script is run and the credentials file is missing, then the script shall print download instructions and exit non-zero without starting an OAuth flow.
- [x] **INTAKE-AUTH-008**: If headless mode requires an OAuth flow and standard input is not an interactive terminal, then the Gmail client shall raise an error naming `setup_token.py` instead of waiting for pasted input.

## Fetching

- [x] **INTAKE-FETCH-001**: When asked for unread messages, the Gmail client shall list messages carrying both the `INBOX` and `UNREAD` labels, up to the requested maximum.
- [x] **INTAKE-FETCH-002**: For each listed message, the Gmail client shall fetch the full message and return a record with `id`, `subject`, `from`, `date`, `body`, and `snippet` fields.
- [x] **INTAKE-FETCH-003**: When building a message record, the Gmail client shall match `Subject`, `From`, and `Date` headers case-insensitively and substitute `No Subject`, `Unknown`, and `Unknown` respectively when a header is absent.
- [x] **INTAKE-FETCH-004**: When building a message record, the Gmail client shall apply URL reduction (INTAKE-TEXT-001) to the extracted body and then cut the body to its first 5000 characters.
- [x] **INTAKE-FETCH-005**: If fetching one message's details fails with a Gmail API error, then the Gmail client shall log the error and omit that message from the returned batch while returning the others.
- [x] **INTAKE-FETCH-006**: If listing unread messages fails with a Gmail API error, then the Gmail client shall log the error and return an empty batch.

## Body Extraction

- [x] **INTAKE-BODY-001**: When a message payload has parts, the Gmail client shall use the first top-level `text/plain` part that has data as the body.
- [x] **INTAKE-BODY-002**: When a message payload has parts and no top-level `text/plain` part has data, the Gmail client shall use the first top-level `text/html` part that has data, reduced to visible text (INTAKE-TEXT-003), as the body.
- [x] **INTAKE-BODY-003**: When a message payload has no parts, the Gmail client shall decode the payload's own body data as the body, reducing it to visible text when the payload MIME type is `text/html`.
- [x] **INTAKE-BODY-004**: When no body data is found in a message payload, the Gmail client shall return an empty body string.
- [x] **INTAKE-BODY-005**: The Gmail client shall decode message body data from URL-safe base64 as UTF-8.

## Text Reduction

- [x] **INTAKE-TEXT-001**: The text-reduction helpers shall replace every `http://` or `https://` URL in a string with its scheme and host (port included), dropping path, query, and fragment.
- [x] **INTAKE-TEXT-002**: When reducing a URL, the text-reduction helpers shall end the match at whitespace or at a closing `)`, `>`, or `]` so surrounding punctuation is preserved.
- [x] **INTAKE-TEXT-003**: When reducing HTML to visible text, the text-reduction helpers shall drop comments and whole `script`, `style`, `head`, and `title` blocks; turn `<br>` and the closing tags of `p`, `div`, `tr`, `li`, `h1`–`h6`, and `table` into newlines; remove all remaining tags; unescape HTML entities; and collapse runs of horizontal whitespace to one space and runs of blank lines to one newline.
- [x] **INTAKE-TEXT-004**: The text-reduction helpers shall classify a string as HTML only when it contains one of the structural tags `html`, `body`, `div`, `p`, `br`, `table`, `tr`, `td`, `span`, `a`, or `img`.
- [x] **INTAKE-TEXT-005**: When reducing HTML that ends in a tag with no closing `>`, the text-reduction helpers shall leave that fragment as literal text rather than removing it.
- [x] **INTAKE-TEXT-006**: URL reduction shall be idempotent: reducing already-reduced text shall return it unchanged.
