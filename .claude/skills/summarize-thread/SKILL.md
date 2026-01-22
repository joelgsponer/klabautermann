---
name: summarize-thread
description: Summarize a conversation thread or email thread to extract key points, action items, and decisions. Use when user asks "summarize this thread", "what was discussed", "give me the gist", or "TLDR".
allowed-tools: Read, Grep
model: claude-3-5-haiku-20241022
user-invocable: true
klabautermann-task-type: research
klabautermann-agent: researcher
klabautermann-blocking: true
klabautermann-payload-schema:
  thread_id:
    type: string
    required: false
    extract-from: user-message
    description: Thread ID for email or conversation thread (if known)
  thread_type:
    type: string
    required: false
    default: conversation
    extract-from: user-message
    description: Type of thread - "email" or "conversation"
  query:
    type: string
    required: false
    extract-from: user-message
    description: Search query to find the thread if ID not provided
---

# Summarize Thread

Summarize a conversation thread or email thread to extract structured information.

## Instructions

1. **Determine Thread Type**
   - If thread_type is "email" or user mentions emails/inbox, use email thread summarization
   - Otherwise, use conversation thread summarization

2. **Find the Thread**
   - If thread_id is provided, use it directly
   - If query is provided, search for matching threads
   - If neither, summarize the current/recent conversation

3. **Generate Summary**
   - Extract the essence, not verbatim transcription
   - Identify key topics discussed
   - List decisions made
   - Extract action items with owners if mentioned
   - Detect sentiment (positive/neutral/negative)

4. **Return Structured Results**
   - Summary: 2-3 sentence overview
   - Key Points: Bullet list of main topics
   - Action Items: Tasks with owners
   - Participants: Who was involved
   - Sentiment: Overall tone

## Examples

**User**: "Summarize the email thread from Sarah"
- thread_type: "email"
- query: "Sarah"
- Action: Search emails from Sarah, get thread, summarize with key points and action items

**User**: "What did we discuss yesterday?"
- thread_type: "conversation"
- query: "yesterday"
- Action: Find yesterday's conversation thread, extract topics and decisions

**User**: "TLDR on the project meeting thread"
- thread_type: "conversation" (or "email" if context suggests)
- query: "project meeting"
- Action: Summarize the project meeting discussion

## Output Format

```
## Summary
[2-3 sentence summary of the thread]

## Key Points
- [Point 1]
- [Point 2]
- [Point 3]

## Action Items
- [ ] [Action] (Owner: [Name])
- [ ] [Action] (Owner: [Name])

## Participants
[List of participants]

## Sentiment
[positive/neutral/negative]
```

## Safety Rules

- Only summarize threads the user has access to
- Preserve attribution (who said what)
- Be conservative - don't infer information not in the thread
- Mark low-confidence extractions accordingly
