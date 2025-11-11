"""
Ollama Local LLM Provider implementation.
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


class OllamaProvider(LLMProvider):
    """Ollama local LLM implementation of LLMProvider."""

    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        """
        Initialize Ollama provider.

        Args:
            model: Model name (default: llama3)
            base_url: Ollama API base URL (default: http://localhost:11434)
        """
        try:
            import ollama
            self.client = ollama.Client(host=base_url)
            self.model = model
            logger.info(f"Initialized Ollama provider with model: {model} at {base_url}")
        except ImportError:
            raise ImportError(
                "ollama package is required for OllamaProvider. "
                "Install it with: pip install ollama"
            )

    def classify_email(
        self,
        email: Dict,
        classification_prompt: str,
        available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using Ollama local LLM.

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

            # Call Ollama API
            response = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                options={
                    "temperature": 0.1,  # Low temperature for more deterministic classification
                    "num_predict": 500,
                }
            )

            # Extract text from response
            response_text = response['message']['content']

            # Parse the response using shared utility
            labels = parse_labels_from_response(response_text, available_labels)

            # Log result
            log_classification_result(email, labels, "Ollama")

            return labels

        except ImportError:
            logger.error("ollama package not installed. Install with: pip install ollama")
            return []
        except Exception as e:
            logger.error(f"Error classifying email with Ollama: {e}", exc_info=True)
            return []
