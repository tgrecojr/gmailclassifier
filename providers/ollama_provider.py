"""
Ollama Local LLM Provider implementation.
"""

import json
import logging
from typing import List, Dict
from llm_provider import LLMProvider

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
            # Construct the prompt with email content
            email_content = f"""
Subject: {email.get('subject', 'No Subject')}
From: {email.get('from', 'Unknown')}
Date: {email.get('date', 'Unknown')}

Body:
{email.get('body', email.get('snippet', 'No content'))}
"""

            full_prompt = f"""{classification_prompt}

Available labels: {', '.join(available_labels)}

Email to classify:
{email_content}

Respond with ONLY a JSON object containing a "labels" array with the applicable label names. Example: {{"labels": ["Work", "Urgent"]}}
Do not include any other text or explanation.
"""

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

            # Parse the response to extract labels
            labels = self._parse_labels_from_response(response_text, available_labels)

            logger.info(f"Classified email '{email.get('subject', 'No Subject')}' with labels: {labels}")
            return labels

        except Exception as e:
            logger.error(f"Error classifying email with Ollama: {e}")
            return []

    def _parse_labels_from_response(self, response: str, available_labels: List[str]) -> List[str]:
        """
        Parse labels from the model response.

        Args:
            response: Raw response from the model
            available_labels: List of valid label names

        Returns:
            List of applicable labels
        """
        try:
            # Try to find JSON in the response
            response = response.strip()

            # If response starts with ```json, remove the code block markers
            if response.startswith('```'):
                lines = response.split('\n')
                response = '\n'.join(lines[1:-1]) if len(lines) > 2 else response

            # Parse JSON
            data = json.loads(response)

            # Extract labels
            if isinstance(data, dict) and 'labels' in data:
                labels = data['labels']
            elif isinstance(data, list):
                labels = data
            else:
                logger.warning(f"Unexpected response format: {response}")
                return []

            # Validate labels against available labels
            valid_labels = [label for label in labels if label in available_labels]

            if len(valid_labels) != len(labels):
                invalid = set(labels) - set(valid_labels)
                logger.warning(f"Model returned invalid labels: {invalid}")

            return valid_labels

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {response}. Error: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing labels: {e}")
            return []
