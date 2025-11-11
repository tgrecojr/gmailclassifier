"""
Unit tests for llm_utils.py

Tests cover:
- Email content construction
- Classification prompt construction
- JSON parsing edge cases
- Label validation
- Case-insensitive matching
"""

import pytest
import json
from llm_utils import (
    construct_email_content,
    construct_classification_prompt,
    parse_labels_from_response,
    log_classification_result
)


class TestConstructEmailContent:
    """Test email content construction."""

    def test_complete_email(self):
        """Test formatting a complete email with all fields."""
        email = {
            'subject': 'Test Subject',
            'from': 'test@example.com',
            'date': '2025-01-11',
            'body': 'This is the email body'
        }

        result = construct_email_content(email)

        assert 'Subject: Test Subject' in result
        assert 'From: test@example.com' in result
        assert 'Date: 2025-01-11' in result
        assert 'Body:\nThis is the email body' in result

    def test_missing_subject(self):
        """Test email with missing subject."""
        email = {
            'from': 'test@example.com',
            'date': '2025-01-11',
            'body': 'Body text'
        }

        result = construct_email_content(email)

        assert 'Subject: No Subject' in result

    def test_missing_sender(self):
        """Test email with missing sender."""
        email = {
            'subject': 'Test',
            'date': '2025-01-11',
            'body': 'Body text'
        }

        result = construct_email_content(email)

        assert 'From: Unknown' in result

    def test_missing_date(self):
        """Test email with missing date."""
        email = {
            'subject': 'Test',
            'from': 'test@example.com',
            'body': 'Body text'
        }

        result = construct_email_content(email)

        assert 'Date: Unknown' in result

    def test_snippet_instead_of_body(self):
        """Test using snippet when body is not available."""
        email = {
            'subject': 'Test',
            'from': 'test@example.com',
            'date': '2025-01-11',
            'snippet': 'This is a snippet'
        }

        result = construct_email_content(email)

        assert 'This is a snippet' in result

    def test_no_body_or_snippet(self):
        """Test email with no body or snippet."""
        email = {
            'subject': 'Test',
            'from': 'test@example.com',
            'date': '2025-01-11'
        }

        result = construct_email_content(email)

        assert 'Body:\nNo content' in result


class TestConstructClassificationPrompt:
    """Test classification prompt construction."""

    def test_prompt_includes_all_components(self):
        """Test that prompt includes instructions, labels, and email."""
        classification_prompt = "Classify this email into categories."
        available_labels = ["Work", "Personal", "Finance"]
        email_content = "Subject: Test\nFrom: test@example.com"

        result = construct_classification_prompt(
            classification_prompt,
            available_labels,
            email_content
        )

        assert "Classify this email into categories." in result
        assert "Work, Personal, Finance" in result
        assert "Subject: Test" in result
        assert "JSON" in result

    def test_prompt_with_many_labels(self):
        """Test prompt with many labels."""
        classification_prompt = "Classify"
        available_labels = [f"Label{i}" for i in range(20)]
        email_content = "Test email"

        result = construct_classification_prompt(
            classification_prompt,
            available_labels,
            email_content
        )

        for label in available_labels:
            assert label in result


