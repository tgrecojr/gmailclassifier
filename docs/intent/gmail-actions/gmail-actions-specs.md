# Gmail Actions — EARS Specs

Prefix `ACTIONS`. Facets: `LABEL` (ensuring labels exist), `MSG` (modifying messages).

Status markers: `[x]` observed working in current code, `[ ]` specified but broken or partial, `[D]` explicit non-want.

## Ensuring Labels

- [x] **ACTIONS-LABEL-001**: When asked to ensure a Gmail label exists, the Gmail client shall list the account's labels and return the id of the label whose name matches the requested name case-insensitively.
- [x] **ACTIONS-LABEL-002**: When asked to ensure a Gmail label exists and no label name matches case-insensitively, the Gmail client shall create a label with the requested name, `labelListVisibility` of `labelShow`, and `messageListVisibility` of `show`, and return the new label's id.
- [x] **ACTIONS-LABEL-003**: If listing or creating a Gmail label fails with a Gmail API error, then the Gmail client shall log the error and return no id (`None`) without raising.

## Modifying Messages

- [x] **ACTIONS-MSG-001**: When asked to add labels to a message, the Gmail client shall issue a single Gmail `modify` call whose `addLabelIds` are exactly the given label ids.
- [x] **ACTIONS-MSG-002**: When asked to add labels to a message with removal from inbox requested, the Gmail client shall include `removeLabelIds` of `INBOX` in the same `modify` call that adds the labels.
- [x] **ACTIONS-MSG-003**: If a `modify` call made to add labels fails with a Gmail API error, then the Gmail client shall log the error and return without raising.
- [x] **ACTIONS-MSG-006**: When adding labels to a message (with or without removal from inbox), the Gmail client shall not remove the `UNREAD` label, so labeled mail remains unread.
