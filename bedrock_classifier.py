import json
import boto3
import logging
from typing import List, Dict
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BedrockClassifier:
    """Client for classifying emails using AWS Bedrock."""

    def __init__(self, region: str, model_id: str, aws_access_key_id: str = None, aws_secret_access_key: str = None):
        """
        Initialize Bedrock client.

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
                'bedrock-runtime',
                region_name=region,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key
            )
        else:
            # Use default credential chain (environment variables, IAM role, etc.)
            self.client = boto3.client('bedrock-runtime', region_name=region)

        logger.info(f"Initialized Bedrock client with model: {model_id}")

    def classify_email(self, email: Dict, classification_prompt: str, available_labels: List[str]) -> List[str]:
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

Respond with ONLY a JSON object containing a "labels" array with the applicable label names. Example: {{"labels": ["AWS", "Github"]}}
"""

            # Call Bedrock with Claude model
            response = self._invoke_bedrock(full_prompt)

            # Parse the response to extract labels
            labels = self._parse_labels_from_response(response, available_labels)

            logger.info(f"Classified email '{email.get('subject', 'No Subject')}' with labels: {labels}")
            return labels

        except Exception as e:
            logger.error(f"Error classifying email: {e}")
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
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1  # Low temperature for more deterministic classification
            }

            # Invoke the model
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )

            # Parse response
            response_body = json.loads(response['body'].read())

            # Extract text from Claude's response
            if 'content' in response_body and len(response_body['content']) > 0:
                return response_body['content'][0]['text']
            else:
                logger.error("Unexpected response format from Bedrock")
                return ""

        except ClientError as e:
            logger.error(f"AWS Bedrock API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Error invoking Bedrock: {e}")
            raise

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
