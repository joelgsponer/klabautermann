# Implement Executor Agent

## Metadata
- **ID**: T029
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: pending
- **Assignee**: carpenter

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.4
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [ ] T021 - Agent delegation pattern
- [ ] T028 - Google Workspace MCP bridge
- [x] T016 - Base Agent class

## Context
The Executor is the "Admin" that performs real-world actions via MCP tools. It uses Claude Sonnet for reasoning about context and confirmation. The Executor must VERIFY all information before executing actions - it should never send emails to addresses not found in the graph or create events without proper validation.

## Requirements
- [ ] Create `src/klabautermann/agents/executor.py`:

### Action Types
- [ ] EMAIL_SEND: Send or draft email
- [ ] EMAIL_SEARCH: Search inbox
- [ ] CALENDAR_CREATE: Create calendar event
- [ ] CALENDAR_LIST: List/check events

### Verification
- [ ] Verify recipient email exists in context or graph
- [ ] Verify event times are valid and not conflicting
- [ ] Verify all required fields present before execution
- [ ] Never hallucinate missing information

### Confirmation Protocol
- [ ] For sending emails: summarize what will be sent
- [ ] For creating events: summarize event details
- [ ] For destructive actions: require explicit confirmation

### Error Handling
- [ ] Graceful error messages for users
- [ ] No retries without user confirmation
- [ ] Clear error attribution (MCP vs validation)

### System Prompt
- [ ] Verification rules
- [ ] Confirmation protocol
- [ ] Error handling guidelines

## Acceptance Criteria
- [ ] "Send email to Sarah" uses email from graph context
- [ ] Missing email triggers "I need Sarah's email address"
- [ ] "Schedule meeting tomorrow" creates valid event
- [ ] MCP errors reported clearly to user
- [ ] All actions logged with trace ID

## Implementation Notes

