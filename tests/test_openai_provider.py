"""
Unit tests for OpenAIProvider.
"""

import pytest
from unittest.mock import Mock, patch


@pytest.fixture
def mock_openai():
    """Mock openai module."""
    mock_module = Mock()
    mock_client = Mock()
    mock_module.OpenAI = Mock(return_value=mock_client)
    return mock_module, mock_client


@pytest.mark.unit
class TestOpenAIProvider:
    """Tests for OpenAI API provider."""

    def test_classify_email_success(self, mock_openai, test_email, test_labels, classification_prompt):
        """Test successful email classification."""
        mock_module, mock_client = mock_openai

        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = '{"labels": ["AWS", "Finance"]}'
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict('sys.modules', {'openai': mock_module}):
            from providers.openai_provider import OpenAIProvider

            provider = OpenAIProvider(api_key="test-key")
            result = provider.classify_email(test_email, classification_prompt, test_labels)

            assert result == ["AWS", "Finance"]
