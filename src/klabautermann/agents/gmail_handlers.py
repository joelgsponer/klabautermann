"""
Gmail handlers for the Executor agent.

Provides sophisticated email composition, query building, and formatting
for Gmail operations. These handlers bridge natural language intent
and Gmail API operations.

Reference: specs/architecture/AGENTS.md Section 1.4
"""

from __future__ import annotations

import re

from klabautermann.mcp.google_workspace import EmailMessage


# ===========================================================================
# Email Composer
# ===========================================================================


class EmailComposer:
    """
    Helper for composing emails from natural language intent.

    Extracts or generates subjects, formats greetings and signatures,
    and prepares email bodies with appropriate tone.
    """

    # Common greeting patterns by tone
    GREETINGS = {
        "formal": "Dear {name},",
        "casual": "Hi {name},",
        "brief": "{name},",
    }

    # Default signature
    SIGNATURE = "\n\nBest regards"

    @classmethod
    def compose_email(
        cls,
        intent: str,
        recipient_name: str,
        context: str | None = None,
        tone: str = "casual",
    ) -> tuple[str, str]:
        """
        Compose email subject and body from natural language intent.

        Extracts subject from intent or generates one, formats greeting
        based on tone, and provides a template for body content.

        Args:
            intent: Natural language description of what to write
            recipient_name: Full name of recipient
            context: Optional additional context for the email
            tone: Communication tone (formal, casual, brief)

        Returns:
            Tuple of (subject, body_template)

        Example:
            >>> EmailComposer.compose_email(
            ...     "email Sarah about the meeting",
            ...     "Sarah Chen",
            ...     "discuss budget",
            ...     "casual"
            ... )
            ("Meeting", "Hi Sarah,\\n\\n[Message about: email Sarah about the meeting]\\n\\nBest regards")
        """
        # Extract or generate subject
        subject = cls._extract_subject(intent)

        # Generate greeting using first name only
        first_name = recipient_name.split()[0]
        greeting = cls.GREETINGS.get(tone, cls.GREETINGS["casual"]).format(name=first_name)

        # Build body template
        body_parts = [greeting, ""]

        # Add context placeholder
        context_text = f"[Message about: {intent}]"
        if context:
            context_text += f"\n[Context: {context}]"
        body_parts.append(context_text)

        # Add signature
        body_parts.append(cls.SIGNATURE)

        body_template = "\n".join(body_parts)

        return subject, body_template

    @classmethod
    def _extract_subject(cls, intent: str) -> str:
        """
        Extract or generate subject line from intent.

        Tries multiple strategies:
        1. Explicit "subject:" mention
        2. "about X" pattern extraction
        3. Keyword detection (meeting, update, etc.)
        4. Default to "Message"

        Args:
            intent: Natural language intent

        Returns:
            Extracted or generated subject line

        Example:
            >>> EmailComposer._extract_subject("email about the meeting")
            "The Meeting"
            >>> EmailComposer._extract_subject('subject: "Q1 Budget Review"')
            "Q1 Budget Review"
        """
        # Look for explicit subject
        subject_match = re.search(r'subject[:\s]+["\']?([^"\']+)["\']?', intent, re.IGNORECASE)
        if subject_match:
            return subject_match.group(1).strip()

        # Look for "about X" pattern
        about_match = re.search(r"about\s+(?:the\s+)?(.+?)(?:\s+to|\s*$)", intent, re.IGNORECASE)
        if about_match:
            subject = about_match.group(1).strip()
            # Capitalize appropriately
            return cls._capitalize_subject(subject)

        # Generate from common keywords
        keywords = ["meeting", "update", "question", "request", "follow-up", "followup"]
        for kw in keywords:
            if kw in intent.lower():
                return kw.replace("-", " ").title()

        # Default fallback
        return "Message"

    @classmethod
    def _capitalize_subject(cls, subject: str) -> str:
        """
        Capitalize subject line appropriately.

        Uses title case for short subjects, preserves existing
        capitalization for longer subjects.

        Args:
            subject: Raw subject text

        Returns:
            Properly capitalized subject
        """
        # If already capitalized, keep it
        if subject and subject[0].isupper():
            return subject

        # Title case for all subjects (preserves "the", "a", etc.)
        return subject.title() if subject else ""

    @classmethod
    def format_reply(
        cls,
        original_email: EmailMessage,
        reply_intent: str,
        quote_original: bool = False,
    ) -> tuple[str, str]:
        """
        Format a reply to an existing email.

        Args:
            original_email: The email being replied to
            reply_intent: What to say in the reply
            quote_original: Whether to quote the original message

        Returns:
            Tuple of (subject, body)

        Example:
            >>> email = EmailMessage(...)
            >>> EmailComposer.format_reply(email, "I agree", quote_original=True)
            ("Re: Original Subject", "...")
        """
        # Add "Re:" prefix if not already present
        subject = original_email.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Extract sender's first name
        sender_name = cls._extract_name_from_email(original_email.sender)
        first_name = sender_name.split()[0] if sender_name else "there"

        # Build reply body
        body_parts = [f"Hi {first_name},", ""]
        body_parts.append(f"[Reply about: {reply_intent}]")

        # Quote original if requested
        if quote_original:
            body_parts.append("")
            body_parts.append(
                f"On {original_email.date.strftime('%Y-%m-%d')}, {original_email.sender} wrote:"
            )
            # Quote the snippet or body
            quoted_text = original_email.body or original_email.snippet
            quoted_lines = [f"> {line}" for line in quoted_text.split("\n")]
            body_parts.extend(quoted_lines)

        body_parts.append(cls.SIGNATURE)

        return subject, "\n".join(body_parts)

    @classmethod
    def _extract_name_from_email(cls, email_address: str) -> str:
        """
        Extract name from email address.

        Handles formats like:
        - "Sarah Chen <sarah@example.com>"
        - "sarah@example.com"

        Args:
            email_address: Email address string

        Returns:
            Extracted name or email username
        """
        # Check for "Name <email>" format
        name_match = re.search(r"^(.+?)\s*<", email_address)
        if name_match:
            return name_match.group(1).strip()

        # Extract username from email
        username_match = re.search(r"^([^@]+)@", email_address)
        if username_match:
            username = username_match.group(1)
            # Convert "sarah.chen" to "Sarah Chen"
            return username.replace(".", " ").replace("_", " ").title()

        return "there"


