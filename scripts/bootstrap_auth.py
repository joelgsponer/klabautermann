#!/usr/bin/env python3
"""
Google OAuth Bootstrap Script for Klabautermann.

This script guides you through Google OAuth2 authentication
to obtain a refresh token for Gmail and Calendar access.

Usage:
    python scripts/bootstrap_auth.py              # Interactive (opens browser)
    python scripts/bootstrap_auth.py --headless   # Headless (copy/paste auth code)

Prerequisites:
    1. Create a Google Cloud Project at https://console.cloud.google.com
    2. Enable Gmail API and Calendar API
    3. Create OAuth2 credentials (Desktop application)
    4. Download credentials.json to project root
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Google OAuth libraries - imports needed at runtime for script
from typing import TYPE_CHECKING

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials


# Scopes required for Klabautermann
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",  # Read, send, draft emails
    "https://www.googleapis.com/auth/calendar.events",  # Read, create events
]

ENV_FILE = Path(".env")
CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path(".google_token.json")  # Temporary, not committed


def print_header():
    """Print script header."""
    print("=" * 60)
    print("  Klabautermann Google OAuth Bootstrap")
    print("=" * 60)
    print()


def check_prerequisites():
    """Check that prerequisites are in place."""
    print("[1/5] Checking prerequisites...")

    if not CREDENTIALS_FILE.exists():
        print(f"\n  ERROR: {CREDENTIALS_FILE} not found!")
        print("\n  To fix this:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create or select a project")
        print("  3. Enable Gmail API and Calendar API")
        print("  4. Create OAuth2 credentials (Desktop application)")
        print(f"  5. Download and save as {CREDENTIALS_FILE}")
        sys.exit(1)

    print(f"  - {CREDENTIALS_FILE} found")

    # Check for existing credentials
    from dotenv import load_dotenv

    load_dotenv()
    existing_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    if existing_token:
        print("  - Existing GOOGLE_REFRESH_TOKEN found in environment")
        response = input("\n  Replace existing credentials? [y/N]: ")
        if response.lower() != "y":
            print("\n  Keeping existing credentials. Exiting.")
            sys.exit(0)

    print()


def run_oauth_flow(headless: bool = False):
    """Run the OAuth2 flow."""
    print("[2/5] Starting OAuth flow...")

    # For headless mode, we use a redirect URI that the user will manually handle
    redirect_uri = "http://localhost:8080/" if headless else None

    # Allow HTTP for localhost (required for headless mode)
    if headless:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        SCOPES,
        redirect_uri=redirect_uri,
    )

    if headless:
        # Headless mode: manual copy/paste of auth code
        print("  - Running in HEADLESS mode")
        print()
        print("  IMPORTANT: Your Google Cloud OAuth client must have this redirect URI:")
        print("     http://localhost:8080/")
        print()
        print(
            "  (Add it at: Google Cloud Console → APIs & Services → Credentials → Edit OAuth Client)"
        )
        print()

        # Generate authorization URL
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )

        print("  1. Open this URL in any browser:")
        print()
        print(f"     {auth_url}")
        print()
        print("  2. Log in and grant access to Gmail and Calendar")
        print("  3. After authorization, you'll be redirected to a localhost URL that won't load")
        print("  4. Copy the ENTIRE URL from your browser's address bar")
        print("     (It looks like: http://localhost:8080/?code=4/0ABC...&scope=...)")
        print()

        redirect_response = input("  Paste the full redirect URL here: ").strip()

        if not redirect_response:
            print("\n  ERROR: No URL provided!")
            sys.exit(1)

        # Extract code from URL and fetch token
        flow.fetch_token(authorization_response=redirect_response)
        credentials = flow.credentials
    else:
        # Interactive mode: local server
        print("  - Opening browser for Google authorization")
        print("  - Please log in and grant access to Gmail and Calendar")
        print()

        credentials = flow.run_local_server(
            port=8080,
            prompt="consent",  # Force consent to get refresh token
            access_type="offline",  # Required for refresh token
        )

    print("  - Authorization successful!")
    print()

    return credentials


def verify_credentials(credentials: Credentials):
    """Verify credentials work by making test API calls."""
    print("[3/5] Verifying credentials...")

    try:
        # Test Gmail API
        gmail = build("gmail", "v1", credentials=credentials)
        profile = gmail.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "unknown")
        print(f"  - Gmail: Connected as {email}")

        # Test Calendar API (use events.list on primary calendar - works with calendar.events scope)
        calendar = build("calendar", "v3", credentials=credentials)
        _ = calendar.events().list(calendarId="primary", maxResults=1).execute()
        print("  - Calendar: Access confirmed")

    except Exception as e:
        print(f"\n  ERROR: Credential verification failed: {e}")
        sys.exit(1)

    print()


def save_credentials(credentials: Credentials):
    """Save refresh token to .env file."""
    print("[4/5] Saving credentials...")

    refresh_token = credentials.refresh_token
    if not refresh_token:
        print("\n  ERROR: No refresh token received!")
        print("  This usually means the app was already authorized.")
        print("  Please revoke access at https://myaccount.google.com/permissions")
        print("  and run this script again.")
        sys.exit(1)

    # Read credentials.json to get client ID and secret
    with CREDENTIALS_FILE.open() as f:
        creds_data = json.load(f)
        installed = creds_data.get("installed", {})
        client_id = installed.get("client_id", "")
        client_secret = installed.get("client_secret", "")

    # Backup existing .env
    if ENV_FILE.exists():
        backup = f".env.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(ENV_FILE, backup)
        print(f"  - Backed up existing .env to {backup}")

    # Read existing .env
    env_content = ""
    if ENV_FILE.exists():
        env_content = ENV_FILE.read_text()

    # Update or add Google OAuth section
    lines = env_content.split("\n")
    new_lines = []
    token_updated = False
    client_id_updated = False
    client_secret_updated = False
    in_google_section = False

    for line in lines:
        stripped = line.strip()

        # Track if we're in the Google OAuth section
        if stripped.startswith("# Google OAuth"):
            in_google_section = True
        elif stripped.startswith("#") and in_google_section and not stripped.startswith("# Google"):
            in_google_section = False

        # Update existing values
        if line.startswith("GOOGLE_REFRESH_TOKEN="):
            new_lines.append(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
            token_updated = True
        elif line.startswith("GOOGLE_CLIENT_ID="):
            new_lines.append(f"GOOGLE_CLIENT_ID={client_id}")
            client_id_updated = True
        elif line.startswith("GOOGLE_CLIENT_SECRET="):
            new_lines.append(f"GOOGLE_CLIENT_SECRET={client_secret}")
            client_secret_updated = True
        else:
            new_lines.append(line)

    # Add Google OAuth section if not present
    if not token_updated:
        # Find or create Google OAuth section
        if "# Google OAuth" not in env_content:
            # Add section after Sprint 2 marker or at end
            insert_idx = len(new_lines)
            for idx, line in enumerate(new_lines):
                if "# === REQUIRED FOR SPRINT 2" in line:
                    # Insert after this section
                    insert_idx = idx + 1
                    break

            # Find end of Sprint 2 section
            for idx in range(insert_idx, len(new_lines)):
                if (
                    new_lines[idx].strip().startswith("# === REQUIRED FOR")
                    and "SPRINT 2" not in new_lines[idx]
                ):
                    insert_idx = idx
                    break

            # Insert before next section
            new_lines.insert(insert_idx, "")
            new_lines.insert(
                insert_idx + 1, "# Google OAuth (run: python scripts/bootstrap_auth.py)"
            )
            new_lines.insert(insert_idx + 2, f"GOOGLE_CLIENT_ID={client_id}")
            new_lines.insert(insert_idx + 3, f"GOOGLE_CLIENT_SECRET={client_secret}")
            new_lines.insert(insert_idx + 4, f"GOOGLE_REFRESH_TOKEN={refresh_token}")
        else:
            # Section exists, just add missing values
            if not token_updated:
                new_lines.append(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
            if not client_id_updated:
                new_lines.append(f"GOOGLE_CLIENT_ID={client_id}")
            if not client_secret_updated:
                new_lines.append(f"GOOGLE_CLIENT_SECRET={client_secret}")

    # Write updated .env
    ENV_FILE.write_text("\n".join(new_lines))
    print(f"  - Saved credentials to {ENV_FILE}")

    # Clean up temporary token file if exists
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()

    print()


def print_summary():
    """Print completion summary."""
    print("[5/5] Setup complete!")
    print()
    print("  Your Google credentials are now configured.")
    print("  The Executor agent can now:")
    print("    - Read and send Gmail messages")
    print("    - Create and list Calendar events")
    print()
    print("  SECURITY NOTES:")
    print("    - Never commit .env to version control")
    print("    - .env is listed in .gitignore for safety")
    print("    - Refresh tokens can be revoked at:")
    print("      https://myaccount.google.com/permissions")
    print()
    print("=" * 60)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Google OAuth Bootstrap for Klabautermann")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no browser, copy/paste auth code)",
    )
    args = parser.parse_args()

    print_header()
    check_prerequisites()
    credentials = run_oauth_flow(headless=args.headless)
    verify_credentials(credentials)
    save_credentials(credentials)
    print_summary()


if __name__ == "__main__":
    main()
