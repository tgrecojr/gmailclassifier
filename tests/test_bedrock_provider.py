"""
Unit tests for BedrockProvider.

Tests cover:
- Successful classification
- Error handling
- JSON parsing edge cases
- API errors
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from botocore.exceptions import ClientError
import json


@pytest.mark.unit
class TestBedrockProvider:
    """Tests for AWS Bedrock provider."""

    @patch('boto3.client')
    def test_init_with_credentials(self, mock_boto_client):
        """Test initialization with explicit credentials."""
        from providers.bedrock_provider import BedrockProvider

        provider = BedrockProvider(
            region="us-east-1",
            model_id="test-model",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret"
        )

        mock_boto_client.assert_called_once_with(
            'bedrock-runtime',
            region_name="us-east-1",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret"
        )
        assert provider.model_id == "test-model"

    @patch('boto3.client')
    def test_init_without_credentials(self, mock_boto_client):
        """Test initialization using environment credentials."""
        from providers.bedrock_provider import BedrockProvider

        provider = BedrockProvider(
            region="us-west-2",
            model_id="test-model"
        )

        mock_boto_client.assert_called_once_with(
            'bedrock-runtime',
            region_name="us-west-2"
        )

    @patch('boto3.client')
    def test_classify_email_success(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test successful email classification."""
        from providers.bedrock_provider import BedrockProvider

        # Mock the Bedrock response
        mock_client = Mock()
        mock_body = Mock()
        mock_body.read.return_value = b'{"content": [{"text": "{\\"labels\\": [\\"AWS\\", \\"Finance\\"]}"}]}'
        mock_client.invoke_model.return_value = {'body': mock_body}
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert result == ["AWS", "Finance"]
        assert mock_client.invoke_model.called

    @patch('boto3.client')
    def test_classify_email_with_markdown_response(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test classification with markdown code block in response."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_body = Mock()
        response_text = '```json\\n{\\"labels\\": [\\"AWS\\", \\"Finance\\"]}\\n```'
        mock_body.read.return_value = f'{{"content": [{{"text": "{response_text}"}}]}}'.encode()
        mock_client.invoke_model.return_value = {'body': mock_body}
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert "AWS" in result
        assert "Finance" in result

    @patch('boto3.client')
    def test_classify_email_invalid_json(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test handling of invalid JSON response."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_body = Mock()
        mock_body.read.return_value = b'{"content": [{"text": "invalid json"}]}'
        mock_client.invoke_model.return_value = {'body': mock_body}
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert result == []

    @patch('boto3.client')
    def test_classify_email_client_error(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test handling of Bedrock API error."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_client.invoke_model.side_effect = ClientError(
            {'Error': {'Code': 'ThrottlingException', 'Message': 'Rate exceeded'}},
            'InvokeModel'
        )
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert result == []

    @patch('boto3.client')
    def test_classify_email_connection_error(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test handling of connection error."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_client.invoke_model.side_effect = Exception("Connection timeout")
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert result == []

    @patch('boto3.client')
    def test_classify_email_filters_invalid_labels(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test that invalid labels are filtered out."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_body = Mock()
        mock_body.read.return_value = b'{"content": [{"text": "{\\"labels\\": [\\"AWS\\", \\"InvalidLabel\\", \\"Finance\\"]}"}]}'
        mock_client.invoke_model.return_value = {'body': mock_body}
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert "AWS" in result
        assert "Finance" in result
        assert "InvalidLabel" not in result

    @patch('boto3.client')
    def test_classify_email_case_insensitive(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test case-insensitive label matching."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_body = Mock()
        mock_body.read.return_value = b'{"content": [{"text": "{\\"labels\\": [\\"aws\\", \\"FINANCE\\"]}"}]}'
        mock_client.invoke_model.return_value = {'body': mock_body}
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert "AWS" in result
        assert "Finance" in result

    @patch('boto3.client')
    def test_classify_email_empty_response(self, mock_boto_client, test_email, test_labels, classification_prompt):
        """Test handling of empty labels in response."""
        from providers.bedrock_provider import BedrockProvider

        mock_client = Mock()
        mock_body = Mock()
        mock_body.read.return_value = b'{"content": [{"text": "{\\"labels\\": []}"}]}'
        mock_client.invoke_model.return_value = {'body': mock_body}
        mock_boto_client.return_value = mock_client

        provider = BedrockProvider(region="us-east-1", model_id="test-model")
        result = provider.classify_email(test_email, classification_prompt, test_labels)

        assert result == []
