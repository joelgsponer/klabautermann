---
name: google-contacts
description: Search and view Google Contacts. Use when user asks "find contact", "list contacts", "get contact info", "lookup email", or needs contact information.
allowed-tools: Bash
model: claude-3-5-haiku-20241022
user-invocable: true
klabautermann-task-type: research
klabautermann-agent: researcher
klabautermann-blocking: true
klabautermann-requires-confirmation: false
klabautermann-payload-schema:
  action:
    type: string
    required: true
    extract-from: user-message
    description: Action to perform (list, search, get)
  query:
    type: string
    required: false
    extract-from: user-message
    description: Search query (name, email, company)
  contact_id:
    type: string
    required: false
    extract-from: user-message
    description: Google Contacts resource ID
---

# Google Contacts

Search and view Google Contacts using gogcli.

## Prerequisites

Requires gogcli. Run `/gogcli-setup` if not installed or authenticated.

## Commands Reference

### List Contacts
```bash
# List all contacts
gogcli contacts list --json

# List with limit
gogcli contacts list --limit 50 --json

# List with specific fields
gogcli contacts list --fields "names,emailAddresses,phoneNumbers" --json
```

### Search Contacts
```bash
# Search by name
gogcli contacts search "John" --json

# Search by email domain
gogcli contacts search "@company.com" --json

# Search by company
gogcli contacts search "Acme Corp" --json
```

### Get Contact Details
```bash
# Get full contact details by ID
gogcli contacts get "contact_id" --json
```

## Instructions

1. **Determine the action** from user request
2. **Always use `--json` flag** for machine-readable output
3. **Use search for specific lookups**, list for browsing
4. **Parse JSON response** to extract relevant contact fields
5. **Present information clearly** with available contact methods

## Examples

**User**: "Find John's contact info"
```bash
gogcli contacts search "John" --json
```

**User**: "List my contacts"
```bash
gogcli contacts list --limit 20 --json
```

**User**: "What's Sarah's email address?"
```bash
gogcli contacts search "Sarah" --json
```

**User**: "Find contacts from Acme Corp"
```bash
gogcli contacts search "Acme Corp" --json
```

## Output Format

When presenting contact information:

```
## Contact: John Smith
- **Email**: john.smith@example.com
- **Phone**: +1 555-123-4567
- **Company**: Acme Corp
- **Title**: Product Manager
```

For multiple results:
```
## Search Results for "John"

1. **John Smith** - john.smith@example.com (Acme Corp)
2. **John Doe** - jdoe@company.com (Beta Inc)
3. **Johnny Appleseed** - johnny@startup.io
```

## Safety Rules

- This is a read-only skill (no confirmation required)
- Always parse JSON output, never assume structure
- Handle missing fields gracefully (not all contacts have all info)
- Respect privacy - only retrieve what's needed
- Never log or expose sensitive contact details
