#!/usr/bin/env python3
"""Get Google OAuth refresh token for Klabautermann."""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv


# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]


def main():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first")
        return

    redirect_uri = "http://127.0.0.1:8080"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(params)}"

    print("\n1. Open this URL in your browser:\n")
    print(auth_url)
    print("\n2. Authorize the app")
    print("\n3. You'll be redirected to a page that won't load.")
    print("   Look at the URL bar - it will be something like:")
    print("   http://127.0.0.1:8080/?code=4/0XXXXX...")
    print("\n4. Copy the 'code' value from the URL (everything after 'code=')\n")

    user_input = input("Paste the code (or full URL): ").strip()

    # Extract code from URL if user pasted full URL
    if user_input.startswith("http"):
        parsed = urlparse(user_input)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            print("Could not extract code from URL")
            return
    else:
        code = user_input

    # Exchange code for tokens
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )

    if response.status_code != 200:
        print(f"Error: {response.json()}")
        return

    tokens = response.json()
    refresh_token = tokens.get("refresh_token")

    if refresh_token:
        print("\n" + "=" * 60)
        print("Add this to your .env file:")
        print("=" * 60)
        print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
        print("=" * 60)
    else:
        print("No refresh token returned.")
        print(f"Response: {tokens}")


if __name__ == "__main__":
    main()
