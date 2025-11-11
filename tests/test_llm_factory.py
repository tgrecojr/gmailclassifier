"""
Unit tests for llm_factory.py

Tests cover:
- Provider creation for all types
- Configuration handling
- Error handling for invalid providers
- Error handling for missing API keys
"""

import pytest
from unittest.mock import Mock, patch


@pytest.mark.unit
class TestLLMFactory:
    """Tests for LLM provider factory."""

    @patch('llm_factory.BedrockProvider')
    def test_create_bedrock_provider(self, mock_bedrock_class, mock_config):
        """Test creating Bedrock provider."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "bedrock"
        mock_provider = Mock()
        mock_bedrock_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        mock_bedrock_class.assert_called_once_with(
            region=mock_config.AWS_REGION,
            model_id=mock_config.BEDROCK_MODEL_ID,
            aws_access_key_id=mock_config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=mock_config.AWS_SECRET_ACCESS_KEY
        )
        assert result == mock_provider

    @patch('llm_factory.AnthropicProvider')
    def test_create_anthropic_provider(self, mock_anthropic_class, mock_config):
        """Test creating Anthropic provider."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "anthropic"
        mock_provider = Mock()
        mock_anthropic_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        mock_anthropic_class.assert_called_once_with(
            api_key=mock_config.ANTHROPIC_API_KEY,
            model=mock_config.ANTHROPIC_MODEL
        )
        assert result == mock_provider

    @patch('llm_factory.OpenAIProvider')
    def test_create_openai_provider(self, mock_openai_class, mock_config):
        """Test creating OpenAI provider."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "openai"
        mock_provider = Mock()
        mock_openai_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        mock_openai_class.assert_called_once_with(
            api_key=mock_config.OPENAI_API_KEY,
            model=mock_config.OPENAI_MODEL
        )
        assert result == mock_provider

    @patch('llm_factory.OllamaProvider')
    def test_create_ollama_provider(self, mock_ollama_class, mock_config):
        """Test creating Ollama provider."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "ollama"
        mock_provider = Mock()
        mock_ollama_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        mock_ollama_class.assert_called_once_with(
            model=mock_config.OLLAMA_MODEL,
            base_url=mock_config.OLLAMA_BASE_URL
        )
        assert result == mock_provider

    def test_create_unknown_provider(self, mock_config):
        """Test error handling for unknown provider."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "unknown_provider"

        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_provider(mock_config)

    def test_create_anthropic_without_api_key(self, mock_config):
        """Test error handling when Anthropic API key is missing."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "anthropic"
        mock_config.ANTHROPIC_API_KEY = None

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
            create_llm_provider(mock_config)

    def test_create_openai_without_api_key(self, mock_config):
        """Test error handling when OpenAI API key is missing."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "openai"
        mock_config.OPENAI_API_KEY = None

        with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
            create_llm_provider(mock_config)

    @patch('llm_factory.BedrockProvider')
    def test_provider_type_case_insensitive(self, mock_bedrock_class, mock_config):
        """Test that provider type is case-insensitive."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "BEDROCK"
        mock_provider = Mock()
        mock_bedrock_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        assert result == mock_provider

    @patch('llm_factory.BedrockProvider')
    def test_bedrock_without_explicit_credentials(self, mock_bedrock_class, mock_config):
        """Test Bedrock creation works without explicit credentials (uses environment)."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "bedrock"
        mock_config.AWS_ACCESS_KEY_ID = None
        mock_config.AWS_SECRET_ACCESS_KEY = None
        mock_provider = Mock()
        mock_bedrock_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        # Should still be called, just with None values
        mock_bedrock_class.assert_called_once()
        assert result == mock_provider

    @patch('llm_factory.OllamaProvider')
    def test_ollama_with_custom_url(self, mock_ollama_class, mock_config):
        """Test Ollama creation with custom base URL."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "ollama"
        mock_config.OLLAMA_BASE_URL = "http://custom-host:11434"
        mock_provider = Mock()
        mock_ollama_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        call_kwargs = mock_ollama_class.call_args[1]
        assert call_kwargs['base_url'] == "http://custom-host:11434"

    @patch('llm_factory.logger')
    @patch('llm_factory.BedrockProvider')
    def test_factory_logs_provider_creation(self, mock_bedrock_class, mock_logger, mock_config):
        """Test that factory logs provider creation."""
        from llm_factory import create_llm_provider

        mock_config.LLM_PROVIDER = "bedrock"
        mock_provider = Mock()
        mock_bedrock_class.return_value = mock_provider

        result = create_llm_provider(mock_config)

        # Check that info log was called
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "bedrock" in log_message.lower()
