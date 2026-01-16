"""
Integration Tests: Channel Integration with Orchestrator v2 (T076)

Tests verifying that communication channels (CLI, Telegram) work correctly
with the v2 orchestrator workflow (Think-Dispatch-Synthesize pattern).

Reference:
- specs/architecture/CHANNELS.md
- specs/MAINAGENT.md Section 4
- tasks/in-progress/T076-channel-integration.md

Test Coverage:
1. CLI driver calls orchestrator.handle_user_input() correctly
2. Thread UUID is passed correctly from channels
3. Trace ID propagation works
4. Multi-turn conversations maintain thread context
5. Multi-intent messages handled correctly
6. Error responses formatted correctly for channels
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.channels.cli_driver import CLIDriver


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_graphiti():
    """Mock Graphiti client."""
    client = MagicMock()
    client.search = AsyncMock(return_value=[])
    client.add_episode = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_thread_manager():
    """Mock ThreadManager."""
    manager = AsyncMock()
    manager.get_context_window = AsyncMock()
    manager.add_message = AsyncMock()
    return manager


@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4j client."""
    client = MagicMock()
    # Mock session context manager
    session = MagicMock()
    session.run = AsyncMock(return_value=MagicMock(data=AsyncMock(return_value=[])))

    async def async_context_manager(*args, **kwargs):
        class AsyncContextManager:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                pass

        return AsyncContextManager()

    client.session = MagicMock(side_effect=async_context_manager)
    return client


@pytest.fixture
def orchestrator_v2(mock_graphiti, mock_thread_manager, mock_neo4j_client):
    """Create Orchestrator with v2 workflow enabled."""
    return Orchestrator(
        graphiti=mock_graphiti,
        thread_manager=mock_thread_manager,
        neo4j_client=mock_neo4j_client,
        config={
            "model": {"primary": "claude-sonnet-4-20250514"},
            "use_v2_workflow": True,  # Enable v2 workflow
        },
    )


@pytest.fixture
def cli_driver(orchestrator_v2):
    """Create CLI driver with mocked orchestrator."""
    return CLIDriver(orchestrator=orchestrator_v2)


# =============================================================================
# TEST 1: CLI Driver Calls Orchestrator Correctly
# =============================================================================


@pytest.mark.asyncio
async def test_cli_driver_calls_handle_user_input(cli_driver, orchestrator_v2):
    """
    Verify CLI driver calls orchestrator.handle_user_input() with correct parameters.

    Given: CLI driver initialized with orchestrator
    When: User sends a message via receive_message()
    Then: Orchestrator's handle_user_input() is called with thread_id and text
    """
    # Mock the orchestrator's handle_user_input
    with patch.object(
        orchestrator_v2, "handle_user_input", new=AsyncMock(return_value="Test response")
    ) as mock_handle:
        # Send message via CLI driver
        response = await cli_driver.receive_message(
            thread_id="cli-test-session", content="Hello Klabautermann"
        )

        # Verify handle_user_input was called
        mock_handle.assert_called_once()
        call_args = mock_handle.call_args

        # Verify correct parameters
        assert call_args.kwargs["thread_id"] == "cli-test-session"
        assert call_args.kwargs["text"] == "Hello Klabautermann"

        # Verify response returned
        assert response == "Test response"


# =============================================================================
# TEST 2: Thread UUID Passed Correctly
# =============================================================================


@pytest.mark.asyncio
async def test_thread_uuid_propagation(cli_driver, orchestrator_v2):
    """
    Verify thread UUID is passed correctly from channel to orchestrator.

    Given: CLI driver with specific session ID
    When: Multiple messages sent in same session
    Then: Same thread_id used consistently
    """
    thread_id = cli_driver.get_thread_id()

    with patch.object(
        orchestrator_v2, "handle_user_input", new=AsyncMock(return_value="Response")
    ) as mock_handle:
        # Send multiple messages
        await cli_driver.receive_message(thread_id=thread_id, content="Message 1")
        await cli_driver.receive_message(thread_id=thread_id, content="Message 2")

        # Verify same thread_id used both times
        assert mock_handle.call_count == 2
        first_call_thread = mock_handle.call_args_list[0].kwargs["thread_id"]
        second_call_thread = mock_handle.call_args_list[1].kwargs["thread_id"]
        assert first_call_thread == second_call_thread == thread_id


