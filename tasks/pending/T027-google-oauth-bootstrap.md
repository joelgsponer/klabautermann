# Implement Google OAuth Bootstrap Script

## Metadata
- **ID**: T027
- **Priority**: P0
- **Category**: deployment
- **Effort**: M
- **Status**: pending
- **Assignee**: purser

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.4
- Related: [PRD.md](../../specs/PRD.md) Section 9.3

## Dependencies
- [ ] T026 - MCP client wrapper
- [x] T004 - Environment configuration template

## Context
The Executor agent needs access to Gmail and Calendar via Google Workspace MCP. This requires OAuth2 authentication with a refresh token that can be used for headless operation. This script guides users through the OAuth flow and stores credentials securely.

## Requirements
- [ ] Create `scripts/bootstrap_auth.py`:

### OAuth2 Flow
- [ ] Use Google OAuth2 installed app flow
- [ ] Open browser for user authorization
- [ ] Handle callback with authorization code
- [ ] Exchange code for tokens
- [ ] Obtain refresh token for headless use

### Credential Storage
- [ ] Store refresh token in .env file
- [ ] Never store access tokens (short-lived)
- [ ] Validate existing credentials before overwriting
- [ ] Backup existing .env before modification

### Scope Configuration
- [ ] Gmail: `gmail.modify` (read, send, draft)
- [ ] Calendar: `calendar.events` (read, create)
- [ ] Minimal scopes (not full account access)

### User Experience
- [ ] Clear console instructions
- [ ] Progress indicators
- [ ] Error messages with resolution steps
- [ ] Verification of successful auth

### Security
- [ ] Never log tokens
- [ ] Warn about credential security
- [ ] Support credential rotation

## Acceptance Criteria
- [ ] Running script opens browser for Google login
- [ ] Successful auth stores GOOGLE_REFRESH_TOKEN in .env
- [ ] Script validates token works before completing
- [ ] Error messages guide user to resolution
- [ ] Re-running script offers to keep or replace credentials

## Implementation Notes

```python
#!/usr/bin/env python3
"""
Google OAuth Bootstrap Script for Klabautermann.

This script guides you through Google OAuth2 authentication
to obtain a refresh token for Gmail and Calendar access.

Usage:
    python scripts/bootstrap_auth.py

Prerequisites:
    1. Create a Google Cloud Project at https://console.cloud.google.com
    2. Enable Gmail API and Calendar API
    3. Create OAuth2 credentials (Desktop application)
    4. Download credentials.json to project root
"""

import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Google OAuth libraries
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

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

    print("  - credentials.json found")

    # Check for existing credentials
    existing_token = os.getenv("GOOGLE_REFRESH_TOKEN")
    if existing_token:
        print("  - Existing GOOGLE_REFRESH_TOKEN found in environment")
        response = input("\n  Replace existing credentials? [y/N]: ")
        if response.lower() != "y":
            print("\n  Keeping existing credentials. Exiting.")
            sys.exit(0)

    print()


def run_oauth_flow():
    """Run the OAuth2 flow."""
    print("[2/5] Starting OAuth flow...")
    print("  - Opening browser for Google authorization")
    print("  - Please log in and grant access to Gmail and Calendar")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        SCOPES,
    )

    # Run local server for OAuth callback
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

        # Test Calendar API
        calendar = build("calendar", "v3", credentials=credentials)
        calendars = calendar.calendarList().list(maxResults=1).execute()
        print(f"  - Calendar: Access confirmed")

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

    # Backup existing .env
    if ENV_FILE.exists():
        backup = f".env.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(ENV_FILE, backup)
        print(f"  - Backed up existing .env to {backup}")

    # Read existing .env
    env_content = ""
    if ENV_FILE.exists():
        env_content = ENV_FILE.read_text()

    # Update or add GOOGLE_REFRESH_TOKEN
    lines = env_content.split("\n")
    new_lines = []
    token_updated = False

    for line in lines:
        if line.startswith("GOOGLE_REFRESH_TOKEN="):
            new_lines.append(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
            token_updated = True
        else:
            new_lines.append(line)

    if not token_updated:
        # Add section header if not present
        if "# Google OAuth" not in env_content:
            new_lines.append("")
            new_lines.append("# Google OAuth (generated by bootstrap_auth.py)")
        new_lines.append(f"GOOGLE_REFRESH_TOKEN={refresh_token}")

    # Write updated .env
    ENV_FILE.write_text("\n".join(new_lines))
    print(f"  - Saved refresh token to {ENV_FILE}")

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
    print("    - Refresh tokens can be revoked at:")
    print("      https://myaccount.google.com/permissions")
    print()
    print("=" * 60)


def main():
    """Main entry point."""
    print_header()
    check_prerequisites()
    credentials = run_oauth_flow()
    verify_credentials(credentials)
    save_credentials(credentials)
    print_summary()


if __name__ == "__main__":
    main()
```

Add to requirements.txt:
```
google-auth>=2.0.0
google-auth-oauthlib>=1.0.0
google-api-python-client>=2.0.0
```

Update .env.example:
```
# Google OAuth (run: python scripts/bootstrap_auth.py)
GOOGLE_REFRESH_TOKEN=
GOOGLE_CLIENT_ID=  # From credentials.json
GOOGLE_CLIENT_SECRET=  # From credentials.json
```
