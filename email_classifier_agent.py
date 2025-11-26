import json
import time
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict
from gmail_client import GmailClient
from openrouter_classifier import OpenRouterClassifier
import config

logger = logging.getLogger(__name__)


class EmailClassifierAgent:
    """Main agent for classifying and labeling Gmail emails."""

    def __init__(self):
        """Initialize the email classifier agent."""
        # Initialize Gmail client
        self.gmail_client = GmailClient(
            credentials_path=config.GMAIL_CREDENTIALS_PATH,
            token_path=config.GMAIL_TOKEN_PATH,
            scopes=config.GMAIL_SCOPES,
            headless=config.GMAIL_HEADLESS_MODE,
        )

        # Initialize OpenRouter classifier
        self.classifier = OpenRouterClassifier(
            api_key=config.OPENROUTER_API_KEY,
            model=config.OPENROUTER_MODEL
        )

        # Create Gmail labels if they don't exist
        self.label_id_map = self._initialize_labels()

        # Load processed email state
        self.state_file = config.STATE_FILE
        self.retention_days = config.STATE_RETENTION_DAYS
        self.processed_emails: Dict[str, str] = self._load_state()

        logger.info(
            f"Email Classifier Agent initialized with OpenRouter (model: {config.OPENROUTER_MODEL})"
        )
        logger.info(
            f"Loaded {len(self.processed_emails)} processed emails from state "
            f"(retention: {self.retention_days} days)"
        )

    def _initialize_labels(self) -> Dict[str, str]:
        """
        Create Gmail labels for all configured labels.

        Returns:
            Dictionary mapping label names to Gmail label IDs
        """
        label_map = {}
        for label_name in config.LABELS:
            label_id = self.gmail_client.create_label_if_not_exists(label_name)
            if label_id:
                label_map[label_name] = label_id

        logger.info(f"Initialized {len(label_map)} Gmail labels")
        return label_map

    def _load_state(self) -> Dict[str, str]:
        """
        Load processed email IDs with timestamps from state file.

        Returns:
            Dictionary mapping email IDs to ISO format timestamps
        """
        if not os.path.exists(self.state_file):
            logger.info(f"No state file found at {self.state_file}, starting fresh")
            return {}

        try:
            with open(self.state_file, "r") as f:
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
                processed_emails = self._cleanup_old_state(processed_emails)

                logger.info(
                    f"Loaded {len(processed_emails)} processed email IDs from {self.state_file}"
                )
                return processed_emails
        except Exception as e:
            logger.error(f"Error loading state file {self.state_file}: {e}")
            return {}

    def _cleanup_old_state(self, processed_emails: Dict[str, str]) -> Dict[str, str]:
        """
        Remove entries older than retention period.

        Args:
            processed_emails: Dictionary of email_id -> timestamp

        Returns:
            Cleaned dictionary with only recent entries
        """
        if self.retention_days <= 0:
            # Retention disabled (keep all)
            return processed_emails

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        original_count = len(processed_emails)

        cleaned = {}
        for email_id, timestamp_str in processed_emails.items():
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                if timestamp >= cutoff_date:
                    cleaned[email_id] = timestamp_str
            except (ValueError, TypeError) as e:
                # Invalid timestamp, skip this entry
                logger.warning(
                    f"Skipping entry with invalid timestamp: {email_id} - {e}"
                )
                continue

        removed_count = original_count - len(cleaned)
        if removed_count > 0:
            logger.info(
                f"Removed {removed_count} email(s) older than {self.retention_days} days from state"
            )

        return cleaned

    def _save_state(self):
        """
        Save processed email IDs with timestamps to state file.
        """
        try:
            # Ensure directory exists
            state_dir = os.path.dirname(self.state_file)
            if state_dir and not os.path.exists(state_dir):
                os.makedirs(state_dir, exist_ok=True)

            state_data = {"processed_emails": self.processed_emails}
            with open(self.state_file, "w") as f:
                json.dump(state_data, f, indent=2)
            logger.debug(f"State saved to {self.state_file}")
        except Exception as e:
            logger.error(f"Error saving state file {self.state_file}: {e}")

    def process_email(self, email: Dict) -> bool:
        """
        Process a single email: classify it and apply labels.

        Args:
            email: Email dictionary from Gmail API

        Returns:
            True if successfully processed, False otherwise
        """
        try:
            email_id = email.get("id")
            if not email_id:
                logger.error("Email missing ID field")
                return False

            # Check if already processed
            if email_id in self.processed_emails:
                logger.info(
                    f"Skipping already processed email: {email['subject'][:50]}..."
                )
                return True  # Return True since it was successfully handled before

            logger.info(f"Processing email: {email['subject'][:50]}...")

            # Classify the email
            predicted_labels = self.classifier.classify_email(
                email=email,
                classification_prompt=config.CLASSIFICATION_PROMPT,
                available_labels=config.LABELS,
            )

            if not predicted_labels:
                logger.warning(f"No labels predicted for email: {email['subject']}")
                # Still mark as processed to avoid re-attempting
                self.processed_emails[email_id] = datetime.now(timezone.utc).isoformat()
                self._save_state()
                return False

            # Get Gmail label IDs
            label_ids = [
                self.label_id_map[label]
                for label in predicted_labels
                if label in self.label_id_map
            ]

            if label_ids:
                # Apply labels to the email and optionally remove from inbox
                self.gmail_client.add_labels_to_message(
                    email["id"], label_ids, remove_from_inbox=config.REMOVE_FROM_INBOX
                )
                action = (
                    "Applied labels and archived"
                    if config.REMOVE_FROM_INBOX
                    else "Applied labels"
                )
                logger.info(
                    f"{action} {predicted_labels} to email: {email['subject'][:50]}"
                )
            else:
                logger.warning(
                    f"No valid label IDs found for predicted labels: {predicted_labels}"
                )

            # Mark as processed with timestamp and save state
            self.processed_emails[email_id] = datetime.now(timezone.utc).isoformat()
            self._save_state()

            return True

        except Exception as e:
            logger.error(f"Error processing email {email.get('id', 'unknown')}: {e}")
            return False

    def run_continuous(self):
        """
        Run the agent continuously, polling for new emails.
        """
        logger.info(
            f"Starting continuous email classifier agent (polling every {config.POLL_INTERVAL_SECONDS}s)"
        )

        while True:
            try:
                logger.info("=== Checking for new emails ===")

                # Cleanup old state entries periodically
                self.processed_emails = self._cleanup_old_state(self.processed_emails)

                # Get unread emails
                emails = self.gmail_client.get_unread_messages(
                    max_results=config.MAX_EMAILS_PER_POLL
                )

                if not emails:
                    logger.debug("No unread emails to process")
                else:
                    # Process each email
                    processed_count = 0
                    for email in emails:
                        if self.process_email(email):
                            processed_count += 1

                    logger.info(
                        f"=== Processed {processed_count} out of {len(emails)} emails ==="
                    )

                # Wait before next poll
                logger.debug(f"Sleeping for {config.POLL_INTERVAL_SECONDS} seconds...")
                time.sleep(config.POLL_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                logger.info("Received interrupt signal, shutting down gracefully...")
                break
            except Exception as e:
                logger.error(f"Error in continuous loop: {e}")
                logger.info(
                    f"Waiting {config.POLL_INTERVAL_SECONDS} seconds before retry..."
                )
                time.sleep(config.POLL_INTERVAL_SECONDS)

        logger.info("Email Classifier Agent stopped")
