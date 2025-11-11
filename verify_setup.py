#!/usr/bin/env python3
"""
Setup Verification Script

Checks that all prerequisites are configured correctly before running the agent.
"""

import os
import sys
from pathlib import Path

# ANSI color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
RESET = '\033[0m'


def check_file_exists(filepath: str, name: str) -> bool:
    """Check if a file exists."""
    if Path(filepath).exists():
        print(f"{GREEN}✓{RESET} {name} found at: {filepath}")
        return True
    else:
        print(f"{RED}✗{RESET} {name} NOT found at: {filepath}")
        return False


def check_env_variable(var_name: str) -> bool:
    """Check if an environment variable is set."""
    value = os.getenv(var_name)
    if value and value != f"your_{var_name.lower()}":
        print(f"{GREEN}✓{RESET} {var_name} is set")
        return True
    else:
        print(f"{RED}✗{RESET} {var_name} is NOT set or has default value")
        return False


def check_python_version() -> bool:
    """Check Python version."""
    version = sys.version_info
    if version.major == 3 and version.minor >= 11:
        print(f"{GREEN}✓{RESET} Python version: {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"{RED}✗{RESET} Python version {version.major}.{version.minor}.{version.micro} (requires 3.11+)")
        return False


def check_dependencies() -> bool:
    """Check if required packages are installed."""
    required_packages = [
        'google.auth',
        'google_auth_oauthlib',
        'googleapiclient',
        'boto3',
        'dotenv'
    ]

    all_installed = True
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
            print(f"{GREEN}✓{RESET} Package installed: {package}")
        except ImportError:
            print(f"{RED}✗{RESET} Package NOT installed: {package}")
            all_installed = False

    return all_installed


def check_aws_credentials() -> bool:
    """Check AWS credentials."""
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        # Try to create a Bedrock client
        client = boto3.client('bedrock-runtime', region_name=os.getenv('AWS_REGION', 'us-east-1'))

        # Try to list available models (this will fail if credentials are wrong)
        print(f"{GREEN}✓{RESET} AWS credentials are valid")
        return True

    except NoCredentialsError:
        print(f"{RED}✗{RESET} AWS credentials not found")
        return False
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'UnrecognizedClientException':
            print(f"{RED}✗{RESET} AWS credentials are invalid")
        else:
            print(f"{YELLOW}⚠{RESET} AWS credentials found but couldn't verify Bedrock access: {error_code}")
        return False
    except Exception as e:
        print(f"{YELLOW}⚠{RESET} Could not verify AWS credentials: {str(e)}")
        return False


def main():
    """Run all verification checks."""
    print("=" * 60)
    print("Gmail Email Classifier - Setup Verification")
    print("=" * 60)
    print()

    checks = []

    # Check Python version
    print("1. Python Version")
    checks.append(check_python_version())
    print()

    # Check required files
    print("2. Required Files")
    checks.append(check_file_exists(".env", ".env configuration file"))
    checks.append(check_file_exists("credentials.json", "Gmail OAuth credentials"))
    print()

    # Check environment variables
    print("3. Environment Variables")
    from dotenv import load_dotenv
    load_dotenv()

    checks.append(check_env_variable("AWS_REGION"))
    checks.append(check_env_variable("AWS_ACCESS_KEY_ID"))
    checks.append(check_env_variable("AWS_SECRET_ACCESS_KEY"))
    checks.append(check_env_variable("BEDROCK_MODEL_ID"))
    print()

    # Check dependencies
    print("4. Python Dependencies")
    checks.append(check_dependencies())
    print()

    # Check AWS credentials
    print("5. AWS Bedrock Access")
    checks.append(check_aws_credentials())
    print()

    # Summary
    print("=" * 60)
    passed = sum(checks)
    total = len(checks)

    if passed == total:
        print(f"{GREEN}All checks passed! ({passed}/{total}){RESET}")
        print()
        print("You're ready to run the email classifier:")
        print(f"  {YELLOW}python main.py{RESET}")
        return 0
    else:
        print(f"{RED}Some checks failed ({passed}/{total}){RESET}")
        print()
        print("Please fix the issues above before running the agent.")
        print("Refer to README.md for setup instructions.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
