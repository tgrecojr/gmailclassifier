# Processed State — EARS Specs

Prefix `STATE`. Facets: `FILE` (file layout, loading, saving), `MARK` (recording a processed email), `RET` (retention pruning).

Status markers: `[x]` observed working in current code, `[ ]` specified but broken or partial, `[D]` explicit non-want.

## File Layout, Loading, Saving

- [x] **STATE-FILE-001**: The state store shall persist the processed-email ledger as a JSON object with a single `processed_emails` key mapping each Gmail message id to a timezone-aware UTC ISO 8601 timestamp.
- [x] **STATE-FILE-002**: When the state file does not exist at the configured path, the state store shall return an empty ledger and log that it is starting fresh.
- [x] **STATE-FILE-003**: If the state file cannot be read or is not valid JSON, then the state store shall log the error and return an empty ledger rather than raising.
- [x] **STATE-FILE-004**: When the state file's `processed_emails` value is a list of ids (legacy layout), the state store shall return a ledger mapping each id to the load-time timestamp.
- [x] **STATE-FILE-005**: When loading the state file, the state store shall ignore any top-level key other than `processed_emails` (including a legacy `pending_retries` block), and the next save shall not write such keys back.
- [x] **STATE-FILE-006**: When saving the ledger, the state store shall create the state file's parent directory if it does not exist.
- [x] **STATE-FILE-007**: If saving the ledger fails, then the state store shall log the error and return without raising.
- [x] **STATE-FILE-009**: When saving the ledger, the state store shall write the JSON to a temporary file beside the state file and then atomically replace the state file with it, so a crash mid-write leaves the previous ledger intact.
- [x] **STATE-FILE-008**: While dry run is on (the agent-runtime setting that suppresses all Gmail and disk writes), the agent shall not write the state file, keeping processed ids in memory only for the life of the process.

## Marking Processed

- [x] **STATE-MARK-001**: When the agent marks an email processed, it shall record the email's id with the current UTC time as a timezone-aware ISO 8601 timestamp and save the ledger immediately (subject to STATE-FILE-008).
- [x] **STATE-MARK-002**: When the agent starts, it shall load the ledger from the configured state file and apply retention pruning (STATE-RET-001) before the first poll.

## Retention

- [x] **STATE-RET-001**: When pruning the ledger with a positive retention in days, the agent shall remove every entry whose timestamp is earlier than the current UTC time minus that many days.
- [x] **STATE-RET-002**: When the configured retention is zero or negative, the agent shall skip pruning and keep every ledger entry.
- [x] **STATE-RET-003**: When pruning the ledger and an entry's timestamp cannot be parsed or compared to the cutoff, the agent shall drop that entry and log a warning naming the id.
- [x] **STATE-RET-004**: When pruning removes one or more entries, the agent shall log the number removed and the retention period at INFO level.
- [x] **STATE-RET-005**: At the start of every poll cycle, the agent shall prune the in-memory ledger (STATE-RET-001 and STATE-RET-002) before fetching unread messages.
