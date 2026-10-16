"""
Unit tests for gmail_client.py
"""

import base64
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest
from googleapiclient.errors import HttpError

from gmail_client import GmailClient


def _make_http_error(status: int = 500, reason: str = "error") -> HttpError:
    resp = Mock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=b"")


def _get_call(client):
    """The mocked messages().get().execute for a test client."""
    return (
        client.service.users.return_value.messages.return_value.get.return_value.execute
    )


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
    """Token handling in _authenticate: JSON token, legacy pickle, refresh, OAuth flows."""

    # @spec INTAKE-AUTH-001
    def test_uses_existing_valid_json_token(self):
        creds = MagicMock()
        creds.valid = True
        creds.expired = False

        with (
            patch("gmail_client.os.path.exists", return_value=True),
            patch(
                "gmail_client.Credentials.from_authorized_user_file", return_value=creds
            ) as mock_load,
            patch("gmail_client.open", mock_open()) as mock_file,
            patch("gmail_client.build") as mock_build,
        ):
            mock_build.return_value = "gmail-service"
            c = GmailClient("creds.json", "token.json", ["scope"])

        mock_load.assert_called_once_with("token.json", ["scope"])
        assert c.service == "gmail-service"
        mock_build.assert_called_once_with("gmail", "v1", credentials=creds)
        mock_file.assert_not_called()  # a valid JSON token is not rewritten

    # @spec INTAKE-AUTH-001, INTAKE-AUTH-005
    def test_legacy_pickle_token_is_read_and_rewritten_as_json(self):
        creds = MagicMock()
        creds.valid = True
        creds.expired = False
        creds.to_json.return_value = '{"token": "t"}'

        with (
            patch("gmail_client.os.path.exists", return_value=True),
            patch(
                "gmail_client.Credentials.from_authorized_user_file",
                side_effect=ValueError("not json"),
            ),
            patch("gmail_client.open", mock_open(read_data=b"\x80pickle")) as mock_file,
            patch("gmail_client.pickle.load", return_value=creds),
            patch("gmail_client.build"),
        ):
            GmailClient("creds.json", "token.json", ["scope"])

        mock_file().write.assert_called_once_with('{"token": "t"}')

    # @spec INTAKE-AUTH-002, INTAKE-AUTH-005
    def test_refreshes_expired_token_and_saves_json(self):
        creds = MagicMock()
        creds.valid = False
        creds.expired = True
        creds.refresh_token = "refresh"
        creds.to_json.return_value = '{"token": "fresh"}'

        with (
            patch("gmail_client.os.path.exists", return_value=True),
            patch(
                "gmail_client.Credentials.from_authorized_user_file", return_value=creds
            ),
            patch("gmail_client.open", mock_open()) as mock_file,
            patch("gmail_client.build"),
        ):
            GmailClient("creds.json", "token.json", ["scope"])

        creds.refresh.assert_called_once()
        mock_file.assert_called_once_with("token.json", "w", encoding="utf-8")
        mock_file().write.assert_called_once_with('{"token": "fresh"}')

    # @spec INTAKE-AUTH-003, INTAKE-AUTH-005
    def test_runs_oauth_flow_when_no_token(self):
        new_creds = MagicMock()
        new_creds.to_json.return_value = '{"token": "new"}'

        with (
            patch("gmail_client.os.path.exists", return_value=False),
            patch("gmail_client.InstalledAppFlow") as mock_flow_cls,
            patch("gmail_client.open", mock_open()) as mock_file,
            patch("gmail_client.build"),
        ):
            mock_flow = MagicMock()
            mock_flow.run_local_server.return_value = new_creds
            mock_flow_cls.from_client_secrets_file.return_value = mock_flow

            GmailClient("creds.json", "token.json", ["scope"], headless=False)

        mock_flow.run_local_server.assert_called_once_with(port=8080)
        mock_file().write.assert_called_once_with('{"token": "new"}')

    # @spec INTAKE-AUTH-004
    def test_headless_mode_uses_console_flow(self):
        new_creds = MagicMock()

        with (
            patch("gmail_client.os.path.exists", return_value=False),
            patch("gmail_client.InstalledAppFlow") as mock_flow_cls,
            patch("gmail_client.open", mock_open()),
            patch("gmail_client.build"),
            patch.object(
                GmailClient, "_run_console_flow", return_value=new_creds
            ) as mock_console,
        ):
            mock_flow_cls.from_client_secrets_file.return_value = MagicMock()
            GmailClient("creds.json", "token.json", ["scope"], headless=True)

        mock_console.assert_called_once()

    # @spec INTAKE-AUTH-008
    def test_console_flow_without_a_terminal_fails_and_points_at_setup_token(
        self, client
    ):
        flow = MagicMock()
        with patch("gmail_client.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            with pytest.raises(RuntimeError, match="setup_token.py"):
                client._run_console_flow(flow)

        flow.authorization_url.assert_not_called()


@pytest.mark.unit
class TestListUnreadIds:
    # @spec INTAKE-FETCH-001
    def test_returns_ids_newest_first_up_to_max(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}]
        }
        assert client.list_unread_ids(max_results=5) == ["m1", "m2"]
        _, kwargs = (
            client.service.users.return_value.messages.return_value.list.call_args
        )
        assert kwargs["labelIds"] == ["INBOX", "UNREAD"]
        assert kwargs["maxResults"] == 5

    # @spec INTAKE-FETCH-001
    def test_returns_empty_list_when_no_messages(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.return_value = (
            {}
        )
        assert client.list_unread_ids() == []

    # @spec INTAKE-FETCH-006
    def test_http_error_propagates(self, client):
        client.service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            _make_http_error()
        )
        with pytest.raises(HttpError):
            client.list_unread_ids()


