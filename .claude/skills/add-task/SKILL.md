---
name: add-task
description: Create a new task or todo item
version: "1.0.0"
executor: ingestor

parameters:
  - name: title
    type: string
    required: true
    description: Task title/description
  - name: due_date
    type: datetime
    required: false
    description: When the task is due
  - name: priority
    type: enum
    values: [low, medium, high]
    required: false
    default: medium
    description: Task priority level
  - name: assignee
    type: string
    required: false
    description: Person responsible for the task
  - name: blocked_by
    type: string
    required: false
    description: What/who is blocking this task
---

# Add Task Skill

Creates tasks and todo items in the knowledge graph.

## Usage Examples

- "Add a task to review the PR"
- "Create a todo: Send report to Sarah by Friday"
- "Remind me to follow up with John next week"
- "Add high priority task: Fix the login bug"

## Executor Integration

Routes to the `ingestor` agent which:
1. Creates a Task node
2. Extracts related entities (people, deadlines)
3. Creates blocking relationships if specified

## Task Entity

```cypher
(:Task {
  id: string,
  title: string,
  status: "pending" | "in_progress" | "completed",
  priority: "low" | "medium" | "high",
  due_date: datetime,
  created_at: datetime
})
```

## Relationships

- `(Task)-[:ASSIGNED_TO]->(Person)`
- `(Task)-[:BLOCKED_BY]->(Task|Person|Topic)`
- `(Task)-[:RELATES_TO]->(Topic|Project)`

## Response Format

Returns confirmation with:
- Task ID
- Due date (if set)
- Assigned to (if set)
- Related entities
