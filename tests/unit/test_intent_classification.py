"""
Unit tests for Orchestrator intent classification.

Reference: specs/architecture/AGENTS.md Section 1.1
Task: T020 - Orchestrator Intent Classification

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

import pytest

from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.models import IntentClassification, IntentType


class TestIntentClassification:
    """Test suite for intent classification functionality."""

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
        intent = await orchestrator._classify_intent(
            text="Who is Sarah?",
            _context=None,
            trace_id="test-001",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.confidence == 0.9
        assert intent.query == "Who is Sarah?"

    @pytest.mark.asyncio
    async def test_what_is_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'What is the status of Project Alpha?' should be SEARCH intent."""
        intent = await orchestrator._classify_intent(
            text="What is the status of Project Alpha?",
            _context=None,
            trace_id="test-002",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_tell_me_about_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'Tell me about John's company' should be SEARCH intent."""
        intent = await orchestrator._classify_intent(
            text="Tell me about John's company",
            _context=None,
            trace_id="test-003",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_find_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'Find all tasks for this week' should be SEARCH intent."""
        intent = await orchestrator._classify_intent(
            text="Find all tasks for this week",
            _context=None,
            trace_id="test-004",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_remind_me_classified_as_search(self, orchestrator: Orchestrator) -> None:
        """'Remind me what we discussed about budget' should be SEARCH intent."""
        intent = await orchestrator._classify_intent(
            text="Remind me what we discussed about budget",
            _context=None,
            trace_id="test-005",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.confidence == 0.9

    # =========================================================================
    # Action Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_email_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Send an email to John' should be classified as ACTION intent."""
        intent = await orchestrator._classify_intent(
            text="Send an email to John",
            _context=None,
            trace_id="test-010",
        )

        assert intent.type == IntentType.ACTION
        assert intent.confidence == 0.9
        assert intent.action == "Send an email to John"

    @pytest.mark.asyncio
    async def test_schedule_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Schedule a meeting with Sarah for tomorrow' should be ACTION intent."""
        intent = await orchestrator._classify_intent(
            text="Schedule a meeting with Sarah for tomorrow",
            _context=None,
            trace_id="test-011",
        )

        assert intent.type == IntentType.ACTION
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_create_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Create a task to follow up with client' should be ACTION intent."""
        intent = await orchestrator._classify_intent(
            text="Create a task to follow up with client",
            _context=None,
            trace_id="test-012",
        )

        assert intent.type == IntentType.ACTION
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_draft_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Draft a response to the proposal' should be ACTION intent."""
        intent = await orchestrator._classify_intent(
            text="Draft a response to the proposal",
            _context=None,
            trace_id="test-013",
        )

        assert intent.type == IntentType.ACTION
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_book_classified_as_action(self, orchestrator: Orchestrator) -> None:
        """'Book a conference room for 3pm' should be ACTION intent."""
        intent = await orchestrator._classify_intent(
            text="Book a conference room for 3pm",
            _context=None,
            trace_id="test-014",
        )

        assert intent.type == IntentType.ACTION
        assert intent.confidence == 0.9

    # =========================================================================
    # Ingestion Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_i_met_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I met Tom from Google' should be classified as INGESTION intent."""
        intent = await orchestrator._classify_intent(
            text="I met Tom from Google",
            _context=None,
            trace_id="test-020",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.confidence == 0.8

    @pytest.mark.asyncio
    async def test_i_talked_to_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I talked to Sarah about the project' should be INGESTION intent."""
        intent = await orchestrator._classify_intent(
            text="I talked to Sarah about the project",
            _context=None,
            trace_id="test-021",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.confidence == 0.8

    @pytest.mark.asyncio
    async def test_im_working_on_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I'm working on a new feature for the app' should be INGESTION intent."""
        intent = await orchestrator._classify_intent(
            text="I'm working on a new feature for the app",
            _context=None,
            trace_id="test-022",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.confidence == 0.8

    @pytest.mark.asyncio
    async def test_i_learned_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I learned that John is moving to a new role' should be INGESTION intent."""
        intent = await orchestrator._classify_intent(
            text="I learned that John is moving to a new role",
            _context=None,
            trace_id="test-023",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.confidence == 0.8

    @pytest.mark.asyncio
    async def test_i_just_classified_as_ingestion(self, orchestrator: Orchestrator) -> None:
        """'I just finished a call with the team' should be INGESTION intent."""
        intent = await orchestrator._classify_intent(
            text="I just finished a call with the team",
            _context=None,
            trace_id="test-024",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.confidence == 0.8

    # =========================================================================
    # Conversation Intent Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_hello_classified_as_conversation(self, orchestrator: Orchestrator) -> None:
        """'Hello, how are you?' should be classified as CONVERSATION intent."""
        intent = await orchestrator._classify_intent(
            text="Hello, how are you?",
            _context=None,
            trace_id="test-030",
        )

        assert intent.type == IntentType.CONVERSATION
        assert intent.confidence == 0.7

    @pytest.mark.asyncio
    async def test_thanks_classified_as_conversation(self, orchestrator: Orchestrator) -> None:
        """'Thanks for your help!' should be CONVERSATION intent."""
        intent = await orchestrator._classify_intent(
            text="Thanks for your help!",
            _context=None,
            trace_id="test-031",
        )

        assert intent.type == IntentType.CONVERSATION
        assert intent.confidence == 0.7

    @pytest.mark.asyncio
    async def test_random_statement_classified_as_conversation(
        self, orchestrator: Orchestrator
    ) -> None:
        """Random statements without keywords should be CONVERSATION intent."""
        intent = await orchestrator._classify_intent(
            text="The weather is nice today",
            _context=None,
            trace_id="test-032",
        )

        assert intent.type == IntentType.CONVERSATION
        assert intent.confidence == 0.7

    # =========================================================================
    # Case Insensitivity Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_uppercase_search_keyword(self, orchestrator: Orchestrator) -> None:
        """'WHO IS SARAH?' (uppercase) should still be classified as SEARCH."""
        intent = await orchestrator._classify_intent(
            text="WHO IS SARAH?",
            _context=None,
            trace_id="test-040",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_mixed_case_action_keyword(self, orchestrator: Orchestrator) -> None:
        """'Send An Email' (mixed case) should still be classified as ACTION."""
        intent = await orchestrator._classify_intent(
            text="Send An Email to the team",
            _context=None,
            trace_id="test-041",
        )

        assert intent.type == IntentType.ACTION
        assert intent.confidence == 0.9

    @pytest.mark.asyncio
    async def test_mixed_case_ingestion_keyword(self, orchestrator: Orchestrator) -> None:
        """'I MET someone new' should still be classified as INGESTION."""
        intent = await orchestrator._classify_intent(
            text="I MET someone new today",
            _context=None,
            trace_id="test-042",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.confidence == 0.8

    # =========================================================================
    # Priority Tests (Search > Action > Ingestion > Conversation)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_search_takes_priority_first_match(self, orchestrator: Orchestrator) -> None:
        """When multiple keywords match, first keyword type wins."""
        # "Who is" appears before any action keyword
        intent = await orchestrator._classify_intent(
            text="Who is going to send the email?",
            _context=None,
            trace_id="test-050",
        )

        # Search keywords are checked first, so SEARCH wins
        assert intent.type == IntentType.SEARCH

    # =========================================================================
    # Intent Model Validation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_intent_classification_model_fields(
        self, orchestrator: Orchestrator
    ) -> None:
        """IntentClassification model should have all expected fields."""
        intent = await orchestrator._classify_intent(
            text="Who is Sarah?",
            _context=None,
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
        intent = await orchestrator._classify_intent(
            text="Who is Sarah?",
            _context=None,
            trace_id="test-061",
        )

        assert intent.type == IntentType.SEARCH
        assert intent.query is not None
        assert intent.query == "Who is Sarah?"
        assert intent.action is None

    @pytest.mark.asyncio
    async def test_action_intent_has_action(self, orchestrator: Orchestrator) -> None:
        """ACTION intent should populate the action field."""
        intent = await orchestrator._classify_intent(
            text="Send an email to John",
            _context=None,
            trace_id="test-062",
        )

        assert intent.type == IntentType.ACTION
        assert intent.action is not None
        assert intent.action == "Send an email to John"
        assert intent.query is None

    @pytest.mark.asyncio
    async def test_ingestion_intent_has_no_query_or_action(
        self, orchestrator: Orchestrator
    ) -> None:
        """INGESTION intent should not populate query or action fields."""
        intent = await orchestrator._classify_intent(
            text="I met Tom from Google",
            _context=None,
            trace_id="test-063",
        )

        assert intent.type == IntentType.INGESTION
        assert intent.query is None
        assert intent.action is None
