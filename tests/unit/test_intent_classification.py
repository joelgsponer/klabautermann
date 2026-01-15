"""
Unit tests for Orchestrator intent classification.

Reference: specs/architecture/AGENTS.md Section 1.1
Task: T020 - Orchestrator Intent Classification

Tests LLM-based intent classification with mocked API responses.
Also tests fallback behavior when LLM is unavailable.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import IntentClassification, IntentType


def mock_classification_response(
    intent_type: str,
    confidence: float = 0.9,
    reasoning: str = "Test classification",
    extracted_query: str | None = None,
    extracted_action: str | None = None,
) -> str:
    """Helper to create mock LLM classification response JSON.

    Note: intent_type should be lowercase to match IntentType enum values.
    """
    return json.dumps(
        {
            "intent_type": intent_type.lower(),  # Enum expects lowercase
            "confidence": confidence,
            "reasoning": reasoning,
            "extracted_query": extracted_query,
            "extracted_action": extracted_action,
        }
    )


class TestIntentClassification:
    """Test suite for LLM-based intent classification functionality."""

    @pytest.fixture
    def orchestrator(self) -> Orchestrator:
        """Create an Orchestrator instance for testing."""
        return Orchestrator(graphiti=None, thread_manager=None, config={})

    # =========================================================================
    # Search Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_who_is_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'Who is Sarah?' should be classified as SEARCH intent."""
        mock_response = mock_classification_response(
            "SEARCH", 0.95, "User asking about a person", "Who is Sarah?"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Who is Sarah?",
                context=None,
                trace_id="test-001",
            )

            assert intent.type == IntentType.SEARCH
            assert intent.confidence >= 0.8
            assert intent.query == "Who is Sarah?"

    @pytest.mark.asyncio
    async def test_what_is_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'What is the status of Project Alpha?' should be SEARCH intent."""
        mock_response = mock_classification_response(
            "SEARCH", 0.9, "User asking for information", "What is the status of Project Alpha?"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="What is the status of Project Alpha?",
                context=None,
                trace_id="test-002",
            )

            assert intent.type == IntentType.SEARCH
            assert intent.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_tell_me_about_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'Tell me about John's company' should be SEARCH intent."""
        mock_response = mock_classification_response(
            "SEARCH", 0.9, "User requesting information retrieval"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Tell me about John's company",
                context=None,
                trace_id="test-003",
            )

            assert intent.type == IntentType.SEARCH

    # =========================================================================
    # Action Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_email_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Send an email to John' should be classified as ACTION intent."""
        mock_response = mock_classification_response(
            "ACTION", 0.95, "User wants to send email", None, "Send an email to John"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Send an email to John",
                context=None,
                trace_id="test-010",
            )

            assert intent.type == IntentType.ACTION
            assert intent.confidence >= 0.8
            assert intent.action == "Send an email to John"

    @pytest.mark.asyncio
    async def test_schedule_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Schedule a meeting with Sarah for tomorrow' should be ACTION intent."""
        mock_response = mock_classification_response(
            "ACTION", 0.9, "User wants to schedule meeting"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Schedule a meeting with Sarah for tomorrow",
                context=None,
                trace_id="test-011",
            )

            assert intent.type == IntentType.ACTION

    # =========================================================================
    # Ingestion Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_i_met_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I met Tom from Google' should be classified as INGESTION intent."""
        mock_response = mock_classification_response(
            "INGESTION", 0.9, "User sharing new information about a person"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="I met Tom from Google",
                context=None,
                trace_id="test-020",
            )

            assert intent.type == IntentType.INGESTION

    @pytest.mark.asyncio
    async def test_i_talked_to_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I talked to Sarah about the project' should be INGESTION intent."""
        mock_response = mock_classification_response(
            "INGESTION", 0.85, "User sharing conversation information"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="I talked to Sarah about the project",
                context=None,
                trace_id="test-021",
            )

            assert intent.type == IntentType.INGESTION

    # =========================================================================
    # Conversation Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_hello_classified_as_conversation(self, orchestrator: Orchestrator) -> None:
        """'Hello, how are you?' should be classified as CONVERSATION intent."""
        mock_response = mock_classification_response(
            "CONVERSATION", 0.95, "Greeting/social interaction"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Hello, how are you?",
                context=None,
                trace_id="test-030",
            )

            assert intent.type == IntentType.CONVERSATION

    @pytest.mark.asyncio
    async def test_thanks_classified_as_conversation(self, orchestrator: Orchestrator) -> None:
        """'Thanks for your help!' should be CONVERSATION intent."""
        mock_response = mock_classification_response(
            "CONVERSATION", 0.9, "Acknowledgment/gratitude"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Thanks for your help!",
                context=None,
                trace_id="test-031",
            )

            assert intent.type == IntentType.CONVERSATION

    # =========================================================================
    # Fallback Tests (when LLM fails)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self, orchestrator: Orchestrator) -> None:
        """When LLM fails, should fall back to heuristics."""
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = Exception("API Error")

            # Question mark should trigger SEARCH fallback
            intent = await orchestrator._classify_intent(
                text="Who is Sarah?",
                context=None,
                trace_id="test-fallback-001",
            )

            assert intent.type == IntentType.SEARCH
            assert intent.confidence == 0.6  # Fallback confidence

    @pytest.mark.asyncio
    async def test_fallback_action_keyword(self, orchestrator: Orchestrator) -> None:
        """Fallback should detect action keywords."""
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = Exception("API Error")

            intent = await orchestrator._classify_intent(
                text="Send an email to John",
                context=None,
                trace_id="test-fallback-002",
            )

            assert intent.type == IntentType.ACTION
            assert intent.confidence == 0.6

    @pytest.mark.asyncio
    async def test_fallback_ingestion_keyword(self, orchestrator: Orchestrator) -> None:
        """Fallback should detect ingestion keywords."""
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = Exception("API Error")

            intent = await orchestrator._classify_intent(
                text="I met Sarah yesterday",
                context=None,
                trace_id="test-fallback-003",
            )

            assert intent.type == IntentType.INGESTION
            assert intent.confidence == 0.6

    @pytest.mark.asyncio
    async def test_fallback_default_conversation(self, orchestrator: Orchestrator) -> None:
        """Fallback should default to CONVERSATION for unclear messages."""
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.side_effect = Exception("API Error")

            intent = await orchestrator._classify_intent(
                text="The weather is nice",
                context=None,
                trace_id="test-fallback-004",
            )

            assert intent.type == IntentType.CONVERSATION
            assert intent.confidence == 0.5

    # =========================================================================
    # JSON Parsing Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_handles_uppercase_intent_type(self, orchestrator: Orchestrator) -> None:
        """Should handle LLM returning uppercase intent_type.

        Real LLMs often return 'INGESTION' instead of 'ingestion' despite
        the prompt example. This test ensures normalization works.
        """
        # Deliberately use uppercase - DO NOT call .lower()
        mock_response = json.dumps(
            {
                "intent_type": "INGESTION",  # Uppercase like real LLM returns
                "confidence": 0.9,
                "reasoning": "User sharing information",
                "extracted_query": None,
                "extracted_action": None,
            }
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="I met Sarah from Acme",
                context=None,
                trace_id="test-uppercase-001",
            )

            assert intent.type == IntentType.INGESTION
            assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_handles_markdown_code_block(self, orchestrator: Orchestrator) -> None:
        """Should handle LLM response wrapped in markdown code block."""
        mock_response = f"""```json
{mock_classification_response("SEARCH", 0.9, "Test")}
```"""

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Who is Sarah?",
                context=None,
                trace_id="test-json-001",
            )

            assert intent.type == IntentType.SEARCH

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, orchestrator: Orchestrator) -> None:
        """Should fall back when LLM returns invalid JSON."""
        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "This is not valid JSON"

            # Should fall back to heuristics
            intent = await orchestrator._classify_intent(
                text="Who is Sarah?",
                context=None,
                trace_id="test-json-002",
            )

            # Question mark triggers SEARCH in fallback
            assert intent.type == IntentType.SEARCH
            assert intent.confidence == 0.6

    # =========================================================================
    # Intent Model Validation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_intent_classification_model_fields(self, orchestrator: Orchestrator) -> None:
        """IntentClassification model should have all expected fields."""
        mock_response = mock_classification_response("SEARCH", 0.9, "Test", "Who is Sarah?")

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Who is Sarah?",
                context=None,
                trace_id="test-060",
            )

            assert isinstance(intent, IntentClassification)
            assert hasattr(intent, "type")
            assert hasattr(intent, "confidence")
            assert hasattr(intent, "query")
            assert hasattr(intent, "action")
            assert hasattr(intent, "context_query")

    @pytest.mark.asyncio
    async def test_search_intent_has_query(self, orchestrator: Orchestrator) -> None:
        """SEARCH intent should populate the query field."""
        mock_response = mock_classification_response("SEARCH", 0.9, "Test", "Who is Sarah?")

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Who is Sarah?",
                context=None,
                trace_id="test-061",
            )

            assert intent.type == IntentType.SEARCH
            assert intent.query == "Who is Sarah?"
            assert intent.action is None

    @pytest.mark.asyncio
    async def test_action_intent_has_action(self, orchestrator: Orchestrator) -> None:
        """ACTION intent should populate the action field."""
        mock_response = mock_classification_response(
            "ACTION", 0.9, "Test", None, "Send an email to John"
        )

        with patch.object(
            orchestrator, "_call_classification_model", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = mock_response

            intent = await orchestrator._classify_intent(
                text="Send an email to John",
                context=None,
                trace_id="test-062",
            )

            assert intent.type == IntentType.ACTION
            assert intent.action == "Send an email to John"
            assert intent.query is None
