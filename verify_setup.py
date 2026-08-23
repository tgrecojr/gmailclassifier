#!/usr/bin/env python3
"""
Setup Verification Script

Checks that all prerequisites are configured correctly before running the agent.
"""

import os
import sys
from pathlib import Path

# ANSI color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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
        "openai",
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


def resolve_base_url() -> str:
    """Return the effective LLM base URL (mirrors config.py logic)."""
    return os.getenv("LLM_BASE_URL", "").strip() or OPENROUTER_BASE_URL


def check_llm_endpoint() -> bool:
    """Check that the configured LLM endpoint accepts the API key."""
    base_url = resolve_base_url()
    if base_url == OPENROUTER_BASE_URL:
        print(f"  Endpoint: {base_url} (OpenRouter default)")
    else:
        print(f"  Endpoint: {base_url} (custom via LLM_BASE_URL)")

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print(f"{RED}✗{RESET} Cannot test endpoint without OPENROUTER_API_KEY")
        return False

    try:
        import openai

        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        # /models is served by OpenRouter and LiteLLM alike; cheap auth + reachability probe
        client.models.list()
        print(f"{GREEN}✓{RESET} LLM endpoint reachable and API key accepted")
        return True
    except openai.AuthenticationError:
        print(f"{RED}✗{RESET} LLM endpoint rejected the API key (401)")
        return False
    except openai.APIConnectionError as e:
        print(f"{RED}✗{RESET} Could not connect to LLM endpoint: {e}")
        if base_url != OPENROUTER_BASE_URL:
            print(
                f"{YELLOW}  Hint:{RESET} if running in Docker, 'localhost' refers to the "
                "container - use host.docker.internal or the LAN IP instead"
            )
        return False
    except Exception as e:
        print(f"{YELLOW}⚠{RESET} Could not verify LLM endpoint: {e}")
        return False


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
    checks.append(check_file_exists(classifier_config, "Classifier config"))
    print()

    print("3. Environment Variables")
    checks.append(check_env_variable("OPENROUTER_API_KEY"))
    print()

    print("4. Python Dependencies")
    checks.append(check_dependencies())
    print()

    print("5. LLM Endpoint Access")
    checks.append(check_llm_endpoint())
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
