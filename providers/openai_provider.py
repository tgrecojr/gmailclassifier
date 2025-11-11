"""
OpenAI API LLM Provider implementation.
"""

import logging
from typing import List, Dict
from llm_provider import LLMProvider
from llm_utils import (
    construct_email_content,
    construct_classification_prompt,
    parse_labels_from_response,
    log_classification_result,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """OpenAI API implementation of LLMProvider."""

    def __init__(self, api_key: str, model: str = "gpt-4-turbo"):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            model: Model ID (default: gpt-4-turbo)
        """
        try:
            import openai

            self.client = openai.OpenAI(api_key=api_key)
            self.model = model
            logger.info(f"Initialized OpenAI provider with model: {model}")
        except ImportError:
            raise ImportError(
                "openai package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            )

    def classify_email(
        self, email: Dict, classification_prompt: str, available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using OpenAI API.

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

            # Call OpenAI API
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
                response_format={"type": "json_object"},  # Force JSON response
            )

            # Extract text from response
            response_text = response.choices[0].message.content

            # Parse the response using shared utility
            labels = parse_labels_from_response(response_text, available_labels)

            # Log result
            log_classification_result(email, labels, "OpenAI")

            return labels

        except ImportError:
            logger.error(
                "openai package not installed. Install with: pip install openai"
            )
            return []
        except Exception as e:
            logger.error(f"Error classifying email with OpenAI: {e}", exc_info=True)
            return []
