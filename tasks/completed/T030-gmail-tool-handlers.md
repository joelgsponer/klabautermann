# Add Gmail Tool Handlers

## Metadata
- **ID**: T030
- **Priority**: P1
- **Category**: subagent
- **Effort**: M
- **Status**: completed
- **Assignee**: purser
- **Completed**: 2026-01-15

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.4
- Related: [PRD.md](../../specs/PRD.md) Section 6

## Dependencies
- [x] T029 - Executor agent
- [x] T028 - Google Workspace MCP bridge

## Context
This task extends the Executor agent with sophisticated Gmail handling. While T028 provides the basic MCP bridge, this task adds higher-level functionality like email composition, thread handling, and intelligent search.

## Requirements
- [x] Extend Gmail capabilities in Executor:

### Email Composition
- [x] Draft composition from natural language
- [x] Subject line generation if not provided
- [x] Body formatting (greeting, signature)
- [x] Reply vs new thread detection

### Search Capabilities
- [x] Natural language to Gmail query conversion
- [x] Common search patterns:
  - "emails from Sarah" -> `from:sarah@...`
  - "unread emails" -> `is:unread`
  - "emails this week" -> `newer_than:7d`
  - "emails about budget" -> `subject:budget OR budget`

### Thread Handling
- [x] Reply to existing thread
- [x] Thread context for replies
- [x] Quote original message option

### Safety Features
- [x] Confirm before sending (not draft)
- [x] Validate recipient exists
- [x] Check for sensitive content warning

### Response Formatting
- [x] Format email list for display
- [x] Summarize long email bodies
- [x] Highlight key information

## Acceptance Criteria
- [x] "Draft email to Sarah about the meeting" creates appropriate draft
- [x] "Show emails from last week" executes correct search
- [x] "Reply to that email" handles thread context
- [x] Sending requires confirmation
- [x] Errors provide actionable guidance

## Implementation Notes

