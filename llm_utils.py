"""
Shared utility functions for LLM providers.

This module contains common functionality used across all LLM providers
to reduce code duplication and ensure consistent behavior.
"""

import json
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


def construct_email_content(email: Dict) -> str:
    """
    Construct a formatted email content string from email dictionary.

    Args:
        email: Email dictionary with subject, from, date, body/snippet fields

    Returns:
        Formatted email content string
    """
    return f"""
Subject: {email.get('subject', 'No Subject')}
From: {email.get('from', 'Unknown')}
Date: {email.get('date', 'Unknown')}

Body:
{email.get('body', email.get('snippet', 'No content'))}
""".strip()


def construct_classification_prompt(
    classification_prompt: str,
    available_labels: List[str],
    email_content: str
) -> str:
    """
    Construct the full classification prompt for the LLM.

    Args:
        classification_prompt: Base classification instructions
        available_labels: List of valid label names
        email_content: Formatted email content

    Returns:
        Complete prompt for the LLM
    """
    return f"""{classification_prompt}

Available labels: {', '.join(available_labels)}

Email to classify:
{email_content}

Respond with ONLY a JSON object containing a "labels" array with the applicable label names. Example: {{"labels": ["Work", "Urgent"]}}
Do not include any other text or explanation."""


def parse_labels_from_response(response: str, available_labels: List[str]) -> List[str]:
    """
    Parse and validate labels from LLM response.

    This function handles various response formats:
    - Plain JSON object: {"labels": ["Work", "Personal"]}
    - JSON in markdown code blocks: ```json\n{...}\n```
    - JSON array: ["Work", "Personal"]
    - JSON with extra text before/after

    Args:
        response: Raw response text from LLM
        available_labels: List of valid label names for validation

    Returns:
        List of validated label names (subset of available_labels)
    """
    try:
        response = response.strip()

        # Remove markdown code block markers if present
        if '```' in response:
            # Extract content between code blocks
            code_block_pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
            match = re.search(code_block_pattern, response, re.DOTALL)
            if match:
                response = match.group(1).strip()
            else:
                # Fall back to removing just the markers
                response = response.replace('```json', '').replace('```', '').strip()

        # Try to find JSON object in the response (even if surrounded by text)
        json_pattern = r'\{[^{}]*"labels"[^{}]*\}'
        json_match = re.search(json_pattern, response, re.DOTALL)
        if json_match:
            response = json_match.group(0)

        # Parse JSON
        data = json.loads(response)

        # Extract labels from different formats
        if isinstance(data, dict) and 'labels' in data:
            labels = data['labels']
        elif isinstance(data, list):
            labels = data
        else:
            logger.warning(f"Unexpected JSON structure: {response[:200]}")
            return []

        # Ensure labels is a list
        if not isinstance(labels, list):
            logger.warning(f"Labels field is not a list: {type(labels)}")
            return []

        # Validate labels against available labels (case-insensitive)
        available_labels_lower = {label.lower(): label for label in available_labels}
        valid_labels = []

        for label in labels:
            if not isinstance(label, str):
                logger.warning(f"Non-string label found: {label} ({type(label)})")
                continue

            # Try exact match first
            if label in available_labels:
                valid_labels.append(label)
            # Try case-insensitive match
            elif label.lower() in available_labels_lower:
                valid_labels.append(available_labels_lower[label.lower()])
            else:
                logger.warning(f"Model returned invalid label: '{label}'")

        # Log if some labels were invalid
        if len(valid_labels) != len(labels):
            invalid = [l for l in labels if l not in valid_labels and isinstance(l, str)]
            if invalid:
                logger.warning(f"Filtered out invalid labels: {invalid}")

        return valid_labels

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from response: {response[:200]}... Error: {e}")
        # Try one more time to extract JSON from text
        try:
            # Look for any JSON-like structure
            json_like_pattern = r'\[[^\[\]]*\]|\{[^{}]*\}'
            matches = re.findall(json_like_pattern, response)
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, list):
                        return parse_labels_from_response(json.dumps({"labels": data}), available_labels)
                    elif isinstance(data, dict) and 'labels' in data:
                        return parse_labels_from_response(match, available_labels)
                except json.JSONDecodeError:
                    continue
        except Exception as fallback_error:
            logger.error(f"Fallback JSON parsing also failed: {fallback_error}")

        return []

    except Exception as e:
        logger.error(f"Unexpected error parsing labels: {e}", exc_info=True)
        return []


def log_classification_result(email: Dict, labels: List[str], provider: str):
    """
    Log the classification result in a consistent format.

    Args:
        email: Email dictionary
        labels: Predicted labels
        provider: Provider name for logging
    """
    subject = email.get('subject', 'No Subject')
    if labels:
        logger.info(f"[{provider}] Classified '{subject[:50]}...' with labels: {labels}")
    else:
        logger.warning(f"[{provider}] No labels predicted for '{subject[:50]}...'")
