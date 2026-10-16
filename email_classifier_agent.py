import logging
import signal
import time
from datetime import UTC, datetime

import config
import state_store
from gmail_client import GmailClient
from jev_classifier import OPENROUTER_DECISIONS_URL, JevClassifier

logger = logging.getLogger(__name__)

# After consecutive failed poll cycles the retry delay doubles from
# POLL_INTERVAL_SECONDS up to this many times the interval.
MAX_BACKOFF_MULTIPLIER = 10


class EmailClassifierAgent:
    """Main agent for classifying and labeling Gmail emails."""

    # @spec AGENT-INIT-001, AGENT-INIT-002, AGENT-INIT-003, AGENT-INIT-004, AGENT-INIT-006
    def __init__(self):
        """Initialize the email classifier agent."""
        self.dry_run = config.DRY_RUN

        # The classifier only validates configuration; build it first so a bad
        # label set or key fails before Gmail starts an OAuth prompt or refresh.
        self.classifier = JevClassifier(
            api_key=config.OPENROUTER_API_KEY,
            labels=config.LABELS,
            label_descriptions=config.LABEL_DESCRIPTIONS,
            model=config.JEV_MODEL,
            label_threshold=config.JEV_LABEL_THRESHOLD,
            fallback_confidence=config.JEV_FALLBACK_CONFIDENCE,
            timeout_seconds=config.JEV_TIMEOUT_SECONDS,
        )

        self.gmail_client = GmailClient(
            credentials_path=config.GMAIL_CREDENTIALS_PATH,
            token_path=config.GMAIL_TOKEN_PATH,
            scopes=config.GMAIL_SCOPES,
            headless=config.GMAIL_HEADLESS_MODE,
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
            f"{OPENROUTER_DECISIONS_URL} (model: {config.JEV_MODEL}, "
            f"label_threshold: {config.JEV_LABEL_THRESHOLD}, "
            f"fallback_confidence: {config.JEV_FALLBACK_CONFIDENCE}, "
            f"review_label: {config.JEV_REVIEW_LABEL or '<none>'}"
            f"{', DRY RUN' if self.dry_run else ''})"
        )
        logger.info(
            f"Loaded {len(self.processed_emails)} processed emails from state "
            f"(retention: {self.retention_days} days)"
        )

    # @spec AGENT-INIT-003, AGENT-INIT-005
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

    # @spec STATE-MARK-002
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

    # @spec STATE-RET-002
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

    # @spec STATE-FILE-008
    def _save_state(self):
        """Persist processed email IDs (never in dry run)."""
        if self.dry_run:
            return
        state_store.save_state(self.state_file, self.processed_emails)

    # @spec STATE-MARK-001
    def _mark_processed(self, email_id: str) -> None:
        self.processed_emails[email_id] = datetime.now(UTC).isoformat()
        self._save_state()

    # @spec AGENT-PROC-001, AGENT-PROC-002, AGENT-PROC-003, AGENT-PROC-004,
    # @spec AGENT-PROC-007, AGENT-PROC-008, AGENT-PROC-009, AGENT-PROC-010
    def process_email(self, email: dict) -> bool:
        """
        Process a single email: classify it and apply labels.

        Args:
            email: Email dictionary from Gmail API

        Returns:
            True when the email was handled (labeled, sent to review, left
            unlabeled, or already processed); False when it could not be
            handled (no id, or an unexpected error) and should be retried.
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
                return True

            if not predicted_labels:
                self._handle_unlabeled(email)
                return True

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

    # @spec AGENT-PROC-005, AGENT-PROC-006
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

    @staticmethod
    def _backoff_seconds(consecutive_failures: int) -> float:
        """
        Sleep after a failed poll cycle: the poll interval, doubled for each
        further consecutive failure, capped at MAX_BACKOFF_MULTIPLIER times
        the interval. A successful cycle resets the count.
        """
        interval = config.POLL_INTERVAL_SECONDS
        multiplier = min(2 ** (consecutive_failures - 1), MAX_BACKOFF_MULTIPLIER)
        return interval * multiplier

    # @spec STATE-RET-005
    def _poll_once(self) -> None:
        """One poll cycle: prune state, fetch unread mail, process each email."""
        logger.info("=== Checking for new emails ===")

        # Cleanup old state entries periodically
        self.processed_emails = self._cleanup_old_state(self.processed_emails)

        emails = self.gmail_client.get_unread_messages(
            max_results=config.MAX_EMAILS_PER_POLL
        )
        if not emails:
            logger.debug("No unread emails to process")
            return

        handled = sum(1 for email in emails if self.process_email(email))
        failed = len(emails) - handled
        logger.info(
            f"=== Handled {handled} of {len(emails)} emails ({failed} failed) ==="
        )

    @staticmethod
    def _raise_interrupt(signum, frame):
        """SIGTERM (what `docker stop` sends) ends the loop like Ctrl-C."""
        raise KeyboardInterrupt

    # @spec AGENT-LOOP-001, AGENT-LOOP-002, AGENT-LOOP-003, AGENT-LOOP-004, AGENT-LOOP-005
    def run_continuous(self):
        """
        Run the agent continuously, polling for new emails, until interrupted
        by Ctrl-C or SIGTERM.
        """
        logger.info(
            f"Starting continuous email classifier agent (polling every {config.POLL_INTERVAL_SECONDS}s)"
        )
        signal.signal(signal.SIGTERM, self._raise_interrupt)
        consecutive_failures = 0

        try:
            while True:
                try:
                    self._poll_once()
                    consecutive_failures = 0
                    delay = config.POLL_INTERVAL_SECONDS
                    logger.debug(f"Sleeping for {delay} seconds...")
                except Exception as e:
                    consecutive_failures += 1
                    delay = self._backoff_seconds(consecutive_failures)
                    logger.error(f"Error in continuous loop: {e}")
                    logger.info(
                        f"Waiting {delay:g} seconds before retry "
                        f"(consecutive failures: {consecutive_failures})..."
                    )
                time.sleep(delay)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down gracefully...")

        logger.info("Email Classifier Agent stopped")
