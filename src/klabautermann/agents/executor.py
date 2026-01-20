"""
Executor Agent - The "Admin" that performs real-world actions.

Handles email sending, calendar management, and other external actions via MCP tools.
Uses Claude Sonnet for reasoning about context and never hallucniates missing information.

Reference: specs/architecture/AGENTS.md Section 1.4
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.calendar_handlers import (
    CalendarFormatter,
    ConflictChecker,
    TimeParser,
)
from klabautermann.agents.gmail_handlers import EmailComposer, EmailFormatter, GmailQueryBuilder
from klabautermann.core.logger import logger
from klabautermann.core.models import ActionRequest, ActionResult, ActionType, AgentMessage
from klabautermann.mcp.client import ToolInvocationContext
from klabautermann.mcp.google_workspace import GoogleWorkspaceBridge


class Executor(BaseAgent):
    """
    The Executor agent - performs real-world actions via MCP tools.

    Responsibilities:
    1. Parse action requests into structured commands
    2. Verify all required information before execution
    3. Execute actions via GoogleWorkspaceBridge
    4. Report results with clear success/error messages
    5. NEVER send emails to unverified addresses
    6. NEVER hallucinate missing information

    Model: Claude Sonnet (for reasoning about context)
    MCP Access: Gmail (write), Calendar (write)
    Graph Access: Read (for context verification)
    """

    SYSTEM_PROMPT = """You are the Klabautermann Executor. You execute real-world actions via email and calendar.

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
"""

    # Default email configuration values
    DEFAULT_EMAIL_MAX_RESULTS = 20
    DEFAULT_EMAIL_MAX_DISPLAY = 10

    def __init__(
        self,
        name: str = "executor",
        config: dict[str, Any] | None = None,
        google_bridge: GoogleWorkspaceBridge | None = None,
    ) -> None:
        """
        Initialize the Executor agent.

        Args:
            name: Agent name (default: "executor")
            config: Agent configuration (model, etc.)
            google_bridge: GoogleWorkspaceBridge instance for MCP operations
        """
        super().__init__(name, config)
        self.google = google_bridge or GoogleWorkspaceBridge()
        if config:
            model_config = self.config.get("model", {})
            if isinstance(model_config, dict):
                self.model = model_config.get("primary", "claude-3-5-sonnet-20241022")
            else:
                self.model = model_config or "claude-3-5-sonnet-20241022"

            # Load email configuration
            email_config = self.config.get("email", {})
            self.email_max_results = email_config.get(
                "max_results", self.DEFAULT_EMAIL_MAX_RESULTS
            )
            self.email_max_display = email_config.get(
                "max_display", self.DEFAULT_EMAIL_MAX_DISPLAY
            )
        else:
            self.model = "claude-3-5-sonnet-20241022"
            self.email_max_results = self.DEFAULT_EMAIL_MAX_RESULTS
            self.email_max_display = self.DEFAULT_EMAIL_MAX_DISPLAY

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process action request from Orchestrator.

        Args:
            msg: Agent message with action payload

        Returns:
            Response message with action result
        """
        action = msg.payload.get("action", "")
        action_type = msg.payload.get("action_type", "")  # Structured action type from LLM
        gmail_query = msg.payload.get("gmail_query", "")  # Gmail query for email_search
        context = msg.payload.get("context", {})

        # Pass structured fields to context for _parse_action
        context["action_type"] = action_type
        context["gmail_query"] = gmail_query

        if not action and not action_type:
            return self._create_response(
                msg, ActionResult(success=False, message="No action specified.")
            )

        try:
            # Parse the action request
            request = await self._parse_action(action, context, msg.trace_id)

            logger.debug(
                f"[WHISPER] Parsed action: {request.type}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )

            # Validate the request
            validation = await self._validate_request(request, context, msg.trace_id)
            if not validation.success:
                return self._create_response(msg, validation)

            # Execute the action
            result = await self._execute_action(request, context, msg.trace_id)

            logger.info(
                f"[BEACON] Action {request.type} completed: {result.success}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
            )

            return self._create_response(msg, result)

        except Exception as e:
            logger.error(
                f"[STORM] Executor failed: {e}",
                extra={"trace_id": msg.trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return self._create_response(
                msg, ActionResult(success=False, message=f"Action failed: {e!s}")
            )

    async def _parse_action(
        self, action: str, context: dict[str, Any], _trace_id: str
    ) -> ActionRequest:
        """
        Parse action payload into structured request.

        Uses action_type from task planner (LLM output) - no keyword detection.

        Args:
            action: Legacy action string (fallback only)
            context: Context containing action_type and gmail_query from LLM
            trace_id: Request trace ID

        Returns:
            Parsed ActionRequest
        """
        # Get structured action_type from task planner (LLM output)
        action_type = context.get("action_type", "").lower()

        logger.debug(
            f"[WHISPER] Parsing action: action_type={action_type}",
            extra={"action": action, "context_keys": list(context.keys())},
        )

        # Direct mapping from action_type - no keyword detection
        if action_type == "email_search":
            query = context.get("gmail_query") or "in:inbox"
            return ActionRequest(type=ActionType.EMAIL_SEARCH, query=query)

        elif action_type == "email_send":
            return ActionRequest(
                type=ActionType.EMAIL_SEND,
                draft_only=context.get("draft_only", True),
            )

        elif action_type == "calendar_list":
            return ActionRequest(type=ActionType.CALENDAR_LIST)

        elif action_type == "calendar_create":
            return ActionRequest(type=ActionType.CALENDAR_CREATE)

        # Fallback: If no action_type provided, default to email search with inbox
        # This handles legacy payloads or when LLM doesn't follow the schema
        logger.warning(
            "[SWELL] No action_type provided, defaulting to email_search (inbox)",
            extra={"action": action, "action_type": action_type},
        )
        return ActionRequest(type=ActionType.EMAIL_SEARCH, query="in:inbox")

    async def _validate_request(
        self, request: ActionRequest, context: dict[str, Any], _trace_id: str
    ) -> ActionResult:
        """
        Validate request has all required information.

        Verification rules:
        1. Email sending requires verified recipient email
        2. Calendar events require valid start and end times
        3. Never guess missing information

        Args:
            request: Parsed action request
            context: Context from Researcher
            trace_id: Request trace ID

        Returns:
            ActionResult with validation status
        """
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

            # Validate ISO format
            try:
                datetime.fromisoformat(request.start_time.replace("Z", ""))
                datetime.fromisoformat(request.end_time.replace("Z", ""))
            except (ValueError, AttributeError):
                return ActionResult(
                    success=False,
                    message="The time format is invalid. Please specify times in ISO format (e.g., 2026-01-15T14:00:00).",
                )

        return ActionResult(success=True, message="Validation passed")

    async def _execute_action(
        self, request: ActionRequest, context: dict[str, Any], trace_id: str
    ) -> ActionResult:
        """
        Execute the validated action via MCP tools.

        Args:
            request: Validated action request
            context: Context from Researcher (for email composition, etc.)
            trace_id: Request trace ID

        Returns:
            ActionResult with execution status
        """
        ctx = ToolInvocationContext(trace_id=trace_id, agent_name=self.name)

        try:
            if request.type == ActionType.EMAIL_SEND:
                return await self._handle_gmail_send(request, context, trace_id, ctx)

            elif request.type == ActionType.EMAIL_SEARCH:
                return await self._handle_gmail_search(request, trace_id, ctx)

            elif request.type == ActionType.CALENDAR_CREATE:
                return await self._handle_calendar_create(request, context, trace_id, ctx)

            elif request.type == ActionType.CALENDAR_LIST:
                return await self._handle_calendar_list(request, trace_id, ctx)

            return ActionResult(success=False, message="Unknown action type.")

        except Exception as e:
            logger.error(
                f"[STORM] Action execution failed: {e}",
                extra={"trace_id": trace_id, "agent_name": self.name},
                exc_info=True,
            )
            return ActionResult(success=False, message=f"Execution error: {e!s}")

    async def _handle_gmail_send(
        self,
        request: ActionRequest,
        context: dict[str, Any],
        trace_id: str,
        invocation_ctx: ToolInvocationContext,
    ) -> ActionResult:
        """
        Handle email sending with sophisticated composition.

        Uses EmailComposer to generate appropriate subject and body,
        always creates a draft first for safety, and provides clear
        confirmation prompt.

        Args:
            request: Validated email send request
            context: Context from Researcher (for recipient info, etc.)
            trace_id: Request trace ID
            invocation_ctx: MCP tool invocation context

        Returns:
            ActionResult with draft confirmation or send status
        """
        # Get recipient name from context
        recipient_name = context.get("name", "there")

        # Check if we have subject and body already (from explicit user input)
        if request.subject and request.body:
            # Use provided content
            subject = request.subject
            body = request.body
        else:
            # Compose email using intent
            # Extract intent from action or context
            intent = context.get("action", "message")

            subject, body_template = EmailComposer.compose_email(
                intent=intent,
                recipient_name=recipient_name,
                context=context.get("context_text"),
                tone="casual",
            )

            # For now, use the template as-is
            # Future: LLM could fill in the template here
            body = body_template

        # Always create draft first for safety
        result = await self.google.send_email(
            to=request.target or "",
            subject=subject,
            body=body,
            draft_only=True,
            context=invocation_ctx,
        )

        if result.success:
            logger.debug(
                f"[WHISPER] Created email draft: {result.message_id}",
                extra={"trace_id": trace_id},
            )

            return ActionResult(
                success=True,
                message=f"I've drafted an email to {recipient_name} ({request.target}) with subject '{subject}'.\n\n"
                f"Preview:\n{body[:200]}{'...' if len(body) > 200 else ''}\n\n"
                "Would you like me to send it?",
                needs_confirmation=True,
                confirmation_prompt="Say 'send it' to send the draft, or 'show draft' to review.",
                details={
                    "draft_id": result.message_id,
                    "recipient": request.target,
                    "subject": subject,
                },
            )

        return ActionResult(success=False, message=f"Failed to create draft: {result.error}")

    async def _handle_gmail_search(
        self,
        request: ActionRequest,
        trace_id: str,
        invocation_ctx: ToolInvocationContext,
    ) -> ActionResult:
        """
        Handle email search with natural language query conversion.

        Uses GmailQueryBuilder to convert natural language to Gmail
        query syntax, executes search, and formats results with
        EmailFormatter.

        Args:
            request: Email search request with natural language query
            trace_id: Request trace ID
            invocation_ctx: MCP tool invocation context

        Returns:
            ActionResult with formatted email list
        """
        # Convert natural language to Gmail query
        gmail_query = GmailQueryBuilder.build_query(request.query or "")

        logger.debug(
            f"[WHISPER] Gmail search query: {gmail_query}",
            extra={"trace_id": trace_id, "natural_query": request.query},
        )

        try:
            # Execute search using the built query
            emails = await self.google.search_emails(
                query=gmail_query,
                max_results=self.email_max_results,
                context=invocation_ctx,
            )

            # Format results using EmailFormatter with full body content
            formatted = EmailFormatter.format_email_list(
                emails,
                max_display=self.email_max_display,
                include_body=True,
                body_max_length=500,
                total_available=self.email_max_results,  # Hint for "may have more"
            )

            logger.info(
                f"[BEACON] Found {len(emails)} emails for query: {gmail_query}",
                extra={"trace_id": trace_id},
            )

            return ActionResult(
                success=True,
                message=formatted,
                details={
                    "query": gmail_query,
                    "natural_query": request.query,
                    "count": len(emails),
                },
            )

        except Exception as e:
            logger.error(
                f"[STORM] Gmail search failed: {e}",
                extra={"trace_id": trace_id, "query": gmail_query},
                exc_info=True,
            )
            return ActionResult(
                success=False,
                message=f"Failed to search emails: {e!s}",
            )

    def _find_email_in_context(self, context: dict[str, Any]) -> str | None:
        """
        Extract email address from context.

        Searches in multiple places:
        1. Direct "email" field
        2. Search results from Researcher
        3. Email pattern in content string

        Args:
            context: Context dictionary from Researcher

        Returns:
            Email address if found, None otherwise
        """
        # Check direct email field
        if email := context.get("email"):
            return str(email)

        # Check search results
        for result in context.get("results", []):
            if email := result.get("email"):
                return str(email)

        # Check content for email pattern
        content = context.get("result", "")
        match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", content)
        if match:
            return match.group(0)

        return None

    def _create_response(self, original_msg: AgentMessage, result: ActionResult) -> AgentMessage:
        """
        Create response message for Orchestrator.

        Args:
            original_msg: Original request message
            result: Action execution result

        Returns:
            Response AgentMessage
        """
        payload = {
            "result": result.message,
            "success": result.success,
            "details": result.details,
        }

        # Include confirmation fields if present
        if result.needs_confirmation:
            payload["needs_confirmation"] = result.needs_confirmation
        if result.confirmation_prompt:
            payload["confirmation_prompt"] = result.confirmation_prompt

        return AgentMessage(
            trace_id=original_msg.trace_id,
            source_agent=self.name,
            target_agent=original_msg.source_agent,
            intent="action_response",
            payload=payload,
        )

    async def _handle_calendar_create(
        self,
        request: ActionRequest,
        context: dict[str, Any],
        trace_id: str,
        invocation_ctx: ToolInvocationContext,
    ) -> ActionResult:
        """
        Handle calendar event creation with natural language time parsing and conflict detection.

        Features:
        1. Parse natural language times (e.g., "tomorrow at 2pm", "next Monday")
        2. Check for scheduling conflicts
        3. Suggest alternative times if conflicts found
        4. Extract event title from action text

        Args:
            request: Validated calendar create request
            context: Context from Researcher (for additional context)
            trace_id: Request trace ID
            invocation_ctx: MCP tool invocation context

        Returns:
            ActionResult with event creation status or conflict warnings
        """
        # Parse times from the action text if not already provided
        if not request.start_time or not request.end_time:
            # Extract action text from context
            action_text = context.get("action", "")
            start, end = TimeParser.parse_range(action_text, timezone="UTC")

            if not start or not end:
                return ActionResult(
                    success=False,
                    message="I couldn't understand the time. Please specify when, like 'tomorrow at 2pm' or '3pm to 4pm'.",
                )

            # Convert to ISO format for the request
            request.start_time = start.isoformat()
            request.end_time = end.isoformat()

        # Parse the times
        start = datetime.fromisoformat(request.start_time.replace("Z", ""))
        end = datetime.fromisoformat(request.end_time.replace("Z", ""))

        # Check for conflicts
        existing_events = await self.google.list_events(
            start=start.replace(hour=0, minute=0, second=0),
            end=start.replace(hour=23, minute=59, second=59),
            context=invocation_ctx,
        )

        conflicts = ConflictChecker.check_conflicts(start, end, existing_events)

        if conflicts:
            # Format conflict warning
            conflict_names = ", ".join(c.title for c in conflicts)

            # Find free slots
            free_slots = ConflictChecker.find_free_slots(
                date=start,
                duration=end - start,
                existing_events=existing_events,
            )

            message = f"That time conflicts with: {conflict_names}."
            if free_slots:
                slot_suggestions = [
                    f"{s[0].strftime('%H:%M')} - {s[1].strftime('%H:%M')}" for s in free_slots[:3]
                ]
                message += "\n\nSuggested free times:\n- " + "\n- ".join(slot_suggestions)

            return ActionResult(
                success=False,
                message=message,
                needs_confirmation=True,
                details={
                    "conflicts": [c.title for c in conflicts],
                    "free_slots": [
                        {
                            "start": s[0].isoformat(),
                            "end": s[1].isoformat(),
                        }
                        for s in free_slots[:3]
                    ],
                },
            )

        # Extract title from action text if not provided
        title = request.subject or self._extract_event_title(context.get("action", ""))

        # Create the event
        result = await self.google.create_event(
            title=title,
            start=start,
            end=end,
            description=request.body,
            context=invocation_ctx,
        )

        if result.success:
            logger.info(
                f"[BEACON] Created calendar event: {title}",
                extra={"trace_id": trace_id, "event_id": result.event_id},
            )

            return ActionResult(
                success=True,
                message=f"Created '{title}' on {start.strftime('%A, %B %d at %H:%M')}.",
                details={
                    "event_id": result.event_id,
                    "link": result.event_link,
                },
            )
        else:
            return ActionResult(
                success=False,
                message=f"Failed to create event: {result.error}",
            )

    async def _handle_calendar_list(
        self,
        _request: ActionRequest,
        trace_id: str,
        invocation_ctx: ToolInvocationContext,
    ) -> ActionResult:
        """
        Handle calendar event listing with formatted output.

        Provides rich formatting of calendar events including:
        1. Date-grouped display
        2. Duration formatting
        3. Location information
        4. Schedule summaries

        Args:
            request: Calendar list request
            trace_id: Request trace ID
            invocation_ctx: MCP tool invocation context

        Returns:
            ActionResult with formatted event list
        """
        try:
            # Get today's events
            events = await self.google.get_todays_events(context=invocation_ctx)

            if not events:
                return ActionResult(
                    success=True,
                    message="No events scheduled for today.",
                )

            # Format events using CalendarFormatter
            formatted_list = CalendarFormatter.format_event_list(events, max_display=10)
            summary = CalendarFormatter.format_schedule_summary(events)

            logger.info(
                f"[BEACON] Listed {len(events)} events for today",
                extra={"trace_id": trace_id, "count": len(events)},
            )

            return ActionResult(
                success=True,
                message=f"Today's schedule:\n{formatted_list}\n\n{summary}",
                details={"count": len(events)},
            )

        except Exception as e:
            logger.error(
                f"[STORM] Calendar list failed: {e}",
                extra={"trace_id": trace_id},
                exc_info=True,
            )
            return ActionResult(
                success=False,
                message=f"Failed to list events: {e!s}",
            )

    def _extract_event_title(self, action_text: str) -> str:
        """
        Extract event title from action text.

        Uses simple heuristics to extract a title from text like:
        - "Schedule meeting with Sarah"
        - "Book dentist appointment tomorrow"
        - "Add team standup to calendar"

        Args:
            action_text: Raw action text from user

        Returns:
            Extracted title or "New Event" as fallback
        """
        # Remove common action verbs
        text = action_text.lower()
        for verb in ["schedule", "book", "add", "create", "set up", "arrange"]:
            text = text.replace(verb, "").strip()

        # Remove calendar-related words
        for word in ["meeting", "appointment", "event", "to calendar", "on calendar"]:
            text = text.replace(word, "").strip()

        # Remove time-related phrases
        text = re.sub(r"\b(tomorrow|today|next \w+|at \d+|in \d+)\b.*", "", text).strip()

        # Capitalize first letter
        if text:
            title = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
            return title or "New Event"

        return "New Event"


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Executor"]
