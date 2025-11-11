"""
Abstract base class for LLM providers.

This module defines the interface that all LLM providers must implement
to be compatible with the Gmail Email Classifier.
"""

from abc import ABC, abstractmethod
from typing import Dict, List


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def classify_email(
        self, email: Dict, classification_prompt: str, available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using the LLM provider.

        Args:
            email: Email dictionary with keys:
                - subject: Email subject line
                - body: Email body content
                - sender: Sender email address
                - date: Email date
            classification_prompt: The classification instructions
            available_labels: List of valid label names

        Returns:
            List of predicted label names (must be subset of available_labels)

        Raises:
            Exception: If classification fails
        """
        pass
