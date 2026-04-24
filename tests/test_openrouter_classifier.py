"""
Unit tests for openrouter_classifier.py
"""

from unittest.mock import Mock, MagicMock, patch

import pytest

from openrouter_classifier import OpenRouterClassifier


@pytest.fixture
def sample_email():
    return {
        "subject": "Your AWS Bill is Ready",
        "from": "billing@aws.amazon.com",
        "date": "2026-04-24",
        "body": "Your monthly AWS bill is now available.",
    }


@pytest.fixture
def available_labels():
    return ["Billing", "Personal", "Work", "Spam"]


@pytest.fixture
def classification_prompt():
    return "Classify this email into one of the available labels."


def _mock_openai_response(content: str):
    """Build a mock OpenAI SDK chat-completion response whose content is `content`."""
    message = Mock()
    message.content = content
    choice = Mock()
    choice.message = message
    response = Mock()
    response.choices = [choice]
    return response


@pytest.mark.unit
class TestOpenRouterClassifierInit:
    """Test OpenRouterClassifier construction."""

    def test_init_stores_defaults(self):
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            classifier = OpenRouterClassifier(api_key="test-key")

        assert classifier.model == "anthropic/claude-3.5-sonnet"
        assert classifier.temperature == 0.0
        assert classifier.max_tokens == 1000

    def test_init_stores_custom_values(self):
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            classifier = OpenRouterClassifier(
                api_key="test-key",
                model="openai/gpt-4o",
                temperature=0.5,
                max_tokens=500,
            )

        assert classifier.model == "openai/gpt-4o"
        assert classifier.temperature == 0.5
        assert classifier.max_tokens == 500

    def test_init_configures_openrouter_base_url(self):
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            OpenRouterClassifier(api_key="test-key")

        _, kwargs = mock_openai.call_args
        assert kwargs["api_key"] == "test-key"
        assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
        assert "HTTP-Referer" in kwargs["default_headers"]
        assert "X-Title" in kwargs["default_headers"]


@pytest.mark.unit
class TestOpenRouterClassifyEmail:
    """Test OpenRouterClassifier.classify_email."""

    def _build_classifier(self):
        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            classifier = OpenRouterClassifier(api_key="test-key")
        # Replace with a fresh MagicMock so each test controls its own return
        classifier.client = MagicMock()
        return classifier

    def test_classify_email_returns_labels(
        self, sample_email, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": ["Billing"]}'
        )

        result = classifier.classify_email(
            sample_email, classification_prompt, available_labels
        )

        assert result == ["Billing"]

    def test_classify_email_calls_model_with_configured_params(
        self, sample_email, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.model = "openai/gpt-4o"
        classifier.temperature = 0.3
        classifier.max_tokens = 750
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": []}'
        )

        classifier.classify_email(sample_email, classification_prompt, available_labels)

        _, kwargs = classifier.client.chat.completions.create.call_args
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_tokens"] == 750
        # system + user messages
        assert len(kwargs["messages"]) == 2
        assert kwargs["messages"][0]["role"] == "system"
        assert kwargs["messages"][1]["role"] == "user"

    def test_classify_email_returns_empty_when_api_errors(
        self, sample_email, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.side_effect = RuntimeError("boom")

        result = classifier.classify_email(
            sample_email, classification_prompt, available_labels
        )

        assert result == []

    def test_classify_email_filters_unknown_labels(
        self, sample_email, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": ["Billing", "NotARealLabel"]}'
        )

        result = classifier.classify_email(
            sample_email, classification_prompt, available_labels
        )

        assert "Billing" in result
        assert "NotARealLabel" not in result

    def test_classify_email_handles_empty_label_response(
        self, sample_email, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": []}'
        )

        result = classifier.classify_email(
            sample_email, classification_prompt, available_labels
        )

        assert result == []
