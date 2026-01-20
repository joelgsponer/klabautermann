"""
Unit tests for Gmail handlers.

Tests EmailComposer, GmailQueryBuilder, and EmailFormatter classes
for proper email composition, query building, and formatting.
"""

from __future__ import annotations

from datetime import datetime

from klabautermann.agents.gmail_handlers import (
    EmailComposer,
    EmailFormatter,
    GmailQueryBuilder,
)
from klabautermann.mcp.google_workspace import EmailMessage


# ===========================================================================
# Test EmailComposer
# ===========================================================================


class TestEmailComposer:
    """Test email composition from natural language."""

    def test_compose_email_basic(self):
        """Test basic email composition."""
        subject, body = EmailComposer.compose_email(
            intent="email about the meeting",
            recipient_name="Sarah Chen",
            tone="casual",
        )

        assert subject == "The Meeting"
        assert "Hi Sarah," in body
        assert "[Message about: email about the meeting]" in body
        assert "Best regards" in body

    def test_compose_email_formal_tone(self):
        """Test formal tone in composition."""
        _subject, body = EmailComposer.compose_email(
            intent="regarding the budget",
            recipient_name="John Smith",
            tone="formal",
        )

        assert "Dear John," in body
        assert "Best regards" in body

    def test_compose_email_brief_tone(self):
        """Test brief tone (no greeting)."""
        _subject, body = EmailComposer.compose_email(
            intent="quick question",
            recipient_name="Alice Johnson",
            tone="brief",
        )

        assert "Alice," in body
        assert "Dear" not in body
        assert "Hi" not in body

    def test_compose_email_with_context(self):
        """Test composition with additional context."""
        _subject, body = EmailComposer.compose_email(
            intent="discuss the project",
            recipient_name="Bob Williams",
            context="Q1 timeline",
            tone="casual",
        )

        assert "[Context: Q1 timeline]" in body

    def test_extract_subject_explicit(self):
        """Test extracting explicit subject."""
        subject = EmailComposer._extract_subject('subject: "Q1 Budget Review"')
        assert subject == "Q1 Budget Review"

    def test_extract_subject_about_pattern(self):
        """Test extracting subject from 'about' pattern."""
        subject = EmailComposer._extract_subject("email about the meeting")
        assert subject == "The Meeting"

        subject = EmailComposer._extract_subject("message about budget review")
        assert subject == "Budget Review"

    def test_extract_subject_keywords(self):
        """Test subject generation from keywords."""
        assert EmailComposer._extract_subject("send meeting invite") == "Meeting"
        assert EmailComposer._extract_subject("send an update") == "Update"
        assert EmailComposer._extract_subject("follow-up on request") == "Follow-Up"

    def test_extract_subject_default(self):
        """Test default subject when nothing matches."""
        subject = EmailComposer._extract_subject("send something")
        assert subject == "Message"

    def test_capitalize_subject_already_capitalized(self):
        """Test that already capitalized subjects are preserved."""
        subject = EmailComposer._capitalize_subject("Q1 Budget Review")
        assert subject == "Q1 Budget Review"

    def test_capitalize_subject_title_case_short(self):
        """Test title case for short subjects."""
        subject = EmailComposer._capitalize_subject("the meeting")
        assert subject == "The Meeting"

    def test_capitalize_subject_sentence_case_long(self):
        """Test sentence case for longer subjects."""
        subject = EmailComposer._capitalize_subject("this is a very long subject line")
        assert subject == "This is a very long subject line"

    def test_format_reply_basic(self):
        """Test basic reply formatting."""
        original = EmailMessage(
            id="1",
            thread_id="t1",
            subject="Meeting Tomorrow",
            sender="sarah@example.com",
            date=datetime(2026, 1, 15, 10, 0),
            snippet="Let's discuss the budget",
        )

        subject, body = EmailComposer.format_reply(
            original_email=original,
            reply_intent="I agree with the proposal",
            quote_original=False,
        )

        assert subject == "Re: Meeting Tomorrow"
        assert "Hi sarah," in body or "Hi Sarah," in body
        assert "[Reply about: I agree with the proposal]" in body
        assert "Best regards" in body

    def test_format_reply_with_re_prefix(self):
        """Test reply doesn't duplicate Re: prefix."""
        original = EmailMessage(
            id="1",
            thread_id="t1",
            subject="Re: Budget Discussion",
            sender="john@example.com",
            date=datetime(2026, 1, 15, 10, 0),
            snippet="Here are my thoughts",
        )

        subject, _body = EmailComposer.format_reply(
            original_email=original,
            reply_intent="Thanks for the update",
            quote_original=False,
        )

        # Should not add another "Re:"
        assert subject == "Re: Budget Discussion"
        assert subject.count("Re:") == 1

    def test_format_reply_with_quote(self):
        """Test reply with quoted original message."""
        original = EmailMessage(
            id="1",
            thread_id="t1",
            subject="Question",
            sender="Sarah Chen <sarah@example.com>",
            date=datetime(2026, 1, 15, 10, 0),
            snippet="What's the timeline?",
            body="What's the timeline for the project?",
        )

        _subject, body = EmailComposer.format_reply(
            original_email=original,
            reply_intent="By end of Q1",
            quote_original=True,
        )

        assert "On 2026-01-15, Sarah Chen <sarah@example.com> wrote:" in body
        assert "> What's the timeline for the project?" in body

    def test_extract_name_from_email_with_name(self):
        """Test name extraction from 'Name <email>' format."""
        name = EmailComposer._extract_name_from_email("Sarah Chen <sarah@example.com>")
        assert name == "Sarah Chen"

    def test_extract_name_from_email_plain(self):
        """Test name extraction from plain email address."""
        name = EmailComposer._extract_name_from_email("sarah.chen@example.com")
        assert name == "Sarah Chen"

        name = EmailComposer._extract_name_from_email("john_doe@example.com")
        assert name == "John Doe"

    def test_extract_name_from_email_fallback(self):
        """Test fallback when extraction fails."""
        name = EmailComposer._extract_name_from_email("invalid")
        assert name == "there"


