"""
Unit tests for LLM Summarization Pipeline.

Tests the format_messages and summarize_thread functions with mocked Anthropic API.

Reference: specs/architecture/AGENTS.md Section 1.5
Task: T039 - LLM Summarization Pipeline
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from klabautermann.agents.summarization import (
    _create_minimal_summary,
    _format_timestamp,
    format_messages,
    summarize_thread,
)
from klabautermann.core.models import (
    ActionItem,
    ActionStatus,
    ExtractedFact,
    ThreadSummary,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def sample_messages():
    """Sample conversation messages for testing."""
    base_time = time.time()
    return [
        {
            "role": "user",
            "content": "I met Sarah today at the conference",
            "timestamp": base_time - 3600,  # 1 hour ago
        },
        {
            "role": "assistant",
            "content": "That's great! Tell me more about Sarah.",
            "timestamp": base_time - 3595,
        },
        {
            "role": "user",
            "content": "She's a PM at Acme Corp. Her email is sarah@acme.com",
            "timestamp": base_time - 3590,
        },
        {
            "role": "assistant",
            "content": "Got it! I'll remember that Sarah works at Acme as a PM.",
            "timestamp": base_time - 3585,
        },
    ]


@pytest.fixture
def sample_thread_summary():
    """Sample ThreadSummary for mocking LLM response."""
    return ThreadSummary(
        summary="User shared information about meeting Sarah, a PM at Acme Corp",
        topics=["Sarah", "Acme Corp", "new contact", "conference"],
        action_items=[
            ActionItem(
                action="Follow up with Sarah",
                assignee="user",
                status=ActionStatus.PENDING,
                confidence=0.7,
            )
        ],
        new_facts=[
            ExtractedFact(
                entity="Sarah",
                entity_type="Person",
                fact="Works as PM at Acme Corp",
                confidence=0.95,
            ),
            ExtractedFact(
                entity="Sarah",
                entity_type="Person",
                fact="Email is sarah@acme.com",
                confidence=1.0,
            ),
        ],
        conflicts=[],
        participants=["user", "assistant"],
        sentiment="positive",
    )


# ===========================================================================
# Test format_messages
# ===========================================================================


def test_format_messages_basic(sample_messages):
    """Test basic message formatting."""
    formatted = format_messages(sample_messages)

    assert "User:" in formatted
    assert "Assistant:" in formatted
    assert "Sarah" in formatted
    assert "Acme Corp" in formatted


def test_format_messages_timestamp_formatting(sample_messages):
    """Test that timestamps are formatted as relative time."""
    formatted = format_messages(sample_messages)

    # Should contain relative time markers
    assert "hour" in formatted.lower() or "minute" in formatted.lower()


def test_format_messages_with_long_content():
    """Test that long messages are truncated."""
    long_content = "A" * 1500  # Exceeds MAX_MESSAGE_LENGTH
    messages = [{"role": "user", "content": long_content, "timestamp": time.time()}]

    formatted = format_messages(messages)

    # Should be truncated with ellipsis
    assert "..." in formatted
    assert len(formatted) < len(long_content)


def test_format_messages_cleans_roleplay_markers():
    """Test that asterisks and roleplay markers are removed."""
    messages = [
        {
            "role": "user",
            "content": "*does something* and **says something**",
            "timestamp": time.time(),
        }
    ]

    formatted = format_messages(messages)

    # Asterisks should be removed
    assert "*" not in formatted


def test_format_messages_with_missing_fields():
    """Test handling of messages with missing fields."""
    messages = [
        {"role": "user"},  # No content or timestamp
        {"content": "Hello"},  # No role or timestamp
    ]

    formatted = format_messages(messages)

    # Should not crash and should handle gracefully
    assert "User:" in formatted or "Unknown:" in formatted


def test_format_messages_empty_list():
    """Test formatting empty message list."""
    formatted = format_messages([])
    assert formatted == ""


# ===========================================================================
# Test _format_timestamp
# ===========================================================================


def test_format_timestamp_just_now():
    """Test timestamp formatting for recent times."""
    now = time.time()
    result = _format_timestamp(now - 30)
    assert result == "just now"


def test_format_timestamp_minutes_ago():
    """Test timestamp formatting for minutes."""
    now = time.time()
    result = _format_timestamp(now - 300)  # 5 minutes ago
    assert "minute" in result
    assert "5" in result


def test_format_timestamp_hours_ago():
    """Test timestamp formatting for hours."""
    now = time.time()
    result = _format_timestamp(now - 7200)  # 2 hours ago
    assert "hour" in result
    assert "2" in result


def test_format_timestamp_days_ago():
    """Test timestamp formatting for days."""
    now = time.time()
    result = _format_timestamp(now - 172800)  # 2 days ago
    assert "day" in result
    assert "2" in result


def test_format_timestamp_iso_format():
    """Test timestamp formatting with ISO string."""
    # Create ISO timestamp for 1 hour ago
    dt = datetime.now(UTC) - timedelta(hours=1)
    iso_string = dt.isoformat()

    result = _format_timestamp(iso_string)
    assert "hour" in result or "minute" in result


def test_format_timestamp_none():
    """Test timestamp formatting with None."""
    result = _format_timestamp(None)
    assert result == "unknown time"


def test_format_timestamp_invalid():
    """Test timestamp formatting with invalid value."""
    result = _format_timestamp("invalid")
    assert result == "unknown time"


# ===========================================================================
# Test summarize_thread
# ===========================================================================


@pytest.mark.asyncio
async def test_summarize_thread_success(sample_messages, sample_thread_summary, monkeypatch):
    """Test successful thread summarization with mocked API."""
    # Mock environment variable
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    # Mock the Anthropic client and response
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = sample_thread_summary.model_dump()

    mock_response = MagicMock()
    mock_response.content = [mock_tool_use]

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        # Call the function
        result = await summarize_thread(
            messages=sample_messages,
            context={"user_name": "John"},
            trace_id="test-trace-123",
        )

        # Verify result
        assert isinstance(result, ThreadSummary)
        assert result.summary == sample_thread_summary.summary
        assert len(result.topics) == 4
        assert len(result.action_items) == 1
        assert len(result.new_facts) == 2
        assert result.sentiment == "positive"

        # Verify API was called correctly
        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-3-5-haiku-20241022"
        assert call_kwargs["max_tokens"] == 2000
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["name"] == "extract_summary"


@pytest.mark.asyncio
async def test_summarize_thread_no_tool_use_block(sample_messages, monkeypatch):
    """Test handling when LLM doesn't return tool_use block."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    # Mock response without tool_use block
    mock_text_block = MagicMock()
    mock_text_block.type = "text"

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        result = await summarize_thread(sample_messages)

        # Should return minimal summary
        assert isinstance(result, ThreadSummary)
        assert "summarization failed" in result.summary
        assert len(result.topics) == 0
        assert len(result.action_items) == 0


