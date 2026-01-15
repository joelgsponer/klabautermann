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
        self.model = (
            self.config.get("model", "claude-3-5-sonnet-20241022")
            if config
            else "claude-3-5-sonnet-20241022"
        )

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process action request from Orchestrator.

        Args:
            msg: Agent message with action payload

        Returns:
            Response message with action result
        """
        action = msg.payload.get("action", "")
        context = msg.payload.get("context", {})

        if not action:
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
        self, action: str, context: dict[str, Any], trace_id: str
    ) -> ActionRequest:
        """
        Parse action string into structured request.

        Uses keyword detection to classify the action type.

        Args:
            action: User's action request text
            context: Context from Researcher (entities, search results)
            trace_id: Request trace ID

        Returns:
            Parsed ActionRequest
        """
        action_lower = action.lower()

        # Detect action type based on keywords
        if any(kw in action_lower for kw in ["send email", "email to", "draft email", "compose"]):
            return ActionRequest(
                type=ActionType.EMAIL_SEND,
                draft_only="draft" in action_lower,
            )
        elif any(
            kw in action_lower
            for kw in ["check email", "search email", "emails from", "find email"]
        ):
            return ActionRequest(type=ActionType.EMAIL_SEARCH, query=action)
        elif any(
            kw in action_lower
            for kw in ["schedule", "create event", "book meeting", "add to calendar"]
        ):
            return ActionRequest(type=ActionType.CALENDAR_CREATE)
        elif any(
            kw in action_lower for kw in ["calendar", "what's on", "check schedule", "my day"]
        ):
            return ActionRequest(type=ActionType.CALENDAR_LIST)

        # Default to email search if unclear
        return ActionRequest(type=ActionType.EMAIL_SEARCH, query=action)

    async def _validate_request(
        self, request: ActionRequest, context: dict[str, Any], trace_id: str
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
                start = datetime.fromisoformat(
                    request.start_time.replace("Z", "") if request.start_time else ""
                )
                end = datetime.fromisoformat(
                    request.end_time.replace("Z", "") if request.end_time else ""
                )

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
                        details={
                            "event_id": result.event_id,
                            "link": result.event_link,
                        },
                    )
                else:
                    return ActionResult(
                        success=False, message=f"Failed to create event: {result.error}"
                    )

            elif request.type == ActionType.CALENDAR_LIST:
                events = await self.google.get_todays_events(context=ctx)
                if events:
                    summaries = [f"- {e.start.strftime('%H:%M')}: {e.title}" for e in events]
                    return ActionResult(
                        success=True,
                        message="Today's schedule:\n" + "\n".join(summaries),
                        details={"count": len(events)},
                    )
                else:
                    return ActionResult(success=True, message="No events scheduled for today.")

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
                max_results=10,
                context=invocation_ctx,
            )

            # Format results using EmailFormatter
            formatted = EmailFormatter.format_email_list(
                emails, max_display=5, include_snippet=True
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
            return email

        # Check search results
        for result in context.get("results", []):
            if email := result.get("email"):
                return email

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
        )


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["Executor"]
