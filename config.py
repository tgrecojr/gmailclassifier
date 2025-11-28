import os
import json
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


def load_model_config(config_path: str) -> dict:
    """
    Load model configuration from JSON file.

    Args:
        config_path: Path to the model configuration JSON file

    Returns:
        Dictionary containing 'model', 'temperature', and 'max_tokens'

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Model config file not found: {config_path}\n"
            f"Please create it or copy from model_config.example.json"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Validate required fields
        if "model" not in config:
            raise ValueError("Config file must contain 'model' field")
        if "temperature" not in config:
            raise ValueError("Config file must contain 'temperature' field")
        if "max_tokens" not in config:
            raise ValueError("Config file must contain 'max_tokens' field")
        if not isinstance(config["model"], str):
            raise ValueError("'model' must be a string")
        if not isinstance(config["temperature"], (int, float)):
            raise ValueError("'temperature' must be a number")
        if not isinstance(config["max_tokens"], int):
            raise ValueError("'max_tokens' must be an integer")
        if config["temperature"] < 0 or config["temperature"] > 2:
            raise ValueError("'temperature' must be between 0 and 2")
        if config["max_tokens"] <= 0:
            raise ValueError("'max_tokens' must be greater than 0")

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

# OpenRouter API Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Model Configuration - Load from file if available, otherwise from env vars
MODEL_CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH")

if MODEL_CONFIG_PATH:
    try:
        _model_config = load_model_config(MODEL_CONFIG_PATH)
        OPENROUTER_MODEL = _model_config["model"]
        OPENROUTER_TEMPERATURE = _model_config["temperature"]
        OPENROUTER_MAX_TOKENS = _model_config["max_tokens"]
        print(f"Loaded model configuration from {MODEL_CONFIG_PATH}")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading model config: {e}")
        print("Falling back to environment variables.")
        OPENROUTER_MODEL = os.getenv(
            "OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"
        )
        OPENROUTER_TEMPERATURE = float(
            os.getenv("OPENROUTER_TEMPERATURE", "0.0")
        )
        OPENROUTER_MAX_TOKENS = int(
            os.getenv("OPENROUTER_MAX_TOKENS", "1000")
        )
else:
    # Fallback to environment variables
    OPENROUTER_MODEL = os.getenv(
        "OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"
    )
    OPENROUTER_TEMPERATURE = float(
        os.getenv("OPENROUTER_TEMPERATURE", "0.0")
    )
    OPENROUTER_MAX_TOKENS = int(
        os.getenv("OPENROUTER_MAX_TOKENS", "1000")
    )

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