@pytest.mark.asyncio
async def test_summarize_thread_api_error(sample_messages, monkeypatch):
    """Test handling of Anthropic API errors."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    import anthropic

    # Create a proper API error with required parameters
    mock_request = MagicMock()
    mock_request.url = "https://api.anthropic.com/v1/messages"

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="API failure", request=mock_request, body=None
        )
        mock_anthropic_class.return_value = mock_client

        # Should raise after retries
        with pytest.raises(anthropic.APIError):
            await summarize_thread(sample_messages)


@pytest.mark.asyncio
async def test_summarize_thread_validation_error(sample_messages, monkeypatch):
    """Test handling when LLM returns invalid data."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    # Mock response with invalid schema
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = {
        "summary": "Valid summary",
        "topics": "not a list",  # Invalid - should be list
        "action_items": [],
        "new_facts": [],
        "conflicts": [],
        "participants": [],
    }

    mock_response = MagicMock()
    mock_response.content = [mock_tool_use]

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        result = await summarize_thread(sample_messages)

        # Should fall back to minimal summary
        assert isinstance(result, ThreadSummary)
        assert "summarization failed" in result.summary


@pytest.mark.asyncio
async def test_summarize_thread_low_confidence_warning(sample_messages, monkeypatch):
    """Test that low confidence facts trigger warnings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    low_confidence_summary = ThreadSummary(
        summary="Test summary",
        topics=["test"],
        action_items=[],
        new_facts=[
            ExtractedFact(
                entity="Test",
                entity_type="Person",
                fact="Uncertain fact",
                confidence=0.3,  # Low confidence
            )
        ],
        conflicts=[],
        participants=["user"],
        sentiment="neutral",
    )

    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = low_confidence_summary.model_dump()

    mock_response = MagicMock()
    mock_response.content = [mock_tool_use]

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        with patch("klabautermann.agents.summarization.logger") as mock_logger:
            await summarize_thread(sample_messages)

            # Should log warning for low confidence
            assert mock_logger.warning.called
            warning_calls = [
                call
                for call in mock_logger.warning.call_args_list
                if "Low-confidence fact" in str(call)
            ]
            assert len(warning_calls) > 0


@pytest.mark.asyncio
async def test_summarize_thread_with_context(sample_messages, monkeypatch):
    """Test that context is included in the prompt."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = ThreadSummary(
        summary="Test",
        topics=[],
        action_items=[],
        new_facts=[],
        conflicts=[],
        participants=[],
    ).model_dump()

    mock_response = MagicMock()
    mock_response.content = [mock_tool_use]

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        context = {"user_name": "John", "thread_id": "test-123"}
        await summarize_thread(sample_messages, context=context)

        # Check that context was included in the prompt
        call_kwargs = mock_client.messages.create.call_args.kwargs
        prompt = call_kwargs["messages"][0]["content"]
        assert "ADDITIONAL CONTEXT" in prompt
        assert "user_name: John" in prompt
        assert "thread_id: test-123" in prompt