# ===========================================================================
# Gmail Query Builder
# ===========================================================================


class GmailQueryBuilder:
    """
    Convert natural language to Gmail search queries.

    Applies regex patterns to detect common search intents and
    converts them to Gmail query syntax.
    """

    # Pattern matching rules: (pattern, template)
    # {0}, {1}, etc. are group captures from the pattern
    PATTERNS = [
        # From patterns
        (r"(?:emails?|messages?)\s+from\s+(\S+)", "from:{0}"),
        (r"from\s+(\S+)", "from:{0}"),
        # To patterns
        (r"(?:emails?|messages?)\s+to\s+(\S+)", "to:{0}"),
        (r"to\s+(\S+)", "to:{0}"),
        # Time patterns
        (r"(?:from\s+)?(?:this|last)\s+week", "newer_than:7d"),
        (r"(?:from\s+)?today", "newer_than:1d"),
        (r"(?:from\s+)?yesterday", "newer_than:2d older_than:1d"),
        (r"(?:from\s+)?last\s+month", "newer_than:30d"),
        (r"(?:from\s+)?last\s+(\d+)\s+days?", "newer_than:{0}d"),
        # Status patterns
        (r"\bunread\b", "is:unread"),
        (r"\bstarred\b", "is:starred"),
        (r"\bimportant\b", "is:important"),
        (r"\bhas\s+attachment", "has:attachment"),
        # Subject/content patterns
        (r"about\s+(.+?)(?:\s+from|\s+to|\s*$)", "subject:{0} OR {0}"),
        (r'subject[:\s]+["\']?([^"\']+)["\']?', "subject:{0}"),
    ]

    @classmethod
    def build_query(cls, natural_query: str) -> str:
        """
        Convert natural language to Gmail query string.

        Applies pattern matching to extract search criteria and
        converts to Gmail query syntax.

        Args:
            natural_query: Natural language search request

        Returns:
            Gmail search query string

        Example:
            >>> GmailQueryBuilder.build_query("emails from sarah about meeting")
            "from:sarah subject:meeting OR meeting"
            >>> GmailQueryBuilder.build_query("unread emails from last week")
            "is:unread newer_than:7d"
        """
        query_parts = []
        remaining = natural_query

        for pattern, template in cls.PATTERNS:
            match = re.search(pattern, remaining, re.IGNORECASE)
            if match:
                # Format template with captured groups
                if match.groups():
                    query_part = template.format(*match.groups())
                else:
                    query_part = template

                query_parts.append(query_part)

                # Remove matched part from remaining text
                remaining = remaining[: match.start()] + remaining[match.end() :]

        # If nothing matched, use remaining text as general search
        remaining = remaining.strip()
        if remaining and not query_parts:
            # Remove common filler words
            filler_words = ["show", "me", "find", "search", "get", "emails?", "messages?"]
            for word in filler_words:
                remaining = re.sub(rf"\b{word}\b", "", remaining, flags=re.IGNORECASE)
            remaining = remaining.strip()
            if remaining:
                query_parts.append(remaining)

        # Return joined query or default to inbox
        return " ".join(query_parts) if query_parts else "in:inbox"