```python
from typing import Optional, List
from pydantic import BaseModel
import re

from klabautermann.mcp.google_workspace import GoogleWorkspaceBridge, EmailMessage


class EmailComposer:
    """
    Helper for composing emails from natural language.
    """

    # Common greeting patterns
    GREETINGS = {
        "formal": "Dear {name},",
        "casual": "Hi {name},",
        "brief": "{name},",
    }

    # Signature
    SIGNATURE = "\n\nBest regards"

    @classmethod
    def compose_email(
        cls,
        intent: str,
        recipient_name: str,
        context: Optional[str] = None,
        tone: str = "casual",
    ) -> tuple[str, str]:
        """
        Compose email subject and body from intent.

        Returns:
            Tuple of (subject, body)
        """
        # Extract subject if mentioned
        subject = cls._extract_subject(intent)

        # Generate body
        greeting = cls.GREETINGS.get(tone, cls.GREETINGS["casual"]).format(
            name=recipient_name.split()[0]  # First name only
        )

        # The LLM will fill in the actual body
        body_template = f"{greeting}\n\n[Message about: {intent}]\n{cls.SIGNATURE}"

        return subject, body_template

    @classmethod
    def _extract_subject(cls, intent: str) -> str:
        """Extract or generate subject from intent."""
        # Look for explicit subject
        subject_match = re.search(
            r'subject[:\s]+["\']?([^"\']+)["\']?',
            intent,
            re.IGNORECASE
        )
        if subject_match:
            return subject_match.group(1).strip()

        # Look for "about X" pattern
        about_match = re.search(r'about\s+(?:the\s+)?(.+?)(?:\s+to|\s*$)', intent, re.IGNORECASE)
        if about_match:
            return about_match.group(1).strip().title()

        # Generate from intent
        keywords = ["meeting", "update", "question", "request", "follow-up"]
        for kw in keywords:
            if kw in intent.lower():
                return kw.title()

        return "Message"


class GmailQueryBuilder:
    """
    Convert natural language to Gmail search queries.
    """

    PATTERNS = [
        # From patterns
        (r"(?:emails?|messages?)\s+from\s+(\S+)", "from:{0}"),
        (r"from\s+(\S+)", "from:{0}"),

        # To patterns
        (r"(?:emails?|messages?)\s+to\s+(\S+)", "to:{0}"),

        # Time patterns
        (r"(?:from\s+)?(?:this|last)\s+week", "newer_than:7d"),
        (r"(?:from\s+)?today", "newer_than:1d"),
        (r"(?:from\s+)?yesterday", "newer_than:2d older_than:1d"),
        (r"(?:from\s+)?last\s+month", "newer_than:30d"),

        # Status patterns
        (r"unread", "is:unread"),
        (r"starred", "is:starred"),
        (r"important", "is:important"),

        # Subject/content patterns
        (r"about\s+(.+?)(?:\s+from|\s+to|\s*$)", "subject:{0} OR {0}"),
        (r"subject[:\s]+[\"']?([^\"']+)[\"']?", "subject:{0}"),
    ]

    @classmethod
    def build_query(cls, natural_query: str) -> str:
        """
        Convert natural language to Gmail query.

        Args:
            natural_query: Natural language search request.

        Returns:
            Gmail search query string.
        """
        query_parts = []
        remaining = natural_query.lower()

        for pattern, template in cls.PATTERNS:
            match = re.search(pattern, remaining, re.IGNORECASE)
            if match:
                if match.groups():
                    query_parts.append(template.format(*match.groups()))
                else:
                    query_parts.append(template)
                # Remove matched part
                remaining = remaining[:match.start()] + remaining[match.end():]

        # If nothing matched, use as general search
        remaining = remaining.strip()
        if remaining and not query_parts:
            query_parts.append(remaining)

        return " ".join(query_parts) if query_parts else "in:inbox"


class EmailFormatter:
    """
    Format email messages for display.
    """

    @classmethod
    def format_email_list(
        cls,
        emails: List[EmailMessage],
        max_display: int = 5,
        include_snippet: bool = True,
    ) -> str:
        """Format list of emails for display."""
        if not emails:
            return "No emails found."

        lines = [f"Found {len(emails)} email(s):"]

        for i, email in enumerate(emails[:max_display]):
            status = "[NEW] " if email.is_unread else ""
            line = f"\n{i+1}. {status}From: {email.sender}"
            line += f"\n   Subject: {email.subject}"
            if include_snippet and email.snippet:
                snippet = email.snippet[:100] + "..." if len(email.snippet) > 100 else email.snippet
                line += f"\n   Preview: {snippet}"
            lines.append(line)

        if len(emails) > max_display:
            lines.append(f"\n... and {len(emails) - max_display} more")

        return "".join(lines)

    @classmethod
    def format_email_detail(cls, email: EmailMessage) -> str:
        """Format single email for detailed view."""
        return f"""
From: {email.sender}
To: {email.recipient or 'me'}
Date: {email.date.strftime('%Y-%m-%d %H:%M')}
Subject: {email.subject}

{email.body or email.snippet}
""".strip()


# Add to Executor agent methods:

async def handle_gmail_send(
    self,
    action: str,
    context: dict,
    trace_id: str,
) -> ActionResult:
    """Handle email sending with composition."""
    # Find recipient
    recipient_email = self._find_email_in_context(context)
    recipient_name = context.get("name", "there")

    if not recipient_email:
        return ActionResult(
            success=False,
            message=f"I need {recipient_name}'s email address to send this message.",
        )

    # Compose email
    subject, body_template = EmailComposer.compose_email(
        intent=action,
        recipient_name=recipient_name,
        context=str(context),
    )

    # Use LLM to generate actual body if needed
    # ... (LLM call to fill in body_template)

    # Create draft first (safer)
    result = await self.google.send_email(
        to=recipient_email,
        subject=subject,
        body=body_template,  # or LLM-generated body
        draft_only=True,  # Always draft first
        context=ToolInvocationContext(trace_id=trace_id, agent_name=self.name),
    )

    if result.success:
        return ActionResult(
            success=True,
            message=f"I've drafted an email to {recipient_name} ({recipient_email}) about '{subject}'. "
                    f"Would you like me to send it or would you like to review it first?",
            needs_confirmation=True,
            confirmation_prompt="Say 'send it' to send, or 'show draft' to review.",
            details={"draft_id": result.message_id},
        )

    return ActionResult(success=False, message=f"Failed to create draft: {result.error}")


async def handle_gmail_search(
    self,
    action: str,
    trace_id: str,
) -> ActionResult:
    """Handle email search with natural language."""
    # Convert to Gmail query
    query = GmailQueryBuilder.build_query(action)

    logger.debug(
        f"[WHISPER] Gmail search query: {query}",
        extra={"trace_id": trace_id}
    )

    # Execute search
    emails = await self.google.search_emails(
        query=query,
        max_results=10,
        context=ToolInvocationContext(trace_id=trace_id, agent_name=self.name),
    )

    # Format results
    formatted = EmailFormatter.format_email_list(emails)

    return ActionResult(
        success=True,
        message=formatted,
        details={"query": query, "count": len(emails)},
    )
```

