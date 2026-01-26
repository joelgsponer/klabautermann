---
name: google-drive
description: Manage Google Drive files - upload, download, list, share. Use when user asks "upload to drive", "download from drive", "list drive files", "share file", or needs Drive operations.
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
    description: Action to perform (list, upload, download, mkdir, share)
  path:
    type: string
    required: false
    extract-from: user-message
    description: Local file path for upload/download
  remote_path:
    type: string
    required: false
    extract-from: user-message
    description: Drive path or folder name
  file_id:
    type: string
    required: false
    extract-from: user-message
    description: Google Drive file ID
  email:
    type: string
    required: false
    extract-from: user-message
    description: Email address for sharing
---

# Google Drive

Manage files in Google Drive using gogcli.

## Prerequisites

Requires gogcli. Run `/gogcli-setup` if not installed or authenticated.

## Commands Reference

### List Files
```bash
# List files in root
gogcli drive list --json

# List with limit
gogcli drive list --limit 20 --json

# List files in a folder
gogcli drive list --parent "folder_id" --json

# Search for files by name
gogcli drive list --query "name contains 'report'" --json
```

### Upload Files
```bash
# Upload to root
gogcli drive upload /local/path/file.pdf --json

# Upload to specific folder
gogcli drive upload /local/path/file.pdf --parent "folder_id" --json

# Upload with custom name
gogcli drive upload /local/path/file.pdf --name "Custom Name.pdf" --json
```

### Download Files
```bash
# Download by file ID
gogcli drive download "file_id" --output /local/path/ --json

# Download to specific path
gogcli drive download "file_id" --output /local/path/custom_name.pdf --json
```

### Create Folders
```bash
# Create folder in root
gogcli drive mkdir "Folder Name" --json

# Create folder in parent
gogcli drive mkdir "Subfolder" --parent "parent_folder_id" --json
```

### Share Files
```bash
# Share with user (reader)
gogcli drive share "file_id" --email user@example.com --role reader --json

# Share with user (writer)
gogcli drive share "file_id" --email user@example.com --role writer --json

# Share with anyone (link sharing)
gogcli drive share "file_id" --anyone --role reader --json
```

### Delete Files
```bash
# Move to trash
gogcli drive delete "file_id" --json
```

## Instructions

1. **Determine the action** from user request
2. **Always use `--json` flag** for machine-readable output
3. **Confirm before destructive operations** (delete, overwrite)
4. **Parse JSON response** to extract relevant information
5. **Report success/failure** with actionable details

## Examples

**User**: "List my drive files"
```bash
gogcli drive list --limit 10 --json
```

**User**: "Upload report.pdf to the Reports folder"
```bash
# First find the Reports folder
gogcli drive list --query "name = 'Reports' and mimeType = 'application/vnd.google-apps.folder'" --json
# Then upload
gogcli drive upload report.pdf --parent "folder_id_from_above" --json
```

**User**: "Share the budget file with alice@company.com"
```bash
# Find the file
gogcli drive list --query "name contains 'budget'" --json
# Share it
gogcli drive share "file_id" --email alice@company.com --role reader --json
```

## Safety Rules

- Always parse JSON output, never assume structure
- Confirm before delete or overwrite operations
- Verify file existence before download
- Check available space before upload
- Handle errors gracefully with user feedback
