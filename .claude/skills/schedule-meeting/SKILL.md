---
name: schedule-meeting
description: Schedule a calendar meeting. Use when user says "schedule meeting", "book meeting", "set up meeting", or wants to create a calendar event.
user-invocable: true
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-blocking: true
klabautermann-requires-confirmation: true
klabautermann-payload-schema:
  action_type:
    type: string
    required: true
    default: calendar_create
  title:
    type: string
    required: true
    extract-from: user-message
    description: Meeting title extracted from user message
  start_time:
    type: string
    required: true
    extract-from: user-message
    description: Start time in natural language (e.g., "tomorrow at 2pm", "next Monday 10am")
  end_time:
    type: string
    required: false
    extract-from: user-message
    description: End time (defaults to 1 hour after start if not specified)
  attendees:
    type: array
    required: false
    extract-from: user-message
    description: List of attendee names or emails
  location:
    type: string
    required: false
    extract-from: user-message
    description: Meeting location or video call link
  description:
    type: string
    required: false
    extract-from: user-message
    description: Meeting description or agenda
---

# Schedule Meeting Skill

Schedule calendar meetings with natural language time parsing.

## Triggers

This skill activates when the user wants to:
- Schedule a meeting
- Book a calendar event
- Set up a call or appointment
- Create a calendar entry

## Examples

- "Schedule a meeting with Sarah tomorrow at 2pm"
- "Book a standup for Monday 10am"
- "Set up a 30-minute call with John at 3pm"
- "Create a team sync for next Friday 11am-12pm"

## Behavior

1. **Extract meeting details** from user message:
   - Title/subject
   - Start time (required)
   - End time (optional, defaults to +1 hour)
   - Attendees (optional)
   - Location (optional)

2. **Check for conflicts** with existing calendar events

3. **Confirm before creating** if attendees or important details are unclear

4. **Create the event** via Google Calendar API

## Payload Schema

```json
{
  "action_type": "calendar_create",
  "title": "Meeting with Sarah",
  "start_time": "tomorrow at 2pm",
  "end_time": "tomorrow at 3pm",
  "attendees": ["sarah@example.com"],
  "location": "Zoom",
  "description": "Weekly sync"
}
```

## Response Format

On success:
```
Meeting scheduled: "Team Standup"
When: Monday, Jan 20, 2025 10:00 AM - 11:00 AM
Link: https://calendar.google.com/event?eid=xxx
```

On conflict:
```
Conflict detected: You have "Lunch with John" at 12:00 PM
Would you like to schedule anyway or pick a different time?
```
