"""
Factory for creating LLM provider instances.
"""

import logging
from llm_provider import LLMProvider
from providers.bedrock_provider import BedrockProvider
from providers.anthropic_provider import AnthropicProvider
from providers.openai_provider import OpenAIProvider
from providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


def create_llm_provider(config) -> LLMProvider:
    """
    Factory function to create LLM provider instances based on configuration.

    Args:
        config: Configuration module with provider settings

    Returns:
        LLMProvider instance

    Raises:
        ValueError: If provider type is unknown or configuration is invalid
    """
    provider_type = config.LLM_PROVIDER.lower()

    logger.info(f"Creating LLM provider: {provider_type}")

    if provider_type == "bedrock":
        return BedrockProvider(
            region=config.AWS_REGION,
            model_id=config.BEDROCK_MODEL_ID,
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY
        )

    elif provider_type == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required for Anthropic provider")
        return AnthropicProvider(
            api_key=config.ANTHROPIC_API_KEY,
            model=config.ANTHROPIC_MODEL
        )

    elif provider_type == "openai":
        if not config.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for OpenAI provider")
        return OpenAIProvider(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_MODEL
        )

    elif provider_type == "ollama":
        return OllamaProvider(
            model=config.OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider_type}. "
            f"Supported providers: bedrock, anthropic, openai, ollama"
        )
