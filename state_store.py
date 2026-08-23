"""
Persistence for the agent's processed-email state file.

File layout:

    {
        "processed_emails": {"<email_id>": "<iso timestamp>", ...},
        "pending_retries":  {"<email_id>": {...}, ...}   # see retry_tracker
    }

Older files stored "processed_emails" as a plain list of IDs; those are
migrated on load with the current time as the timestamp.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


def load_state(path: str) -> Tuple[Dict[str, str], Dict[str, dict]]:
    """
    Read the state file.

    Returns:
        (processed_emails, pending_retries). Both empty if the file is
        missing or unreadable — a bad state file must never stop the agent.
    """
    if not os.path.exists(path):
        logger.info(f"No state file found at {path}, starting fresh")
        return {}, {}

    try:
        with open(path, "r") as f:
            state_data = json.load(f)
    except Exception as e:
        logger.error(f"Error loading state file {path}: {e}")
        return {}, {}

    processed_raw = state_data.get("processed_emails", {})
    if isinstance(processed_raw, list):
        logger.info("Migrating state from old format (list) to new format (dict)")
        now = datetime.now(timezone.utc).isoformat()
        processed = {email_id: now for email_id in processed_raw}
    else:
        processed = processed_raw

    pending = state_data.get("pending_retries", {}) or {}
    return processed, pending


def save_state(
    path: str, processed_emails: Dict[str, str], pending_retries: Dict[str, dict]
) -> None:
    """Write the state file, creating its directory if needed. Errors are logged."""
    try:
        state_dir = os.path.dirname(path)
        if state_dir and not os.path.exists(state_dir):
            os.makedirs(state_dir, exist_ok=True)

        state_data = {
            "processed_emails": processed_emails,
            "pending_retries": pending_retries,
        }
        with open(path, "w") as f:
            json.dump(state_data, f, indent=2)
        logger.debug(f"State saved to {path}")
    except Exception as e:
        logger.error(f"Error saving state file {path}: {e}")


def retention_cutoff(retention_days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=retention_days)


def cleanup_old_entries(
    processed_emails: Dict[str, str], cutoff: datetime, retention_days: int
) -> Dict[str, str]:
    """
    Drop processed-email entries older than cutoff (or with unreadable
    timestamps). retention_days is only used for the log line.
    """
    cleaned = {}
    for email_id, timestamp_str in processed_emails.items():
        try:
            if datetime.fromisoformat(timestamp_str) >= cutoff:
                cleaned[email_id] = timestamp_str
        except (ValueError, TypeError) as e:
            logger.warning(f"Skipping entry with invalid timestamp: {email_id} - {e}")

    removed = len(processed_emails) - len(cleaned)
    if removed > 0:
        logger.info(
            f"Removed {removed} email(s) older than {retention_days} days from state"
        )
    return cleaned