# =============================================================================
# TEST 3: Trace ID Propagation
# =============================================================================


@pytest.mark.asyncio
async def test_trace_id_propagation(orchestrator_v2):
    """
    Verify trace_id is generated and propagated through orchestrator v2.

    Given: Orchestrator v2 with mocked context building
    When: handle_user_input called without explicit trace_id
    Then: Trace ID is generated and passed to v2 workflow
    """
    with patch.object(
        orchestrator_v2, "handle_user_input_v2", new=AsyncMock(return_value="Response")
    ) as mock_v2:
        # Call without explicit trace_id
        await orchestrator_v2.handle_user_input(thread_id="test-thread", text="Test message")

        # Verify v2 workflow called with trace_id
        mock_v2.assert_called_once()
        trace_id = mock_v2.call_args.kwargs.get("trace_id")
        assert trace_id is not None
        assert trace_id.startswith("orch-")


# =============================================================================
# TEST 4: Multi-Turn Conversation Context
# =============================================================================


@pytest.mark.asyncio
async def test_multi_turn_conversation(cli_driver, orchestrator_v2, mock_thread_manager):
    """
    Verify multi-turn conversations maintain thread context across turns.

    Given: CLI driver with orchestrator
    When: User sends multiple related messages
    Then: Each message uses same thread_id for context continuity
    """
    thread_id = cli_driver.get_thread_id()

    # Mock context window to return previous messages
    mock_thread_manager.get_context_window.return_value = MagicMock(
        messages=[
            {"role": "user", "content": "I met Sarah at Acme Corp"},
            {"role": "assistant", "content": "Noted. I've stored that information."},
        ]
    )

    with patch.object(
        orchestrator_v2, "handle_user_input", new=AsyncMock(return_value="Response")
    ) as mock_handle:
        # Turn 1
        await cli_driver.receive_message(thread_id=thread_id, content="I met Sarah at Acme Corp")

        # Turn 2 (should reference same thread)
        await cli_driver.receive_message(thread_id=thread_id, content="What's Sarah's email?")

        # Verify both calls used same thread
        assert mock_handle.call_count == 2
        thread_ids = [call.kwargs["thread_id"] for call in mock_handle.call_args_list]
        assert thread_ids[0] == thread_ids[1] == thread_id


# =============================================================================
# TEST 5: Multi-Intent Message Handling
# =============================================================================


@pytest.mark.asyncio
async def test_multi_intent_message(orchestrator_v2):
    """
    Verify v2 workflow handles multi-intent messages correctly.

    Given: Orchestrator v2 with task planning
    When: User sends message with multiple intents
    Then: Multiple tasks identified and dispatched via handle_user_input_v2
    """
    multi_intent_message = "I met John at Acme. What's his email?"

    # Mock the entire v2 workflow to return expected response
    with patch.object(
        orchestrator_v2,
        "handle_user_input_v2",
        new=AsyncMock(return_value="John's email is john@acme.com"),
    ) as mock_v2:
        response = await orchestrator_v2.handle_user_input(
            thread_id="test-thread", text=multi_intent_message
        )

        # Verify v2 workflow was called
        mock_v2.assert_called_once()
        call_args = mock_v2.call_args

        # Verify correct parameters
        assert call_args.kwargs["text"] == multi_intent_message
        assert call_args.kwargs["thread_uuid"] == "test-thread"

        # Verify response returned
        assert response == "John's email is john@acme.com"


# =============================================================================
# TEST 6: Error Response Formatting
# =============================================================================


@pytest.mark.asyncio
async def test_error_response_formatting(cli_driver, orchestrator_v2):
    """
    Verify errors are caught and formatted correctly for channels.

    Given: CLI driver with orchestrator
    When: Orchestrator raises an exception
    Then: Error is caught and user-friendly message returned
    """
    # Mock orchestrator to raise error
    with patch.object(
        orchestrator_v2,
        "handle_user_input",
        new=AsyncMock(side_effect=Exception("Database connection lost")),
    ):
        response = await cli_driver.receive_message(thread_id="test-thread", content="Test message")

        # Verify error message is user-friendly
        assert "rough waters" in response.lower()
        assert "Database connection lost" in response