@pytest.mark.unit
class TestGetUnreadMessages:
    # @spec INTAKE-FETCH-007
    def test_lists_then_fetches_each_and_skips_failures(self, client):
        with (
            patch.object(GmailClient, "list_unread_ids", return_value=["m1", "m2"]),
            patch.object(GmailClient, "get_message", side_effect=[{"id": "m1"}, None]),
        ):
            result = client.get_unread_messages(max_results=2)

        assert [m["id"] for m in result] == ["m1"]


@pytest.mark.unit
class TestGetMessage:
    def _payload_with_headers(self, headers, body_text="hello"):
        return {
            "payload": {
                "headers": headers,
                "body": {"data": _b64(body_text)},
            },
            "snippet": "snip",
        }

    # @spec INTAKE-FETCH-002
    def test_extracts_headers_and_body(self, client):
        message = self._payload_with_headers(
            [
                {"name": "Subject", "value": "Hi"},
                {"name": "From", "value": "a@b.com"},
                {"name": "Date", "value": "2026-04-24"},
            ]
        )
        _get_call(client).return_value = message

        result = client.get_message("m1")

        assert result["id"] == "m1"
        assert result["subject"] == "Hi"
        assert result["from"] == "a@b.com"
        assert result["date"] == "2026-04-24"
        assert result["body"] == "hello"
        assert result["snippet"] == "snip"
        _, kwargs = (
            client.service.users.return_value.messages.return_value.get.call_args
        )
        assert kwargs["format"] == "full"

    # @spec INTAKE-FETCH-003
    def test_fills_defaults_when_headers_missing(self, client):
        _get_call(client).return_value = self._payload_with_headers([])
        result = client.get_message("m1")

        assert result["subject"] == "No Subject"
        assert result["from"] == "Unknown"
        assert result["date"] == "Unknown"

    # @spec INTAKE-FETCH-003
    def test_header_matching_is_case_insensitive(self, client):
        _get_call(client).return_value = self._payload_with_headers(
            [{"name": "subject", "value": "Lower"}]
        )
        assert client.get_message("m1")["subject"] == "Lower"

    # @spec INTAKE-FETCH-004
    def test_body_is_returned_untruncated_and_unrewritten(self, client):
        """Reduction and capping are the classifier's job, not the Gmail client's."""
        body_text = "Visit https://click.example.com/ls/click?upn=" + "A" * 6000
        _get_call(client).return_value = {
            "payload": {"headers": [], "body": {"data": _b64(body_text)}},
            "snippet": "",
        }
        assert client.get_message("m1")["body"] == body_text

    # @spec INTAKE-FETCH-005
    def test_http_error_returns_none(self, client):
        _get_call(client).side_effect = _make_http_error()
        assert client.get_message("m1") is None


