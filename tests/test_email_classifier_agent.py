"""
Unit tests for EmailClassifierAgent with state tracking.
"""

import json
import os
import tempfile
import pytest
from datetime import timezone
from unittest.mock import Mock, patch
from email_classifier_agent import EmailClassifierAgent


@pytest.fixture
def temp_state_file():
    """Create a temporary state file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        temp_path = f.name
    yield temp_path
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def mock_config_with_state(temp_state_file):
    """Mock config with temporary state file."""
    # Patch config at import time to avoid loading classifier_config.json
    with patch("email_classifier_agent.config") as mock_config:
        mock_config.STATE_FILE = temp_state_file
        mock_config.STATE_RETENTION_DAYS = 30
        mock_config.GMAIL_CREDENTIALS_PATH = "credentials.json"
        mock_config.GMAIL_TOKEN_PATH = "token.json"
        mock_config.GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
        mock_config.GMAIL_HEADLESS_MODE = True
        mock_config.LLM_PROVIDER = "bedrock"
        mock_config.LABELS = ["AWS", "Github", "Shipping"]
        mock_config.CLASSIFICATION_PROMPT = "Test classification prompt for unit tests"
        mock_config.REMOVE_FROM_INBOX = True
        yield mock_config


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
def mock_llm_provider():
    """Mock LLM provider."""
    with patch("email_classifier_agent.create_llm_provider") as mock:
        provider = Mock()
        provider.classify_email = Mock(return_value=["AWS", "Github"])
        mock.return_value = provider
        yield provider


@pytest.mark.unit
class TestEmailClassifierAgentStateTracking:
    """Tests for state tracking functionality."""

    def test_load_state_no_file(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test loading state when no state file exists."""
        agent = EmailClassifierAgent()
        assert len(agent.processed_emails) == 0
        assert agent.state_file == mock_config_with_state.STATE_FILE

    def test_load_state_existing_file(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test loading state from existing file."""
        # Create state file with some processed emails
        state_data = {"processed_emails": ["email1", "email2", "email3"]}
        with open(mock_config_with_state.STATE_FILE, "w") as f:
            json.dump(state_data, f)

        agent = EmailClassifierAgent()
        assert len(agent.processed_emails) == 3
        assert "email1" in agent.processed_emails
        assert "email2" in agent.processed_emails
        assert "email3" in agent.processed_emails

    def test_load_state_corrupted_file(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test loading state from corrupted file."""
        # Write invalid JSON
        with open(mock_config_with_state.STATE_FILE, "w") as f:
            f.write("invalid json{{{")

        agent = EmailClassifierAgent()
        # Should gracefully handle error and return empty set
        assert len(agent.processed_emails) == 0

    def test_save_state(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test saving state to file."""
        from datetime import datetime

        agent = EmailClassifierAgent()
        timestamp1 = datetime.now(timezone.utc).isoformat()
        timestamp2 = datetime.now(timezone.utc).isoformat()
        agent.processed_emails["email1"] = timestamp1
        agent.processed_emails["email2"] = timestamp2
        agent._save_state()

        # Verify state file contents
        with open(mock_config_with_state.STATE_FILE, "r") as f:
            state_data = json.load(f)
        assert "email1" in state_data["processed_emails"]
        assert "email2" in state_data["processed_emails"]
        assert isinstance(state_data["processed_emails"], dict)

    def test_save_state_creates_directory(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that save_state creates directory if it doesn't exist."""
        from datetime import datetime

        # Use a state file in a non-existent directory
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = os.path.join(tmpdir, "subdir", "state.json")
            mock_config_with_state.STATE_FILE = state_path

            agent = EmailClassifierAgent()
            agent.processed_emails["email1"] = datetime.now(timezone.utc).isoformat()
            agent._save_state()

            assert os.path.exists(state_path)
            with open(state_path, "r") as f:
                state_data = json.load(f)
            assert "email1" in state_data["processed_emails"]

    def test_process_email_saves_state(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that processing an email saves it to state."""
        agent = EmailClassifierAgent()

        email = {
            "id": "test_email_123",
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }

        result = agent.process_email(email)

        assert result is True
        assert "test_email_123" in agent.processed_emails

        # Verify state was saved to disk
        with open(mock_config_with_state.STATE_FILE, "r") as f:
            state_data = json.load(f)
        assert "test_email_123" in state_data["processed_emails"]

    def test_process_email_skips_already_processed(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that already-processed emails are skipped."""
        agent = EmailClassifierAgent()

        email = {
            "id": "test_email_123",
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }

        # Process email first time
        agent.process_email(email)
        assert mock_llm_provider.classify_email.call_count == 1

        # Process same email again
        result = agent.process_email(email)

        # Should skip LLM call
        assert mock_llm_provider.classify_email.call_count == 1
        assert result is True
        assert "test_email_123" in agent.processed_emails

    def test_process_email_no_id(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test processing email without ID field."""
        agent = EmailClassifierAgent()

        email = {
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }

        result = agent.process_email(email)
        assert result is False

    def test_process_email_no_labels_still_saves_state(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that emails with no labels are still marked as processed."""
        agent = EmailClassifierAgent()
        mock_llm_provider.classify_email.return_value = []

        email = {
            "id": "test_email_456",
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }

        result = agent.process_email(email)

        # Should return False but still mark as processed
        assert result is False
        assert "test_email_456" in agent.processed_emails

        # Should not retry on next poll
        result2 = agent.process_email(email)
        assert result2 is True
        assert mock_llm_provider.classify_email.call_count == 1

    def test_state_persistence_across_restarts(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that state persists across agent restarts."""
        # First agent instance processes an email
        agent1 = EmailClassifierAgent()
        email = {
            "id": "test_email_789",
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }
        agent1.process_email(email)

        # Second agent instance should load the state
        agent2 = EmailClassifierAgent()
        assert "test_email_789" in agent2.processed_emails

        # Should skip already-processed email
        result = agent2.process_email(email)
        assert result is True
        # LLM should only be called once (from first agent)
        assert mock_llm_provider.classify_email.call_count == 1

    def test_process_email_exception_does_not_save_state(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that failed email processing doesn't save to state."""
        agent = EmailClassifierAgent()
        mock_llm_provider.classify_email.side_effect = Exception("LLM error")

        email = {
            "id": "test_email_error",
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }

        result = agent.process_email(email)

        assert result is False
        # Should NOT be marked as processed due to error
        assert "test_email_error" not in agent.processed_emails

    def test_multiple_emails_state_tracking(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test state tracking with multiple emails."""
        agent = EmailClassifierAgent()

        emails = [
            {
                "id": f"email_{i}",
                "subject": f"Email {i}",
                "from": "test@example.com",
                "body": "Test",
            }
            for i in range(5)
        ]

        # Process all emails
        for email in emails:
            agent.process_email(email)

        # All should be in state
        assert len(agent.processed_emails) == 5
        for i in range(5):
            assert f"email_{i}" in agent.processed_emails

        # Verify state file
        with open(mock_config_with_state.STATE_FILE, "r") as f:
            state_data = json.load(f)
        assert len(state_data["processed_emails"]) == 5

        # Process same emails again
        for email in emails:
            agent.process_email(email)

        # LLM should only be called 5 times (once per unique email)
        assert mock_llm_provider.classify_email.call_count == 5

    def test_state_retention_removes_old_entries(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that old entries are removed based on retention period."""
        from datetime import datetime, timedelta

        # Set retention to 7 days
        mock_config_with_state.STATE_RETENTION_DAYS = 7

        # Create state with old and new emails
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        recent_timestamp = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        current_timestamp = datetime.now(timezone.utc).isoformat()

        state_data = {
            "processed_emails": {
                "old_email_1": old_timestamp,
                "old_email_2": old_timestamp,
                "recent_email": recent_timestamp,
                "current_email": current_timestamp,
            }
        }
        with open(mock_config_with_state.STATE_FILE, "w") as f:
            json.dump(state_data, f)

        agent = EmailClassifierAgent()

        # Only recent and current emails should be loaded
        assert len(agent.processed_emails) == 2
        assert "recent_email" in agent.processed_emails
        assert "current_email" in agent.processed_emails
        assert "old_email_1" not in agent.processed_emails
        assert "old_email_2" not in agent.processed_emails

    def test_state_retention_migration_from_list(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test migration from old list format to new dict format."""
        # Create state file with old list format
        state_data = {"processed_emails": ["email1", "email2", "email3"]}
        with open(mock_config_with_state.STATE_FILE, "w") as f:
            json.dump(state_data, f)

        agent = EmailClassifierAgent()

        # All emails should be loaded
        assert len(agent.processed_emails) == 3
        assert "email1" in agent.processed_emails
        assert "email2" in agent.processed_emails
        assert "email3" in agent.processed_emails

        # All should have timestamps
        for email_id in ["email1", "email2", "email3"]:
            assert isinstance(agent.processed_emails[email_id], str)
            # Verify it's a valid ISO format timestamp
            from datetime import datetime

            datetime.fromisoformat(agent.processed_emails[email_id])

    def test_state_retention_disabled(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that retention can be disabled (retention_days <= 0)."""
        from datetime import datetime, timedelta

        # Disable retention
        mock_config_with_state.STATE_RETENTION_DAYS = 0

        # Create state with very old emails
        very_old_timestamp = (
            datetime.now(timezone.utc) - timedelta(days=365)
        ).isoformat()

        state_data = {
            "processed_emails": {
                "old_email_1": very_old_timestamp,
                "old_email_2": very_old_timestamp,
            }
        }
        with open(mock_config_with_state.STATE_FILE, "w") as f:
            json.dump(state_data, f)

        agent = EmailClassifierAgent()

        # All emails should be kept when retention is disabled
        assert len(agent.processed_emails) == 2
        assert "old_email_1" in agent.processed_emails
        assert "old_email_2" in agent.processed_emails

    def test_cleanup_old_state_periodic(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that periodic cleanup in run_continuous works."""
        from datetime import datetime, timedelta

        mock_config_with_state.STATE_RETENTION_DAYS = 5

        agent = EmailClassifierAgent()

        # Add old and new emails
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        new_timestamp = datetime.now(timezone.utc).isoformat()

        agent.processed_emails["old_email"] = old_timestamp
        agent.processed_emails["new_email"] = new_timestamp

        assert len(agent.processed_emails) == 2

        # Call cleanup manually (simulating what happens in run_continuous)
        agent.processed_emails = agent._cleanup_old_state(agent.processed_emails)

        # Only new email should remain
        assert len(agent.processed_emails) == 1
        assert "new_email" in agent.processed_emails
        assert "old_email" not in agent.processed_emails

    def test_process_email_stores_timestamp(
        self, mock_config_with_state, mock_gmail_client, mock_llm_provider
    ):
        """Test that processing an email stores a valid timestamp."""
        from datetime import datetime

        agent = EmailClassifierAgent()

        email = {
            "id": "test_timestamp_email",
            "subject": "Test Email",
            "from": "test@example.com",
            "body": "Test body",
        }

        agent.process_email(email)

        # Email should be in state
        assert "test_timestamp_email" in agent.processed_emails

        # Should have a valid ISO format timestamp
        timestamp_str = agent.processed_emails["test_timestamp_email"]
        timestamp = datetime.fromisoformat(timestamp_str)

        # Timestamp should be recent (within last minute)
        time_diff = datetime.now(timezone.utc) - timestamp
        assert time_diff.total_seconds() < 60