# ===========================================================================
# Test _create_minimal_summary
# ===========================================================================


def test_create_minimal_summary(sample_messages):
    """Test creation of minimal fallback summary."""
    summary = _create_minimal_summary(sample_messages)

    assert isinstance(summary, ThreadSummary)
    assert "summarization failed" in summary.summary
    assert len(summary.topics) == 0
    assert len(summary.action_items) == 0
    assert len(summary.new_facts) == 0
    assert len(summary.conflicts) == 0
    assert "user" in summary.participants or "assistant" in summary.participants


# ===========================================================================
# Test Real Conversation Example
# ===========================================================================


@pytest.mark.asyncio
async def test_real_conversation_example(monkeypatch):
    """Test with a realistic multi-turn conversation."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")

    messages = [
        {
            "role": "user",
            "content": "I met Sarah today. She's the new PM at Acme Corp.",
            "timestamp": time.time() - 600,
        },
        {
            "role": "assistant",
            "content": "Great! I'll remember that Sarah is a PM at Acme. Do you have her contact info?",
            "timestamp": time.time() - 595,
        },
        {
            "role": "user",
            "content": "Yes, her email is sarah@acme.com. We're planning to collaborate on Project Phoenix.",
            "timestamp": time.time() - 590,
        },
        {
            "role": "assistant",
            "content": "Got it! I've noted Sarah's email and the Project Phoenix collaboration.",
            "timestamp": time.time() - 585,
        },
        {
            "role": "user",
            "content": "Actually, I need to send her the proposal by Friday.",
            "timestamp": time.time() - 580,
        },
        {
            "role": "assistant",
            "content": "Understood - I'll help you remember to send the proposal to Sarah by Friday.",
            "timestamp": time.time() - 575,
        },
    ]

    expected_summary = ThreadSummary(
        summary="User met Sarah, new PM at Acme, to collaborate on Project Phoenix. Action item to send proposal by Friday.",
        topics=["Sarah", "Acme Corp", "Project Phoenix", "proposal"],
        action_items=[
            ActionItem(
                action="Send proposal to Sarah",
                assignee="user",
                due_date="Friday",
                status=ActionStatus.PENDING,
                confidence=0.9,
            )
        ],
        new_facts=[
            ExtractedFact(
                entity="Sarah",
                entity_type="Person",
                fact="PM at Acme Corp",
                confidence=0.95,
            ),
            ExtractedFact(
                entity="Sarah",
                entity_type="Person",
                fact="Email: sarah@acme.com",
                confidence=1.0,
            ),
            ExtractedFact(
                entity="Project Phoenix",
                entity_type="Project",
                fact="Collaboration with Sarah",
                confidence=0.85,
            ),
        ],
        conflicts=[],
        participants=["user", "assistant"],
        sentiment="positive",
    )

    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = expected_summary.model_dump()

    mock_response = MagicMock()
    mock_response.content = [mock_tool_use]

    with patch("anthropic.Anthropic") as mock_anthropic_class:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_class.return_value = mock_client

        result = await summarize_thread(messages)

        assert isinstance(result, ThreadSummary)
        assert "Sarah" in result.summary
        assert "Project Phoenix" in result.topics or "proposal" in result.topics
        assert any(item.action == "Send proposal to Sarah" for item in result.action_items)
        assert len(result.new_facts) >= 2
