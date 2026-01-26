---
name: gogcli-setup
description: Install and configure gogcli for Google Workspace access. Use when user asks "setup gogcli", "configure google access", "authenticate google", or needs to set up Google API access.
allowed-tools: Bash
model: claude-3-5-haiku-20241022
user-invocable: true
klabautermann-task-type: execute
klabautermann-agent: executor
klabautermann-blocking: true
klabautermann-requires-confirmation: false
---

# gogcli Setup

Install and configure [gogcli](https://github.com/steipete/gogcli) for Google Workspace integration.

## Prerequisites

- Go 1.21+ installed (`go version` to verify)
- Internet access for OAuth flow
- Browser access for Google authentication

## Instructions

1. **Check Installation**
   ```bash
   which gogcli || echo "Not installed"
   gogcli --version 2>/dev/null || echo "Version check failed"
   ```

2. **Install gogcli (if needed)**
   ```bash
   go install github.com/steipete/gogcli@latest
   ```

   Verify Go's bin directory is in PATH:
   ```bash
   echo $PATH | grep -q "$(go env GOPATH)/bin" || echo "Add $(go env GOPATH)/bin to PATH"
   ```

3. **Authenticate with Google**
   ```bash
   gogcli auth login
   ```
   This opens a browser for OAuth2 consent. Follow the prompts.

4. **Verify Authentication**
   ```bash
   gogcli auth status
   ```
   Should show authenticated user email and available scopes.

5. **Test Access**
   ```bash
   gogcli drive list --limit 1 --json
   ```
   Should return JSON with at least one file (if Drive has files).

## Troubleshooting

- **"go: command not found"**: Install Go from https://go.dev/doc/install
- **gogcli not found after install**: Add `$(go env GOPATH)/bin` to your PATH
- **OAuth errors**: Try `gogcli auth logout` then `gogcli auth login` again
- **Scope missing**: Re-authenticate to add required scopes

## Available Services After Setup

Once authenticated, these skills become available:
- `/google-drive` - File operations (upload, download, list, share)
- `/google-docs` - Document operations (create, read, list)
- `/google-sheets` - Spreadsheet operations (create, read, list)
- `/google-contacts` - Contact lookup and search
- `/google-tasks` - Task management
- `/google-keep` - Notes (Workspace accounts only)

## Safety Rules

- Store credentials securely (gogcli handles this automatically)
- Never expose tokens in logs or output
- Verify successful authentication before proceeding