# ===========================================================================
# Test GmailQueryBuilder
# ===========================================================================


class TestGmailQueryBuilder:
    """Test natural language to Gmail query conversion."""

    def test_build_query_from_sender(self):
        """Test 'from' pattern detection."""
        query = GmailQueryBuilder.build_query("emails from sarah")
        assert "from:sarah" in query

        query = GmailQueryBuilder.build_query("messages from john@example.com")
        assert "from:john@example.com" in query

    def test_build_query_to_recipient(self):
        """Test 'to' pattern detection."""
        query = GmailQueryBuilder.build_query("emails to alice")
        assert "to:alice" in query

    def test_build_query_time_week(self):
        """Test 'last week' time pattern."""
        query = GmailQueryBuilder.build_query("emails from last week")
        assert "newer_than:7d" in query

        query = GmailQueryBuilder.build_query("this week")
        assert "newer_than:7d" in query

    def test_build_query_time_today(self):
        """Test 'today' time pattern."""
        query = GmailQueryBuilder.build_query("emails from today")
        assert "newer_than:1d" in query

    def test_build_query_time_yesterday(self):
        """Test 'yesterday' time pattern."""
        query = GmailQueryBuilder.build_query("emails from yesterday")
        assert "newer_than:2d" in query
        assert "older_than:1d" in query

    def test_build_query_time_month(self):
        """Test 'last month' time pattern."""
        query = GmailQueryBuilder.build_query("from last month")
        assert "newer_than:30d" in query

    def test_build_query_time_custom_days(self):
        """Test custom day count pattern."""
        query = GmailQueryBuilder.build_query("last 5 days")
        assert "newer_than:5d" in query

        query = GmailQueryBuilder.build_query("from last 14 days")
        assert "newer_than:14d" in query

    def test_build_query_status_unread(self):
        """Test unread status pattern."""
        query = GmailQueryBuilder.build_query("unread emails")
        assert "is:unread" in query

    def test_build_query_status_starred(self):
        """Test starred status pattern."""
        query = GmailQueryBuilder.build_query("starred messages")
        assert "is:starred" in query

    def test_build_query_status_important(self):
        """Test important status pattern."""
        query = GmailQueryBuilder.build_query("important emails")
        assert "is:important" in query

    def test_build_query_has_attachment(self):
        """Test attachment pattern."""
        query = GmailQueryBuilder.build_query("emails has attachment")
        assert "has:attachment" in query

    def test_build_query_about_subject(self):
        """Test 'about' subject pattern."""
        query = GmailQueryBuilder.build_query("emails about meeting")
        assert "subject:meeting OR meeting" in query

    def test_build_query_explicit_subject(self):
        """Test explicit subject pattern."""
        query = GmailQueryBuilder.build_query('subject: "Budget Review"')
        assert "subject:Budget Review" in query

    def test_build_query_combined(self):
        """Test combining multiple patterns."""
        query = GmailQueryBuilder.build_query("unread emails from sarah about meeting")
        assert "is:unread" in query
        assert "from:sarah" in query
        assert "subject:meeting OR meeting" in query

    def test_build_query_complex(self):
        """Test complex multi-pattern query."""
        query = GmailQueryBuilder.build_query(
            "unread emails from sarah from last week about budget"
        )
        assert "is:unread" in query
        assert "from:sarah" in query
        assert "newer_than:7d" in query
        assert "subject:budget OR budget" in query

    def test_build_query_no_match_fallback(self):
        """Test fallback when no patterns match."""
        query = GmailQueryBuilder.build_query("random text")
        # Should use remaining text as general search
        assert "random text" in query

    def test_build_query_empty(self):
        """Test empty query defaults to inbox."""
        query = GmailQueryBuilder.build_query("")
        assert query == "in:inbox"

    def test_build_query_only_filler_words(self):
        """Test query with only filler words."""
        query = GmailQueryBuilder.build_query("show me emails")
        # Filler words removed, defaults to inbox
        assert query == "in:inbox"


