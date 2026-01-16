"""
Unit tests for the agent delegation pattern (T021).

Tests dispatch_and_wait, dispatch_fire_and_forget, and intent handler delegation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import AgentMessage, IntentClassification, IntentType


class MockSubAgent(BaseAgent):
    """Mock sub-agent for testing delegation."""

    def __init__(self, name: str, response_payload: dict | None = None):
        super().__init__(name=name)
        self.response_payload = response_payload or {"result": "mock response"}
        self.received_messages: list[AgentMessage] = []

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """Record message and return configured response."""
        self.received_messages.append(msg)
        return AgentMessage(
            trace_id=msg.trace_id,
            source_agent=self.name,
            target_agent=msg.source_agent,
            intent="response",
            payload=self.response_payload,
        )


class TestDispatchAndWait:
    """Tests for the _dispatch_and_wait method."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mocked dependencies."""
        return Orchestrator(graphiti=None, thread_manager=None)

    @pytest.fixture
    def mock_researcher(self) -> MockSubAgent:
        """Create mock researcher agent."""
        return MockSubAgent("researcher", {"result": "Found: John at Acme Corp"})

    @pytest.mark.asyncio
    async def test_dispatch_and_wait_returns_response(
        self, orchestrator: Orchestrator, mock_researcher: MockSubAgent
    ) -> None:
        """dispatch_and_wait returns response from target agent."""
        # Register mock researcher
        orchestrator.agent_registry = {"researcher": mock_researcher}

        # Start mock researcher in background
        task = asyncio.create_task(mock_researcher.run())

        try:
            response = await orchestrator._dispatch_and_wait(
                "researcher",
                {"query": "who is John?", "intent": "search"},
                "trace-123",
            )

            assert response is not None
            assert response.payload["result"] == "Found: John at Acme Corp"
            assert len(mock_researcher.received_messages) == 1
            assert mock_researcher.received_messages[0].payload["query"] == "who is John?"

        finally:
            await mock_researcher.stop()
            task.cancel()

    @pytest.mark.asyncio
    async def test_dispatch_and_wait_unknown_agent_returns_none(
        self, orchestrator: Orchestrator
    ) -> None:
        """dispatch_and_wait returns None for unknown agent."""
        orchestrator.agent_registry = {}

        response = await orchestrator._dispatch_and_wait(
            "nonexistent",
            {"query": "test"},
            "trace-123",
        )

        assert response is None

    @pytest.mark.asyncio
    async def test_dispatch_and_wait_timeout_returns_none(self, orchestrator: Orchestrator) -> None:
        """dispatch_and_wait returns None on timeout."""

        # Create agent that never responds
        class SlowAgent(BaseAgent):
            async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
                await asyncio.sleep(10)  # Very slow
                return None

        slow_agent = SlowAgent("slow")
        orchestrator.agent_registry = {"slow": slow_agent}

        # Start agent
        task = asyncio.create_task(slow_agent.run())

        try:
            response = await orchestrator._dispatch_and_wait(
                "slow",
                {"query": "test"},
                "trace-123",
                timeout=0.1,  # Very short timeout
            )

            assert response is None

        finally:
            await slow_agent.stop()
            task.cancel()


class TestDispatchFireAndForget:
    """Tests for the _dispatch_fire_and_forget method."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mocked dependencies."""
        return Orchestrator(graphiti=None, thread_manager=None)

    @pytest.mark.asyncio
    async def test_fire_and_forget_sends_message(self, orchestrator: Orchestrator) -> None:
        """fire_and_forget puts message in target agent's inbox."""
        mock_ingestor = MockSubAgent("ingestor")
        orchestrator.agent_registry = {"ingestor": mock_ingestor}

        await orchestrator._dispatch_fire_and_forget(
            "ingestor",
            {"text": "I met Sarah at Acme", "intent": "ingest"},
            "trace-123",
        )

        # Check message is in inbox (not processed yet)
        assert not mock_ingestor.inbox.empty()
        msg = await mock_ingestor.inbox.get()
        assert msg.payload["text"] == "I met Sarah at Acme"

    @pytest.mark.asyncio
    async def test_fire_and_forget_no_response_queue(self, orchestrator: Orchestrator) -> None:
        """fire_and_forget messages have no response_queue."""
        mock_ingestor = MockSubAgent("ingestor")
        orchestrator.agent_registry = {"ingestor": mock_ingestor}

        await orchestrator._dispatch_fire_and_forget(
            "ingestor",
            {"text": "test"},
            "trace-123",
        )

        msg = await mock_ingestor.inbox.get()
        assert msg.response_queue is None

    @pytest.mark.asyncio
    async def test_fire_and_forget_unknown_agent_no_error(self, orchestrator: Orchestrator) -> None:
        """fire_and_forget silently handles unknown agents."""
        orchestrator.agent_registry = {}

        # Should not raise
        await orchestrator._dispatch_fire_and_forget(
            "nonexistent",
            {"text": "test"},
            "trace-123",
        )


