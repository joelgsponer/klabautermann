---
name: send-email
description: Send an email to a contact. Use when user says "send email to X" or "email X about Y".
allowed-tools: Read, Grep, Bash
model: claude-sonnet-4-20250514
user-invocable: true
# Klabautermann orchestrator integration
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-blocking: true
klabautermann-requires-confirmation: true
klabautermann-payload-schema:
  recipient:
    type: string
    required: true
    extract-from: user-message
    description: Email address or contact name
  subject:
    type: string
    required: false
    extract-from: user-message
    description: Email subject line
  body:
    type: string
    required: false
    extract-from: user-message
    description: Email body content
  draft_only:
    type: boolean
    required: false
    default: false
    description: Create draft instead of sending
---

# Send Email

Send an email to a contact via Gmail integration.

## Instructions

1. Extract the recipient from the user request
   - If a name is given, look up the email address first
   - If an email is given directly, use it
2. Extract or ask for the subject line
3. Extract or compose the email body
4. Show a preview and ask for confirmation
5. Send the email or create a draft

## For Claude Code

When invoked via `/send-email`:
1. Parse the user's request for recipient, subject, body
2. If recipient is a name, use `/lookup-person` to find email
3. Compose the email preview
4. Confirm with user before sending
5. Execute via Gmail API

## For Klabautermann Orchestrator

When routing this skill:
- **task_type**: execute
- **agent**: executor
- **payload**:
  ```json
  {
    "type": "email_send",
    "target": "<email address>",
    "subject": "<subject>",
    "body": "<body>",
    "draft_only": false
  }
  ```
- **blocking**: true (wait for confirmation)
- **requires_confirmation**: true (always confirm before sending)

The executor agent will:
1. Validate the recipient email
2. Format the email via Gmail handlers
3. Present confirmation prompt
4. Send via MCP Gmail bridge

## Safety Rules

- **Never send** to unverified email addresses
- **Always confirm** before sending (not drafting)
- **Respect** dry_run mode in executor config

## Examples

**User**: "Send an email to Sarah about the meeting tomorrow"
- Lookup Sarah's email via researcher
- Subject: "Meeting Tomorrow"
- Body: Compose appropriate message
- Confirm before sending

**User**: "Email john@example.com to follow up on the proposal"
- Direct email address provided
- Subject: "Follow Up: Proposal"
- Body: Compose follow-up message
- Confirm before sending

**User**: "Draft an email to the team about project status"
- Set `draft_only: true`
- Create draft without sending
- Return draft link for review
