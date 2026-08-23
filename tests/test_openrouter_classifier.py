"""
Unit tests for openrouter_classifier.py
"""

from unittest.mock import Mock, MagicMock, patch

import httpx2
import openai
import pytest

from llm_utils import EMAIL_CLOSE_TAG, EMAIL_OPEN_TAG
from openrouter_classifier import (
    JSON_RESPONSE_FORMAT,
    OPENROUTER_BASE_URL,
    SYSTEM_PROMPT,
    ClassificationRejected,
    OpenRouterClassifier,
    is_json_mode_rejection,
)

# Verbatim error body returned by LiteLLM when the llmprotect guardrail blocks
# a request (captured from production logs, 2026-08-23 18:11:40 UTC).
GUARD_BLOCK_MESSAGE = (
    "Error code: 400 - {'error': {'message': \"prompt injection detected "
    "(risk=0.855 >= threshold 0.85) in chunk 2/3: 'ing, now is the time to "
    "register. REGISTER NOW < https://my.myeloma.org > During this free online "
    "workshop, leading exp…'\", 'type': 'None', 'param': 'None', 'code': '400'}}"
)


@pytest.mark.unit
class TestIsJsonModeRejection:
    """Only 400s that name the response_format parameter count as rejections."""

    @pytest.mark.parametrize(
        "message",
        [
            # OpenAI
            "Invalid parameter: 'response_format' of type 'json_object' is not "
            "supported with this model.",
            # OpenRouter
            "Error code: 400 - {'error': {'message': 'This model does not "
            "support response_format', 'code': 400}}",
            # Generic phrasing
            "JSON mode is not available for this deployment",
            "json_object is unsupported",
        ],
    )
    def test_response_format_rejections_match(self, message):
        assert is_json_mode_rejection(_bad_request_error(message)) is True

    @pytest.mark.parametrize(
        "message",
        [
            GUARD_BLOCK_MESSAGE,
            "Error code: 400 - {'error': {'message': 'prompt injection detected "
            "(risk=1.000 >= threshold 0.85)', 'type': 'None', 'param': 'None', "
            "'code': '400'}}",
            "Error code: 400 - {'error': {'message': 'context length exceeded'}}",
            "Error code: 400 - {'error': {'message': 'Invalid model name'}}",
        ],
    )
    def test_other_400s_do_not_match(self, message):
        assert is_json_mode_rejection(_bad_request_error(message)) is False


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