# ===========================================================================
# Email Formatter
# ===========================================================================


class EmailFormatter:
    """
    Format email messages for display.

    Provides consistent formatting for email lists and individual
    email details with configurable truncation and highlighting.
    """

    @classmethod
    def format_email_list(
        cls,
        emails: list[EmailMessage],
        max_display: int = 5,
        include_snippet: bool = True,
    ) -> str:
        """
        Format list of emails for display.

        Args:
            emails: List of email messages to format
            max_display: Maximum number of emails to show (default: 5)
            include_snippet: Whether to include preview snippets

        Returns:
            Formatted string for display

        Example:
            >>> emails = [EmailMessage(...), EmailMessage(...)]
            >>> EmailFormatter.format_email_list(emails, max_display=3)
            "Found 2 email(s):\\n\\n1. From: sarah@example.com\\n   Subject: Meeting..."
        """
        if not emails:
            return "No emails found."

        lines = [f"Found {len(emails)} email(s):"]

        for i, email in enumerate(emails[:max_display]):
            lines.append("")  # Blank line between emails

            # Add unread indicator
            status = "[NEW] " if email.is_unread else ""

            # Format sender
            lines.append(f"{i + 1}. {status}From: {email.sender}")

            # Format subject
            lines.append(f"   Subject: {email.subject}")

            # Add date
            date_str = email.date.strftime("%Y-%m-%d %H:%M")
            lines.append(f"   Date: {date_str}")

            # Add snippet if requested
            if include_snippet and email.snippet:
                snippet = cls._truncate_text(email.snippet, max_length=100)
                lines.append(f"   Preview: {snippet}")

        # Add overflow indicator
        if len(emails) > max_display:
            lines.append("")
            lines.append(f"... and {len(emails) - max_display} more")

        return "\n".join(lines)

    @classmethod
    def format_email_detail(cls, email: EmailMessage) -> str:
        """
        Format single email for detailed view.

        Args:
            email: Email message to format

        Returns:
            Formatted string with full email details

        Example:
            >>> email = EmailMessage(...)
            >>> EmailFormatter.format_email_detail(email)
            "From: sarah@example.com\\nTo: me\\nDate: 2026-01-15 14:30\\nSubject: Meeting\\n\\n..."
        """
        lines = [
            f"From: {email.sender}",
            f"To: {email.recipient or 'me'}",
            f"Date: {email.date.strftime('%Y-%m-%d %H:%M')}",
            f"Subject: {email.subject}",
            "",  # Blank line before body
        ]

        # Use body if available, otherwise snippet
        content = email.body or email.snippet or "(no content)"
        lines.append(content)

        return "\n".join(lines)

    @classmethod
    def format_thread_summary(cls, emails: list[EmailMessage]) -> str:
        """
        Format a thread of emails as a conversation summary.

        Args:
            emails: List of emails in thread, ordered by date

        Returns:
            Formatted thread summary

        Example:
            >>> emails = [EmailMessage(...), EmailMessage(...)]
            >>> EmailFormatter.format_thread_summary(emails)
            "Thread: Meeting Discussion (3 messages)\\n\\n1. Sarah Chen (2026-01-15):\\n   ..."
        """
        if not emails:
            return "Empty thread."

        # Extract thread subject (use first email)
        subject = emails[0].subject
        lines = [f"Thread: {subject} ({len(emails)} message{'s' if len(emails) != 1 else ''})"]
        lines.append("")

        for i, email in enumerate(emails):
            sender_name = EmailComposer._extract_name_from_email(email.sender)
            date_str = email.date.strftime("%Y-%m-%d")

            lines.append(f"{i + 1}. {sender_name} ({date_str}):")

            # Show snippet or body (truncated)
            content = email.body or email.snippet or "(no content)"
            truncated = cls._truncate_text(content, max_length=200)
            # Indent content
            content_lines = truncated.split("\n")
            for line in content_lines:
                lines.append(f"   {line}")

            lines.append("")  # Blank line between messages

        return "\n".join(lines)

    @classmethod
    def _truncate_text(cls, text: str, max_length: int = 100) -> str:
        """
        Truncate text with ellipsis if too long.

        Args:
            text: Text to truncate
            max_length: Maximum length before truncation

        Returns:
            Truncated text with ellipsis if needed
        """
        if len(text) <= max_length:
            return text

        # Truncate at word boundary if possible
        truncated = text[:max_length]
        last_space = truncated.rfind(" ")

        if last_space > max_length * 0.8:  # Only use word boundary if close to end
            truncated = truncated[:last_space]

        return truncated + "..."


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "EmailComposer",
    "GmailQueryBuilder",
    "EmailFormatter",
]
