---
name: google-docs
description: Manage Google Docs - create, read, list documents. Use when user asks "create google doc", "get doc content", "list my docs", "read document", or needs Docs operations.
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
    description: Action to perform (list, get, create)
  title:
    type: string
    required: false
    extract-from: user-message
    description: Document title for creation or search
  doc_id:
    type: string
    required: false
    extract-from: user-message
    description: Google Docs document ID
  content:
    type: string
    required: false
    extract-from: user-message
    description: Initial content for new document
---

# Google Docs

Manage Google Docs documents using gogcli.

## Prerequisites

Requires gogcli. Run `/gogcli-setup` if not installed or authenticated.

## Commands Reference

### List Documents
```bash
# List all Google Docs
gogcli docs list --json

# List with limit
gogcli docs list --limit 20 --json

# Search by title
gogcli docs list --query "title contains 'meeting'" --json
```

### Get Document Content
```bash
# Get document by ID (returns plain text)
gogcli docs get "document_id" --json

# Get with formatting preserved (if supported)
gogcli docs get "document_id" --format markdown --json
```

### Create Document
```bash
# Create empty document
gogcli docs create --title "My New Document" --json

# Create with initial content
gogcli docs create --title "Meeting Notes" --content "# Meeting Notes\n\nDate: $(date)" --json
```

## Instructions

1. **Determine the action** from user request
2. **Always use `--json` flag** for machine-readable output
3. **For document creation**, confirm title before proceeding
4. **Parse JSON response** to extract document ID and URL
5. **Report success** with shareable link

## Examples

**User**: "List my Google Docs"
```bash
gogcli docs list --limit 10 --json
```

**User**: "Show me the content of the project plan document"
```bash
# First find the document
gogcli docs list --query "title contains 'project plan'" --json
# Then get content
gogcli docs get "doc_id_from_above" --json
```

**User**: "Create a new doc called Meeting Notes"
```bash
gogcli docs create --title "Meeting Notes" --json
```

**User**: "Create a doc with today's date as title"
```bash
gogcli docs create --title "Notes - $(date +%Y-%m-%d)" --json
```

## Output Format

When listing or creating documents, report:
- Document title
- Document ID
- Direct link (https://docs.google.com/document/d/{id}/edit)
- Last modified date (if available)

## Safety Rules

- Always parse JSON output, never assume structure
- Confirm document title before creation
- Verify document exists before attempting to read
- Handle large documents gracefully (may be truncated)
- Never expose full document content in logs
