"""
Markdown formatting utilities for Telegram channel.

Provides escaping and formatting for Telegram's Markdown parser.
Telegram supports a subset of Markdown with specific escape requirements.

Reference: https://core.telegram.org/bots/api#markdownv2-style
Issue: #139
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from klabautermann.core.logger import logger


@dataclass
class FormattingResult:
    """Result of markdown formatting operation."""

    original: str
    formatted: str
    was_escaped: bool = False
    escape_count: int = 0


class TelegramMarkdownFormatter:
    """
    Formatter for Telegram Markdown messages.

    Telegram's Markdown parser is strict about special characters.
    This formatter escapes characters that would break parsing while
    preserving intentional formatting.

    Supported formatting (preserved):
    - *bold*
    - _italic_
    - `code`
    - ```pre```
    - [links](url)

    Special characters (escaped):
    - _ * [ ] ( ) ~ ` > # + - = | { } . !

    Issue: #139
    """

    # Characters that need escaping in Telegram Markdown
    # Note: We don't escape * and _ by default since they're used for formatting
    ESCAPE_CHARS: ClassVar[str] = r"[\[\]()~`>#+=|{}.!-]"
    ESCAPE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(ESCAPE_CHARS)

    # Pattern to detect markdown formatting we want to preserve
    # Matches *bold*, _italic_, `code`, ```pre```, [text](url)
    FORMATTING_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"\*[^*]+\*"),  # *bold*
        re.compile(r"_[^_]+_"),  # _italic_
        re.compile(r"`[^`]+`"),  # `code`
        re.compile(r"```[\s\S]*?```"),  # ```pre```
        re.compile(r"\[[^\]]+\]\([^)]+\)"),  # [text](url)
    ]

    def __init__(self, preserve_formatting: bool = True) -> None:
        """
        Initialize the formatter.

        Args:
            preserve_formatting: If True, preserve intentional Markdown formatting.
                               If False, escape everything for plain text display.
        """
        self.preserve_formatting = preserve_formatting

    def format(self, text: str) -> FormattingResult:
        """
        Format text for Telegram Markdown.

        Escapes special characters while preserving intentional formatting.

        Args:
            text: Raw text to format.

        Returns:
            FormattingResult with formatted text and metadata.
        """
        if not text:
            return FormattingResult(original=text, formatted=text)

        if self.preserve_formatting:
            formatted, count = self._escape_preserving_formatting(text)
        else:
            formatted, count = self._escape_all(text)

        return FormattingResult(
            original=text,
            formatted=formatted,
            was_escaped=count > 0,
            escape_count=count,
        )

    def _escape_preserving_formatting(self, text: str) -> tuple[str, int]:
        """
        Escape special characters while preserving Markdown formatting.

        Strategy:
        1. Find all formatting spans (bold, italic, code, etc.)
        2. Mark those regions as protected
        3. Escape special characters only in unprotected regions

        Args:
            text: Text to process.

        Returns:
            Tuple of (formatted_text, escape_count).
        """
        # Find all protected regions (formatting we want to keep)
        protected_regions: list[tuple[int, int]] = []
        for pattern in self.FORMATTING_PATTERNS:
            for match in pattern.finditer(text):
                protected_regions.append((match.start(), match.end()))

        # Sort and merge overlapping regions
        protected_regions.sort()
        merged: list[tuple[int, int]] = []
        for start, end in protected_regions:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        # Build result by processing unprotected regions
        result: list[str] = []
        escape_count = 0
        pos = 0

        for region_start, region_end in merged:
            # Process unprotected text before this region
            if pos < region_start:
                unprotected = text[pos:region_start]
                escaped, count = self._escape_segment(unprotected)
                result.append(escaped)
                escape_count += count

            # Add protected region unchanged
            result.append(text[region_start:region_end])
            pos = region_end

        # Process remaining unprotected text
        if pos < len(text):
            unprotected = text[pos:]
            escaped, count = self._escape_segment(unprotected)
            result.append(escaped)
            escape_count += count

        return "".join(result), escape_count

    def _escape_segment(self, text: str) -> tuple[str, int]:
        """
        Escape special characters in a text segment.

        Args:
            text: Text segment to escape.

        Returns:
            Tuple of (escaped_text, escape_count).
        """
        count = len(self.ESCAPE_PATTERN.findall(text))
        escaped = self.ESCAPE_PATTERN.sub(r"\\\g<0>", text)
        return escaped, count

    def _escape_all(self, text: str) -> tuple[str, int]:
        """
        Escape all special characters including formatting markers.

        Args:
            text: Text to escape.

        Returns:
            Tuple of (escaped_text, escape_count).
        """
        # Extended pattern including * and _
        full_pattern = re.compile(r"[_*\[\]()~`>#+=|{}.!-]")
        count = len(full_pattern.findall(text))
        escaped = full_pattern.sub(r"\\\g<0>", text)
        return escaped, count


def escape_markdown(text: str, preserve_formatting: bool = True) -> str:
    """
    Convenience function to escape text for Telegram Markdown.

    Args:
        text: Text to escape.
        preserve_formatting: Whether to preserve intentional formatting.

    Returns:
        Escaped text safe for Telegram's Markdown parser.
    """
    formatter = TelegramMarkdownFormatter(preserve_formatting=preserve_formatting)
    return formatter.format(text).formatted


async def safe_send_markdown(
    send_func: object,
    text: str,
    **kwargs: object,
) -> bool:
    """
    Send a message with Markdown, falling back to plain text on error.

    Attempts to send with Markdown parsing. If that fails (due to malformed
    Markdown), retries without parse_mode.

    Args:
        send_func: Async function to send message (e.g., bot.send_message).
        text: Message text.
        **kwargs: Additional arguments for send_func.

    Returns:
        True if message was sent successfully.

    Issue: #139
    """
    # Type narrowing for the send function
    from collections.abc import Callable
    from typing import Any, cast

    send = cast(Callable[..., Any], send_func)

    try:
        # First attempt: with Markdown
        await send(text=text, parse_mode="Markdown", **kwargs)
        return True
    except Exception as e:
        error_msg = str(e).lower()

        # Check if it's a Markdown parsing error
        if "parse" in error_msg or "markdown" in error_msg or "can't" in error_msg:
            logger.warning(
                f"[SWELL] Markdown parsing failed, retrying as plain text: {e}",
                extra={"agent_name": "telegram"},
            )
            try:
                # Retry without Markdown
                await send(text=text, **kwargs)
                return True
            except Exception as retry_error:
                logger.error(
                    f"[STORM] Message send failed even without Markdown: {retry_error}",
                    extra={"agent_name": "telegram"},
                )
                return False
        else:
            # Not a Markdown error, re-raise
            logger.error(
                f"[STORM] Message send failed: {e}",
                extra={"agent_name": "telegram"},
            )
            return False


# ===========================================================================
# Export
# ===========================================================================

__all__ = [
    "FormattingResult",
    "TelegramMarkdownFormatter",
    "escape_markdown",
    "safe_send_markdown",
]
