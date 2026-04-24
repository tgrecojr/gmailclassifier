"""
Unit tests for gmail_client.py
"""

import base64
import pickle
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from googleapiclient.errors import HttpError

from gmail_client import GmailClient


def _make_http_error(status: int = 500, reason: str = "error") -> HttpError:
    resp = Mock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=b"")


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


@pytest.fixture
def client():
    """A GmailClient with _authenticate bypassed and a mocked service attached."""
    with patch.object(GmailClient, "_authenticate"):
        c = GmailClient("creds.json", "token.json", ["scope"])
    c.service = MagicMock()
    return c


@pytest.mark.unit
class TestAuthenticate:
    """Test OAuth/token handling in _authenticate."""

    def test_uses_existing_valid_token(self):
        creds = MagicMock()
        creds.valid = True
        creds.expired = False

        with patch("gmail_client.os.path.exists", return_value=True), patch(
            "gmail_client.open", mock_open(read_data=b"irrelevant")
        ), patch("gmail_client.pickle.load", return_value=creds), patch(
            "gmail_client.build"
        ) as mock_build:
            mock_build.return_value = "gmail-service"
            c = GmailClient("creds.json", "token.json", ["scope"])

        assert c.service == "gmail-service"
        mock_build.assert_called_once_with("gmail", "v1", credentials=creds)

    def test_refreshes_expired_token(self):
        creds = MagicMock()
        creds.valid = False
        creds.expired = True
        creds.refresh_token = "refresh"

        with patch("gmail_client.os.path.exists", return_value=True), patch(
            "gmail_client.open", mock_open(read_data=b"irrelevant")
        ), patch("gmail_client.pickle.load", return_value=creds), patch(
            "gmail_client.pickle.dump"
        ), patch(
            "gmail_client.build"
        ):
            GmailClient("creds.json", "token.json", ["scope"])

        creds.refresh.assert_called_once()

    def test_runs_oauth_flow_when_no_token(self):
        new_creds = MagicMock()

        with patch("gmail_client.os.path.exists", return_value=False), patch(
            "gmail_client.InstalledAppFlow"
        ) as mock_flow_cls, patch("gmail_client.open", mock_open()), patch(
            "gmail_client.pickle.dump"
        ) as mock_dump, patch(
            "gmail_client.build"
        ):
            mock_flow = MagicMock()
            mock_flow.run_local_server.return_value = new_creds
            mock_flow_cls.from_client_secrets_file.return_value = mock_flow

            GmailClient("creds.json", "token.json", ["scope"], headless=False)

        mock_flow.run_local_server.assert_called_once_with(port=8080)
        # Credentials get persisted
        assert mock_dump.called

    def test_headless_mode_uses_console_flow(self):
        new_creds = MagicMock()

        with patch("gmail_client.os.path.exists", return_value=False), patch(
            "gmail_client.InstalledAppFlow"
        ) as mock_flow_cls, patch("gmail_client.open", mock_open()), patch(
            "gmail_client.pickle.dump"
        ), patch(
            "gmail_client.build"
        ), patch.object(
            GmailClient, "_run_console_flow", return_value=new_creds
        ) as mock_console:
            mock_flow_cls.from_client_secrets_file.return_value = MagicMock()
            GmailClient("creds.json", "token.json", ["scope"], headless=True)

        mock_console.assert_called_once()


@pytest.mark.unit
class TestGetUnreadMessages:
    def test_returns_detailed_messages(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}]
        }
        with patch.object(
            GmailClient,
            "_get_message_details",
            side_effect=[{"id": "m1"}, {"id": "m2"}],
        ):
            result = client.get_unread_messages(max_results=5)

        assert [m["id"] for m in result] == ["m1", "m2"]

    def test_returns_empty_list_when_no_messages(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.return_value = (
            {}
        )
        assert client.get_unread_messages() == []

    def test_skips_messages_whose_details_fail(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}]
        }
        with patch.object(
            GmailClient, "_get_message_details", side_effect=[{"id": "m1"}, None]
        ):
            result = client.get_unread_messages()

        assert [m["id"] for m in result] == ["m1"]

    def test_http_error_returns_empty_list(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            _make_http_error()
        )
        assert client.get_unread_messages() == []


