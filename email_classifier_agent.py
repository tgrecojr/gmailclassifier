import logging
import time
from datetime import UTC, datetime

import config
import state_store
from gmail_client import GmailClient
from jev_classifier import JevClassifier

logger = logging.getLogger(__name__)


class EmailClassifierAgent:
    """Main agent for classifying and labeling Gmail emails."""

    def __init__(self):
        """Initialize the email classifier agent."""
        self.dry_run = config.DRY_RUN

        self.gmail_client = GmailClient(
            credentials_path=config.GMAIL_CREDENTIALS_PATH,
            token_path=config.GMAIL_TOKEN_PATH,
            scopes=config.GMAIL_SCOPES,
            headless=config.GMAIL_HEADLESS_MODE,
        )

        self.classifier = JevClassifier(
            api_key=config.OPENROUTER_API_KEY,
            labels=config.LABELS,
            label_descriptions=config.LABEL_DESCRIPTIONS,
            model=config.JEV_MODEL,
            decisions_url=config.JEV_DECISIONS_URL,
            label_threshold=config.JEV_LABEL_THRESHOLD,
            fallback_confidence=config.JEV_FALLBACK_CONFIDENCE,
            timeout_seconds=config.JEV_TIMEOUT_SECONDS,
        )

        # Gmail labels are created up front (skipped in dry run: no writes)
        self.label_id_map = self._initialize_labels()
        self.review_label_id = (
            self.gmail_client.create_label_if_not_exists(config.JEV_REVIEW_LABEL)
            if config.JEV_REVIEW_LABEL and not self.dry_run
            else None
        )

        self.state_file = config.STATE_FILE
        self.retention_days = config.STATE_RETENTION_DAYS
        self.processed_emails: dict[str, str] = self._load_state()

        logger.info(
            f"Email Classifier Agent initialized with Jev at "
            f"{config.JEV_DECISIONS_URL} (model: {config.JEV_MODEL}, "
            f"label_threshold: {config.JEV_LABEL_THRESHOLD}, "
            f"fallback_confidence: {config.JEV_FALLBACK_CONFIDENCE}, "
            f"review_label: {config.JEV_REVIEW_LABEL or '<none>'}"
            f"{', DRY RUN' if self.dry_run else ''})"
        )
        logger.info(
            f"Loaded {len(self.processed_emails)} processed emails from state "
            f"(retention: {self.retention_days} days)"
        )

    def _initialize_labels(self) -> dict[str, str]:
        """
        Create Gmail labels for all configured labels.

        Returns:
            Dictionary mapping label names to Gmail label IDs
        """
        if self.dry_run:
            logger.info("DRY RUN: not creating Gmail labels")
            return {}

        label_map = {}
        for label_name in config.LABELS:
            label_id = self.gmail_client.create_label_if_not_exists(label_name)
            if label_id:
                label_map[label_name] = label_id

        logger.info(f"Initialized {len(label_map)} Gmail labels")
        return label_map

    def _load_state(self) -> dict[str, str]:
        """
        Load processed email IDs from the state file, applying retention cleanup.

        Returns:
            Dictionary mapping email IDs to ISO format timestamps
        """
        processed_emails = state_store.load_state(self.state_file)
        processed_emails = self._cleanup_old_state(processed_emails)
        logger.info(
            f"Loaded {len(processed_emails)} processed email IDs from {self.state_file}"
        )
        return processed_emails

    def _cleanup_old_state(self, processed_emails: dict[str, str]) -> dict[str, str]:
        """
        Remove processed entries older than the retention period.
        Retention <= 0 keeps everything.
        """
        if self.retention_days <= 0:
            return processed_emails

        cutoff = state_store.retention_cutoff(self.retention_days)
        return state_store.cleanup_old_entries(
            processed_emails, cutoff, self.retention_days
        )

    def _save_state(self):
        """Persist processed email IDs (never in dry run)."""
        if self.dry_run:
            return
        state_store.save_state(self.state_file, self.processed_emails)

    def _mark_processed(self, email_id: str) -> None:
        self.processed_emails[email_id] = datetime.now(UTC).isoformat()
        self._save_state()

    def process_email(self, email: dict) -> bool:
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

            subject = email.get("subject", "")[:50]

            # Check if already processed
            if email_id in self.processed_emails:
                logger.info(f"Skipping already processed email: {subject}...")
                return True  # Return True since it was successfully handled before

            logger.info(f"Processing email: {subject}...")

            predicted_labels = self.classifier.classify_email(email)

            if self.dry_run:
                logger.info(
                    f"DRY RUN: would apply {predicted_labels or 'no labels'} "
                    f"to email: {subject}"
                )
                # Remembered in memory only so the same poll results are not
                # re-classified every cycle; nothing is written to disk.
                self._mark_processed(email_id)
                return bool(predicted_labels)

            if not predicted_labels:
                self._handle_unlabeled(email)
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
                logger.info(f"{action} {predicted_labels} to email: {subject}")
            else:
                logger.warning(
                    f"No valid label IDs found for predicted labels: {predicted_labels}"
                )

            self._mark_processed(email_id)
            return True

        except Exception as e:
            logger.error(f"Error processing email {email.get('id', 'unknown')}: {e}")
            return False

    def _handle_unlabeled(self, email: dict) -> None:
        """
        No label cleared either threshold (or the request failed). The email
        is marked processed so it is not re-sent; with JEV_REVIEW_LABEL set it
        is also labeled and left in the inbox so a human sees it.
        """
        subject = email.get("subject", "")[:50]
        if self.review_label_id:
            self.gmail_client.add_labels_to_message(
                email["id"], [self.review_label_id], remove_from_inbox=False
            )
            logger.warning(
                f"No labels predicted; labeled {config.JEV_REVIEW_LABEL} and "
                f"marked processed: {subject}"
            )
        else:
            logger.warning(f"No labels predicted for email: {subject}")
        self._mark_processed(email["id"])

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
