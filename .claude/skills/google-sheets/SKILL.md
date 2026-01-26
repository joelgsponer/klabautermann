---
name: google-sheets
description: Manage Google Sheets - create, read, list spreadsheets. Use when user asks "create spreadsheet", "read sheet", "list spreadsheets", "get cell data", or needs Sheets operations.
allowed-tools: Bash
model: claude-3-5-haiku-20241022
user-invocable: true
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-blocking: true
klabautermann-requires-confirmation: true
klabautermann-payload-schema:
  action:
    type: string
    required: true
    extract-from: user-message
    description: Action to perform (list, get, create, read)
  title:
    type: string
    required: false
    extract-from: user-message
    description: Spreadsheet title for creation or search
  sheet_id:
    type: string
    required: false
    extract-from: user-message
    description: Google Sheets spreadsheet ID
  range:
    type: string
    required: false
    extract-from: user-message
    description: Cell range to read (e.g., "A1:D10", "Sheet1!A1:B5")
---

# Google Sheets

Manage Google Sheets spreadsheets using gogcli.

## Prerequisites

Requires gogcli. Run `/gogcli-setup` if not installed or authenticated.

## Commands Reference

### List Spreadsheets
```bash
# List all Google Sheets
gogcli sheets list --json

# List with limit
gogcli sheets list --limit 20 --json

# Search by title
gogcli sheets list --query "title contains 'budget'" --json
```

### Get Spreadsheet Metadata
```bash
# Get spreadsheet info (sheets, properties)
gogcli sheets get "spreadsheet_id" --json
```

### Read Cell Data
```bash
# Read specific range
gogcli sheets read "spreadsheet_id" --range "A1:D10" --json

# Read from specific sheet tab
gogcli sheets read "spreadsheet_id" --range "Sheet2!A1:C5" --json

# Read entire sheet
gogcli sheets read "spreadsheet_id" --range "Sheet1" --json
```

### Create Spreadsheet
```bash
# Create empty spreadsheet
gogcli sheets create --title "My Spreadsheet" --json

# Create with initial sheet name
gogcli sheets create --title "Budget 2024" --sheet-name "Q1" --json
```

## Instructions

1. **Determine the action** from user request
2. **Always use `--json` flag** for machine-readable output
3. **Specify range explicitly** when reading data
4. **Parse JSON response** to extract data in usable format
5. **Format data clearly** when presenting to user

## Examples

**User**: "List my spreadsheets"
```bash
gogcli sheets list --limit 10 --json
```

**User**: "Show me the budget spreadsheet data"
```bash
# First find the spreadsheet
gogcli sheets list --query "title contains 'budget'" --json
# Get the data
gogcli sheets read "sheet_id" --range "A1:Z100" --json
```

**User**: "Create a new spreadsheet for expense tracking"
```bash
gogcli sheets create --title "Expense Tracking" --json
```

**User**: "Read cells A1 to C10 from the Sales sheet"
```bash
gogcli sheets read "spreadsheet_id" --range "Sales!A1:C10" --json
```

## Output Format

When presenting sheet data:
- Format as table when appropriate
- Include column headers if present
- Note the range that was read
- Provide spreadsheet URL for user access

```
## Spreadsheet: Budget 2024
**Range**: A1:D5
**URL**: https://docs.google.com/spreadsheets/d/{id}

| Category | Q1 | Q2 | Q3 |
|----------|-----|-----|-----|
| Marketing | 5000 | 6000 | 5500 |
| ...
```

## Safety Rules

- Always parse JSON output, never assume structure
- Confirm spreadsheet title before creation
- Be mindful of large ranges (may timeout or be truncated)
- Handle empty cells gracefully
- Never expose sensitive data in logs