@pytest.mark.unit
class TestGetMessageDetails:
    def _payload_with_headers(self, headers, body_text="hello"):
        return {
            "payload": {
                "headers": headers,
                "body": {"data": _b64(body_text)},
            },
            "snippet": "snip",
        }

    def test_extracts_headers_and_body(self, client):
        message = self._payload_with_headers(
            [
                {"name": "Subject", "value": "Hi"},
                {"name": "From", "value": "a@b.com"},
                {"name": "Date", "value": "2026-04-24"},
            ]
        )
        client.service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            message
        )

        result = client._get_message_details("m1")

        assert result["id"] == "m1"
        assert result["subject"] == "Hi"
        assert result["from"] == "a@b.com"
        assert result["date"] == "2026-04-24"
        assert result["body"] == "hello"
        assert result["snippet"] == "snip"

    def test_fills_defaults_when_headers_missing(self, client):
        client.service.users.return_value.messages.return_value.get.return_value.execute.return_value = self._payload_with_headers(
            []
        )
        result = client._get_message_details("m1")

        assert result["subject"] == "No Subject"
        assert result["from"] == "Unknown"
        assert result["date"] == "Unknown"

    def test_header_matching_is_case_insensitive(self, client):
        client.service.users.return_value.messages.return_value.get.return_value.execute.return_value = self._payload_with_headers(
            [{"name": "subject", "value": "Lower"}]
        )
        assert client._get_message_details("m1")["subject"] == "Lower"

    def test_body_truncated_to_5000_chars(self, client):
        long_text = "x" * 6000
        client.service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
            "payload": {"headers": [], "body": {"data": _b64(long_text)}},
            "snippet": "",
        }
        assert len(client._get_message_details("m1")["body"]) == 5000

    def test_http_error_returns_none(self, client):
        client.service.users.return_value.messages.return_value.get.return_value.execute.side_effect = (
            _make_http_error()
        )
        assert client._get_message_details("m1") is None


@pytest.mark.unit
class TestGetMessageBody:
    def test_prefers_text_plain_part(self, client):
        payload = {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("plain-body")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
            ]
        }
        assert client._get_message_body(payload) == "plain-body"

    def test_falls_back_to_text_html_when_no_plain(self, client):
        payload = {
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
            ]
        }
        assert client._get_message_body(payload) == "<p>html</p>"

    def test_uses_direct_body_when_no_parts(self, client):
        payload = {"body": {"data": _b64("direct")}}
        assert client._get_message_body(payload) == "direct"

    def test_returns_empty_when_no_body(self, client):
        assert client._get_message_body({}) == ""

    def test_returns_empty_when_part_has_no_data(self, client):
        payload = {"parts": [{"mimeType": "text/plain", "body": {}}]}
        assert client._get_message_body(payload) == ""


@pytest.mark.unit
class TestCreateLabelIfNotExists:
    def test_returns_existing_label_id(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": [{"id": "L1", "name": "Billing"}]
        }
        assert client.create_label_if_not_exists("Billing") == "L1"
        # Should not attempt to create when already present
        client.service.users.return_value.labels.return_value.create.assert_not_called()

    def test_creates_new_label_when_missing(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": []
        }
        client.service.users.return_value.labels.return_value.create.return_value.execute.return_value = {
            "id": "L99",
            "name": "New",
        }

        assert client.create_label_if_not_exists("New") == "L99"

    def test_http_error_returns_none(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.side_effect = (
            _make_http_error()
        )
        assert client.create_label_if_not_exists("Anything") is None


@pytest.mark.unit
class TestAddLabelsToMessage:
    def test_adds_labels_without_archiving(self, client):
        client.add_labels_to_message("m1", ["L1", "L2"])

        _, kwargs = (
            client.service.users.return_value.messages.return_value.modify.call_args
        )
        assert kwargs["id"] == "m1"
        assert kwargs["body"] == {"addLabelIds": ["L1", "L2"]}

    def test_adds_labels_and_archives(self, client):
        client.add_labels_to_message("m1", ["L1"], remove_from_inbox=True)

        _, kwargs = (
            client.service.users.return_value.messages.return_value.modify.call_args
        )
        assert kwargs["body"]["addLabelIds"] == ["L1"]
        assert kwargs["body"]["removeLabelIds"] == ["INBOX"]

    def test_http_error_does_not_raise(self, client):
        client.service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            _make_http_error()
        )
        # Must not raise
        client.add_labels_to_message("m1", ["L1"])


@pytest.mark.unit
class TestMarkAsRead:
    def test_removes_unread_label(self, client):
        client.mark_as_read("m1")
        _, kwargs = (
            client.service.users.return_value.messages.return_value.modify.call_args
        )
        assert kwargs["body"] == {"removeLabelIds": ["UNREAD"]}

    def test_http_error_does_not_raise(self, client):
        client.service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            _make_http_error()
        )
        client.mark_as_read("m1")


@pytest.mark.unit
class TestArchiveMessage:
    def test_removes_inbox_label(self, client):
        client.archive_message("m1")
        _, kwargs = (
            client.service.users.return_value.messages.return_value.modify.call_args
        )
        assert kwargs["body"] == {"removeLabelIds": ["INBOX"]}

    def test_http_error_does_not_raise(self, client):
        client.service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            _make_http_error()
        )
        client.archive_message("m1")
