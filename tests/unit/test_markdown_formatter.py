"""
Unit tests for Telegram Markdown formatter.

Issue: #139
"""

import pytest

from klabautermann.channels.markdown_formatter import (
    FormattingResult,
    TelegramMarkdownFormatter,
    escape_markdown,
)


class TestTelegramMarkdownFormatter:
    """Tests for TelegramMarkdownFormatter class."""

    @pytest.fixture
    def formatter(self) -> TelegramMarkdownFormatter:
        """Create a formatter with default settings."""
        return TelegramMarkdownFormatter()

    def test_empty_string(self, formatter: TelegramMarkdownFormatter) -> None:
        """Empty string should return unchanged."""
        result = formatter.format("")
        assert result.formatted == ""
        assert result.was_escaped is False

    def test_plain_text_unchanged(self, formatter: TelegramMarkdownFormatter) -> None:
        """Plain text without special characters should be unchanged."""
        text = "Hello world"
        result = formatter.format(text)
        assert result.formatted == text
        assert result.was_escaped is False

    def test_escapes_brackets(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should escape square brackets."""
        text = "Array [0] and [1]"
        result = formatter.format(text)
        assert "\\[" in result.formatted
        assert "\\]" in result.formatted
        assert result.was_escaped is True

    def test_escapes_parentheses(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should escape parentheses outside of links."""
        text = "Function call (with args)"
        result = formatter.format(text)
        assert "\\(" in result.formatted
        assert "\\)" in result.formatted

    def test_escapes_special_chars(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should escape various special characters."""
        text = "Price: $100.00 + tax = total"
        result = formatter.format(text)
        assert "\\." in result.formatted
        assert "\\+" in result.formatted
        assert "\\=" in result.formatted

    def test_preserves_bold_formatting(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should preserve *bold* formatting."""
        text = "This is *bold* text"
        result = formatter.format(text)
        assert "*bold*" in result.formatted

    def test_preserves_italic_formatting(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should preserve _italic_ formatting."""
        text = "This is _italic_ text"
        result = formatter.format(text)
        assert "_italic_" in result.formatted

    def test_preserves_code_formatting(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should preserve `code` formatting."""
        text = "Use `print()` function"
        result = formatter.format(text)
        assert "`print()`" in result.formatted

    def test_preserves_pre_formatting(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should preserve ```pre``` blocks."""
        text = "Code:\n```\nprint('hello')\n```"
        result = formatter.format(text)
        assert "```" in result.formatted

    def test_preserves_links(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should preserve [text](url) links."""
        text = "Check [this link](https://example.com)"
        result = formatter.format(text)
        assert "[this link](https://example.com)" in result.formatted

    def test_mixed_formatting_and_special_chars(
        self, formatter: TelegramMarkdownFormatter
    ) -> None:
        """Should handle mix of formatting and special characters."""
        text = "*Bold* text [array] with (parens)"
        result = formatter.format(text)
        # Bold should be preserved
        assert "*Bold*" in result.formatted
        # Brackets should be escaped
        assert "\\[array\\]" in result.formatted
        # Parens should be escaped
        assert "\\(parens\\)" in result.formatted

    def test_escape_all_mode(self) -> None:
        """With preserve_formatting=False, should escape everything."""
        formatter = TelegramMarkdownFormatter(preserve_formatting=False)
        text = "*bold* and _italic_"
        result = formatter.format(text)
        # Asterisks and underscores should be escaped
        assert "\\*" in result.formatted
        assert "\\_" in result.formatted

    def test_formatting_result_properties(
        self, formatter: TelegramMarkdownFormatter
    ) -> None:
        """FormattingResult should have correct properties."""
        text = "Test [with] special"
        result = formatter.format(text)
        assert result.original == text
        assert result.was_escaped is True
        assert result.escape_count == 2  # [ and ]


class TestEscapeMarkdownFunction:
    """Tests for the escape_markdown convenience function."""

    def test_basic_escape(self) -> None:
        """Should escape special characters."""
        text = "Price: $100.00"
        result = escape_markdown(text)
        assert "\\." in result

    def test_preserve_formatting_default(self) -> None:
        """Should preserve formatting by default."""
        text = "*bold* text"
        result = escape_markdown(text)
        assert "*bold*" in result

    def test_no_preserve_formatting(self) -> None:
        """Should escape everything when preserve_formatting=False."""
        text = "*bold* text"
        result = escape_markdown(text, preserve_formatting=False)
        assert "\\*" in result


class TestFormattingEdgeCases:
    """Tests for edge cases in formatting."""

    @pytest.fixture
    def formatter(self) -> TelegramMarkdownFormatter:
        """Create a formatter."""
        return TelegramMarkdownFormatter()

    def test_nested_formatting(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should handle adjacent formatting markers."""
        text = "*bold* and _italic_ together"
        result = formatter.format(text)
        assert "*bold*" in result.formatted
        assert "_italic_" in result.formatted

    def test_unclosed_formatting(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should handle unclosed formatting markers gracefully."""
        text = "Unclosed *bold and text"
        result = formatter.format(text)
        # Should not crash, may escape or pass through
        assert "Unclosed" in result.formatted

    def test_multiple_special_chars_together(
        self, formatter: TelegramMarkdownFormatter
    ) -> None:
        """Should escape consecutive special characters."""
        text = "Math: a + b = c (where c > 0)"
        result = formatter.format(text)
        assert "\\+" in result.formatted
        assert "\\=" in result.formatted
        assert "\\>" in result.formatted
        assert "\\(" in result.formatted
        assert "\\)" in result.formatted

    def test_url_with_special_chars(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should preserve URLs in links even with special chars."""
        text = "Visit [site](https://example.com/path?q=1&x=2)"
        result = formatter.format(text)
        # Link should be preserved intact
        assert "[site](https://example.com/path?q=1&x=2)" in result.formatted

    def test_multiline_text(self, formatter: TelegramMarkdownFormatter) -> None:
        """Should handle multiline text correctly."""
        text = "Line 1 [array]\nLine 2 *bold*\nLine 3"
        result = formatter.format(text)
        assert "\\[array\\]" in result.formatted
        assert "*bold*" in result.formatted
        assert "Line 3" in result.formatted
