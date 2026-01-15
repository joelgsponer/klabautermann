#!/usr/bin/env python3
# ruff: noqa: ERA001
"""
Example: Using the Google Workspace Bridge

This example demonstrates how to use the GoogleWorkspaceBridge to interact
with Gmail and Google Calendar via MCP.

Prerequisites:
1. Complete Google OAuth setup (run scripts/google_oauth_bootstrap.py)
2. Ensure GOOGLE_REFRESH_TOKEN, GOOGLE_CLIENT_ID, and GOOGLE_CLIENT_SECRET
   are set in your .env file
"""

import asyncio
from datetime import datetime, timedelta

from klabautermann.mcp import GoogleWorkspaceBridge


async def main():
    """Demonstrate Google Workspace bridge functionality."""
    # Create the bridge
    bridge = GoogleWorkspaceBridge()

    try:
        print("=== Google Workspace Bridge Example ===\n")

        # Gmail Examples
        print("1. Searching recent emails...")
        emails = await bridge.get_recent_emails(hours=24)
        print(f"   Found {len(emails)} emails from the last 24 hours")
        for email in emails[:3]:  # Show first 3
            print(f"   - {email.subject} from {email.sender}")
            print(f"     {email.snippet[:80]}...")
        print()

        print("2. Searching emails from specific sender...")
        emails = await bridge.search_emails("from:noreply@github.com", max_results=5)
        print(f"   Found {len(emails)} emails from GitHub")
        print()

        # Calendar Examples
        print("3. Getting today's events...")
        events = await bridge.get_todays_events()
        print(f"   Found {len(events)} events today")
        for event in events:
            print(f"   - {event.title}")
            print(f"     {event.start.strftime('%H:%M')} - {event.end.strftime('%H:%M')}")
            if event.location:
                print(f"     Location: {event.location}")
        print()

        print("4. Listing upcoming events (next 7 days)...")
        tomorrow = datetime.now() + timedelta(days=1)
        next_week = datetime.now() + timedelta(days=7)
        events = await bridge.list_events(start=tomorrow, end=next_week)
        print(f"   Found {len(events)} upcoming events")
        print()

        # Optional: Create a test event (commented out by default)
        # print("5. Creating a test event...")
        # start = datetime.now() + timedelta(hours=1)
        # end = start + timedelta(minutes=30)
        # result = await bridge.create_event(
        #     title="Test Event from Klabautermann",
        #     start=start,
        #     end=end,
        #     description="This is a test event created by the Google Workspace bridge",
        #     location="Virtual",
        # )
        # if result.success:
        #     print(f"   Event created successfully!")
        #     print(f"   Event ID: {result.event_id}")
        #     print(f"   Event link: {result.event_link}")
        # else:
        #     print(f"   Failed to create event: {result.error}")
        # print()

        # Optional: Send a draft email (commented out by default)
        # print("6. Creating a draft email...")
        # result = await bridge.send_email(
        #     to="your-email@example.com",
        #     subject="Test from Klabautermann",
        #     body="This is a test draft created by the Google Workspace bridge.",
        #     draft_only=True,
        # )
        # if result.success:
        #     print(f"   Draft created successfully!")
        #     print(f"   Message ID: {result.message_id}")
        # else:
        #     print(f"   Failed to create draft: {result.error}")

    finally:
        # Clean up
        await bridge.stop()
        print("\nBridge stopped. Example complete.")


if __name__ == "__main__":
    asyncio.run(main())