class TestParseLabelsParsing:
    """Test JSON parsing edge cases."""

    @pytest.fixture
    def available_labels(self):
        """Standard set of available labels for testing."""
        return ["AWS", "Finance", "Work", "Personal"]

    def test_plain_json_object(self, available_labels):
        """Test parsing plain JSON object."""
        response = '{"labels": ["AWS", "Finance"]}'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_json_in_markdown_code_block(self, available_labels):
        """Test parsing JSON in markdown code block."""
        response = '''```json
{"labels": ["AWS", "Finance"]}
```'''

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_json_in_code_block_without_language(self, available_labels):
        """Test parsing JSON in code block without language specifier."""
        response = '''```
{"labels": ["AWS", "Finance"]}
```'''

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_json_with_text_before(self, available_labels):
        """Test parsing JSON with explanatory text before."""
        response = 'Here are the labels: {"labels": ["AWS", "Finance"]}'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_json_with_text_after(self, available_labels):
        """Test parsing JSON with text after."""
        response = '{"labels": ["AWS", "Finance"]} These are the most relevant labels.'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_json_with_text_before_and_after(self, available_labels):
        """Test parsing JSON with text on both sides."""
        response = 'Based on analysis: {"labels": ["AWS", "Finance"]} Hope this helps!'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_json_array_format(self, available_labels):
        """Test parsing JSON array directly."""
        response = '["AWS", "Finance"]'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_invalid_json(self, available_labels):
        """Test handling invalid JSON."""
        response = '{"labels": ["AWS", "Finance"'  # Missing closing brackets

        result = parse_labels_from_response(response, available_labels)

        assert result == []

    def test_json_with_wrong_structure(self, available_labels):
        """Test handling JSON with wrong structure."""
        response = '{"results": ["AWS", "Finance"]}'  # Wrong key

        result = parse_labels_from_response(response, available_labels)

        assert result == []

    def test_json_with_non_string_labels(self, available_labels):
        """Test handling non-string labels in array."""
        response = '{"labels": ["AWS", 123, "Finance", null]}'

        result = parse_labels_from_response(response, available_labels)

        # Should filter out non-string values
        assert result == ["AWS", "Finance"]

    def test_case_insensitive_matching(self, available_labels):
        """Test case-insensitive label matching."""
        response = '{"labels": ["aws", "FINANCE", "Work"]}'

        result = parse_labels_from_response(response, available_labels)

        # Should match with proper casing
        assert "AWS" in result
        assert "Finance" in result
        assert "Work" in result

    def test_invalid_labels_filtered_out(self, available_labels):
        """Test that invalid labels are filtered out."""
        response = '{"labels": ["AWS", "InvalidLabel", "Finance"]}'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]
        assert "InvalidLabel" not in result

    def test_empty_labels_array(self, available_labels):
        """Test handling empty labels array."""
        response = '{"labels": []}'

        result = parse_labels_from_response(response, available_labels)

        assert result == []

    def test_labels_field_not_a_list(self, available_labels):
        """Test handling labels field that's not a list."""
        response = '{"labels": "AWS"}'

        result = parse_labels_from_response(response, available_labels)

        assert result == []

    def test_multiline_json_in_code_block(self, available_labels):
        """Test parsing multiline JSON in code block."""
        response = '''```json
{
  "labels": [
    "AWS",
    "Finance"
  ]
}
```'''

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_nested_json_extraction(self, available_labels):
        """Test extracting JSON from complex response."""
        response = '''The email discusses AWS billing and financial matters.

Based on this analysis: {"labels": ["AWS", "Finance"]}

These labels indicate the primary topics.'''

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_whitespace_handling(self, available_labels):
        """Test handling of extra whitespace."""
        response = '''

        {"labels": ["AWS", "Finance"]}

        '''

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_unicode_in_response(self, available_labels):
        """Test handling Unicode characters in response."""
        response = '{"labels": ["AWS", "Finance"]} ✓'

        result = parse_labels_from_response(response, available_labels)

        assert result == ["AWS", "Finance"]

    def test_duplicate_labels(self, available_labels):
        """Test handling duplicate labels in response."""
        response = '{"labels": ["AWS", "AWS", "Finance"]}'

        result = parse_labels_from_response(response, available_labels)

        # Should include duplicates (let caller handle deduplication if needed)
        assert result == ["AWS", "AWS", "Finance"]


class TestLogClassificationResult:
    """Test classification result logging."""

    def test_log_with_labels(self, caplog):
        """Test logging when labels are predicted."""
        import logging
        caplog.set_level(logging.INFO)

        email = {'subject': 'Test Email Subject'}
        labels = ['AWS', 'Finance']
        provider = 'TestProvider'

        log_classification_result(email, labels, provider)

        assert 'TestProvider' in caplog.text
        assert 'Test Email Subject' in caplog.text
        assert 'AWS' in caplog.text
        assert 'Finance' in caplog.text

    def test_log_without_labels(self, caplog):
        """Test logging when no labels are predicted."""
        import logging
        caplog.set_level(logging.WARNING)

        email = {'subject': 'Test Email'}
        labels = []
        provider = 'TestProvider'

        log_classification_result(email, labels, provider)

        assert 'No labels predicted' in caplog.text

    def test_log_with_long_subject(self, caplog):
        """Test logging with long email subject (should be truncated)."""
        import logging
        caplog.set_level(logging.INFO)

        email = {'subject': 'A' * 100}
        labels = ['AWS']
        provider = 'TestProvider'

        log_classification_result(email, labels, provider)

        # Should truncate at 50 chars
        assert caplog.text.count('A') <= 53  # 50 + '...'

    def test_log_with_no_subject(self, caplog):
        """Test logging when email has no subject."""
        import logging
        caplog.set_level(logging.INFO)

        email = {}
        labels = ['AWS']
        provider = 'TestProvider'

        log_classification_result(email, labels, provider)

        assert 'No Subject' in caplog.text
