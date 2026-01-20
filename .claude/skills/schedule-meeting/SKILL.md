---
name: schedule-meeting
description: Schedule a calendar meeting or event
version: "1.0.0"
executor: calendar

parameters:
  - name: title
    type: string
    required: true
    description: Title/subject of the meeting
  - name: start_time
    type: datetime
    required: true
    description: Meeting start time (ISO 8601 format)
  - name: end_time
    type: datetime
    required: false
    description: Meeting end time (defaults to 1 hour after start)
  - name: attendees
    type: array[string]
    required: false
    description: List of attendee email addresses
  - name: location
    type: string
    required: false
    description: Physical location or video call URL
  - name: description
    type: string
    required: false
    description: Meeting description/agenda
---

# Schedule Meeting Skill

Creates calendar events and meetings via the Google Calendar MCP integration.

## Usage Examples

- "Schedule a meeting with John tomorrow at 2pm"
- "Book a call with the team on Friday at 10am for 30 minutes"
- "Create an event called 'Project Review' next Monday at 3pm"

## Executor Integration

Routes to the `calendar` executor which uses the Google Calendar MCP server:

```
mcp://google-calendar/create-event
```

## Response Format

Returns confirmation with:
- Event ID
- Calendar link
- Attendee notification status