# ===========================================================================
# Test EmailFormatter
# ===========================================================================


class TestEmailFormatter:
    """Test email message formatting."""

    def test_format_email_list_empty(self):
        """Test formatting empty email list."""
        result = EmailFormatter.format_email_list([])
        assert result == "No emails found."

    def test_format_email_list_basic(self):
        """Test basic email list formatting."""
        emails = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Meeting Tomorrow",
                sender="sarah@example.com",
                date=datetime(2026, 1, 15, 10, 0),
                snippet="Let's discuss the budget",
                is_unread=True,
            ),
            EmailMessage(
                id="2",
                thread_id="t2",
                subject="Project Update",
                sender="john@example.com",
                date=datetime(2026, 1, 15, 11, 0),
                snippet="Here's the latest status",
                is_unread=False,
            ),
        ]

        result = EmailFormatter.format_email_list(emails)

        assert "Showing 2 email(s):" in result
        assert "1. [NEW] From: sarah@example.com" in result
        assert "Subject: Meeting Tomorrow" in result
        assert "2. From: john@example.com" in result
        assert "Subject: Project Update" in result
        assert "Let's discuss the budget" in result
        assert "Here's the latest status" in result

    def test_format_email_list_without_snippet(self):
        """Test formatting without snippets."""
        emails = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Test",
                sender="test@example.com",
                date=datetime(2026, 1, 15, 10, 0),
                snippet="Short snippet",
            ),
        ]

        result = EmailFormatter.format_email_list(emails, include_snippet=False)

        assert "From: test@example.com" in result
        assert "Subject: Test" in result
        assert "Short snippet" not in result

    def test_format_email_list_max_display(self):
        """Test max display limit."""
        emails = [
            EmailMessage(
                id=str(i),
                thread_id=f"t{i}",
                subject=f"Email {i}",
                sender=f"user{i}@example.com",
                date=datetime(2026, 1, 15, 10, i),
                snippet=f"Content {i}",
            )
            for i in range(10)
        ]

        result = EmailFormatter.format_email_list(emails, max_display=3)

        assert "Showing 3 of 10 email(s):" in result
        assert "1. From: user0@example.com" in result
        assert "3. From: user2@example.com" in result
        assert "... and 7 more in results" in result
        # Should not show 4th email
        assert "4. From: user3@example.com" not in result

    def test_format_email_list_with_total_available(self):
        """Test format with total_available parameter."""
        emails = [
            EmailMessage(
                id=str(i),
                thread_id=f"t{i}",
                subject=f"Email {i}",
                sender=f"user{i}@example.com",
                date=datetime(2026, 1, 15, 10, i),
                snippet=f"Content {i}",
            )
            for i in range(20)
        ]

        # When results hit the total_available limit, show hint
        result = EmailFormatter.format_email_list(emails, max_display=5, total_available=20)

        assert "Showing 5 of 20 email(s):" in result
        assert "(More emails may exist - ask for more results if needed)" in result

    def test_format_email_list_under_total_available(self):
        """Test format when results are under total_available limit."""
        emails = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Test Email",
                sender="test@example.com",
                date=datetime(2026, 1, 15, 10, 0),
                snippet="Test content",
            ),
        ]

        # When results are under total_available, no hint
        result = EmailFormatter.format_email_list(emails, max_display=5, total_available=20)

        assert "Showing 1 email(s):" in result
        assert "(More emails may exist" not in result

    def test_format_email_list_long_snippet(self):
        """Test snippet truncation."""
        long_snippet = "A" * 200

        emails = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Test",
                sender="test@example.com",
                date=datetime(2026, 1, 15, 10, 0),
                snippet=long_snippet,
            ),
        ]

        result = EmailFormatter.format_email_list(emails)

        # Should be truncated to ~100 chars + "..."
        assert "AAA..." in result
        assert len(result) < len(long_snippet) + 100  # Should be significantly shorter

    def test_format_email_detail_basic(self):
        """Test detailed email formatting."""
        email = EmailMessage(
            id="1",
            thread_id="t1",
            subject="Meeting Tomorrow",
            sender="sarah@example.com",
            recipient="me",
            date=datetime(2026, 1, 15, 10, 30),
            snippet="Short snippet",
            body="Let's meet at 2pm to discuss the Q1 budget.",
        )

        result = EmailFormatter.format_email_detail(email)

        assert "From: sarah@example.com" in result
        assert "To: me" in result
        assert "Date: 2026-01-15 10:30" in result
        assert "Subject: Meeting Tomorrow" in result
        assert "Let's meet at 2pm to discuss the Q1 budget." in result

    def test_format_email_detail_no_recipient(self):
        """Test detail formatting without recipient."""
        email = EmailMessage(
            id="1",
            thread_id="t1",
            subject="Test",
            sender="test@example.com",
            date=datetime(2026, 1, 15, 10, 0),
            snippet="Content",
        )

        result = EmailFormatter.format_email_detail(email)

        assert "To: me" in result  # Default to 'me'

    def test_format_email_detail_no_body(self):
        """Test detail formatting with only snippet."""
        email = EmailMessage(
            id="1",
            thread_id="t1",
            subject="Test",
            sender="test@example.com",
            date=datetime(2026, 1, 15, 10, 0),
            snippet="This is the snippet",
            body=None,
        )

        result = EmailFormatter.format_email_detail(email)

        assert "This is the snippet" in result

    def test_format_thread_summary_empty(self):
        """Test empty thread formatting."""
        result = EmailFormatter.format_thread_summary([])
        assert result == "Empty thread."

    def test_format_thread_summary_basic(self):
        """Test basic thread summary."""
        emails = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Budget Discussion",
                sender="Sarah Chen <sarah@example.com>",
                date=datetime(2026, 1, 14, 10, 0),
                snippet="What's the budget for Q1?",
            ),
            EmailMessage(
                id="2",
                thread_id="t1",
                subject="Re: Budget Discussion",
                sender="John Smith <john@example.com>",
                date=datetime(2026, 1, 14, 11, 0),
                snippet="I think we have $50k allocated.",
            ),
            EmailMessage(
                id="3",
                thread_id="t1",
                subject="Re: Budget Discussion",
                sender="Sarah Chen <sarah@example.com>",
                date=datetime(2026, 1, 14, 12, 0),
                snippet="Perfect, let's move forward.",
            ),
        ]

        result = EmailFormatter.format_thread_summary(emails)

        assert "Thread: Budget Discussion (3 messages)" in result
        assert "1. Sarah Chen (2026-01-14):" in result
        assert "What's the budget for Q1?" in result
        assert "2. John Smith (2026-01-14):" in result
        assert "I think we have $50k allocated." in result
        assert "3. Sarah Chen (2026-01-14):" in result
        assert "Perfect, let's move forward." in result

    def test_format_thread_summary_long_content(self):
        """Test thread summary with long content truncation."""
        long_body = "A" * 500

        emails = [
            EmailMessage(
                id="1",
                thread_id="t1",
                subject="Long Message",
                sender="test@example.com",
                date=datetime(2026, 1, 15, 10, 0),
                snippet=long_body,
                body=long_body,
            ),
        ]

        result = EmailFormatter.format_thread_summary(emails)

        # Content should be truncated
        assert "AAA..." in result
        # Original long body should not appear in full
        assert len(result) < len(long_body)

    def test_truncate_text_short(self):
        """Test text truncation with short text."""
        text = "Short text"
        result = EmailFormatter._truncate_text(text, max_length=100)
        assert result == "Short text"

    def test_truncate_text_exact_length(self):
        """Test text truncation at exact length."""
        text = "A" * 100
        result = EmailFormatter._truncate_text(text, max_length=100)
        assert result == text

    def test_truncate_text_long(self):
        """Test text truncation with long text."""
        text = "This is a very long text that should be truncated at some point"
        result = EmailFormatter._truncate_text(text, max_length=30)
        assert len(result) <= 33  # 30 + "..."
        assert result.endswith("...")

    def test_truncate_text_word_boundary(self):
        """Test truncation respects word boundaries."""
        text = "This is a long sentence that should be truncated properly"
        result = EmailFormatter._truncate_text(text, max_length=30)

        # Should truncate at word boundary
        assert not result[:-3].endswith(" ")  # No trailing space before "..."
        assert result.endswith("...")
