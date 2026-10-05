#!/usr/bin/env python3
"""
Setup Verification Script

Checks that all prerequisites are configured correctly before running the agent.
"""

import json
import os
import sys
from pathlib import Path

# ANSI color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LITELLM_MIN_VERSION = "v1.104.0"


def check_file_exists(filepath: str, name: str) -> bool:
    """Check if a file exists."""
    if Path(filepath).exists():
        print(f"{GREEN}✓{RESET} {name} found at: {filepath}")
        return True
    else:
        print(f"{RED}✗{RESET} {name} NOT found at: {filepath}")
        return False


def check_env_variable(var_name: str) -> bool:
    """Check if an environment variable is set to a non-placeholder value."""
    value = os.getenv(var_name, "").strip()
    if value and "xxxx" not in value and value != f"your_{var_name.lower()}":
        print(f"{GREEN}✓{RESET} {var_name} is set")
        return True
    else:
        print(f"{RED}✗{RESET} {var_name} is NOT set or has a placeholder value")
        return False


def check_python_version() -> bool:
    """Check Python version."""
    version = sys.version_info
    if version.major == 3 and version.minor >= 14:
        print(
            f"{GREEN}✓{RESET} Python version: {version.major}.{version.minor}.{version.micro}"
        )
        return True
    else:
        print(
            f"{RED}✗{RESET} Python version {version.major}.{version.minor}.{version.micro} (requires 3.14+)"
        )
        return False


def check_dependencies() -> bool:
    """Check if required packages are installed."""
    required_packages = [
        "google.auth",
        "google_auth_oauthlib",
        "googleapiclient",
        "httpx2",
        "dotenv",
    ]

    all_installed = True
    for package in required_packages:
        try:
            __import__(package)
            print(f"{GREEN}✓{RESET} Package installed: {package}")
        except ImportError:
            print(f"{RED}✗{RESET} Package NOT installed: {package}")
            all_installed = False

    return all_installed


def check_classifier_config(path: str) -> bool:
    """Every label needs a description: Jev only ever sees the descriptions."""
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"{RED}✗{RESET} Classifier config unreadable: {e}")
        return False

    labels = cfg.get("labels") or []
    descriptions = cfg.get("label_descriptions") or {}
    missing = [label for label in labels if not descriptions.get(label)]
    if not labels:
        print(f"{RED}✗{RESET} Classifier config has no labels")
        return False
    if missing:
        print(f"{RED}✗{RESET} 'label_descriptions' missing for: {', '.join(missing)}")
        return False
    print(f"{GREEN}✓{RESET} {len(labels)} labels, each with a description")
    if "classification_prompt" in cfg:
        print(
            f"{YELLOW}  Note:{RESET} 'classification_prompt' is no longer used and can be removed"
        )
    return True


def resolve_decisions_url() -> str:
    """Return the effective decisions URL (mirrors config.py logic)."""
    from jev_classifier import decisions_url_for

    explicit = os.getenv("JEV_DECISIONS_URL", "").strip()
    if explicit:
        return explicit
    return decisions_url_for(
        os.getenv("LLM_BASE_URL", "").strip() or OPENROUTER_BASE_URL
    )


def check_jev_endpoint() -> bool:
    """Send one tiny decision (~$0.00002) to prove the route, key and model work."""
    from jev_classifier import DEFAULT_MODEL, JevClassifier, JevRequestError

    url = resolve_decisions_url()
    via_gateway = "openrouter.ai" not in url
    print(
        f"  Endpoint: {url} ({'via gateway' if via_gateway else 'OpenRouter direct'})"
    )

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print(f"{RED}✗{RESET} Cannot test endpoint without OPENROUTER_API_KEY")
        return False

    classifier = JevClassifier(
        api_key=api_key,
        labels=["Probe"],
        label_descriptions={"Probe": "A short test message"},
        model=os.getenv("JEV_MODEL", "").strip() or DEFAULT_MODEL,
        decisions_url=url,
        timeout_seconds=30,
        retry_delay_seconds=0,
    )
    try:
        answers = classifier.decide({"subject": "test", "body": "hello", "from": "x"})
    except JevRequestError as e:
        print(f"{RED}✗{RESET} Decisions endpoint failed: {e}")
        message = str(e)
        if "HTTP 401" in message or "HTTP 403" in message:
            print(f"{YELLOW}  Hint:{RESET} the endpoint rejected OPENROUTER_API_KEY")
        elif "HTTP 404" in message and via_gateway:
            print(
                f"{YELLOW}  Hint:{RESET} the gateway does not serve /openrouter/alpha/decisions; "
                f"LiteLLM {LITELLM_MIN_VERSION} or newer is required"
            )
        elif "transport error" in message and via_gateway:
            print(
                f"{YELLOW}  Hint:{RESET} if running in Docker, 'localhost' refers to the "
                "container - use host.docker.internal or the LAN IP instead"
            )
        return False

    probe = answers.get("is_Probe", {}).get("noul")
    print(
        f"{GREEN}✓{RESET} Decisions endpoint reachable, key accepted (probe noul={probe})"
    )
    return True


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("Gmail Email Classifier - Setup Verification")
    print("=" * 60)
    print()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # reported by check_dependencies below

    checks = []

    print("1. Python Version")
    checks.append(check_python_version())
    print()

    print("2. Required Files")
    checks.append(check_file_exists(".env", ".env configuration file"))
    checks.append(check_file_exists("credentials.json", "Gmail OAuth credentials"))
    classifier_config = os.getenv("CLASSIFIER_CONFIG_PATH", "classifier_config.json")
    config_present = check_file_exists(classifier_config, "Classifier config")
    checks.append(config_present)
    if config_present:
        checks.append(check_classifier_config(classifier_config))
    print()

    print("3. Environment Variables")
    checks.append(check_env_variable("OPENROUTER_API_KEY"))
    print()

    print("4. Python Dependencies")
    deps_ok = check_dependencies()
    checks.append(deps_ok)
    print()

    print("5. Jev Decisions Endpoint")
    checks.append(check_jev_endpoint() if deps_ok else False)
    print()

    # Summary
    print("=" * 60)
    passed = sum(checks)
    total = len(checks)

    if passed == total:
        print(f"{GREEN}All checks passed! ({passed}/{total}){RESET}")
        print()
        print("You're ready to run the email classifier:")
        print(f"  {YELLOW}uv run python main.py{RESET}")
        return 0
    else:
        print(f"{RED}Some checks failed ({passed}/{total}){RESET}")
        print()
        print("Please fix the issues above before running the agent.")
        print("Refer to README.md for setup instructions.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
