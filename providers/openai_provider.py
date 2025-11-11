"""
OpenAI API LLM Provider implementation.
"""

import json
import logging
from typing import List, Dict
from llm_provider import LLMProvider

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
        self,
        email: Dict,
        classification_prompt: str,
        available_labels: List[str]
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
"""

            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an email classification assistant. Respond only with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ],
                temperature=0.1,  # Low temperature for more deterministic classification
                max_tokens=1000,
                response_format={"type": "json_object"}  # Force JSON response
            )

            # Extract text from response
            response_text = response.choices[0].message.content

            # Parse the response to extract labels
            labels = self._parse_labels_from_response(response_text, available_labels)

            logger.info(f"Classified email '{email.get('subject', 'No Subject')}' with labels: {labels}")
            return labels

        except Exception as e:
            logger.error(f"Error classifying email with OpenAI: {e}")
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
