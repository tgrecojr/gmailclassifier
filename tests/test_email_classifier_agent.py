"""
Unit tests for EmailClassifierAgent: classifier wiring, state tracking,
unlabeled handling and dry run.
"""

import json
import logging
import os
import signal
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
        # ids-first fetch: the loop lists ids, then fetches each new one
        client.list_unread_ids = Mock(return_value=[])
        client.get_message = Mock(side_effect=lambda msg_id: _email(msg_id))
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

    # @spec AGENT-INIT-001
    def test_classifier_is_built_before_gmail_client(self, mock_config):
        with (
            patch(
                "email_classifier_agent.JevClassifier", side_effect=ValueError("bad")
            ),
            patch("email_classifier_agent.GmailClient") as mock_gmail,
        ):
            with pytest.raises(ValueError):
                EmailClassifierAgent()
        mock_gmail.assert_not_called()

    # @spec AGENT-INIT-001
    def test_gmail_client_receives_config_values(self, mock_config, mock_classifier):
        with patch("email_classifier_agent.GmailClient") as mock_cls:
            EmailClassifierAgent()

        mock_cls.assert_called_once_with(
            credentials_path="credentials.json",
            token_path="token.json",
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
            headless=True,
        )

    # @spec AGENT-INIT-002
    def test_classifier_receives_config_values(self, mock_config, mock_gmail_client):
        with patch("email_classifier_agent.JevClassifier") as mock_cls:
            EmailClassifierAgent()

        mock_cls.assert_called_once_with(
            api_key="test-key",
            labels=LABELS,
            label_descriptions=DESCRIPTIONS,
            model="typesafe/jev-1.13",
            label_threshold=0.7,
            fallback_confidence=0.5,
            timeout_seconds=30.0,
        )

    # @spec AGENT-INIT-003
    def test_creates_configured_labels(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        assert agent.label_id_map == {label: f"label_id_{label}" for label in LABELS}
        assert agent.review_label_id is None

    # @spec AGENT-INIT-004
    def test_review_label_created_when_configured(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.JEV_REVIEW_LABEL = "Review"
        agent = EmailClassifierAgent()
        mock_gmail_client.create_label_if_not_exists.assert_any_call("Review")
        assert agent.review_label_id == "label_id_Review"


@pytest.mark.unit
class TestProcessEmail:
    # @spec AGENT-PROC-003, AGENT-PROC-007, AGENT-PROC-009, STATE-FILE-001
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

    # @spec AGENT-PROC-007
    def test_keeps_in_inbox_when_remove_disabled(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.REMOVE_FROM_INBOX = False
        agent = EmailClassifierAgent()
        agent.process_email(_email())
        kwargs = mock_gmail_client.add_labels_to_message.call_args.kwargs
        assert kwargs["remove_from_inbox"] is False

    # @spec AGENT-PROC-002
    def test_skips_already_processed(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        agent.process_email(_email())
        assert agent.process_email(_email()) is True
        assert mock_classifier.classify_email.call_count == 1

    # @spec AGENT-PROC-001
    def test_missing_id(self, mock_config, mock_gmail_client, mock_classifier):
        agent = EmailClassifierAgent()
        assert agent.process_email({"subject": "x"}) is False
        mock_classifier.classify_email.assert_not_called()

    # @spec AGENT-PROC-006
    def test_no_labels_marks_processed_without_touching_gmail(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.WARNING)
        mock_classifier.classify_email.return_value = []
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("e456")) is True  # handled, just unlabeled

        assert "e456" in agent.processed_emails
        mock_gmail_client.add_labels_to_message.assert_not_called()
        assert "No labels predicted" in caplog.text
        # Not re-sent on the next poll
        assert agent.process_email(_email("e456")) is True
        assert mock_classifier.classify_email.call_count == 1

    # @spec AGENT-PROC-005
    def test_no_labels_applies_review_label_in_inbox(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.JEV_REVIEW_LABEL = "Review"
        mock_classifier.classify_email.return_value = []
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("e456")) is True

        mock_gmail_client.add_labels_to_message.assert_called_once_with(
            "e456", ["label_id_Review"], remove_from_inbox=False
        )
        assert "e456" in agent.processed_emails

    # @spec AGENT-PROC-008, AGENT-PROC-009
    def test_unknown_label_from_classifier_is_not_applied(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_classifier.classify_email.return_value = ["Nope"]
        agent = EmailClassifierAgent()

        assert agent.process_email(_email()) is True

        mock_gmail_client.add_labels_to_message.assert_not_called()
        assert "test_email_123" in agent.processed_emails

    # @spec AGENT-PROC-010
    def test_exception_does_not_save_state(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_classifier.classify_email.side_effect = Exception("boom")
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("err")) is False
        assert "err" not in agent.processed_emails


@pytest.mark.unit
class TestDryRun:
    # @spec AGENT-PROC-004, AGENT-INIT-005, STATE-FILE-008
    def test_dry_run_never_writes_to_gmail_or_disk(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.DRY_RUN = True
        mock_config.JEV_REVIEW_LABEL = "Review"
        agent = EmailClassifierAgent()

        assert agent.process_email(_email("dry1")) is True
        mock_classifier.classify_email.return_value = []
        assert agent.process_email(_email("dry2")) is True

        mock_gmail_client.create_label_if_not_exists.assert_not_called()
        mock_gmail_client.add_labels_to_message.assert_not_called()
        assert not os.path.exists(mock_config.STATE_FILE)
        assert "DRY RUN: would apply ['AWS', 'Github']" in caplog.text
        assert "DRY RUN: would apply no labels" in caplog.text

    # @spec AGENT-PROC-004
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

    # @spec STATE-FILE-002
    def test_load_state_no_file(self, mock_config, mock_gmail_client, mock_classifier):
        agent = EmailClassifierAgent()
        assert agent.processed_emails == {}
        assert agent.state_file == mock_config.STATE_FILE

    # @spec STATE-FILE-003
    def test_load_state_corrupted_file(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        with open(mock_config.STATE_FILE, "w") as f:
            f.write("invalid json{{{")
        assert EmailClassifierAgent().processed_emails == {}

    # @spec STATE-FILE-004, STATE-FILE-005
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

    # @spec STATE-FILE-006
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

    # @spec STATE-FILE-001, STATE-MARK-002
    def test_state_persists_across_restarts(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        EmailClassifierAgent().process_email(_email("e789"))

        agent2 = EmailClassifierAgent()
        assert "e789" in agent2.processed_emails
        assert agent2.process_email(_email("e789")) is True
        assert mock_classifier.classify_email.call_count == 1

    # @spec STATE-RET-001, STATE-MARK-002
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

    # @spec STATE-RET-002
    def test_retention_disabled_keeps_everything(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.STATE_RETENTION_DAYS = 0
        ancient = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        with open(mock_config.STATE_FILE, "w") as f:
            json.dump({"processed_emails": {"a": ancient, "b": ancient}}, f)

        assert set(EmailClassifierAgent().processed_emails) == {"a", "b"}

    # @spec STATE-RET-001
    def test_periodic_cleanup(self, mock_config, mock_gmail_client, mock_classifier):
        mock_config.STATE_RETENTION_DAYS = 5
        agent = EmailClassifierAgent()
        agent.processed_emails["old"] = (
            datetime.now(UTC) - timedelta(days=10)
        ).isoformat()
        agent.processed_emails["new"] = datetime.now(UTC).isoformat()

        agent.processed_emails = agent._cleanup_old_state(agent.processed_emails)

        assert set(agent.processed_emails) == {"new"}

    # @spec STATE-RET-003, STATE-RET-004
    def test_unparsable_timestamps_are_dropped_with_a_warning(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.STATE_RETENTION_DAYS = 30
        with open(mock_config.STATE_FILE, "w") as f:
            json.dump(
                {
                    "processed_emails": {
                        "good": datetime.now(UTC).isoformat(),
                        "garbage": "not-a-timestamp",
                        "naive": "2026-01-01T00:00:00",
                    }
                },
                f,
            )

        agent = EmailClassifierAgent()

        assert set(agent.processed_emails) == {"good"}
        assert "garbage" in caplog.text
        assert "naive" in caplog.text
        assert "Removed 2 email(s) older than 30 days" in caplog.text

    # @spec STATE-FILE-009
    def test_state_is_written_atomically_via_temp_file_and_replace(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        with patch("state_store.os.replace", wraps=os.replace) as replace:
            agent.process_email(_email("e1"))

        replace.assert_called_once()
        tmp_path, final_path = replace.call_args.args
        assert final_path == mock_config.STATE_FILE
        assert tmp_path != final_path
        assert os.path.dirname(tmp_path) == os.path.dirname(final_path)
        assert not os.path.exists(tmp_path)
        with open(final_path) as f:
            assert "e1" in json.load(f)["processed_emails"]

    # @spec STATE-FILE-007
    def test_unwritable_state_file_is_logged_not_raised(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.ERROR)
        with tempfile.TemporaryDirectory() as tmpdir:
            # a directory where the file should be: open() for writing fails
            mock_config.STATE_FILE = tmpdir
            agent = EmailClassifierAgent()
            agent.process_email(_email("e1"))

        assert "e1" in agent.processed_emails
        assert "Error saving state file" in caplog.text

    # @spec STATE-MARK-001
    def test_processed_timestamp_is_recent(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        agent = EmailClassifierAgent()
        agent.process_email(_email("ts"))
        stamp = datetime.fromisoformat(agent.processed_emails["ts"])
        assert (datetime.now(UTC) - stamp).total_seconds() < 60


@pytest.mark.unit
class TestRunContinuous:
    # @spec AGENT-LOOP-001, AGENT-LOOP-004, STATE-RET-005
    def test_one_poll_processes_then_stops_on_interrupt(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.return_value = ["a", "b"]
        agent = EmailClassifierAgent()
        agent.processed_emails["stale"] = (
            datetime.now(UTC) - timedelta(days=40)
        ).isoformat()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        # the stale entry was pruned at the top of the cycle, then a and b were added
        assert set(agent.processed_emails) == {"a", "b"}
        mock_gmail_client.list_unread_ids.assert_called_once_with(max_results=10)
        assert mock_gmail_client.get_message.call_count == 2

    # @spec AGENT-LOOP-001
    def test_already_processed_ids_are_not_fetched(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.return_value = ["old", "new"]
        agent = EmailClassifierAgent()
        agent.processed_emails["old"] = datetime.now(UTC).isoformat()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        mock_gmail_client.get_message.assert_called_once_with("new")
        assert mock_classifier.classify_email.call_count == 1
        assert "1 already processed" in caplog.text

    # @spec AGENT-LOOP-001
    def test_poll_summary_counts_handled_and_failed(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.return_value = [
            "labeled",
            "unlabeled",
            "broken",
        ]
        mock_gmail_client.get_message.side_effect = [
            _email("labeled"),
            _email("unlabeled"),
            {"subject": "no id"},
        ]
        mock_classifier.classify_email.side_effect = [["AWS"], []]
        agent = EmailClassifierAgent()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        assert "Handled 2 of 3 emails (1 failed)" in caplog.text

    # @spec AGENT-LOOP-001
    def test_message_whose_fetch_fails_is_left_for_the_next_poll(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.return_value = ["gone", "ok"]
        mock_gmail_client.get_message.side_effect = [None, _email("ok")]
        agent = EmailClassifierAgent()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        assert set(agent.processed_emails) == {"ok"}

    # @spec AGENT-LOOP-005, AGENT-LOOP-004
    def test_sigterm_handler_is_installed_and_stops_the_loop(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        agent = EmailClassifierAgent()
        installed = {}

        def fake_signal(signum, handler):
            installed[signum] = handler

        def sleep_then_terminate(seconds):
            installed[signal.SIGTERM](signal.SIGTERM, None)

        with (
            patch("email_classifier_agent.signal.signal", side_effect=fake_signal),
            patch(
                "email_classifier_agent.time.sleep", side_effect=sleep_then_terminate
            ),
        ):
            agent.run_continuous()

        assert signal.SIGTERM in installed
        assert "Email Classifier Agent stopped" in caplog.text

    # @spec AGENT-LOOP-004
    def test_interrupt_during_failure_sleep_stops_cleanly(
        self, mock_config, mock_gmail_client, mock_classifier, caplog
    ):
        caplog.set_level(logging.INFO)
        mock_config.POLL_INTERVAL_SECONDS = 60
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.side_effect = RuntimeError("down")
        agent = EmailClassifierAgent()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()  # must not raise

        assert "Email Classifier Agent stopped" in caplog.text

    # @spec AGENT-LOOP-002
    def test_empty_inbox_sleeps_without_fetching_or_classifying(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.return_value = []
        agent = EmailClassifierAgent()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        mock_gmail_client.get_message.assert_not_called()
        mock_classifier.classify_email.assert_not_called()
        assert agent.processed_emails == {}

    # @spec AGENT-LOOP-002
    def test_all_listed_ids_already_processed_fetches_nothing(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.return_value = ["seen"]
        agent = EmailClassifierAgent()
        agent.processed_emails["seen"] = datetime.now(UTC).isoformat()

        with patch("email_classifier_agent.time.sleep", side_effect=KeyboardInterrupt):
            agent.run_continuous()

        mock_gmail_client.get_message.assert_not_called()

    # @spec AGENT-LOOP-003
    def test_loop_survives_gmail_errors(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 0
        mock_config.MAX_EMAILS_PER_POLL = 10
        mock_gmail_client.list_unread_ids.side_effect = [
            RuntimeError("gmail down"),
            ["a"],
        ]
        agent = EmailClassifierAgent()

        # First sleep follows the logged error; the second ends the loop
        with patch(
            "email_classifier_agent.time.sleep", side_effect=[None, KeyboardInterrupt]
        ):
            agent.run_continuous()

        assert set(agent.processed_emails) == {"a"}
        assert mock_gmail_client.list_unread_ids.call_count == 2

    # @spec AGENT-LOOP-003
    def test_failed_cycles_back_off_exponentially_and_reset_on_success(
        self, mock_config, mock_gmail_client, mock_classifier
    ):
        mock_config.POLL_INTERVAL_SECONDS = 60
        mock_config.MAX_EMAILS_PER_POLL = 10
        down = RuntimeError("gmail down")
        mock_gmail_client.list_unread_ids.side_effect = [
            down,
            down,
            down,
            down,
            down,  # five consecutive failures
            ["a"],  # success resets the backoff
            down,  # a fresh failure starts over at one interval
            KeyboardInterrupt,  # end the loop from inside the poll body
        ]
        agent = EmailClassifierAgent()
        sleeps = []

        with patch("email_classifier_agent.time.sleep", side_effect=sleeps.append):
            agent.run_continuous()

        # doubles from the interval, capped at ten times the interval
        assert sleeps == [60, 120, 240, 480, 600, 60, 60]