class TestHasAgent:
    """Tests for the _has_agent method."""

    def test_has_agent_returns_true_when_registered(self) -> None:
        """_has_agent returns True for registered agents."""
        orchestrator = Orchestrator()
        orchestrator.agent_registry = {"researcher": MagicMock()}

        assert orchestrator._has_agent("researcher") is True

    def test_has_agent_returns_false_when_not_registered(self) -> None:
        """_has_agent returns False for unregistered agents."""
        orchestrator = Orchestrator()
        orchestrator.agent_registry = {}

        assert orchestrator._has_agent("researcher") is False


class TestIntentHandlerDelegation:
    """Tests for intent handlers using delegation."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create orchestrator with mocked dependencies."""
        return Orchestrator(graphiti=None, thread_manager=None)

    @pytest.mark.asyncio
    async def test_handle_search_delegates_to_researcher(self, orchestrator: Orchestrator) -> None:
        """_handle_search delegates to Researcher when available."""
        # Use the new GraphIntelligenceReport format expected by _handle_search
        mock_researcher = MockSubAgent(
            "researcher",
            {
                "report": {
                    "direct_answer": "John works at Acme Corp as a software engineer.",
                    "confidence": 0.9,
                    "confidence_level": "high",
                    "result_count": 1,
                    "evidence": [{"fact": "John is employed at Acme Corp"}],
                }
            },
        )
        orchestrator.agent_registry = {"researcher": mock_researcher}

        # Start mock researcher
        task = asyncio.create_task(mock_researcher.run())

        try:
            intent = IntentClassification(
                type=IntentType.SEARCH,
                confidence=0.9,
                query="who is John?",
            )

            result = await orchestrator._handle_search(intent, None, "trace-123")

            # Now returns direct_answer with evidence when confidence >= 0.5
            assert "John works at Acme Corp as a software engineer." in result
            assert len(mock_researcher.received_messages) == 1
            # Verify evidence is included in response (confidence >= 0.5)
            assert "Supporting evidence" in result
            assert "John is employed at Acme Corp" in result

        finally:
            await mock_researcher.stop()
            task.cancel()

    @pytest.mark.asyncio
    async def test_handle_search_fallback_without_researcher(
        self, orchestrator: Orchestrator
    ) -> None:
        """_handle_search falls back to Claude when Researcher not available."""
        orchestrator.agent_registry = {}

        intent = IntentClassification(
            type=IntentType.SEARCH,
            confidence=0.9,
            query="who is John?",
        )

        # Mock the _call_claude method
        with patch.object(orchestrator, "_call_claude", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = "I don't have that information."

            result = await orchestrator._handle_search(intent, None, "trace-123")

            assert result == "I don't have that information."
            mock_claude.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_action_delegates_to_executor(self, orchestrator: Orchestrator) -> None:
        """_handle_action delegates to Executor when available."""
        mock_executor = MockSubAgent("executor", {"result": "Email sent to john@example.com"})
        orchestrator.agent_registry = {"executor": mock_executor}

        # Start mock executor
        task = asyncio.create_task(mock_executor.run())

        try:
            intent = IntentClassification(
                type=IntentType.ACTION,
                confidence=0.9,
                action="send email to John",
            )

            result = await orchestrator._handle_action(intent, None, "trace-123")

            assert result == "Email sent to john@example.com"
            assert len(mock_executor.received_messages) == 1

        finally:
            await mock_executor.stop()
            task.cancel()

    @pytest.mark.asyncio
    async def test_handle_action_fallback_without_executor(
        self, orchestrator: Orchestrator
    ) -> None:
        """_handle_action returns fallback message when Executor not available."""
        orchestrator.agent_registry = {}

        intent = IntentClassification(
            type=IntentType.ACTION,
            confidence=0.9,
            action="send email to John",
        )

        result = await orchestrator._handle_action(intent, None, "trace-123")

        assert "I've noted your request" in result
        assert "email to John" in result


class TestResponseQueueRouting:
    """Tests for response queue routing in BaseAgent."""

    @pytest.mark.asyncio
    async def test_response_sent_to_queue_not_inbox(self) -> None:
        """When response_queue is set, response goes to queue instead of inbox."""

        class TestAgent(BaseAgent):
            async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
                return AgentMessage(
                    trace_id=msg.trace_id,
                    source_agent=self.name,
                    target_agent=msg.source_agent,
                    intent="response",
                    payload={"result": "test result"},
                )

        agent = TestAgent("test_agent")
        response_queue: asyncio.Queue[AgentMessage] = asyncio.Queue()

        # Create message with response queue
        msg = AgentMessage(
            trace_id="trace-123",
            source_agent="orchestrator",
            target_agent="test_agent",
            intent="request",
            payload={"query": "test"},
            response_queue=response_queue,
        )

        # Put in agent inbox and process
        await agent.inbox.put(msg)

        # Start agent
        task = asyncio.create_task(agent.run())

        # Wait for response in queue
        try:
            response = await asyncio.wait_for(response_queue.get(), timeout=2.0)
            assert response.payload["result"] == "test result"

        finally:
            await agent.stop()
            task.cancel()