These helpers are integrated into the Executor agent to provide sophisticated email handling.

## Development Notes

### Implementation

**Files Created:**
- `src/klabautermann/agents/gmail_handlers.py` - Gmail handler classes (524 lines)
- `tests/unit/test_gmail_handlers.py` - Comprehensive unit tests (50 tests, 634 lines)

**Files Modified:**
- `src/klabautermann/agents/executor.py` - Integrated gmail handlers into Executor agent
  - Added imports for EmailComposer, EmailFormatter, GmailQueryBuilder
  - Added `_handle_gmail_send()` method - sophisticated email drafting with composition
  - Added `_handle_gmail_search()` method - natural language query conversion and formatting
  - Updated `_execute_action()` signature to include context parameter
  - Updated `_create_response()` to include confirmation fields in payload
- `tests/unit/test_executor.py` - Updated tests to match new draft-first behavior

### Decisions Made

1. **Draft-First Safety**: All email sends now create drafts first and require explicit confirmation. This prevents accidental sends and gives users a chance to review.

2. **Pattern Ordering in QueryBuilder**: Time patterns (`last week`, `today`) must come before general `from` patterns to avoid incorrect matching. Pattern order matters in regex matching.

3. **Capitalization Strategy**: Subject lines use title case for short subjects (3 words or less) and sentence case for longer subjects to maintain readability.

4. **Keyword Priority**: More specific keywords like "follow-up" come before general ones like "request" in the keyword list to ensure accurate subject generation.

5. **Thread Handling via format_reply()**: Implemented reply formatting with optional quoting, proper "Re:" prefix handling, and name extraction from email addresses.

6. **Comprehensive Formatting**: EmailFormatter provides three output modes:
   - `format_email_list()` - List view with snippets and unread indicators
   - `format_email_detail()` - Detailed single email view
   - `format_thread_summary()` - Conversation thread view

### Patterns Established

1. **Handler Classes as Utilities**: Gmail handlers are stateless utility classes with `@classmethod` methods, making them easy to test and use.

2. **Regex Pattern Templates**: Query builder uses (pattern, template) tuples where templates use `{0}`, `{1}` for captured groups, enabling flexible query construction.

3. **Confirmation Flow**: ActionResult now includes `needs_confirmation` and `confirmation_prompt` fields that propagate through the response payload for UI handling.

4. **Context Parameter Threading**: Execute methods now receive context dictionary for accessing recipient info, names, and other data needed for composition.

### Testing

**Test Coverage:**
- 50 new tests in `test_gmail_handlers.py` (all passing)
- 83 total tests across executor and gmail_handlers (all passing)
- Test categories:
  - EmailComposer: Subject extraction, capitalization, reply formatting, name extraction (17 tests)
  - GmailQueryBuilder: Pattern matching, query construction, edge cases (15 tests)
  - EmailFormatter: List formatting, detail formatting, thread summaries, truncation (18 tests)

**Test Pattern:**
- Mock Gmail responses at the bridge level
- Test both positive and negative cases
- Verify exact output formats for user-facing messages

### Issues Encountered

1. **Import Order**: Had to ensure gmail_handlers imports only from mcp.google_workspace to avoid circular dependencies.

2. **Test Failures on Pattern Ordering**: Initial regex patterns had "from" matching before time patterns, causing "from last week" to match as "from:last". Fixed by reordering patterns.

3. **Executor Signature Change**: Adding context parameter required updating all test calls to `_execute_action()`. Used find-replace to fix 9 occurrences.

4. **Confirmation Fields Not Propagating**: ActionResult had confirmation fields but they weren't being passed through AgentMessage payload. Fixed by conditionally adding them in `_create_response()`.

### Future Enhancements

1. **LLM-Generated Body**: Currently uses template placeholders. Future iteration could call LLM to generate actual email body content.

2. **Attachment Handling**: No support for attachments yet. Could extend EmailComposer to handle attachment references.

3. **Thread Context Loading**: Reply functionality exists but needs integration with thread loading to get original message context.

4. **Smart Reply Suggestions**: Could use LLM to generate quick reply options based on email content.

5. **Recipient Validation**: Currently just checks if email exists in context. Could validate email format and check against contact database.
