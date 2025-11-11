import os
import pickle
import base64
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging

logger = logging.getLogger(__name__)


class GmailClient:
    """Client for interacting with Gmail API."""

    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        scopes: List[str],
        headless: bool = False,
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes
        self.headless = headless
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate and build Gmail service."""
        creds = None

        # Load existing token if available
        if os.path.exists(self.token_path):
            with open(self.token_path, "rb") as token:
                creds = pickle.load(token)

        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired credentials")
                creds.refresh(Request())
            else:
                logger.info("Starting OAuth flow for new credentials")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.scopes
                )

                if self.headless:
                    # Headless mode: print URL and ask for authorization code
                    creds = self._run_console_flow(flow)
                else:
                    # Browser mode: open browser automatically
                    creds = flow.run_local_server(port=8080)

            # Save credentials for next run
            with open(self.token_path, "wb") as token:
                pickle.dump(creds, token)

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authentication successful")

    def _run_console_flow(self, flow):
        """
        Run OAuth flow in console/headless mode.
        User must manually visit URL and paste authorization code.
        """
        # Generate authorization URL
        auth_url, _ = flow.authorization_url(prompt="consent")

        print("\n" + "=" * 80)
        print("GMAIL AUTHORIZATION REQUIRED")
        print("=" * 80)
        print("\nPlease visit this URL to authorize the application:")
        print(f"\n{auth_url}\n")
        print("After authorizing, you will be redirected to a URL.")
        print("Copy the FULL redirect URL and paste it below.")
        print("=" * 80)

        # Get authorization code from user
        redirect_response = input("\nPaste the full redirect URL here: ").strip()

        # Extract code from redirect URL
        flow.fetch_token(authorization_response=redirect_response)

        return flow.credentials

    def get_unread_messages(self, max_results: int = 10) -> List[Dict]:
        """
        Get unread messages from inbox.

        Args:
            max_results: Maximum number of messages to retrieve

        Returns:
            List of message dictionaries with id, subject, from, body
        """
        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results)
                .execute()
            )

            messages = results.get("messages", [])

            if not messages:
                logger.info("No unread messages found")
                return []

            logger.info(f"Found {len(messages)} unread messages")

            # Get full message details
            detailed_messages = []
            for msg in messages:
                detailed_msg = self._get_message_details(msg["id"])
                if detailed_msg:
                    detailed_messages.append(detailed_msg)

            return detailed_messages

        except HttpError as error:
            logger.error(f"An error occurred: {error}")
            return []

    def _get_message_details(self, msg_id: str) -> Optional[Dict]:
        """Get detailed information about a specific message."""
        try:
            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )

            headers = message["payload"].get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            from_email = next(
                (h["value"] for h in headers if h["name"].lower() == "from"), "Unknown"
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"), "Unknown"
            )

            # Get message body
            body = self._get_message_body(message["payload"])

            return {
                "id": msg_id,
                "subject": subject,
                "from": from_email,
                "date": date,
                "body": body[:5000],  # Limit body to 5000 chars to avoid token limits
                "snippet": message.get("snippet", ""),
            }

        except HttpError as error:
            logger.error(f"Error getting message details for {msg_id}: {error}")
            return None

    def _get_message_body(self, payload: Dict) -> str:
        """Extract message body from payload."""
        body = ""

        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    if "data" in part["body"]:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                            "utf-8"
                        )
                        break
                elif part["mimeType"] == "text/html" and not body:
                    if "data" in part["body"]:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                            "utf-8"
                        )
        elif "body" in payload and "data" in payload["body"]:
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")

        return body

    def create_label_if_not_exists(self, label_name: str) -> str:
        """
        Create a Gmail label if it doesn't exist.

        Args:
            label_name: Name of the label to create

        Returns:
            Label ID
        """
        try:
            # Check if label already exists
            results = self.service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])

            for label in labels:
                if label["name"] == label_name:
                    logger.debug(
                        f"Label '{label_name}' already exists with ID: {label['id']}"
                    )
                    return label["id"]

            # Create new label
            label_object = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }

            created_label = (
                self.service.users()
                .labels()
                .create(userId="me", body=label_object)
                .execute()
            )

            logger.info(
                f"Created new label '{label_name}' with ID: {created_label['id']}"
            )
            return created_label["id"]

        except HttpError as error:
            logger.error(f"Error creating label '{label_name}': {error}")
            return None

    def add_labels_to_message(
        self, msg_id: str, label_ids: List[str], remove_from_inbox: bool = False
    ):
        """
        Add labels to a message and optionally remove from inbox.

        Args:
            msg_id: Message ID
            label_ids: List of label IDs to add
            remove_from_inbox: If True, remove INBOX label (archive the email)
        """
        try:
            body = {"addLabelIds": label_ids}

            # Archive email by removing INBOX label
            if remove_from_inbox:
                body["removeLabelIds"] = ["INBOX"]

            self.service.users().messages().modify(
                userId="me", id=msg_id, body=body
            ).execute()

            action = (
                "Added labels and archived" if remove_from_inbox else "Added labels to"
            )
            logger.info(f"{action} message {msg_id}")

        except HttpError as error:
            logger.error(f"Error adding labels to message {msg_id}: {error}")

    def mark_as_read(self, msg_id: str):
        """Mark a message as read."""
        try:
            self.service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
            ).execute()

            logger.debug(f"Marked message {msg_id} as read")

        except HttpError as error:
            logger.error(f"Error marking message {msg_id} as read: {error}")

    def archive_message(self, msg_id: str):
        """
        Archive a message by removing it from inbox.
        The message will still be accessible via its labels and All Mail.
        """
        try:
            self.service.users().messages().modify(
                userId="me", id=msg_id, body={"removeLabelIds": ["INBOX"]}
            ).execute()

            logger.debug(f"Archived message {msg_id}")

        except HttpError as error:
            logger.error(f"Error archiving message {msg_id}: {error}")
