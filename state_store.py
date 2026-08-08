"""
Persistence for processed-email state.

Stores a mapping of email ID -> ISO timestamp in a JSON file, with
retention-based cleanup of old entries.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

logger = logging.getLogger(__name__)


def load_state(state_file: str, retention_days: int) -> Dict[str, str]:
    """
    Load processed email IDs with timestamps from state file.

    Args:
        state_file: Path to the JSON state file
        retention_days: Days to retain entries (<= 0 keeps all)

    Returns:
        Dictionary mapping email IDs to ISO format timestamps
    """
    if not os.path.exists(state_file):
        logger.info(f"No state file found at {state_file}, starting fresh")
        return {}

    try:
        with open(state_file, "r") as f:
            state_data = json.load(f)
            processed_emails_raw = state_data.get("processed_emails", {})

            # Handle migration from old format (list) to new format (dict)
            if isinstance(processed_emails_raw, list):
                logger.info(
                    "Migrating state from old format (list) to new format (dict)"
                )
                # Convert list to dict with current timestamp for all entries
                current_time = datetime.now(timezone.utc).isoformat()
                processed_emails = {
                    email_id: current_time for email_id in processed_emails_raw
                }
            else:
                processed_emails = processed_emails_raw

            # Cleanup old entries
            processed_emails = cleanup_old_state(processed_emails, retention_days)

            logger.info(
                f"Loaded {len(processed_emails)} processed email IDs from {state_file}"
            )
            return processed_emails
    except Exception as e:
        logger.error(f"Error loading state file {state_file}: {e}")
        return {}


def cleanup_old_state(
    processed_emails: Dict[str, str], retention_days: int
) -> Dict[str, str]:
    """
    Remove entries older than retention period.

    Args:
        processed_emails: Dictionary of email_id -> timestamp
        retention_days: Days to retain entries (<= 0 keeps all)

    Returns:
        Cleaned dictionary with only recent entries
    """
    if retention_days <= 0:
        # Retention disabled (keep all)
        return processed_emails

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    original_count = len(processed_emails)

    cleaned = {}
    for email_id, timestamp_str in processed_emails.items():
        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            if timestamp >= cutoff_date:
                cleaned[email_id] = timestamp_str
        except (ValueError, TypeError) as e:
            # Invalid timestamp, skip this entry
            logger.warning(f"Skipping entry with invalid timestamp: {email_id} - {e}")
            continue

    removed_count = original_count - len(cleaned)
    if removed_count > 0:
        logger.info(
            f"Removed {removed_count} email(s) older than {retention_days} days from state"
        )

    return cleaned


def save_state(state_file: str, processed_emails: Dict[str, str]):
    """
    Save processed email IDs with timestamps to state file.

    Args:
        state_file: Path to the JSON state file
        processed_emails: Dictionary of email_id -> timestamp
    """
    try:
        # Ensure directory exists
        state_dir = os.path.dirname(state_file)
        if state_dir and not os.path.exists(state_dir):
            os.makedirs(state_dir, exist_ok=True)

        state_data = {"processed_emails": processed_emails}
        with open(state_file, "w") as f:
            json.dump(state_data, f, indent=2)
        logger.debug(f"State saved to {state_file}")
    except Exception as e:
        logger.error(f"Error saving state file {state_file}: {e}")
