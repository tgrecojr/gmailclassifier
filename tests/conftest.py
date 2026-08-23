"""
Shared test fixtures and configurations for pytest.
"""

import pytest
import json
import os
from typing import Dict, List

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
