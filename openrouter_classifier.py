"""
OpenAI-compatible LLM classifier implementation.

Defaults to the OpenRouter API, but any OpenAI-compatible endpoint
(e.g. a LiteLLM proxy) can be targeted by supplying a custom base URL.
"""

import logging
from typing import List, Dict, Optional
from urllib.parse import urlparse
from llm_utils import (
    construct_email_content,
    construct_classification_prompt,
    parse_labels_from_response,
    log_classification_result,
)

logger = logging.getLogger(__name__)

# Default API endpoint when no custom base URL is configured.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClassifier:
    """OpenAI-compatible API implementation for email classification."""

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-3.5-sonnet",
        temperature: float = 0.0,
        max_tokens: int = 1000,
        base_url: Optional[str] = None,
    ):
        """
        Initialize the classifier.

        Args:
            api_key: API key sent as the bearer token to the configured endpoint
            model: Model ID (default: anthropic/claude-3.5-sonnet)
                   See https://openrouter.ai/docs for available models
            temperature: Sampling temperature (0.0-2.0, default: 0.0)
            max_tokens: Maximum tokens in response (default: 1000)
            base_url: OpenAI-compatible API base URL. Falls back to OpenRouter
                      when None or empty.
        """
        try:
            import openai

            self.base_url = base_url or OPENROUTER_BASE_URL
            # Short label (hostname) for per-email log lines
            self.provider_name = urlparse(self.base_url).netloc or self.base_url
            self.client = openai.OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                default_headers={
                    "HTTP-Referer": ("https://github.com/tgrecojr/gmailclassifier"),
                    "X-Title": "gmailclassifier",
                },
            )
            self.model = model
            self.temperature = temperature
            self.max_tokens = max_tokens
            logger.info(
                f"Initialized LLM classifier at {self.base_url} with model: {model}, "
                f"temperature: {temperature}, max_tokens: {max_tokens}"
            )
        except ImportError:
            raise ImportError(
                "openai package is required for OpenRouter. "
                "Install it with: pip install openai"
            )

    def classify_email(
        self, email: Dict, classification_prompt: str, available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using the configured OpenAI-compatible API.

        Args:
            email: Email dictionary with subject, from, body fields
            classification_prompt: The classification instructions
            available_labels: List of available label names

        Returns:
            List of applicable label names
        """
        try:
            # Construct email content and full prompt using shared utilities
            email_content = construct_email_content(email)
            full_prompt = construct_classification_prompt(
                classification_prompt, available_labels, email_content
            )

            # Call the OpenAI-compatible chat completions endpoint
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an email classification assistant. Respond only with valid JSON.",
                    },
                    {"role": "user", "content": full_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Extract text from response
            response_text = response.choices[0].message.content

            # Parse the response using shared utility
            labels = parse_labels_from_response(response_text, available_labels)

            # Log result
            log_classification_result(email, labels, self.provider_name)

            return labels

        except ImportError:
            logger.error(
                "openai package not installed. Install with: pip install openai"
            )
            return []
        except Exception as e:
            logger.error(
                f"Error classifying email via {self.provider_name}: {e}", exc_info=True
            )
            return []
