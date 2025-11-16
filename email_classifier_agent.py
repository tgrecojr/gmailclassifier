import json
import time
import logging
import os
from typing import Dict, Set
from gmail_client import GmailClient
from llm_factory import create_llm_provider
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

        # Initialize LLM provider (Bedrock, Anthropic, OpenAI, or Ollama)
        self.classifier = create_llm_provider(config)

        # Create Gmail labels if they don't exist
        self.label_id_map = self._initialize_labels()

        # Load processed email state
        self.state_file = config.STATE_FILE
        self.processed_emails: Set[str] = self._load_state()

        logger.info(
            f"Email Classifier Agent initialized with {config.LLM_PROVIDER} provider"
        )
        logger.info(f"Loaded {len(self.processed_emails)} processed emails from state")

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

    def _load_state(self) -> Set[str]:
        """
        Load processed email IDs from state file.

        Returns:
            Set of processed email IDs
        """
        if not os.path.exists(self.state_file):
            logger.info(f"No state file found at {self.state_file}, starting fresh")
            return set()

        try:
            with open(self.state_file, "r") as f:
                state_data = json.load(f)
                processed_ids = set(state_data.get("processed_emails", []))
                logger.info(
                    f"Loaded {len(processed_ids)} processed email IDs from {self.state_file}"
                )
                return processed_ids
        except Exception as e:
            logger.error(f"Error loading state file {self.state_file}: {e}")
            return set()

    def _save_state(self):
        """
        Save processed email IDs to state file.
        """
        try:
            # Ensure directory exists
            state_dir = os.path.dirname(self.state_file)
            if state_dir and not os.path.exists(state_dir):
                os.makedirs(state_dir, exist_ok=True)

            state_data = {"processed_emails": list(self.processed_emails)}
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
                self.processed_emails.add(email_id)
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

            # Mark as processed and save state
            self.processed_emails.add(email_id)
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
