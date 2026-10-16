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
from mail_text import strip_html

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

    # @spec INTAKE-FETCH-001, INTAKE-FETCH-006
    def list_unread_ids(self, max_results: int = 10) -> List[str]:
        """
        Ids of unread inbox messages, newest first, up to max_results.

        A Gmail API error propagates: the caller's poll cycle should count as
        failed rather than look like an empty inbox.
        """
        results = (
            self.service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results)
            .execute()
        )
        ids = [msg["id"] for msg in results.get("messages", [])]
        if ids:
            logger.info(f"Found {len(ids)} unread messages")
        else:
            logger.info("No unread messages found")
        return ids

    # @spec INTAKE-FETCH-007
    def get_unread_messages(self, max_results: int = 10) -> List[Dict]:
        """List unread ids and fetch each; messages whose fetch failed are omitted."""
        messages = []
        for msg_id in self.list_unread_ids(max_results):
            message = self.get_message(msg_id)
            if message:
                messages.append(message)
        return messages

    # @spec INTAKE-FETCH-002, INTAKE-FETCH-003, INTAKE-FETCH-004, INTAKE-FETCH-005
    def get_message(self, msg_id: str) -> Optional[Dict]:
        """
        Fetch one message in full and return its record, or None on a Gmail
        API error. The body is extracted text only: URL reduction and the
        length cap are the classifier's job (jev_classifier.build_state).
        """
        try:
            message = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except HttpError as error:
            logger.error(f"Error getting message details for {msg_id}: {error}")
            return None

        headers = message["payload"].get("headers", [])

        def header(name: str, default: str) -> str:
            return next(
                (h["value"] for h in headers if h["name"].lower() == name), default
            )

        return {
            "id": msg_id,
            "subject": header("subject", "No Subject"),
            "from": header("from", "Unknown"),
            "date": header("date", "Unknown"),
            "body": self._get_message_body(message["payload"]),
            "snippet": message.get("snippet", ""),
        }

    @staticmethod
    def _walk_parts(payload: Dict):
        """Depth-first over a payload's parts, descending into nested multiparts."""
        for part in payload.get("parts", []):
            yield part
            yield from GmailClient._walk_parts(part)

    # @spec INTAKE-BODY-001, INTAKE-BODY-002, INTAKE-BODY-003, INTAKE-BODY-004
    def _get_message_body(self, payload: Dict) -> str:
        """
        Extract message body from payload.

        text/plain is preferred at any depth (attachments wrap the text in a
        nested multipart/alternative). When only text/html is available it is
        reduced to its visible text, since the markup is MIME detail rather
        than message content.
        """
        if "parts" in payload:
            html = ""
            for part in self._walk_parts(payload):
                data = part.get("body", {}).get("data")
                if not data:
                    continue
                if part.get("mimeType") == "text/plain":
                    return _decode(data)
                if part.get("mimeType") == "text/html" and not html:
                    html = strip_html(_decode(data))
            return html

        if "body" in payload and "data" in payload["body"]:
            body = _decode(payload["body"]["data"])
            if payload.get("mimeType") == "text/html":
                body = strip_html(body)
            return body

        return ""

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

            wanted = label_name.casefold()
            for label in labels:
                if label["name"].casefold() == wanted:
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