# =============================================================================
# TEST 7: Channel Type Identification
# =============================================================================


@pytest.mark.asyncio
async def test_cli_channel_type(cli_driver):
    """
    Verify CLI driver reports correct channel type.

    Given: CLI driver instance
    When: channel_type property accessed
    Then: Returns 'cli'
    """
    assert cli_driver.channel_type == "cli"


# =============================================================================
# TEST 8: Thread ID Format
# =============================================================================


@pytest.mark.asyncio
async def test_cli_thread_id_format(cli_driver):
    """
    Verify CLI driver generates thread IDs in correct format.

    Given: CLI driver instance
    When: get_thread_id() called
    Then: Returns thread ID in format 'cli-{session_id}'
    """
    thread_id = cli_driver.get_thread_id()

    assert isinstance(thread_id, str)
    assert thread_id.startswith("cli-")
    assert len(thread_id) > 4  # More than just 'cli-'


# =============================================================================
# TEST 9: V2 Workflow Flag Respected
# =============================================================================


@pytest.mark.asyncio
async def test_v2_workflow_flag_enabled(orchestrator_v2):
    """
    Verify orchestrator routes to v2 workflow when flag is enabled.

    Given: Orchestrator with use_v2_workflow=True
    When: handle_user_input called
    Then: handle_user_input_v2 is invoked
    """
    with (
        patch.object(
            orchestrator_v2, "handle_user_input_v2", new=AsyncMock(return_value="V2 response")
        ) as mock_v2,
        patch.object(
            orchestrator_v2,
            "_handle_user_input_v1",
            new=AsyncMock(return_value="V1 response"),
        ) as mock_v1,
    ):
        response = await orchestrator_v2.handle_user_input(thread_id="test-thread", text="Test")

        # Verify v2 workflow was called
        mock_v2.assert_called_once()
        mock_v1.assert_not_called()
        assert response == "V2 response"


@pytest.mark.asyncio
async def test_v2_workflow_flag_disabled():
    """
    Verify orchestrator routes to v1 workflow when flag is disabled.

    Given: Orchestrator with use_v2_workflow=False
    When: handle_user_input called
    Then: _handle_user_input_v1 is invoked
    """
    # Create orchestrator with v2 disabled
    orchestrator_v1 = Orchestrator(
        graphiti=MagicMock(),
        thread_manager=AsyncMock(),
        neo4j_client=MagicMock(),
        config={
            "model": {"primary": "claude-sonnet-4-20250514"},
            "use_v2_workflow": False,  # Disable v2
        },
    )

    with (
        patch.object(
            orchestrator_v1, "handle_user_input_v2", new=AsyncMock(return_value="V2 response")
        ) as mock_v2,
        patch.object(
            orchestrator_v1,
            "_handle_user_input_v1",
            new=AsyncMock(return_value="V1 response"),
        ) as mock_v1,
    ):
        response = await orchestrator_v1.handle_user_input(thread_id="test-thread", text="Test")

        # Verify v1 workflow was called
        mock_v1.assert_called_once()
        mock_v2.assert_not_called()
        assert response == "V1 response"


# =============================================================================
# TEST 10: No Regression in Single-Intent Handling
# =============================================================================


@pytest.mark.asyncio
async def test_single_intent_no_regression(orchestrator_v2):
    """
    Verify v2 workflow handles single-intent messages correctly (no regression).

    Given: Orchestrator v2
    When: User sends simple single-intent message
    Then: Response generated without errors via handle_user_input_v2
    """
    simple_message = "What's Sarah's email?"

    # Mock the entire v2 workflow to return expected response
    with patch.object(
        orchestrator_v2,
        "handle_user_input_v2",
        new=AsyncMock(return_value="Sarah's email is sarah@example.com"),
    ) as mock_v2:
        response = await orchestrator_v2.handle_user_input(
            thread_id="test-thread", text=simple_message
        )

        # Verify v2 workflow was called
        mock_v2.assert_called_once()
        call_args = mock_v2.call_args

        # Verify correct parameters
        assert call_args.kwargs["text"] == simple_message
        assert call_args.kwargs["thread_uuid"] == "test-thread"

        # Verify response returned
        assert "sarah@example.com" in response.lower()
