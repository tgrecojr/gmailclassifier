import base64
import os
import pickle
import sys
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import logging
from mail_text import normalize_urls, strip_html

logger = logging.getLogger(__name__)


# @spec INTAKE-BODY-005
def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data).decode("utf-8")


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

    def _load_token(self):
        """
        Read the token file. The agent writes JSON; earlier versions wrote a
        pickled Credentials object at the same path. Returns (creds, legacy).
        """
        try:
            return (
                Credentials.from_authorized_user_file(self.token_path, self.scopes),
                False,
            )
        except ValueError, UnicodeDecodeError:
            logger.info("Token file is not JSON; reading legacy pickle format")
            with open(self.token_path, "rb") as token:
                return pickle.load(token), True

    def _save_token(self, creds) -> None:
        with open(self.token_path, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    # @spec INTAKE-AUTH-001, INTAKE-AUTH-002, INTAKE-AUTH-003, INTAKE-AUTH-004, INTAKE-AUTH-005
    def _authenticate(self):
        """Authenticate and build Gmail service."""
        creds = None
        needs_save = False

        if os.path.exists(self.token_path):
            creds, needs_save = self._load_token()

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
                    creds = self._run_console_flow(flow)
                else:
                    creds = flow.run_local_server(port=8080)
            needs_save = True

        if needs_save:
            self._save_token(creds)

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authentication successful")

    # @spec INTAKE-AUTH-004, INTAKE-AUTH-008
    def _run_console_flow(self, flow):
        """
        Run OAuth flow in console/headless mode.
        User must manually visit URL and paste authorization code.
        """
        if not sys.stdin.isatty():
            raise RuntimeError(
                "Headless OAuth needs an interactive terminal to paste the redirect "
                "URL into. Generate the token on a machine with a browser using "
                "setup_token.py and copy it to the configured token path."
            )

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

    # @spec INTAKE-FETCH-001, INTAKE-FETCH-002, INTAKE-FETCH-005, INTAKE-FETCH-006
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

    # @spec INTAKE-FETCH-002, INTAKE-FETCH-003, INTAKE-FETCH-004, INTAKE-FETCH-005
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

            # Get message body. Strip tracking-link paths *before* truncating so
            # they don't eat the body budget in link-heavy marketing emails.
            body = normalize_urls(self._get_message_body(message["payload"]))

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

    # @spec INTAKE-BODY-001, INTAKE-BODY-002, INTAKE-BODY-003, INTAKE-BODY-004
    def _get_message_body(self, payload: Dict) -> str:
        """
        Extract message body from payload.

        text/plain is preferred. When only text/html is available it is reduced
        to its visible text here, before the caller's length cap, so the cap
        is spent on words rather than markup.
        """
        body = ""

        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    if "data" in part["body"]:
                        body = _decode(part["body"]["data"])
                        break
                elif part["mimeType"] == "text/html" and not body:
                    if "data" in part["body"]:
                        body = strip_html(_decode(part["body"]["data"]))
        elif "body" in payload and "data" in payload["body"]:
            body = _decode(payload["body"]["data"])
            if payload.get("mimeType") == "text/html":
                body = strip_html(body)

        return body

    # @spec ACTIONS-LABEL-001, ACTIONS-LABEL-002, ACTIONS-LABEL-003
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

    # @spec ACTIONS-MSG-001, ACTIONS-MSG-002, ACTIONS-MSG-003, ACTIONS-MSG-006
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
