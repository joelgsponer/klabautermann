"""
Unit tests for input sanitization module.

Tests security-focused input validation and sanitization.
"""

from __future__ import annotations

import pytest

from klabautermann.channels.sanitization import (
    InputSanitizer,
    SanitizationConfig,
    SanitizationResult,
    get_sanitizer,
    sanitize_input,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sanitizer() -> InputSanitizer:
    """Create a default sanitizer."""
    return InputSanitizer()


@pytest.fixture
def custom_config() -> SanitizationConfig:
    """Create a custom sanitization config."""
    return SanitizationConfig(
        max_message_length=100,
        max_thread_id_length=50,
        collapse_whitespace=True,
    )


# =============================================================================
# Test SanitizationConfig
# =============================================================================


class TestSanitizationConfig:
    """Tests for SanitizationConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SanitizationConfig()

        assert config.max_message_length == 32_000
        assert config.max_thread_id_length == 256
        assert config.strip_control_chars is True
        assert config.normalize_unicode is True
        assert config.unicode_form == "NFC"
        assert config.remove_null_bytes is True
        assert config.strip_whitespace is True
        assert config.collapse_whitespace is False

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = SanitizationConfig(
            max_message_length=1000,
            strip_control_chars=False,
            collapse_whitespace=True,
        )

        assert config.max_message_length == 1000
        assert config.strip_control_chars is False
        assert config.collapse_whitespace is True


# =============================================================================
# Test SanitizationResult
# =============================================================================


class TestSanitizationResult:
    """Tests for SanitizationResult."""

    def test_was_modified_true(self) -> None:
        """Test was_modified when content changed."""
        result = SanitizationResult(
            original="hello\x00world",
            sanitized="helloworld",
            modifications=["removed 1 null byte(s)"],
        )

        assert result.was_modified is True

    def test_was_modified_false(self) -> None:
        """Test was_modified when content unchanged."""
        result = SanitizationResult(
            original="hello world",
            sanitized="hello world",
        )

        assert result.was_modified is False

    def test_modification_summary_empty(self) -> None:
        """Test modification summary with no modifications."""
        result = SanitizationResult(
            original="hello",
            sanitized="hello",
        )

        assert result.modification_summary == "No modifications"

    def test_modification_summary_with_modifications(self) -> None:
        """Test modification summary with modifications."""
        result = SanitizationResult(
            original="hello\x00",
            sanitized="hello",
            modifications=["removed 1 null byte(s)", "stripped whitespace"],
        )

        assert "removed 1 null byte(s)" in result.modification_summary
        assert "stripped whitespace" in result.modification_summary


# =============================================================================
# Test InputSanitizer - Null Bytes
# =============================================================================


class TestNullByteRemoval:
    """Tests for null byte removal."""

    def test_remove_single_null_byte(self, sanitizer: InputSanitizer) -> None:
        """Test removing a single null byte."""
        result = sanitizer.sanitize("hello\x00world")

        assert result.sanitized == "helloworld"
        assert "removed 1 null byte(s)" in result.modifications

    def test_remove_multiple_null_bytes(self, sanitizer: InputSanitizer) -> None:
        """Test removing multiple null bytes."""
        result = sanitizer.sanitize("a\x00b\x00c\x00d")

        assert result.sanitized == "abcd"
        assert "removed 3 null byte(s)" in result.modifications

    def test_null_byte_at_start(self, sanitizer: InputSanitizer) -> None:
        """Test null byte at start of string."""
        result = sanitizer.sanitize("\x00hello")

        assert result.sanitized == "hello"

    def test_null_byte_at_end(self, sanitizer: InputSanitizer) -> None:
        """Test null byte at end of string."""
        result = sanitizer.sanitize("hello\x00")

        assert result.sanitized == "hello"

    def test_no_null_bytes(self, sanitizer: InputSanitizer) -> None:
        """Test string with no null bytes."""
        result = sanitizer.sanitize("hello world")

        assert result.sanitized == "hello world"
        assert "null byte" not in result.modification_summary


# =============================================================================
# Test InputSanitizer - Control Characters
# =============================================================================


class TestControlCharacterRemoval:
    """Tests for control character removal."""

    def test_remove_bell_character(self, sanitizer: InputSanitizer) -> None:
        """Test removing bell character."""
        result = sanitizer.sanitize("hello\x07world")

        assert result.sanitized == "helloworld"
        assert "control char" in result.modification_summary

    def test_remove_backspace(self, sanitizer: InputSanitizer) -> None:
        """Test removing backspace character."""
        result = sanitizer.sanitize("hello\x08world")

        assert result.sanitized == "helloworld"

    def test_preserve_tab(self, sanitizer: InputSanitizer) -> None:
        """Test that tab character is preserved."""
        result = sanitizer.sanitize("hello\tworld")

        assert result.sanitized == "hello\tworld"
        assert "control char" not in result.modification_summary

    def test_preserve_newline(self, sanitizer: InputSanitizer) -> None:
        """Test that newline character is preserved."""
        result = sanitizer.sanitize("hello\nworld")

        assert result.sanitized == "hello\nworld"

    def test_preserve_carriage_return(self, sanitizer: InputSanitizer) -> None:
        """Test that carriage return is preserved."""
        result = sanitizer.sanitize("hello\rworld")

        assert result.sanitized == "hello\rworld"

    def test_remove_escape_sequence(self, sanitizer: InputSanitizer) -> None:
        """Test removing escape character."""
        result = sanitizer.sanitize("hello\x1bworld")

        assert result.sanitized == "helloworld"

    def test_remove_c1_control_chars(self, sanitizer: InputSanitizer) -> None:
        """Test removing C1 control characters."""
        result = sanitizer.sanitize("hello\x85world")

        assert result.sanitized == "helloworld"


# =============================================================================
# Test InputSanitizer - Unicode Normalization
# =============================================================================


class TestUnicodeNormalization:
    """Tests for unicode normalization."""

    def test_normalize_composed_characters(self, sanitizer: InputSanitizer) -> None:
        """Test normalizing composed characters (NFC)."""
        # é as e + combining acute (NFD form)
        nfd_text = "caf\u0065\u0301"
        result = sanitizer.sanitize(nfd_text)

        # Should normalize to composed form
        assert "\u0301" not in result.sanitized
        assert "é" in result.sanitized or "e\u0301" not in result.sanitized

    def test_preserve_normal_unicode(self, sanitizer: InputSanitizer) -> None:
        """Test that normal unicode is preserved."""
        result = sanitizer.sanitize("Hello 世界 🌍")

        assert result.sanitized == "Hello 世界 🌍"


# =============================================================================
# Test InputSanitizer - Whitespace Handling
# =============================================================================


class TestWhitespaceHandling:
    """Tests for whitespace handling."""

    def test_strip_leading_whitespace(self, sanitizer: InputSanitizer) -> None:
        """Test stripping leading whitespace."""
        result = sanitizer.sanitize("   hello")

        assert result.sanitized == "hello"
        assert "stripped whitespace" in result.modifications

    def test_strip_trailing_whitespace(self, sanitizer: InputSanitizer) -> None:
        """Test stripping trailing whitespace."""
        result = sanitizer.sanitize("hello   ")

        assert result.sanitized == "hello"

    def test_collapse_whitespace(self, custom_config: SanitizationConfig) -> None:
        """Test collapsing multiple whitespace."""
        sanitizer = InputSanitizer(config=custom_config)
        result = sanitizer.sanitize("hello    world")

        assert result.sanitized == "hello world"
        assert "collapsed whitespace" in result.modifications

    def test_preserve_single_spaces(self, sanitizer: InputSanitizer) -> None:
        """Test preserving single spaces."""
        result = sanitizer.sanitize("hello world")

        assert result.sanitized == "hello world"


# =============================================================================
# Test InputSanitizer - Length Limits
# =============================================================================


class TestLengthLimits:
    """Tests for message length limits."""

    def test_truncate_long_message(self) -> None:
        """Test truncating messages over limit."""
        config = SanitizationConfig(max_message_length=10)
        sanitizer = InputSanitizer(config=config)

        result = sanitizer.sanitize("hello world this is long")

        assert len(result.sanitized) == 10
        assert result.sanitized == "hello worl"
        assert result.truncated is True
        assert "truncated" in result.modification_summary

    def test_preserve_short_message(self, sanitizer: InputSanitizer) -> None:
        """Test preserving messages under limit."""
        result = sanitizer.sanitize("short")

        assert result.sanitized == "short"
        assert result.truncated is False

    def test_thread_id_length_limit(self) -> None:
        """Test thread ID length limit."""
        config = SanitizationConfig(max_thread_id_length=10)
        sanitizer = InputSanitizer(config=config)

        result = sanitizer.sanitize("very-long-thread-id", context="thread_id")

        assert len(result.sanitized) == 10
        assert result.truncated is True


# =============================================================================
# Test InputSanitizer - Convenience Methods
# =============================================================================


class TestConvenienceMethods:
    """Tests for convenience methods."""

    def test_sanitize_message(self, sanitizer: InputSanitizer) -> None:
        """Test sanitize_message convenience method."""
        result = sanitizer.sanitize_message("hello\x00world")

        assert result == "helloworld"
        assert isinstance(result, str)

    def test_sanitize_thread_id(self, sanitizer: InputSanitizer) -> None:
        """Test sanitize_thread_id convenience method."""
        result = sanitizer.sanitize_thread_id("thread\x00id")

        assert result == "threadid"
        assert isinstance(result, str)


# =============================================================================
# Test InputSanitizer - Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_string(self, sanitizer: InputSanitizer) -> None:
        """Test sanitizing empty string."""
        result = sanitizer.sanitize("")

        assert result.sanitized == ""
        assert result.was_modified is False

    def test_only_whitespace(self, sanitizer: InputSanitizer) -> None:
        """Test string with only whitespace."""
        result = sanitizer.sanitize("   \t\n   ")

        # After stripping, becomes empty
        assert result.sanitized == ""

    def test_only_null_bytes(self, sanitizer: InputSanitizer) -> None:
        """Test string with only null bytes."""
        result = sanitizer.sanitize("\x00\x00\x00")

        assert result.sanitized == ""

    def test_only_control_chars(self, sanitizer: InputSanitizer) -> None:
        """Test string with only control characters."""
        result = sanitizer.sanitize("\x07\x08\x1b")

        assert result.sanitized == ""

    def test_none_input(self, sanitizer: InputSanitizer) -> None:
        """Test handling None input."""
        result = sanitizer.sanitize(None)  # type: ignore[arg-type]

        assert result.sanitized == ""

    def test_non_string_input(self, sanitizer: InputSanitizer) -> None:
        """Test handling non-string input."""
        result = sanitizer.sanitize(12345)  # type: ignore[arg-type]

        assert result.sanitized == "12345"

    def test_mixed_dangerous_content(self, sanitizer: InputSanitizer) -> None:
        """Test string with multiple types of dangerous content."""
        dangerous = "  \x00hello\x07\x08world\x1b  "
        result = sanitizer.sanitize(dangerous)

        assert result.sanitized == "helloworld"
        assert "null byte" in result.modification_summary
        assert "control char" in result.modification_summary
        assert "whitespace" in result.modification_summary


# =============================================================================
# Test InputSanitizer - Configuration Options
# =============================================================================


class TestConfigurationOptions:
    """Tests for configuration options."""

    def test_disable_null_byte_removal(self) -> None:
        """Test disabling null byte removal."""
        config = SanitizationConfig(remove_null_bytes=False)
        sanitizer = InputSanitizer(config=config)

        result = sanitizer.sanitize("hello\x00world")

        # Null byte NOT removed (but control char stripping might affect it)
        # Actually \x00 is also a control char, let's disable that too
        config = SanitizationConfig(remove_null_bytes=False, strip_control_chars=False)
        sanitizer = InputSanitizer(config=config)

        result = sanitizer.sanitize("hello\x00world")
        assert "\x00" in result.sanitized

    def test_disable_control_char_stripping(self) -> None:
        """Test disabling control character stripping."""
        config = SanitizationConfig(strip_control_chars=False)
        sanitizer = InputSanitizer(config=config)

        result = sanitizer.sanitize("hello\x07world")

        assert "\x07" in result.sanitized

    def test_disable_unicode_normalization(self) -> None:
        """Test disabling unicode normalization."""
        config = SanitizationConfig(normalize_unicode=False)
        sanitizer = InputSanitizer(config=config)

        # NFD form with combining character
        nfd_text = "e\u0301"
        result = sanitizer.sanitize(nfd_text)

        # Should NOT be normalized
        assert "\u0301" in result.sanitized

    def test_disable_whitespace_stripping(self) -> None:
        """Test disabling whitespace stripping."""
        config = SanitizationConfig(strip_whitespace=False)
        sanitizer = InputSanitizer(config=config)

        result = sanitizer.sanitize("  hello  ")

        assert result.sanitized == "  hello  "


# =============================================================================
# Test Module-Level Functions
# =============================================================================


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_sanitizer_singleton(self) -> None:
        """Test get_sanitizer returns singleton."""
        sanitizer1 = get_sanitizer()
        sanitizer2 = get_sanitizer()

        assert sanitizer1 is sanitizer2

    def test_sanitize_input_function(self) -> None:
        """Test sanitize_input convenience function."""
        result = sanitize_input("hello\x00world")

        assert result == "helloworld"
        assert isinstance(result, str)

    def test_sanitize_input_with_context(self) -> None:
        """Test sanitize_input with context parameter."""
        # Should use thread_id length limit when context="thread_id"
        result = sanitize_input("test-thread", context="thread_id")

        assert result == "test-thread"


# =============================================================================
# Test Security Scenarios
# =============================================================================


class TestSecurityScenarios:
    """Tests for security-related scenarios."""

    def test_terminal_injection_attempt(self, sanitizer: InputSanitizer) -> None:
        """Test prevention of terminal injection via escape sequences."""
        # Attempt to change terminal title via escape sequence
        malicious = "\x1b]0;PWNED\x07Normal text"
        result = sanitizer.sanitize(malicious)

        # All control characters should be removed
        assert "\x1b" not in result.sanitized
        assert "\x07" not in result.sanitized
        assert "Normal text" in result.sanitized

    def test_null_byte_injection(self, sanitizer: InputSanitizer) -> None:
        """Test prevention of null byte injection."""
        # Null bytes can truncate strings in C-based systems
        malicious = "valid\x00hidden payload"
        result = sanitizer.sanitize(malicious)

        assert result.sanitized == "validhidden payload"

    def test_unicode_homograph_mitigation(self, sanitizer: InputSanitizer) -> None:
        """Test unicode normalization helps with homographs."""
        # Different ways to represent same character
        result = sanitizer.sanitize("café")

        # Should be consistently normalized
        assert result.sanitized == "café"

    def test_resource_exhaustion_protection(self) -> None:
        """Test protection against resource exhaustion via long messages."""
        config = SanitizationConfig(max_message_length=1000)
        sanitizer = InputSanitizer(config=config)

        # Very long message
        long_message = "x" * 10_000
        result = sanitizer.sanitize(long_message)

        assert len(result.sanitized) == 1000
        assert result.truncated is True


# =============================================================================
# Test Result Tracking
# =============================================================================


class TestResultTracking:
    """Tests for result tracking fields."""

    def test_original_length_tracked(self, sanitizer: InputSanitizer) -> None:
        """Test that original length is tracked."""
        result = sanitizer.sanitize("hello\x00world")

        assert result.original_length == len("hello\x00world")
        assert result.original_length == 11

    def test_sanitized_length_tracked(self, sanitizer: InputSanitizer) -> None:
        """Test that sanitized length is tracked."""
        result = sanitizer.sanitize("hello\x00world")

        assert result.sanitized_length == len("helloworld")
        assert result.sanitized_length == 10

    def test_original_preserved(self, sanitizer: InputSanitizer) -> None:
        """Test that original text is preserved in result."""
        original = "hello\x00world"
        result = sanitizer.sanitize(original)

        assert result.original == original
        assert "\x00" in result.original
