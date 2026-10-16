import json
import os
from pathlib import Path

from dotenv import load_dotenv

from jev_classifier import DEFAULT_MODEL, validate_labels

# @spec AGENT-CFG-001
load_dotenv()


# @spec AGENT-CFG-002, AGENT-CFG-003, AGENT-CFG-004, AGENT-CFG-005, AGENT-CFG-006, AGENT-CFG-007
def load_classifier_config(config_path: str) -> dict:
    """
    Load classifier configuration from JSON file.

    Args:
        config_path: Path to the classifier configuration JSON file

    Returns:
        Dictionary containing 'labels' and 'label_descriptions'

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
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file: {e}")

    if "labels" not in config:
        raise ValueError("Config file must contain 'labels' field")
    if not isinstance(config["labels"], list) or not all(
        isinstance(label, str) and label.strip() for label in config["labels"]
    ):
        raise ValueError("'labels' must be a list of non-empty strings")
    if "label_descriptions" not in config:
        raise ValueError(
            "Config file must contain 'label_descriptions' field: one sentence per "
            "label describing what belongs under it (Jev never sees label names, "
            "only these descriptions)"
        )
    descriptions = config["label_descriptions"]
    if not isinstance(descriptions, dict) or not all(
        isinstance(text, str) for text in descriptions.values()
    ):
        raise ValueError("'label_descriptions' must map each label to a string")
    validate_labels(config["labels"], descriptions)
    return config


# @spec AGENT-CFG-010
def _float_env(name: str, default: float, low: float, high: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value


# @spec AGENT-CFG-014
def _int_env(name: str, default: int, low: int, high: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")
    return value


_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


# @spec AGENT-CFG-013
def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(
        f"{name} must be one of true/false, 1/0, yes/no, on/off; got {raw!r}"
    )


# Classifier Configuration
# @spec AGENT-CFG-002, AGENT-CFG-008
CLASSIFIER_CONFIG_PATH = os.getenv("CLASSIFIER_CONFIG_PATH", "classifier_config.json")

try:
    _classifier_config = load_classifier_config(CLASSIFIER_CONFIG_PATH)
    LABELS = _classifier_config["labels"]
    LABEL_DESCRIPTIONS = _classifier_config["label_descriptions"]
except (FileNotFoundError, ValueError) as e:
    print(f"Error loading classifier config: {e}")
    print("Please ensure classifier_config.json exists and is properly formatted.")
    raise

# OpenRouter API Configuration
# @spec AGENT-CFG-015
# OPENROUTER_API_KEY is sent as the bearer token to OpenRouter's decisions
# endpoint (jev_classifier.OPENROUTER_DECISIONS_URL). Fail at import rather
# than with an HTTP 401 on the first email.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
if not OPENROUTER_API_KEY:
    print("Error: OPENROUTER_API_KEY is not set.")
    print("Add it to the environment (see the example env file) and restart.")
    raise ValueError("OPENROUTER_API_KEY must be set")

# Jev (TypeSafe decisions model) Configuration
# @spec AGENT-CFG-009, AGENT-CFG-010, AGENT-CFG-011
JEV_MODEL = os.getenv("JEV_MODEL", "").strip() or DEFAULT_MODEL
# A label is applied when its yes/no probability reaches JEV_LABEL_THRESHOLD.
# If none does, the single best label is applied when the model's confidence
# in that choice reaches JEV_FALLBACK_CONFIDENCE (and the choice is not "None").
JEV_LABEL_THRESHOLD = _float_env("JEV_LABEL_THRESHOLD", 0.7, 0.0, 1.0)
JEV_FALLBACK_CONFIDENCE = _float_env("JEV_FALLBACK_CONFIDENCE", 0.5, 0.0, 1.0)
JEV_TIMEOUT_SECONDS = _float_env("JEV_TIMEOUT_SECONDS", 30.0, 1.0, 600.0)
# Optional Gmail label for emails that clear neither threshold, so they stay
# visible instead of being silently marked processed. Empty = no label.
JEV_REVIEW_LABEL = os.getenv("JEV_REVIEW_LABEL", "").strip()

# Gmail Configuration
# @spec AGENT-CFG-012, AGENT-CFG-013
GMAIL_CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
GMAIL_TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GMAIL_HEADLESS_MODE = _bool_env("GMAIL_HEADLESS_MODE", False)
REMOVE_FROM_INBOX = _bool_env("REMOVE_FROM_INBOX", True)

# Application Configuration
# @spec AGENT-CFG-013, AGENT-CFG-014
POLL_INTERVAL_SECONDS = _int_env("POLL_INTERVAL_SECONDS", 60, 1, 86400)
MAX_EMAILS_PER_POLL = _int_env("MAX_EMAILS_PER_POLL", 10, 1, 500)  # Gmail list max
STATE_FILE = os.getenv("STATE_FILE", ".email_state.json")
STATE_RETENTION_DAYS = _int_env(
    "STATE_RETENTION_DAYS", 30, 0, 3650
)  # 0 disables pruning
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# DRY_RUN=true classifies and logs the labels it would apply, but never
# creates labels, modifies messages, or writes the state file.
DRY_RUN = _bool_env("DRY_RUN", False)
