#!/usr/bin/env python3
"""
Token Generation Script

Generate Gmail OAuth token for use in headless environments.
Run this on a machine with a browser, then copy token.json to your server/container.
"""

import os
import sys
from pathlib import Path
from gmail_client import GmailClient
import config


def main():
    print("=" * 60)
    print("Gmail Token Generator")
    print("=" * 60)
    print()

    # Check if credentials.json exists
    if not Path(config.GMAIL_CREDENTIALS_PATH).exists():
        print(f"❌ Error: {config.GMAIL_CREDENTIALS_PATH} not found!")
        print()
        print("Please download OAuth credentials from Google Cloud Console:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Navigate to APIs & Services > Credentials")
        print("3. Create or download OAuth 2.0 Client ID credentials")
        print(f"4. Save as {config.GMAIL_CREDENTIALS_PATH}")
        return 1

    # Check if token already exists
    if Path(config.GMAIL_TOKEN_PATH).exists():
        print(f"⚠️  Warning: {config.GMAIL_TOKEN_PATH} already exists!")
        response = input("Do you want to regenerate it? (y/N): ").strip().lower()
        if response != "y":
            print("Aborted.")
            return 0

        # Backup existing token
        backup_path = f"{config.GMAIL_TOKEN_PATH}.backup"
        Path(config.GMAIL_TOKEN_PATH).rename(backup_path)
        print(f"✓ Backed up existing token to {backup_path}")

    print()
    print("Starting OAuth flow...")
    print("Your browser will open automatically.")
    print()

    try:
        # Initialize Gmail client (this will trigger OAuth flow)
        client = GmailClient(
            credentials_path=config.GMAIL_CREDENTIALS_PATH,
            token_path=config.GMAIL_TOKEN_PATH,
            scopes=config.GMAIL_SCOPES,
            headless=False,  # Always use browser mode for this script
        )

        # Test the connection
        print()
        print("Testing Gmail API connection...")
        messages = client.get_unread_messages(max_results=1)
        print(f"✓ Successfully connected to Gmail!")
        print(f"✓ Found {len(messages)} unread message(s)")
        print()

        print("=" * 60)
        print(f"✓ Token saved to: {config.GMAIL_TOKEN_PATH}")
        print("=" * 60)
        print()
        print("Next steps:")
        print("1. Copy token.json to your server/container:")
        print(f"   scp {config.GMAIL_TOKEN_PATH} user@server:/path/to/app/")
        print()
        print("2. Or use it locally:")
        print("   python main.py")
        print()

        return 0

    except Exception as e:
        print()
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
