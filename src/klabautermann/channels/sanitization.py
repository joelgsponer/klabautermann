"""
Input sanitization for all communication channels.

Provides security-focused input validation and sanitization to protect
against injection attacks, malformed input, and resource exhaustion.

Reference: Issue #158
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import ClassVar

from klabautermann.core.logger import logger


@dataclass
class SanitizationConfig:
    """Configuration for input sanitization."""

    # Maximum message length (characters)
    max_message_length: int = 32_000

    # Maximum length for thread IDs
    max_thread_id_length: int = 256

    # Whether to strip control characters
    strip_control_chars: bool = True

    # Whether to normalize unicode
    normalize_unicode: bool = True

    # Unicode normalization form (NFC, NFD, NFKC, NFKD)
    unicode_form: str = "NFC"

    # Whether to remove null bytes
    remove_null_bytes: bool = True

    # Whether to strip leading/trailing whitespace
    strip_whitespace: bool = True

    # Whether to collapse multiple whitespace to single space
    collapse_whitespace: bool = False


@dataclass
class SanitizationResult:
    """Result of sanitization operation."""

    original: str
    sanitized: str
    modifications: list[str] = field(default_factory=list)
    truncated: bool = False
    original_length: int = 0
    sanitized_length: int = 0

    @property
    def was_modified(self) -> bool:
        """Check if input was modified during sanitization."""
        return self.original != self.sanitized

    @property
    def modification_summary(self) -> str:
        """Get a summary of modifications made."""
        if not self.modifications:
            return "No modifications"
        return "; ".join(self.modifications)


class InputSanitizer:
    """
    Sanitizes user input across all communication channels.

    Security features:
    - Removes null bytes (prevents string termination attacks)
    - Strips control characters (prevents terminal injection)
    - Enforces message length limits (prevents resource exhaustion)
    - Normalizes unicode (prevents homograph attacks)
    - Logs all sanitization events for audit trail
    """

    # Control characters to remove (C0 and C1 controls except common whitespace)
    # Preserves: tab (0x09), newline (0x0A), carriage return (0x0D)
    CONTROL_CHAR_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]"
    )

    # Null byte pattern
    NULL_BYTE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"\x00")

    # Multiple whitespace pattern
    MULTI_WHITESPACE_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[ \t]+")

    def __init__(self, config: SanitizationConfig | None = None) -> None:
        """
        Initialize the sanitizer.

        Args:
            config: Sanitization configuration. Uses defaults if not provided.
        """
        self.config = config or SanitizationConfig()

    def sanitize(
        self,
        text: str,
        *,
        context: str = "message",
        trace_id: str | None = None,
    ) -> SanitizationResult:
        """
        Sanitize input text.

        Args:
            text: Input text to sanitize.
            context: Context for logging (e.g., "message", "thread_id").
            trace_id: Optional trace ID for logging.

        Returns:
            SanitizationResult with original and sanitized text.
        """
        if not isinstance(text, str):
            # Convert to string if not already
            text = str(text) if text is not None else ""

        result = SanitizationResult(
            original=text,
            sanitized=text,
            original_length=len(text),
        )

        # Track current state
        current = text

        # Step 1: Remove null bytes
        if self.config.remove_null_bytes:
            current, removed = self._remove_null_bytes(current)
            if removed > 0:
                result.modifications.append(f"removed {removed} null byte(s)")

        # Step 2: Strip control characters
        if self.config.strip_control_chars:
            current, removed = self._strip_control_chars(current)
            if removed > 0:
                result.modifications.append(f"removed {removed} control char(s)")

        # Step 3: Normalize unicode
        if self.config.normalize_unicode:
            current, was_normalized = self._normalize_unicode(current)
            if was_normalized:
                result.modifications.append(f"normalized unicode ({self.config.unicode_form})")

        # Step 4: Handle whitespace
        if self.config.strip_whitespace:
            new_current = current.strip()
            if new_current != current:
                result.modifications.append("stripped whitespace")
                current = new_current

        if self.config.collapse_whitespace:
            new_current = self.MULTI_WHITESPACE_PATTERN.sub(" ", current)
            if new_current != current:
                result.modifications.append("collapsed whitespace")
                current = new_current

        # Step 5: Enforce length limit
        max_length = (
            self.config.max_thread_id_length
            if context == "thread_id"
            else self.config.max_message_length
        )

        if len(current) > max_length:
            current = current[:max_length]
            result.truncated = True
            result.modifications.append(f"truncated to {max_length} chars")

        # Finalize result
        result.sanitized = current
        result.sanitized_length = len(current)

        # Log if modifications were made
        if result.was_modified and trace_id:
            self._log_sanitization(result, context, trace_id)

        return result

    def sanitize_message(
        self,
        message: str,
        trace_id: str | None = None,
    ) -> str:
        """
        Sanitize a user message. Convenience method.

        Args:
            message: Message content to sanitize.
            trace_id: Optional trace ID for logging.

        Returns:
            Sanitized message string.
        """
        return self.sanitize(message, context="message", trace_id=trace_id).sanitized

    def sanitize_thread_id(
        self,
        thread_id: str,
        trace_id: str | None = None,
    ) -> str:
        """
        Sanitize a thread ID. Convenience method.

        Args:
            thread_id: Thread ID to sanitize.
            trace_id: Optional trace ID for logging.

        Returns:
            Sanitized thread ID string.
        """
        return self.sanitize(thread_id, context="thread_id", trace_id=trace_id).sanitized

    def _remove_null_bytes(self, text: str) -> tuple[str, int]:
        """Remove null bytes from text."""
        matches = self.NULL_BYTE_PATTERN.findall(text)
        if matches:
            return self.NULL_BYTE_PATTERN.sub("", text), len(matches)
        return text, 0

    def _strip_control_chars(self, text: str) -> tuple[str, int]:
        """Remove control characters from text."""
        matches = self.CONTROL_CHAR_PATTERN.findall(text)
        if matches:
            return self.CONTROL_CHAR_PATTERN.sub("", text), len(matches)
        return text, 0

    def _normalize_unicode(self, text: str) -> tuple[str, bool]:
        """Normalize unicode characters."""
        normalized = unicodedata.normalize(self.config.unicode_form, text)
        return normalized, normalized != text

    def _log_sanitization(
        self,
        result: SanitizationResult,
        context: str,
        trace_id: str,
    ) -> None:
        """Log sanitization event for audit trail."""
        logger.info(
            f"[SIEVE] Input sanitized: {result.modification_summary}",
            extra={
                "agent_name": "sanitizer",
                "trace_id": trace_id,
                "context": context,
                "original_length": result.original_length,
                "sanitized_length": result.sanitized_length,
                "truncated": result.truncated,
                "modifications": result.modifications,
            },
        )


# Default sanitizer instance
_default_sanitizer: InputSanitizer | None = None


def get_sanitizer() -> InputSanitizer:
    """Get the default sanitizer instance."""
    global _default_sanitizer
    if _default_sanitizer is None:
        _default_sanitizer = InputSanitizer()
    return _default_sanitizer


def sanitize_input(
    text: str,
    *,
    context: str = "message",
    trace_id: str | None = None,
) -> str:
    """
    Sanitize input text using the default sanitizer.

    Convenience function for quick sanitization.

    Args:
        text: Input text to sanitize.
        context: Context for logging.
        trace_id: Optional trace ID for logging.

    Returns:
        Sanitized text string.
    """
    return get_sanitizer().sanitize(text, context=context, trace_id=trace_id).sanitized


__all__ = [
    "InputSanitizer",
    "SanitizationConfig",
    "SanitizationResult",
    "get_sanitizer",
    "sanitize_input",
]