```python
from typing import Optional, Dict, Any, List
from enum import Enum
from pydantic import BaseModel, Field
import time

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.models import AgentMessage
from klabautermann.core.logger import logger
from klabautermann.mcp.google_workspace import (
    GoogleWorkspaceBridge,
    EmailMessage,
    CalendarEvent,
    SendEmailResult,
    CreateEventResult,
)
from klabautermann.mcp.client import ToolInvocationContext


class ActionType(str, Enum):
    EMAIL_SEND = "email_send"
    EMAIL_SEARCH = "email_search"
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_LIST = "calendar_list"


class ActionRequest(BaseModel):
    """Parsed action request."""
    type: ActionType
    target: Optional[str] = None  # Recipient or calendar
    subject: Optional[str] = None
    body: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    draft_only: bool = False


class ActionResult(BaseModel):
    """Result of action execution."""
    success: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    needs_confirmation: bool = False
    confirmation_prompt: Optional[str] = None


class Executor(BaseAgent):
    """
    The Executor: performs real-world actions via MCP tools.

    Uses Claude Sonnet for reasoning about context.
    Verifies all information before execution.
    Never sends to unverified recipients.
    """

    SYSTEM_PROMPT = '''You are the Klabautermann Executor. You execute real-world actions via email and calendar.

VERIFICATION RULES:
1. NEVER send email to an address not provided in context
2. NEVER create events without valid start and end times
3. NEVER guess missing information - ask for it instead

CONFIRMATION RULES:
1. For sending emails: summarize recipient, subject, and body first
2. For creating events: confirm title, time, and attendees
3. For destructive actions: require explicit "yes" from user

ERROR HANDLING:
1. If recipient email not in context: "I need {name}'s email address"
2. If time invalid: "Please specify a valid time for the event"
3. If MCP fails: Report the specific error, don't retry automatically
'''

    def __init__(
        self,
        name: str = "executor",
        config: Optional[dict] = None,
        google_bridge: Optional[GoogleWorkspaceBridge] = None,
        llm_client = None,
    ):
        super().__init__(name, config)
        self.google = google_bridge or GoogleWorkspaceBridge()
        self.llm = llm_client
        self.model = config.get("model", "claude-3-5-sonnet-20241022") if config else "claude-3-5-sonnet-20241022"

    async def process_message(self, msg: AgentMessage) -> Optional[AgentMessage]:
        """Process action request."""
        action = msg.payload.get("action", "")
        context = msg.payload.get("context", {})

        if not action:
            return self._create_response(
                msg,
                ActionResult(success=False, message="No action specified.")
            )

        try:
            # Parse the action request
            request = await self._parse_action(action, context, msg.trace_id)

            logger.debug(
                f"[WHISPER] Parsed action: {request.type}",
                extra={"trace_id": msg.trace_id}
            )

            # Validate the request
            validation = await self._validate_request(request, context, msg.trace_id)
            if not validation.success:
                return self._create_response(msg, validation)

            # Execute the action
            result = await self._execute_action(request, msg.trace_id)

            logger.info(
                f"[BEACON] Action {request.type} completed: {result.success}",
                extra={"trace_id": msg.trace_id}
            )

            return self._create_response(msg, result)

        except Exception as e:
            logger.error(
                f"[STORM] Executor failed: {e}",
                extra={"trace_id": msg.trace_id},
                exc_info=True,
            )
            return self._create_response(
                msg,
                ActionResult(success=False, message=f"Action failed: {str(e)}")
            )

    async def _parse_action(
        self, action: str, context: dict, trace_id: str
    ) -> ActionRequest:
        """Parse action string into structured request."""
        action_lower = action.lower()

        # Detect action type
        if any(kw in action_lower for kw in ["send email", "email to", "draft email"]):
            return ActionRequest(
                type=ActionType.EMAIL_SEND,
                draft_only="draft" in action_lower,
            )
        elif any(kw in action_lower for kw in ["check email", "search email", "emails from"]):
            return ActionRequest(type=ActionType.EMAIL_SEARCH)
        elif any(kw in action_lower for kw in ["schedule", "create event", "book meeting"]):
            return ActionRequest(type=ActionType.CALENDAR_CREATE)
        elif any(kw in action_lower for kw in ["calendar", "schedule", "what's on"]):
            return ActionRequest(type=ActionType.CALENDAR_LIST)

        # Default to email search if unclear
        return ActionRequest(type=ActionType.EMAIL_SEARCH)

    async def _validate_request(
        self, request: ActionRequest, context: dict, trace_id: str
    ) -> ActionResult:
        """Validate request has all required information."""

        if request.type == ActionType.EMAIL_SEND:
            # Must have recipient email from context
            recipient_email = self._find_email_in_context(context)
            if not recipient_email:
                return ActionResult(
                    success=False,
                    message="I need the recipient's email address. Can you provide it or tell me who to look up?",
                )
            request.target = recipient_email

        elif request.type == ActionType.CALENDAR_CREATE:
            # Must have valid times
            if not request.start_time or not request.end_time:
                return ActionResult(
                    success=False,
                    message="I need a start and end time for the event. When should it be?",
                )

        return ActionResult(success=True, message="Validation passed")

    async def _execute_action(
        self, request: ActionRequest, trace_id: str
    ) -> ActionResult:
        """Execute the validated action."""
        ctx = ToolInvocationContext(trace_id=trace_id, agent_name=self.name)

        if request.type == ActionType.EMAIL_SEND:
            result = await self.google.send_email(
                to=request.target,
                subject=request.subject or "(no subject)",
                body=request.body or "",
                draft_only=request.draft_only,
                context=ctx,
            )
            if result.success:
                verb = "drafted" if result.is_draft else "sent"
                return ActionResult(
                    success=True,
                    message=f"Email {verb} to {request.target}.",
                    details={"message_id": result.message_id},
                )
            else:
                return ActionResult(success=False, message=f"Failed to send email: {result.error}")

        elif request.type == ActionType.EMAIL_SEARCH:
            emails = await self.google.get_recent_emails(hours=24, context=ctx)
            if emails:
                summaries = [f"- {e.sender}: {e.subject}" for e in emails[:5]]
                return ActionResult(
                    success=True,
                    message=f"Found {len(emails)} recent emails:\n" + "\n".join(summaries),
                    details={"count": len(emails)},
                )
            else:
                return ActionResult(success=True, message="No recent emails found.")

        elif request.type == ActionType.CALENDAR_CREATE:
            from datetime import datetime
            start = datetime.fromisoformat(request.start_time)
            end = datetime.fromisoformat(request.end_time)

            result = await self.google.create_event(
                title=request.subject or "New Event",
                start=start,
                end=end,
                description=request.body,
                context=ctx,
            )
            if result.success:
                return ActionResult(
                    success=True,
                    message=f"Created event: {request.subject}",
                    details={"event_id": result.event_id, "link": result.event_link},
                )
            else:
                return ActionResult(success=False, message=f"Failed to create event: {result.error}")

        elif request.type == ActionType.CALENDAR_LIST:
            events = await self.google.get_todays_events(context=ctx)
            if events:
                summaries = [f"- {e.start.strftime('%H:%M')}: {e.title}" for e in events]
                return ActionResult(
                    success=True,
                    message=f"Today's schedule:\n" + "\n".join(summaries),
                    details={"count": len(events)},
                )
            else:
                return ActionResult(success=True, message="No events scheduled for today.")

        return ActionResult(success=False, message="Unknown action type.")

    def _find_email_in_context(self, context: dict) -> Optional[str]:
        """Extract email address from context."""
        # Check direct email field
        if email := context.get("email"):
            return email

        # Check search results
        for result in context.get("results", []):
            if email := result.get("email"):
                return email

        # Check content for email pattern
        content = context.get("result", "")
        import re
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', content)
        if match:
            return match.group(0)

        return None

    def _create_response(
        self, original_msg: AgentMessage, result: ActionResult
    ) -> AgentMessage:
        """Create response message for Orchestrator."""
        return AgentMessage(
            trace_id=original_msg.trace_id,
            source_agent=self.name,
            target_agent=original_msg.source_agent,
            intent="action_response",
            payload={
                "result": result.message,
                "success": result.success,
                "details": result.details,
            },
            timestamp=time.time(),
        )
```

**Security Note**: The Executor should NEVER send emails to addresses not explicitly provided or found in the graph. When in doubt, ask the user for confirmation.
