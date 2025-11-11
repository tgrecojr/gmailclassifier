"""
AWS Bedrock LLM Provider implementation.
"""

import json
import boto3
import logging
from typing import List, Dict
from botocore.exceptions import ClientError
from llm_provider import LLMProvider
from llm_utils import (
    construct_email_content,
    construct_classification_prompt,
    parse_labels_from_response,
    log_classification_result,
)

logger = logging.getLogger(__name__)


class BedrockProvider(LLMProvider):
    """AWS Bedrock implementation of LLMProvider."""

    def __init__(
        self,
        region: str,
        model_id: str,
        aws_access_key_id: str = None,
        aws_secret_access_key: str = None,
    ):
        """
        Initialize Bedrock provider.

        Args:
            region: AWS region
            model_id: Bedrock model ID
            aws_access_key_id: AWS access key (optional, can use environment variables)
            aws_secret_access_key: AWS secret key (optional, can use environment variables)
        """
        self.model_id = model_id

        # Create boto3 client
        if aws_access_key_id and aws_secret_access_key:
            self.client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )
        else:
            # Use default credential chain (environment variables, IAM role, etc.)
            self.client = boto3.client("bedrock-runtime", region_name=region)

        logger.info(f"Initialized Bedrock provider with model: {model_id}")

    def classify_email(
        self, email: Dict, classification_prompt: str, available_labels: List[str]
    ) -> List[str]:
        """
        Classify an email using AWS Bedrock.

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
                classification_prompt, available_labels, email_content
            )

            # Call Bedrock with Claude model
            response = self._invoke_bedrock(full_prompt)

            # Parse the response using shared utility
            labels = parse_labels_from_response(response, available_labels)

            # Log result
            log_classification_result(email, labels, "Bedrock")

            return labels

        except ClientError as e:
            logger.error(f"AWS Bedrock API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Error classifying email with Bedrock: {e}", exc_info=True)
            return []

    def _invoke_bedrock(self, prompt: str) -> str:
        """
        Invoke AWS Bedrock with the given prompt.

        Args:
            prompt: The prompt to send to the model

        Returns:
            Model response text
        """
        try:
            # Request body for Claude models on Bedrock
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,  # Low temperature for more deterministic classification
            }

            # Invoke the model
            response = self.client.invoke_model(
                modelId=self.model_id, body=json.dumps(request_body)
            )

            # Parse response
            response_body = json.loads(response["body"].read())

            # Extract text from Claude's response
            if "content" in response_body and len(response_body["content"]) > 0:
                return response_body["content"][0]["text"]
            else:
                logger.error("Unexpected response format from Bedrock")
                return ""

        except ClientError as e:
            logger.error(f"AWS Bedrock API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error invoking Bedrock: {e}")
            raise
