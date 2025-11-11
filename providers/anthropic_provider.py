"""
Anthropic Direct API LLM Provider implementation.
"""

import logging
from typing import List, Dict
from llm_provider import LLMProvider
from llm_utils import (
    construct_email_content,
    construct_classification_prompt,
    parse_labels_from_response,
    log_classification_result
)

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Direct API implementation of LLMProvider."""

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        """
        Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
            model: Model ID (default: claude-3-5-sonnet-20241022)
        """
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = model
            logger.info(f"Initialized Anthropic provider with model: {model}")
        except ImportError:
            raise ImportError(
                "anthropic package is required for AnthropicProvider. "
                "Install it with: pip install anthropic"
            )

    def classify_email(
        self,
        email: Dict,
        classification_prompt: str,
        available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using Anthropic Direct API.

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
                classification_prompt,
                available_labels,
                email_content
            )

            # Call Anthropic API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                temperature=0.1,  # Low temperature for more deterministic classification
                messages=[
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ]
            )

            # Extract text from response
            response_text = response.content[0].text

            # Parse the response using shared utility
            labels = parse_labels_from_response(response_text, available_labels)

            # Log result
            log_classification_result(email, labels, "Anthropic")

            return labels

        except ImportError:
            logger.error("anthropic package not installed. Install with: pip install anthropic")
            return []
        except Exception as e:
            logger.error(f"Error classifying email with Anthropic: {e}", exc_info=True)
            return []
