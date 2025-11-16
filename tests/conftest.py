"""
Shared test fixtures and configurations for pytest.
"""

import pytest
import json
import os
from typing import Dict, List
from unittest.mock import Mock


# Sample test data
TEST_EMAIL = {
    "id": "test123",
    "subject": "AWS Billing Alert",
    "from": "aws-billing@amazon.com",
    "date": "2025-01-11",
    "body": "Your AWS bill for January is $50.00. Visit the billing dashboard for details.",
}

TEST_LABELS = ["AWS", "Finance", "Work", "Personal"]

TEST_CLASSIFICATION_PROMPT = """Classify this email into one or more categories.
Consider the sender, subject, and content to determine the most appropriate labels."""


# Global flag to track if we created the config file
_created_test_config = False


def pytest_configure(config):
    """
    Create classifier_config.json before test collection.

    This runs before pytest starts collecting tests, ensuring the config
    module can import successfully in CI environments where
    classifier_config.json doesn't exist.
    """
    global _created_test_config
    config_path = "classifier_config.json"

    if not os.path.exists(config_path):
        test_config = {
            "labels": TEST_LABELS,
            "classification_prompt": TEST_CLASSIFICATION_PROMPT,
        }
        with open(config_path, "w") as f:
            json.dump(test_config, f, indent=2)
        _created_test_config = True


def pytest_unconfigure(config):
    """
    Cleanup: remove test classifier_config.json if we created it.
    """
    global _created_test_config
    config_path = "classifier_config.json"

    if _created_test_config and os.path.exists(config_path):
        os.unlink(config_path)
        _created_test_config = False


@pytest.fixture
def test_email() -> Dict:
    """Sample test email."""
    return TEST_EMAIL.copy()


@pytest.fixture
def test_labels() -> List[str]:
    """Sample test labels."""
    return TEST_LABELS.copy()


@pytest.fixture
def classification_prompt() -> str:
    """Sample classification prompt."""
    return TEST_CLASSIFICATION_PROMPT


# Mock responses for each provider
class MockResponses:
    """Mock LLM API responses."""

    @staticmethod
    def bedrock_success() -> Dict:
        """Mock successful Bedrock response."""
        return {
            "body": Mock(
                read=lambda: b'{"content": [{"text": "{\\"labels\\": [\\"AWS\\", \\"Finance\\"]}"}]}'
            )
        }

    @staticmethod
    def anthropic_success() -> Mock:
        """Mock successful Anthropic response."""
        response = Mock()
        content_block = Mock()
        content_block.text = '{"labels": ["AWS", "Finance"]}'
        response.content = [content_block]
        return response

    @staticmethod
    def openai_success() -> Mock:
        """Mock successful OpenAI response."""
        response = Mock()
        choice = Mock()
        message = Mock()
        message.content = '{"labels": ["AWS", "Finance"]}'
        choice.message = message
        response.choices = [choice]
        return response

    @staticmethod
    def ollama_success() -> Dict:
        """Mock successful Ollama response."""
        return {"message": {"content": '{"labels": ["AWS", "Finance"]}'}}

    @staticmethod
    def response_with_markdown() -> str:
        """Mock response with markdown code block."""
        return """```json
{"labels": ["AWS", "Finance"]}
```"""

    @staticmethod
    def response_with_text() -> str:
        """Mock response with extra text."""
        return 'Based on the email content: {"labels": ["AWS", "Finance"]}'

    @staticmethod
    def response_invalid_json() -> str:
        """Mock response with invalid JSON."""
        return '{"labels": ["AWS", "Finance"'

    @staticmethod
    def response_invalid_labels() -> str:
        """Mock response with invalid labels."""
        return '{"labels": ["AWS", "InvalidLabel", "Finance"]}'


@pytest.fixture
def mock_responses():
    """Fixture providing mock responses."""
    return MockResponses


@pytest.fixture
def mock_config():
    """Mock config module."""
    config = Mock()
    config.LLM_PROVIDER = "bedrock"
    config.AWS_REGION = "us-east-1"
    config.AWS_ACCESS_KEY_ID = None
    config.AWS_SECRET_ACCESS_KEY = None
    config.BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    config.ANTHROPIC_API_KEY = "test-key"
    config.ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
    config.OPENAI_API_KEY = "test-key"
    config.OPENAI_MODEL = "gpt-4-turbo"
    config.OLLAMA_MODEL = "llama3"
    config.OLLAMA_BASE_URL = "http://localhost:11434"
    return config
