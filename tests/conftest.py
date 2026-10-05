"""
Shared test fixtures and configurations for pytest.
"""

import json
import os
import tempfile
from typing import Dict, List

import pytest

# Sample test data
TEST_EMAIL = {
    "id": "test123",
    "subject": "AWS Billing Alert",
    "from": "aws-billing@amazon.com",
    "date": "2025-01-11",
    "body": "Your AWS bill for January is $50.00. Visit the billing dashboard for details.",
}

TEST_LABELS = ["AWS", "Finance", "Work", "Personal"]

TEST_LABEL_DESCRIPTIONS = {
    "AWS": "Notifications, billing and alerts from Amazon Web Services",
    "Finance": "Bank statements, bills, invoices and payment confirmations",
    "Work": "Professional correspondence, meetings and project updates",
    "Personal": "Messages from friends and family",
}

_config_dir: tempfile.TemporaryDirectory | None = None


def pytest_configure(config):
    """
    Point CLASSIFIER_CONFIG_PATH at a throwaway classifier config before test
    collection, so importing `config` works without a developer's real file
    (and never reads it).
    """
    global _config_dir
    _config_dir = tempfile.TemporaryDirectory(prefix="gmailclassifier-tests-")
    path = os.path.join(_config_dir.name, "classifier_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"labels": TEST_LABELS, "label_descriptions": TEST_LABEL_DESCRIPTIONS},
            f,
            indent=2,
        )
    os.environ["CLASSIFIER_CONFIG_PATH"] = path


def pytest_unconfigure(config):
    """Cleanup the throwaway classifier config."""
    global _config_dir
    if _config_dir is not None:
        _config_dir.cleanup()
        _config_dir = None


@pytest.fixture
def test_email() -> Dict:
    """Sample test email."""
    return TEST_EMAIL.copy()


@pytest.fixture
def test_labels() -> List[str]:
    """Sample test labels."""
    return TEST_LABELS.copy()


@pytest.fixture
def test_label_descriptions() -> Dict[str, str]:
    """Sample per-label descriptions."""
    return dict(TEST_LABEL_DESCRIPTIONS)
