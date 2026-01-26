---
name: google-keep
description: Access Google Keep notes (Workspace accounts only). Use when user asks "list notes", "get note", "read keep note", or needs Keep access. NOTE - Only works with Google Workspace accounts, not personal Gmail.
allowed-tools: Bash
model: claude-3-5-haiku-20241022
user-invocable: true
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-blocking: true
klabautermann-requires-confirmation: false
klabautermann-payload-schema:
  action:
    type: string
    required: true
    extract-from: user-message
    description: Action to perform (list, get)
  note_id:
    type: string
    required: false
    extract-from: user-message
    description: Google Keep note ID
  query:
    type: string
    required: false
    extract-from: user-message
    description: Search query to find notes
---

# Google Keep

Access Google Keep notes using gogcli.

## Important Limitation

**Google Keep API is only available for Google Workspace accounts.**

Personal Gmail accounts (@gmail.com) do not have access to the Keep API. If you receive an authentication or permission error, the user likely has a personal account.

## Prerequisites

- Requires gogcli. Run `/gogcli-setup` if not installed or authenticated.
- Requires Google Workspace account (not personal Gmail)

## Commands Reference

### List Notes
```bash
# List all notes
gogcli keep list --json

# List with limit
gogcli keep list --limit 20 --json

# Search notes
gogcli keep list --query "shopping" --json
```

### Get Note Content
```bash
# Get note by ID
gogcli keep get "note_id" --json
```

## Instructions

1. **Check account type** - if errors occur, note may be due to personal account
2. **Always use `--json` flag** for machine-readable output
3. **Parse JSON response** to extract note content
4. **Present notes clearly** with title and content

## Examples

**User**: "List my Keep notes"
```bash
gogcli keep list --limit 10 --json
```

**User**: "Find my shopping list note"
```bash
gogcli keep list --query "shopping" --json
```

**User**: "Show me the note about project ideas"
```bash
# Search for the note
gogcli keep list --query "project ideas" --json
# Get full content
gogcli keep get "note_id" --json
```

## Output Format

When listing notes:
```
## Google Keep Notes

1. **Shopping List** (Updated: Jan 15)
   - Milk, eggs, bread...

2. **Project Ideas** (Updated: Jan 10)
   - App concept: ...

3. **Meeting Notes** (Updated: Jan 8)
   - Discussed Q1 goals...
```

When showing a note:
```
## Note: Shopping List
**Last Updated**: January 15, 2024

- Milk
- Eggs
- Bread
- Coffee
```

## Error Handling

If you receive an error like "API not enabled" or "Permission denied":

```
Google Keep API is only available for Google Workspace accounts.

Personal Gmail accounts cannot access Keep through the API. If you need
to access Keep data, consider:
1. Using a Workspace account
2. Manually exporting notes from keep.google.com
```

## Safety Rules

- This is primarily a read-only skill
- Always parse JSON output, never assume structure
- Handle API errors gracefully with clear explanation
- Be aware of account type limitations
- Never expose note content in logs
