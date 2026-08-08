import time
import logging
from datetime import datetime, timezone
from typing import Dict, List
from gmail_client import GmailClient
from injection_guard import InjectionGuard
from openrouter_classifier import OpenRouterClassifier
import config
import state_store

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
            model=config.OPENROUTER_MODEL,
            temperature=config.OPENROUTER_TEMPERATURE,
            max_tokens=config.OPENROUTER_MAX_TOKENS,
        )

        # Create Gmail labels if they don't exist
        self.label_id_map = self._initialize_labels()

        # Prompt-injection guard: scans emails locally before any LLM call
        self.injection_guard = None
        self.quarantine_label_id = None
        if config.INJECTION_GUARD_ENABLED:
            self.injection_guard = InjectionGuard(
                ml_enabled=config.INJECTION_ML_ENABLED,
                ml_model=config.INJECTION_ML_MODEL,
                ml_threshold=config.INJECTION_ML_THRESHOLD,
            )
            self.quarantine_label_id = self.gmail_client.create_label_if_not_exists(
                config.INJECTION_QUARANTINE_LABEL
            )

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
        """Load processed email IDs with timestamps from state file."""
        return state_store.load_state(self.state_file, self.retention_days)

    def _cleanup_old_state(self, processed_emails: Dict[str, str]) -> Dict[str, str]:
        """Remove entries older than retention period."""
        return state_store.cleanup_old_state(processed_emails, self.retention_days)

    def _save_state(self):
        """Save processed email IDs with timestamps to state file."""
        state_store.save_state(self.state_file, self.processed_emails)

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

            # Scan for prompt injection BEFORE any content reaches the LLM
            if self.injection_guard is not None:
                scan = self.injection_guard.scan(email)
                if scan.flagged:
                    return self._quarantine_email(email, scan.reasons)
                # Use the sanitized content for classification
                email = scan.sanitized_email

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

    def _quarantine_email(self, email: Dict, reasons: List[str]) -> bool:
        """
        Quarantine a suspicious email without sending it to the LLM.

        Applies the quarantine label, leaves the email in the inbox for
        human review, and marks it processed so it is not re-attempted.

        Args:
            email: Email dictionary from Gmail API
            reasons: Detection reasons from the injection guard

        Returns:
            True (the email was handled)
        """
        logger.warning(
            f"Prompt injection suspected in email '{email['subject'][:50]}' "
            f"({', '.join(reasons)}); quarantining without classification"
        )
        if self.quarantine_label_id:
            self.gmail_client.add_labels_to_message(
                email["id"], [self.quarantine_label_id], remove_from_inbox=False
            )
        self.processed_emails[email["id"]] = datetime.now(timezone.utc).isoformat()
        self._save_state()
        return True

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
