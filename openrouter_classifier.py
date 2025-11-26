"""
OpenRouter LLM classifier implementation.

Uses OpenRouter API (OpenAI-compatible) to classify emails.
"""

import logging
from typing import List, Dict
from llm_utils import (
    construct_email_content,
    construct_classification_prompt,
    parse_labels_from_response,
    log_classification_result,
)

logger = logging.getLogger(__name__)


class OpenRouterClassifier:
    """OpenRouter API implementation for email classification."""

    def __init__(self, api_key: str, model: str = "anthropic/claude-3.5-sonnet"):
        """
        Initialize OpenRouter classifier.

        Args:
            api_key: OpenRouter API key
            model: Model ID (default: anthropic/claude-3.5-sonnet)
                   See https://openrouter.ai/docs for available models
        """
        try:
            import openai

            self.client = openai.OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            self.model = model
            logger.info(f"Initialized OpenRouter classifier with model: {model}")
        except ImportError:
            raise ImportError(
                "openai package is required for OpenRouter. "
                "Install it with: pip install openai"
            )

    def classify_email(
        self, email: Dict, classification_prompt: str, available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using OpenRouter API.

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

            # Call OpenRouter API (OpenAI-compatible)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an email classification assistant. Respond only with valid JSON.",
                    },
                    {"role": "user", "content": full_prompt},
                ],
                temperature=0.1,  # Low temperature for more deterministic classification
                max_tokens=1000,
            )

            # Extract text from response
            response_text = response.choices[0].message.content

            # Parse the response using shared utility
            labels = parse_labels_from_response(response_text, available_labels)

            # Log result
            log_classification_result(email, labels, "OpenRouter")

            return labels

        except ImportError:
            logger.error(
                "openai package not installed. Install with: pip install openai"
            )
            return []
        except Exception as e:
            logger.error(f"Error classifying email with OpenRouter: {e}", exc_info=True)
            return []
