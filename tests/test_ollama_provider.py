"""
Unit tests for OllamaProvider.
"""

import pytest
from unittest.mock import Mock, patch


@pytest.fixture
def mock_ollama():
    """Mock ollama module."""
    mock_module = Mock()
    mock_client = Mock()
    mock_module.Client = Mock(return_value=mock_client)
    return mock_module, mock_client


@pytest.mark.unit
class TestOllamaProvider:
    """Tests for Ollama local LLM provider."""

    def test_classify_email_success(self, mock_ollama, test_email, test_labels, classification_prompt):
        """Test successful email classification."""
        mock_module, mock_client = mock_ollama

        mock_response = {
            'message': {
                'content': '{"labels": ["AWS", "Finance"]}'
            }
        }
        mock_client.chat.return_value = mock_response

        with patch.dict('sys.modules', {'ollama': mock_module}):
            from providers.ollama_provider import OllamaProvider

            provider = OllamaProvider()
            result = provider.classify_email(test_email, classification_prompt, test_labels)

            assert result == ["AWS", "Finance"]
