"""
Unit tests for EmailClassifierAgent: classifier wiring, state tracking,
unlabeled handling and dry run.
"""

import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from email_classifier_agent import EmailClassifierAgent

LABELS = ["AWS", "Github", "Shipping"]
DESCRIPTIONS = {
    "AWS": "Amazon Web Services notifications",
    "Github": "GitHub activity",
    "Shipping": "Parcel and delivery updates",
}


def _email(email_id="test_email_123", subject="Test Email"):
    return {
        "id": email_id,
        "subject": subject,
        "from": "test@example.com",
        "body": "Test body",
    }


@pytest.fixture
def temp_state_file():
    """Create a temporary state file path for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        temp_path = f.name
    os.unlink(temp_path)
    yield temp_path
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def mock_config(temp_state_file):
    """Mock config with temporary state file."""
    with patch("email_classifier_agent.config") as cfg:
        cfg.STATE_FILE = temp_state_file
        cfg.STATE_RETENTION_DAYS = 30
        cfg.GMAIL_CREDENTIALS_PATH = "credentials.json"
        cfg.GMAIL_TOKEN_PATH = "token.json"
        cfg.GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
        cfg.GMAIL_HEADLESS_MODE = True
        cfg.OPENROUTER_API_KEY = "test-key"
        cfg.LABELS = LABELS
        cfg.LABEL_DESCRIPTIONS = DESCRIPTIONS
        cfg.JEV_MODEL = "typesafe/jev-1.13"
        cfg.JEV_DECISIONS_URL = "http://litellm:4000/openrouter/alpha/decisions"
        cfg.JEV_LABEL_THRESHOLD = 0.7
        cfg.JEV_FALLBACK_CONFIDENCE = 0.5
        cfg.JEV_TIMEOUT_SECONDS = 30.0
        cfg.JEV_REVIEW_LABEL = ""
        cfg.REMOVE_FROM_INBOX = True
        cfg.DRY_RUN = False
        yield cfg


@pytest.fixture
def mock_gmail_client():
    """Mock Gmail client."""
    with patch("email_classifier_agent.GmailClient") as mock:
        client = Mock()
        client.create_label_if_not_exists = Mock(
            side_effect=lambda label: f"label_id_{label}"
        )
        client.add_labels_to_message = Mock()
        mock.return_value = client
        yield client


@pytest.fixture
def mock_classifier():
    """Mock Jev classifier."""
    with patch("email_classifier_agent.JevClassifier") as mock:
        classifier = Mock()
        classifier.classify_email = Mock(return_value=["AWS", "Github"])
        mock.return_value = classifier
        yield classifier


@pytest.mark.unit
class TestEmailClassifierAgentInit:
    """Tests for classifier wiring at agent construction."""

    def test_classifier_receives_config_values(self, mock_config, mock_gmail_client):
        with patch("email_classifier_agent.JevClassifier") as mock_cls:
            EmailClassifierAgent()

        mock_cls.assert_called_once_with(
            api_key="test-key",
            labels=LABELS,
            label_descriptions=DESCRIPTIONS,
            model="typesafe/jev-1.13",
            decisions_url="http://litellm:4000/openrouter/alpha/decisions",
            label_threshold=0.7,
            fallback_confidence=0.5,
            timeout_seconds=30.0,
        )

    def test_creates_configured_labels(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        assert agent.label_id_map == {label: f"label_id_{label}" for label in LABELS}
        assert agent.review_label_id is None

    def test_review_label_created_when_configured(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.JEV_REVIEW_LABEL = "Review"
        agent = EmailClassifierAgent()
        mock_gmail_client.create_label_if_not_exists.assert_any_call("Review")
        assert agent.review_label_id == "label_id_Review"


@pytest.mark.unit
class TestProcessEmail:
    def test_applies_labels_archives_and_saves_state(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()

        assert agent.process_email(_email()) is True

        mock_classifier.classify_email.assert_called_once_with(_email())
        mock_gmail_client.add_labels_to_message.assert_called_once_with(
            "test_email_123",
            ["label_id_AWS", "label_id_Github"],
            remove_from_inbox=True,
        )
        assert "test_email_123" in agent.processed_emails
        with open(mock_config.STATE_FILE) as f:
            state = json.load(f)
        assert "test_email_123" in state["processed_emails"]
        assert "pending_retries" not in state

    def test_keeps_in_inbox_when_remove_disabled(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.REMOVE_FROM_INBOX = False
        agent = EmailClassifierAgent()
        agent.process_email(_email())
        kwargs = mock_gmail_client.add_labels_to_message.call_args.kwargs
        assert kwargs["remove_from_inbox"] is False

    def test_skips_already_processed(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        agent.process_email(_email())
        assert agent.process_email(_email()) is True
        assert mock_classifier.classify_email.call_count == 1

    def test_missing_id(self, mock_config, mock_gmail_client, mock_classifier):
        agent = EmailClassifierAgent()
        assert agent.process_email({"subject": "x"}) is False
        mock_classifier.classify_email.assert_not_called()

    def test_no_labels_marks_processed_without_touching_gmail(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.WARNING)
        mock_classifier.classify_email.return_value = []
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("e456")) is False

        assert "e456" in agent.processed_emails
        mock_gmail_client.add_labels_to_message.assert_not_called()
        assert "No labels predicted" in caplog.text
        # Not re-sent on the next poll
        assert agent.process_email(_email("e456")) is True
        assert mock_classifier.classify_email.call_count == 1

    def test_no_labels_applies_review_label_in_inbox(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.JEV_REVIEW_LABEL = "Review"
        mock_classifier.classify_email.return_value = []
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("e456")) is False

        mock_gmail_client.add_labels_to_message.assert_called_once_with(
            "e456", ["label_id_Review"], remove_from_inbox=False
        )
        assert "e456" in agent.processed_emails

    def test_unknown_label_from_classifier_is_not_applied(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_classifier.classify_email.return_value = ["Nope"]
        agent = EmailClassifierAgent()

        assert agent.process_email(_email()) is True

        mock_gmail_client.add_labels_to_message.assert_not_called()
        assert "test_email_123" in agent.processed_emails

    def test_exception_does_not_save_state(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_classifier.classify_email.side_effect = Exception("boom")
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("err")) is False
        assert "err" not in agent.processed_emails


@pytest.mark.unit
class TestDryRun:
    def test_dry_run_never_writes_to_gmail_or_disk(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.DRY_RUN = True
        mock_config.JEV_REVIEW_LABEL = "Review"
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("dry1")) is True
        mock_classifier.classify_email.return_value = []
        assert agent.process_email(_email("dry2")) is False

        mock_gmail_client.create_label_if_not_exists.assert_not_called()
        mock_gmail_client.add_labels_to_message.assert_not_called()
        assert not os.path.exists(mock_config.STATE_FILE)
        assert "DRY RUN: would apply ['AWS', 'Github']" in caplog.text
        assert "DRY RUN: would apply no labels" in caplog.text

    def test_dry_run_remembers_emails_in_memory_only(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.DRY_RUN = True
        agent = EmailClassifierAgent()
        agent.process_email(_email("dry1"))
        agent.process_email(_email("dry1"))
        assert mock_classifier.classify_email.call_count == 1

        # A fresh agent starts without it: nothing was persisted
        assert "dry1" not in EmailClassifierAgent().processed_emails


@pytest.mark.unit
class TestStateTracking:
    """Tests for state persistence and retention."""

    def test_load_state_no_file(self, mock_config, mock_gmail_client, mock_classifier):
        agent = EmailClassifierAgent()
        assert agent.processed_emails == {}
        assert agent.state_file == mock_config.STATE_FILE

    def test_load_state_corrupted_file(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        with open(mock_config.STATE_FILE, "w") as f:
            f.write("invalid json{{{")
        assert EmailClassifierAgent().processed_emails == {}

    def test_legacy_list_format_and_pending_retries_are_migrated(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        with open(mock_config.STATE_FILE, "w") as f:
            json.dump(
                {
                    "processed_emails": ["email1", "email2"],
                    "pending_retries": {"old": {"attempts": 1}},
                },
                f,
            )

        agent = EmailClassifierAgent()

        assert set(agent.processed_emails) == {"email1", "email2"}
        for ts in agent.processed_emails.values():
            datetime.fromisoformat(ts)
        agent._save_state()
        with open(mock_config.STATE_FILE) as f:
            state = json.load(f)
        assert "pending_retries" not in state
        assert isinstance(state["processed_emails"], dict)

    def test_save_state_creates_directory(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_config.STATE_FILE = os.path.join(tmpdir, "subdir", "state.json")
            agent = EmailClassifierAgent()
            agent.processed_emails["email1"] = datetime.now(UTC).isoformat()
            agent._save_state()
            with open(mock_config.STATE_FILE) as f:
                assert "email1" in json.load(f)["processed_emails"]

    def test_state_persists_across_restarts(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        EmailClassifierAgent().process_email(_email("e789"))

        agent2 = EmailClassifierAgent()
        assert "e789" in agent2.processed_emails
        assert agent2.process_email(_email("e789")) is True
        assert mock_classifier.classify_email.call_count == 1

    def test_retention_removes_old_entries(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.STATE_RETENTION_DAYS = 7
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        with open(mock_config.STATE_FILE, "w") as f:
            json.dump({"processed_emails": {"old": old, "recent": recent}}, f)

        agent = EmailClassifierAgent()

        assert set(agent.processed_emails) == {"recent"}

    def test_retention_disabled_keeps_everything(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.STATE_RETENTION_DAYS = 0
        ancient = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        with open(mock_config.STATE_FILE, "w") as f:
            json.dump({"processed_emails": {"a": ancient, "b": ancient}}, f)

        assert set(EmailClassifierAgent().processed_emails) == {"a", "b"}

    def test_periodic_cleanup(self, mock_config, mock_gmail_client, mock_classifier):
        mock_config.STATE_RETENTION_DAYS = 5
        agent = EmailClassifierAgent()
        agent.processed_emails["old"] = (
            datetime.now(UTC) - timedelta(days=10)
        ).isoformat()
        agent.processed_emails["new"] = datetime.now(UTC).isoformat()

        agent.processed_emails = agent._cleanup_old_state(agent.processed_emails)

        assert set(agent.processed_emails) == {"new"}

    def test_processed_timestamp_is_recent(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        agent.process_email(_email("ts"))
        stamp = datetime.fromisoformat(agent.processed_emails["ts"])
        assert (datetime.now(UTC) - stamp).total_seconds() < 60


@pytest.mark.unit
class TestRunContinuous:
    def test_one_poll_processes_then_stops_on_interrupt(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.get_unread_messages.return_value = [_email("a"), _email("b")]
        agent = EmailClassifierAgent()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        assert set(agent.processed_emails) == {"a", "b"}
        mock_gmail_client.get_unread_messages.assert_called_once_with(max_results=10)

    def test_loop_survives_gmail_errors(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.get_unread_messages.side_effect = [
            RuntimeError("gmail down"),
            [_email("a")],
        ]
        agent = EmailClassifierAgent()

        # First sleep follows the logged error; the second ends the loop
        with patch(
            "email_classifier_agent.time.sleep", side_effect=[None, KeyboardInterrupt]
        ):
            agent.run_continuous()

        assert set(agent.processed_emails) == {"a"}
        assert mock_gmail_client.get_unread_messages.call_count == 2
