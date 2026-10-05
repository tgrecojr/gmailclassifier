#!/usr/bin/env python3
"""
Dump recent Gmail messages to a JSONL sample for scripts/eval_jev.py.

Each row carries the fields the classifier sees plus the message's current
Gmail labels (restricted to the configured label set). ``expected_labels`` is
pre-filled with those current labels: open the file and CORRECT them by hand
before evaluating, otherwise you are only measuring agreement with the old
pipeline.

    uv run python scripts/dump_sample.py --out data/jev_sample.jsonl --max 50 \
        --query "newer_than:14d"

The output is real mail. ``data/`` is gitignored; delete the file when done.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from gmail_client import GmailClient  # noqa: E402


def label_names(client: GmailClient) -> dict[str, str]:
    """Gmail label id -> name."""
    result = client.service.users().labels().list(userId="me").execute()
    return {lab["id"]: lab["name"] for lab in result.get("labels", [])}


def message_label_ids(client: GmailClient, msg_id: str) -> list[str]:
    msg = (
        client.service.users()
        .messages()
        .get(userId="me", id=msg_id, format="minimal")
        .execute()
    )
    return msg.get("labelIds", [])


def list_message_ids(client: GmailClient, query: str, max_results: int) -> list[str]:
    result = (
        client.service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    return [m["id"] for m in result.get("messages", [])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="data/jev_sample.jsonl")
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--query", default="newer_than:14d -in:spam -in:trash")
    args = parser.parse_args()

    client = GmailClient(
        credentials_path=config.GMAIL_CREDENTIALS_PATH,
        token_path=config.GMAIL_TOKEN_PATH,
        scopes=config.GMAIL_SCOPES,
        headless=config.GMAIL_HEADLESS_MODE,
    )
    names = label_names(client)
    configured = set(config.LABELS)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8") as fh:
        for msg_id in list_message_ids(client, args.query, args.max):
            details = client._get_message_details(msg_id)  # noqa: SLF001
            if not details:
                continue
            current = sorted(
                names.get(lid, lid)
                for lid in message_label_ids(client, msg_id)
                if names.get(lid, lid) in configured
            )
            row = {
                "id": details["id"],
                "subject": details["subject"],
                "from": details["from"],
                "date": details["date"],
                "body": details["body"],
                "current_labels": current,
                "expected_labels": current,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
    print(f"Wrote {written} messages to {out}. Now correct expected_labels by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
