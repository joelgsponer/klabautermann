---
name: google-tasks
description: Manage Google Tasks - create, list, complete tasks. Use when user asks "add task", "list my tasks", "complete task", "create todo", "mark done", or needs task management.
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
    description: Action to perform (list, create, complete, delete)
  title:
    type: string
    required: false
    extract-from: user-message
    description: Task title for creation
  task_id:
    type: string
    required: false
    extract-from: user-message
    description: Google Tasks task ID
  list_name:
    type: string
    required: false
    extract-from: user-message
    description: Task list name (default is "My Tasks")
  due_date:
    type: string
    required: false
    extract-from: user-message
    description: Due date for task (YYYY-MM-DD format)
  notes:
    type: string
    required: false
    extract-from: user-message
    description: Additional notes for task
---

# Google Tasks

Manage Google Tasks using gogcli.

## Prerequisites

Requires gogcli. Run `/gogcli-setup` if not installed or authenticated.

## Commands Reference

### List Task Lists
```bash
# List all task lists
gogcli tasks lists --json
```

### List Tasks
```bash
# List tasks from default list
gogcli tasks list --json

# List tasks from specific list
gogcli tasks list --list "list_id" --json

# List with completed tasks
gogcli tasks list --show-completed --json

# List with limit
gogcli tasks list --limit 20 --json
```

### Create Task
```bash
# Create simple task
gogcli tasks create --title "Review document" --json

# Create task with due date
gogcli tasks create --title "Submit report" --due "2024-12-31" --json

# Create task with notes
gogcli tasks create --title "Call client" --notes "Discuss Q1 budget" --json

# Create in specific list
gogcli tasks create --title "Buy groceries" --list "list_id" --json
```

### Complete Task
```bash
# Mark task as complete
gogcli tasks complete "task_id" --json
```

### Delete Task
```bash
# Delete task
gogcli tasks delete "task_id" --json
```

## Instructions

1. **Determine the action** from user request
2. **Always use `--json` flag** for machine-readable output
3. **Extract task details** (title, due date, notes) from user message
4. **Confirm task creation** with extracted details
5. **Parse JSON response** and report success with task details

## Examples

**User**: "List my tasks"
```bash
gogcli tasks list --json
```

**User**: "Add a task to call John tomorrow"
```bash
gogcli tasks create --title "Call John" --due "$(date -d tomorrow +%Y-%m-%d)" --json
```

**User**: "Create a todo: Review PR #123"
```bash
gogcli tasks create --title "Review PR #123" --json
```

**User**: "Mark the 'Submit report' task as done"
```bash
# First find the task
gogcli tasks list --json
# Then complete it
gogcli tasks complete "task_id" --json
```

**User**: "Add task with notes: Prepare presentation, include Q3 numbers"
```bash
gogcli tasks create --title "Prepare presentation" --notes "Include Q3 numbers" --json
```

## Output Format

When listing tasks:
```
## My Tasks

1. [ ] Review document (Due: Dec 31)
2. [ ] Call client
   - Notes: Discuss Q1 budget
3. [x] Submit report (Completed)
```

When creating/completing:
```
✓ Task created: "Review document"
  - Due: December 31, 2024
  - List: My Tasks
```

## Safety Rules

- Confirm task title before creation
- Confirm before marking tasks complete
- Confirm before deleting tasks
- Always parse JSON output, never assume structure
- Handle missing fields gracefully
