import os
import json
from typing import List
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def load_classifier_config(config_path: str) -> dict:
    """
    Load classifier configuration from JSON file.

    Args:
        config_path: Path to the classifier configuration JSON file

    Returns:
        Dictionary containing 'labels' and 'classification_prompt'

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Classifier config file not found: {config_path}\n"
            f"Please create it or copy from classifier_config.example.json"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Validate required fields
        if "labels" not in config:
            raise ValueError("Config file must contain 'labels' field")
        if "classification_prompt" not in config:
            raise ValueError("Config file must contain 'classification_prompt' field")
        if not isinstance(config["labels"], list):
            raise ValueError("'labels' must be a list")
        if not isinstance(config["classification_prompt"], str):
            raise ValueError("'classification_prompt' must be a string")
        if len(config["labels"]) == 0:
            raise ValueError("'labels' must contain at least one label")

        return config

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file: {e}")


# Classifier Configuration
CLASSIFIER_CONFIG_PATH = os.getenv("CLASSIFIER_CONFIG_PATH", "classifier_config.json")

# Load labels and classification prompt from config file
try:
    _classifier_config = load_classifier_config(CLASSIFIER_CONFIG_PATH)
    LABELS = _classifier_config["labels"]
    CLASSIFICATION_PROMPT = _classifier_config["classification_prompt"]
except (FileNotFoundError, ValueError) as e:
    print(f"Error loading classifier config: {e}")
    print("Please ensure classifier_config.json exists and is properly formatted.")
    raise

# LLM Provider Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "bedrock")

# AWS Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

# Anthropic API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

# OpenAI API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo")

# Ollama Configuration
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Gmail Configuration
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GMAIL_HEADLESS_MODE = os.getenv("GMAIL_HEADLESS_MODE", "false").lower() == "true"
REMOVE_FROM_INBOX = os.getenv("REMOVE_FROM_INBOX", "true").lower() == "true"

# Application Configuration
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
MAX_EMAILS_PER_POLL = int(os.getenv("MAX_EMAILS_PER_POLL", "10"))
STATE_FILE = os.getenv("STATE_FILE", ".email_state.json")
STATE_RETENTION_DAYS = int(os.getenv("STATE_RETENTION_DAYS", "30"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