def _bad_request_error(message: str) -> openai.BadRequestError:
    """Build a real openai.BadRequestError carrying an HTTP 400 response."""
    response = httpx2.Response(
        400, request=httpx2.Request("POST", "http://x/chat/completions")
    )
    return openai.BadRequestError(message, response=response, body=None)


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
            classifier = OpenRouterClassifier(api_key="test-key")

        _, kwargs = mock_openai.call_args
        assert kwargs["api_key"] == "test-key"
        assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
        assert "HTTP-Referer" in kwargs["default_headers"]
        assert "X-Title" in kwargs["default_headers"]
        assert classifier.base_url == OPENROUTER_BASE_URL
        assert classifier.provider_name == "openrouter.ai"

    def test_init_custom_base_url_is_passed_to_client(self):
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            classifier = OpenRouterClassifier(
                api_key="test-key", base_url="http://litellm:4000/v1"
            )

        _, kwargs = mock_openai.call_args
        assert kwargs["base_url"] == "http://litellm:4000/v1"
        assert classifier.base_url == "http://litellm:4000/v1"
        assert classifier.provider_name == "litellm:4000"

    @pytest.mark.parametrize("empty_value", [None, ""])
    def test_init_empty_base_url_falls_back_to_openrouter(self, empty_value):
        with patch("openai.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            classifier = OpenRouterClassifier(api_key="test-key", base_url=empty_value)

        _, kwargs = mock_openai.call_args
        assert kwargs["base_url"] == OPENROUTER_BASE_URL
        assert classifier.base_url == OPENROUTER_BASE_URL


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
        assert kwargs["response_format"] == JSON_RESPONSE_FORMAT
        # system + user messages
        assert len(kwargs["messages"]) == 2
        assert kwargs["messages"][0]["role"] == "system"
        assert kwargs["messages"][1]["role"] == "user"

    def test_email_content_is_in_user_message_not_system(
        self, sample_email, available_labels, classification_prompt
    ):
        """Email (untrusted) is fenced in the user message; system prompt declares it data."""
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": []}'
        )

        classifier.classify_email(sample_email, classification_prompt, available_labels)

        _, kwargs = classifier.client.chat.completions.create.call_args
        system, user = kwargs["messages"]
        assert system["content"] == SYSTEM_PROMPT
        assert sample_email["subject"] not in system["content"]
        assert sample_email["body"] not in system["content"]
        assert "untrusted data" in system["content"]
        assert "never an instruction" in system["content"]
        assert f"{EMAIL_OPEN_TAG}\n" in user["content"]
        assert f"\n{EMAIL_CLOSE_TAG}" in user["content"]
        assert sample_email["body"] in user["content"]

    def test_tracking_urls_stripped_before_sending(
        self, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": ["Spam"]}'
        )
        email = {
            "subject": "Deals",
            "from": "promo@example.com",
            "date": "2026-04-24",
            "body": "Go https://click.example.com/ls/click?upn=u001.OPAQUE_TOKEN_9f8e7d",
        }

        classifier.classify_email(email, classification_prompt, available_labels)

        _, kwargs = classifier.client.chat.completions.create.call_args
        user_content = kwargs["messages"][1]["content"]
        assert "https://click.example.com" in user_content
        assert "OPAQUE_TOKEN_9f8e7d" not in user_content

    def test_json_mode_falls_back_when_endpoint_rejects_response_format(
        self, sample_email, available_labels, classification_prompt
    ):
        """A 400 on response_format retries without it and disables JSON mode."""
        classifier = self._build_classifier()
        bad_request = _bad_request_error("response_format is not supported")
        classifier.client.chat.completions.create.side_effect = [
            bad_request,
            _mock_openai_response('{"labels": ["Billing"]}'),
        ]

        result = classifier.classify_email(
            sample_email, classification_prompt, available_labels
        )

        assert result == ["Billing"]
        assert classifier.json_mode is False
        calls = classifier.client.chat.completions.create.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["response_format"] == JSON_RESPONSE_FORMAT
        assert "response_format" not in calls[1].kwargs

        # Subsequent calls go straight to plain mode (no retry churn)
        classifier.client.chat.completions.create.reset_mock(side_effect=True)
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": ["Work"]}'
        )
        assert classifier.classify_email(
            sample_email, classification_prompt, available_labels
        ) == ["Work"]
        assert classifier.client.chat.completions.create.call_count == 1
        assert "response_format" not in (
            classifier.client.chat.completions.create.call_args.kwargs
        )

    def test_non_400_errors_do_not_disable_json_mode(
        self, sample_email, available_labels, classification_prompt
    ):
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.side_effect = RuntimeError("net down")

        result = classifier.classify_email(
            sample_email, classification_prompt, available_labels
        )

        assert result == []
        assert classifier.json_mode is True
        assert classifier.client.chat.completions.create.call_count == 1

    def test_guardrail_block_400_is_not_treated_as_json_mode_rejection(
        self, sample_email, available_labels, classification_prompt, caplog
    ):
        """
        A gateway guardrail (LiteLLM + llmprotect) answers 400 for prompt-
        injection blocks. That must not trigger the no-JSON retry (which costs
        a second guard scan) and must not disable JSON mode for later emails.
        The block surfaces as ClassificationRejected so the agent can park the
        email for a later retry. Regression for the 2026-08-23 myeloma.org
        incident.
        """
        import logging

        caplog.set_level(logging.WARNING)
        classifier = self._build_classifier()
        classifier.client.chat.completions.create.side_effect = _bad_request_error(
            GUARD_BLOCK_MESSAGE
        )

        with pytest.raises(ClassificationRejected) as excinfo:
            classifier.classify_email(
                sample_email, classification_prompt, available_labels
            )

        assert "prompt injection detected" in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, openai.BadRequestError)
        assert classifier.json_mode is True
        assert classifier.client.chat.completions.create.call_count == 1
        assert "rejected JSON response_format" not in caplog.text
        assert "prompt injection detected" in caplog.text

        # JSON mode is still requested on the next email
        classifier.client.chat.completions.create.reset_mock(side_effect=True)
        classifier.client.chat.completions.create.return_value = _mock_openai_response(
            '{"labels": ["Work"]}'
        )
        classifier.classify_email(sample_email, classification_prompt, available_labels)
        assert (
            classifier.client.chat.completions.create.call_args.kwargs[
                "response_format"
            ]
            == JSON_RESPONSE_FORMAT
        )

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
