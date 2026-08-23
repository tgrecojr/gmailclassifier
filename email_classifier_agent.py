import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict
from gmail_client import GmailClient
from openrouter_classifier import ClassificationRejected, OpenRouterClassifier
from retry_tracker import RetryTracker
import state_store
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

        # Initialize LLM classifier (OpenRouter by default, or a custom gateway)
        self.classifier = OpenRouterClassifier(
            api_key=config.OPENROUTER_API_KEY,
            model=config.OPENROUTER_MODEL,
            temperature=config.OPENROUTER_TEMPERATURE,
            max_tokens=config.OPENROUTER_MAX_TOKENS,
            base_url=config.LLM_BASE_URL,
        )

        # Create Gmail labels if they don't exist
        self.label_id_map = self._initialize_labels()

        # Load processed email state (+ emails parked for retry after a 400)
        self.state_file = config.STATE_FILE
        self.retention_days = config.STATE_RETENTION_DAYS
        self.retries = RetryTracker(
            max_attempts=config.REJECTED_MAX_ATTEMPTS,
            base_delay=timedelta(minutes=config.REJECTED_RETRY_BASE_MINUTES),
        )
        self.processed_emails: Dict[str, str] = self._load_state()

        logger.info(
            f"Email Classifier Agent initialized with LLM endpoint "
            f"{config.LLM_BASE_URL} (model: {config.OPENROUTER_MODEL})"
        )
        logger.info(
            f"Loaded {len(self.processed_emails)} processed emails and "
            f"{len(self.retries.entries)} pending retries from state "
            f"(retention: {self.retention_days} days; rejected emails retried up to "
            f"{self.retries.max_attempts}x from {config.REJECTED_RETRY_BASE_MINUTES}m)"
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
        Load processed email IDs (and pending retries) from the state file,
        applying retention cleanup.

        Returns:
            Dictionary mapping email IDs to ISO format timestamps
        """
        processed_emails, pending = state_store.load_state(self.state_file)
        self.retries.entries = pending
        processed_emails = self._cleanup_old_state(processed_emails)
        logger.info(
            f"Loaded {len(processed_emails)} processed email IDs from {self.state_file}"
        )
        return processed_emails

    def _cleanup_old_state(self, processed_emails: Dict[str, str]) -> Dict[str, str]:
        """
        Remove processed entries (and pending retries) older than the
        retention period. Retention <= 0 keeps everything.
        """
        if self.retention_days <= 0:
            return processed_emails

        cutoff = state_store.retention_cutoff(self.retention_days)
        self.retries.prune(cutoff)
        return state_store.cleanup_old_entries(
            processed_emails, cutoff, self.retention_days
        )

    def _save_state(self):
        """Persist processed email IDs and pending retries."""
        state_store.save_state(
            self.state_file, self.processed_emails, self.retries.to_dict()
        )

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

            # Rejected earlier and not yet due for another try
            if self.retries.is_deferred(email_id, datetime.now(timezone.utc)):
                logger.debug(
                    f"Deferring retry of rejected email: {email['subject'][:50]}..."
                )
                return False

            logger.info(f"Processing email: {email['subject'][:50]}...")

            # Classify the email
            try:
                predicted_labels = self.classifier.classify_email(
                    email=email,
                    classification_prompt=config.CLASSIFICATION_PROMPT,
                    available_labels=config.LABELS,
                )
            except ClassificationRejected as e:
                self._handle_rejection(email, str(e))
                return False

            # A successful round trip resolves any earlier rejection
            self.retries.clear(email_id)

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

    def _handle_rejection(self, email: Dict, reason: str) -> None:
        """
        The endpoint answered 400 (e.g. guardrail block). Park the email for a
        backed-off retry, or give up and mark it processed once the attempt
        cap is reached so a permanently-blocked email cannot loop forever.
        """
        email_id = email["id"]
        subject = email.get("subject", "")[:50]
        now = datetime.now(timezone.utc)
        gave_up = self.retries.record_rejection(email_id, reason, now)
        if gave_up:
            logger.warning(
                f"Giving up on rejected email after {self.retries.max_attempts} "
                f"attempt(s), marking processed without labels: {subject}"
            )
            self.processed_emails[email_id] = now.isoformat()
        else:
            attempts = self.retries.attempts(email_id)
            logger.warning(
                f"Email rejected (attempt {attempts}/{self.retries.max_attempts}); "
                f"will retry after {self.retries.delay_after(attempts)}: {subject}"
            )
        self._save_state()

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
