"""
Unit tests for AnthropicProvider.

Tests cover:
- Successful classification
- Error handling
- JSON parsing edge cases
- API errors
- ImportError handling
"""

import pytest
from unittest.mock import Mock, patch


@pytest.fixture
def mock_anthropic():
    """Mock anthropic module."""
    mock_module = Mock()
    mock_client = Mock()
    mock_module.Anthropic = Mock(return_value=mock_client)
    return mock_module, mock_client


@pytest.mark.unit
class TestAnthropicProvider:
    """Tests for Anthropic Direct API provider."""

    def test_init_success(self, mock_anthropic):
        """Test successful initialization."""
        mock_module, mock_client = mock_anthropic

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(
                api_key="test-api-key", model="claude-3-5-sonnet-20241022"
            )

            mock_module.Anthropic.assert_called_once_with(api_key="test-api-key")
            assert provider.model == "claude-3-5-sonnet-20241022"
            assert provider.client == mock_client

    def test_classify_email_success(
        self, mock_anthropic, test_email, test_labels, classification_prompt
    ):
        """Test successful email classification."""
        mock_module, mock_client = mock_anthropic

        # Setup mock response
        mock_response = Mock()
        mock_content = Mock()
        mock_content.text = '{"labels": ["AWS", "Finance"]}'
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key="test-key")
            result = provider.classify_email(
                test_email, classification_prompt, test_labels
            )

            assert result == ["AWS", "Finance"]
            assert mock_client.messages.create.called

    def test_classify_email_with_markdown(
        self, mock_anthropic, test_email, test_labels, classification_prompt
    ):
        """Test classification with markdown code block."""
        mock_module, mock_client = mock_anthropic

        mock_response = Mock()
        mock_content = Mock()
        mock_content.text = '```json\n{"labels": ["AWS", "Finance"]}\n```'
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key="test-key")
            result = provider.classify_email(
                test_email, classification_prompt, test_labels
            )

            assert "AWS" in result
            assert "Finance" in result

    def test_classify_email_api_error(
        self, mock_anthropic, test_email, test_labels, classification_prompt
    ):
        """Test handling of API error."""
        mock_module, mock_client = mock_anthropic

        mock_client.messages.create.side_effect = Exception("API rate limit exceeded")

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key="test-key")
            result = provider.classify_email(
                test_email, classification_prompt, test_labels
            )

            assert result == []

    def test_classify_email_invalid_json(
        self, mock_anthropic, test_email, test_labels, classification_prompt
    ):
        """Test handling of invalid JSON response."""
        mock_module, mock_client = mock_anthropic

        mock_response = Mock()
        mock_content = Mock()
        mock_content.text = "This is not valid JSON"
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key="test-key")
            result = provider.classify_email(
                test_email, classification_prompt, test_labels
            )

            assert result == []

    def test_classify_email_filters_invalid_labels(
        self, mock_anthropic, test_email, test_labels, classification_prompt
    ):
        """Test that invalid labels are filtered."""
        mock_module, mock_client = mock_anthropic

        mock_response = Mock()
        mock_content = Mock()
        mock_content.text = '{"labels": ["AWS", "InvalidLabel", "Finance"]}'
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key="test-key")
            result = provider.classify_email(
                test_email, classification_prompt, test_labels
            )

            assert "AWS" in result
            assert "Finance" in result
            assert "InvalidLabel" not in result

    def test_classify_email_case_insensitive(
        self, mock_anthropic, test_email, test_labels, classification_prompt
    ):
        """Test case-insensitive label matching."""
        mock_module, mock_client = mock_anthropic

        mock_response = Mock()
        mock_content = Mock()
        mock_content.text = '{"labels": ["aws", "FINANCE"]}'
        mock_response.content = [mock_content]
        mock_client.messages.create.return_value = mock_response

        with patch.dict("sys.modules", {"anthropic": mock_module}):
            from providers.anthropic_provider import AnthropicProvider

            provider = AnthropicProvider(api_key="test-key")
            result = provider.classify_email(
                test_email, classification_prompt, test_labels
            )

            assert "AWS" in result
            assert "Finance" in result