@pytest.mark.unit
class TestGetMessageBody:
    # @spec INTAKE-BODY-001
    def test_prefers_text_plain_part(self, client):
        payload = {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("plain-body")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
            ]
        }
        assert client._get_message_body(payload) == "plain-body"

    # @spec INTAKE-BODY-002
    def test_falls_back_to_text_html_when_no_plain_and_strips_markup(self, client):
        payload = {
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<style>p{}</style><p>Order &amp; ship</p>")},
                },
            ]
        }
        assert client._get_message_body(payload) == "Order & ship"

    # @spec INTAKE-BODY-003
    def test_html_only_direct_body_is_stripped(self, client):
        payload = {"mimeType": "text/html", "body": {"data": _b64("<div>Hi</div>")}}
        assert client._get_message_body(payload) == "Hi"

    # @spec INTAKE-BODY-003, INTAKE-BODY-005
    def test_uses_direct_body_when_no_parts(self, client):
        payload = {"body": {"data": _b64("direct")}}
        assert client._get_message_body(payload) == "direct"

    # @spec INTAKE-BODY-004
    def test_returns_empty_when_no_body(self, client):
        assert client._get_message_body({}) == ""

    # @spec INTAKE-BODY-004
    def test_returns_empty_when_part_has_no_data(self, client):
        payload = {"parts": [{"mimeType": "text/plain", "body": {}}]}
        assert client._get_message_body(payload) == ""

    # @spec INTAKE-BODY-001
    def test_descends_into_nested_multipart_for_text_plain(self, client):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64("nested plain")},
                        },
                        {
                            "mimeType": "text/html",
                            "body": {"data": _b64("<p>nested html</p>")},
                        },
                    ],
                },
                {"mimeType": "application/pdf", "body": {"attachmentId": "x"}},
            ],
        }
        assert client._get_message_body(payload) == "nested plain"

    # @spec INTAKE-BODY-002
    def test_descends_into_nested_multipart_for_html_when_no_plain(self, client):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/related",
                    "body": {},
                    "parts": [
                        {
                            "mimeType": "text/html",
                            "body": {"data": _b64("<div>Deep &amp; html</div>")},
                        },
                        {"mimeType": "image/png", "body": {"attachmentId": "y"}},
                    ],
                }
            ],
        }
        assert client._get_message_body(payload) == "Deep & html"

    # @spec INTAKE-BODY-001
    def test_prefers_any_text_plain_over_shallower_html(self, client):
        payload = {
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>shallow html</p>")},
                },
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("deep plain")}}
                    ],
                },
            ]
        }
        assert client._get_message_body(payload) == "deep plain"


@pytest.mark.unit
class TestCreateLabelIfNotExists:
    # @spec ACTIONS-LABEL-001
    def test_returns_existing_label_id(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": [{"id": "L1", "name": "Billing"}]
        }
        assert client.create_label_if_not_exists("Billing") == "L1"
        # Should not attempt to create when already present
        client.service.users.return_value.labels.return_value.create.assert_not_called()

    # @spec ACTIONS-LABEL-001
    def test_matches_existing_label_case_insensitively(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": [{"id": "L1", "name": "Finance"}]
        }
        assert client.create_label_if_not_exists("finance") == "L1"
        client.service.users.return_value.labels.return_value.create.assert_not_called()

    # @spec ACTIONS-LABEL-002
    def test_creates_new_label_when_missing(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
            "labels": []
        }
        client.service.users.return_value.labels.return_value.create.return_value.execute.return_value = {
            "id": "L99",
            "name": "New",
        }

        assert client.create_label_if_not_exists("New") == "L99"

    # @spec ACTIONS-LABEL-003
    def test_http_error_returns_none(self, client):
        client.service.users.return_value.labels.return_value.list.return_value.execute.side_effect = (
            _make_http_error()
        )
        assert client.create_label_if_not_exists("Anything") is None


@pytest.mark.unit
class TestAddLabelsToMessage:
    # @spec ACTIONS-MSG-001, ACTIONS-MSG-006
    def test_adds_labels_without_archiving(self, client):
        client.add_labels_to_message("m1", ["L1", "L2"])

        _, kwargs = (
            client.service.users.return_value.messages.return_value.modify.call_args
        )
        assert kwargs["id"] == "m1"
        assert kwargs["body"] == {"addLabelIds": ["L1", "L2"]}

    # @spec ACTIONS-MSG-002
    def test_adds_labels_and_archives(self, client):
        client.add_labels_to_message("m1", ["L1"], remove_from_inbox=True)

        _, kwargs = (
            client.service.users.return_value.messages.return_value.modify.call_args
        )
        assert kwargs["body"]["addLabelIds"] == ["L1"]
        assert kwargs["body"]["removeLabelIds"] == ["INBOX"]

    # @spec ACTIONS-MSG-003
    def test_http_error_does_not_raise(self, client):
        client.service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = (
            _make_http_error()
        )
        # Must not raise
        client.add_labels_to_message("m1", ["L1"])
