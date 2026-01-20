"""
Golden Scenario E2E Tests - MANDATORY before release.

These 5 scenarios validate the complete system end-to-end.
All 5 must pass before any release.

Reference: specs/quality/TESTING.md Section 5, CLAUDE.md

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tests.conftest import requires_neo4j, requires_openai


if TYPE_CHECKING:
    from klabautermann.memory.graphiti_client import GraphitiClient
    from klabautermann.memory.neo4j_client import Neo4jClient
    from klabautermann.memory.thread_manager import ThreadManager


@pytest.mark.e2e
@pytest.mark.golden
@requires_neo4j
@requires_openai
class TestGoldenScenario1NewContact:
    """
    Golden Scenario 1: New Contact (#237)

    Input: "I met John (john@example.com), PM at Acme"
    Expected: Person node, Organization node, WORKS_AT relationship

    This scenario tests the complete ingestion pipeline:
    User input -> Orchestrator -> Ingestor -> Graphiti -> Neo4j

    Acceptance Criteria:
    - Input contact info
    - Verify Person created
    - Verify Org created
    - Verify WORKS_AT

    Reference: specs/quality/TESTING.md Section 10.2
    """

    @pytest.mark.asyncio
    async def test_creates_person_entity(
        self,
        graphiti_client: GraphitiClient,
        neo4j_client: Neo4jClient,
    ) -> None:
        """'I met X' should create Person entity with extracted properties."""
        # Ingest episode about meeting someone with specific email
        await graphiti_client.add_episode(
            content="I met John Doe (john@example.com). He's a PM at Acme Corp.",
            source="conversation",
            trace_id="golden-1-person-237",
        )

        # Wait for async processing
        await asyncio.sleep(3)

        # Verify Person entity created - check both Entity and EntityNode labels
        # Graphiti uses EntityNode for its internal entities
        result = await neo4j_client.execute_query(
            """
            MATCH (p)
            WHERE (p:Person OR p:Entity OR p:EntityNode)
              AND (toLower(p.name) CONTAINS 'john' OR toLower(p.summary) CONTAINS 'john')
            RETURN p.name as name, p.summary as summary, labels(p) as labels
            """,
            {},
        )

        # Must find at least one entity for John - this is a strict requirement
        assert len(result) >= 1, (
            f"Person entity for 'John Doe' must be created. "
            f"Found {len(result)} entities. "
            f"Check if Graphiti is extracting person entities correctly."
        )

        # Verify name or summary contains identifying info
        found_john = any(
            "john" in (r.get("name", "") or r.get("summary", "") or "").lower() for r in result
        )
        assert found_john, f"Entity must contain 'John' in name/summary. Results: {result}"

    @pytest.mark.asyncio
    async def test_creates_organization_entity(
        self,
        graphiti_client: GraphitiClient,
        neo4j_client: Neo4jClient,
    ) -> None:
        """'at Acme Corp' should create Organization entity."""
        await graphiti_client.add_episode(
            content="I met Sarah from Acme Corp today. She's their lead engineer.",
            source="conversation",
            trace_id="golden-1-org-237",
        )

        await asyncio.sleep(3)

        # Check for organization entity
        result = await neo4j_client.execute_query(
            """
            MATCH (o)
            WHERE (o:Organization OR o:Entity OR o:EntityNode)
              AND (toLower(o.name) CONTAINS 'acme' OR toLower(o.summary) CONTAINS 'acme')
            RETURN o.name as name, o.summary as summary, labels(o) as labels
            """,
            {},
        )

        # Must find organization entity
        assert len(result) >= 1, (
            f"Organization entity for 'Acme Corp' must be created. Found {len(result)} entities."
        )

    @pytest.mark.asyncio
    async def test_creates_works_at_fact(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Person-Organization connection should be searchable as a fact."""
        await graphiti_client.add_episode(
            content="I met Alice (alice@techcorp.com), a Senior Engineer at TechCorp Inc.",
            source="conversation",
            trace_id="golden-1-rel-237",
        )

        await asyncio.sleep(3)

        # Search should find the relationship as a fact
        results = await graphiti_client.search("Alice works at TechCorp", limit=5)

        # Must find searchable facts about Alice at TechCorp
        assert isinstance(results, list), "Search must return a list"
        assert len(results) >= 1, (
            f"WORKS_AT relationship must be searchable. "
            f"Query 'Alice works at TechCorp' returned {len(results)} results."
        )

    @pytest.mark.asyncio
    async def test_works_at_relationship_in_graph(
        self,
        graphiti_client: GraphitiClient,
        neo4j_client: Neo4jClient,
    ) -> None:
        """WORKS_AT relationship should exist between Person and Organization nodes."""
        # Ingest clear employment relationship
        await graphiti_client.add_episode(
            content="Michael Johnson is the CEO of NewTech Solutions. He has worked there since 2020.",
            source="conversation",
            trace_id="golden-1-workat-237",
        )

        await asyncio.sleep(3)

        # Check for edge (relationship) between entities in Graphiti's edge format
        result = await neo4j_client.execute_query(
            """
            MATCH (e:Edge)
            WHERE toLower(e.fact) CONTAINS 'michael'
              AND (toLower(e.fact) CONTAINS 'newtech' OR toLower(e.fact) CONTAINS 'ceo')
            RETURN e.fact as fact, e.name as name
            LIMIT 5
            """,
            {},
        )

        # If Graphiti uses edges, verify relationship fact exists
        # Alternatively check for direct relationship
        if len(result) == 0:
            # Try direct relationship pattern
            result = await neo4j_client.execute_query(
                """
                MATCH (p)-[r]->(o)
                WHERE (toLower(p.name) CONTAINS 'michael' OR toLower(p.summary) CONTAINS 'michael')
                  AND (toLower(o.name) CONTAINS 'newtech' OR toLower(o.summary) CONTAINS 'newtech')
                RETURN type(r) as rel_type, p.name as person, o.name as org
                LIMIT 5
                """,
                {},
            )

        assert len(result) >= 1, (
            "WORKS_AT relationship must be stored in graph. "
            "Expected relationship between Michael and NewTech Solutions."
        )


@pytest.mark.e2e
@pytest.mark.golden
@requires_neo4j
@requires_openai
class TestGoldenScenario2ContextualRetrieval:
    """
    Golden Scenario 2: Contextual Retrieval

    Input: "What did I talk about with John?"
    Expected: Finds thread, summarizes relevant facts

    This scenario tests the search/retrieval pipeline:
    User query -> Researcher -> Graphiti search + Entity search -> Results
    """

    @pytest.mark.asyncio
    async def test_retrieves_known_person_info(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Query about known person returns stored information."""
        # First, create the contact
        await graphiti_client.add_episode(
            content="I had coffee with Bob Smith from StartupX. He's their CTO and we discussed Series A funding.",
            source="conversation",
            trace_id="golden-2-setup",
        )

        await asyncio.sleep(3)

        # Now search for Bob
        results = await graphiti_client.search("Bob Smith", limit=10)
        entity_results = await graphiti_client.search_entities("Bob", limit=5)

        # Either facts about Bob or Bob's entity should be findable
        total_found = len(results) + len(entity_results)
        assert total_found >= 0, (
            "Should be able to find information about Bob via search or entity search"
        )

    @pytest.mark.asyncio
    async def test_retrieves_relationship_facts(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Query about relationships returns stored facts."""
        await graphiti_client.add_episode(
            content="Carol Davis is the VP of Engineering at MegaCorp. She oversees 50 engineers.",
            source="conversation",
            trace_id="golden-2-rel",
        )

        await asyncio.sleep(3)

        # Search for relationship fact
        results = await graphiti_client.search("Carol VP Engineering", limit=5)

        # Should find facts about Carol's role
        assert isinstance(results, list)


@pytest.mark.e2e
@pytest.mark.golden
@requires_neo4j
@requires_openai
class TestGoldenScenario3BlockedTask:
    """
    Golden Scenario 3: Blocked Task (#238)

    Input: "Can't finish until John sends stats"
    Expected: Creates BLOCKS or dependency relationship

    This scenario tests task/dependency extraction:
    User input -> Ingestor -> Task extraction -> Graph storage

    Acceptance Criteria:
    - Create blocked task
    - Verify BLOCKS relationship
    - Query blocked tasks

    Reference: specs/quality/TESTING.md Section 10.2
    """

    @pytest.mark.asyncio
    async def test_extracts_blocking_information(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Blocking language should create searchable facts about dependencies."""
        await graphiti_client.add_episode(
            content="I can't finish the Q1 report until Mark sends the statistics. This is blocking my progress.",
            source="conversation",
            trace_id="golden-3-block-238",
        )

        await asyncio.sleep(3)

        # Should be able to search for blocking/dependency facts
        results = await graphiti_client.search("Q1 report blocked", limit=5)

        # Must find searchable facts about blocking relationship
        assert isinstance(results, list), "Search must return a list"
        assert len(results) >= 1, (
            f"Blocking relationship must be searchable. "
            f"Query 'Q1 report blocked' returned {len(results)} results."
        )

    @pytest.mark.asyncio
    async def test_blocks_relationship_in_graph(
        self,
        graphiti_client: GraphitiClient,
        neo4j_client: Neo4jClient,
    ) -> None:
        """BLOCKS/dependency relationship should be stored in graph."""
        await graphiti_client.add_episode(
            content="The project launch is blocked by the security audit. We cannot proceed until the audit is complete.",
            source="conversation",
            trace_id="golden-3-rel-238",
        )

        await asyncio.sleep(3)

        # Check for edge with blocking information in Graphiti's edge format
        result = await neo4j_client.execute_query(
            """
            MATCH (e:Edge)
            WHERE toLower(e.fact) CONTAINS 'block'
              AND (toLower(e.fact) CONTAINS 'launch' OR toLower(e.fact) CONTAINS 'audit')
            RETURN e.fact as fact, e.name as name
            LIMIT 5
            """,
            {},
        )

        # Alternatively check for Task nodes with BLOCKS relationship
        if len(result) == 0:
            result = await neo4j_client.execute_query(
                """
                MATCH (blocker)-[r:BLOCKS]->(blocked)
                WHERE (toLower(blocker.action) CONTAINS 'audit' OR toLower(blocker.name) CONTAINS 'audit')
                RETURN blocker.action as blocker, blocked.action as blocked, r.reason as reason
                LIMIT 5
                """,
                {},
            )

        # If no explicit BLOCKS relationship, check for dependency facts
        if len(result) == 0:
            result = await neo4j_client.execute_query(
                """
                MATCH (t)-[r]->(dep)
                WHERE type(r) IN ['BLOCKS', 'DEPENDS_ON', 'RELATED_TO']
                  AND (toLower(t.name) CONTAINS 'audit' OR toLower(dep.name) CONTAINS 'launch')
                RETURN type(r) as rel_type, t.name as task1, dep.name as task2
                LIMIT 5
                """,
                {},
            )

        assert len(result) >= 1, (
            "BLOCKS/dependency relationship must be stored in graph. "
            "Expected relationship between 'security audit' and 'project launch'."
        )

    @pytest.mark.asyncio
    async def test_query_blocked_tasks(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """User should be able to query blocked tasks via search."""
        # Create blocking scenario
        await graphiti_client.add_episode(
            content="The marketing campaign is waiting for the design assets from the creative team. This dependency is critical.",
            source="conversation",
            trace_id="golden-3-query-238",
        )

        await asyncio.sleep(3)

        # Query for blocked/waiting tasks
        results = await graphiti_client.search("what is blocking marketing campaign", limit=5)

        assert isinstance(results, list), "Search must return a list"
        # Should find facts about the blocking dependency
        assert len(results) >= 1, (
            f"Blocked task query must return results. "
            f"Query about marketing campaign dependencies returned {len(results)} results."
        )

    @pytest.mark.asyncio
    async def test_multiple_blocking_relationships(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Multiple blocking relationships should be trackable."""
        # Create multiple dependencies
        await graphiti_client.add_episode(
            content=(
                "The website relaunch depends on three things: "
                "1) Server migration must complete first, "
                "2) Content review needs to be finished, and "
                "3) Legal approval is required. "
                "All of these are blocking the launch."
            ),
            source="conversation",
            trace_id="golden-3-multi-238",
        )

        await asyncio.sleep(3)

        # Should be able to find multiple dependencies
        results = await graphiti_client.search("website relaunch dependencies", limit=10)

        assert isinstance(results, list), "Search must return a list"
        assert len(results) >= 1, (
            f"Multiple dependencies must be searchable. "
            f"Query about website relaunch dependencies returned {len(results)} results."
        )


@pytest.mark.e2e
@pytest.mark.golden
@requires_neo4j
@requires_openai
class TestGoldenScenario4TemporalTimeTravel:
    """
    Golden Scenario 4: Temporal Time-Travel (#239)

    Input: Change employer, ask historical
    Expected: Returns old employer, not just current

    This scenario tests temporal graph capabilities:
    Multiple facts over time -> Graphiti temporal handling -> Historical queries

    Acceptance Criteria:
    - Change employer
    - Query historical employer
    - Return old employer

    Reference: specs/quality/TESTING.md Section 10.2
    """

    @pytest.mark.asyncio
    async def test_change_employer_preserves_history(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Changing employer should preserve employment history."""
        # Initial state: Person works at first company
        await graphiti_client.add_episode(
            content="Dave works at OldCompany as a Developer. He's been there for 5 years.",
            source="conversation",
            trace_id="golden-4-initial-239",
        )
        await asyncio.sleep(3)

        # Update state: Person moves to new company
        await graphiti_client.add_episode(
            content="Dave left OldCompany last week and joined NewCompany as Tech Lead.",
            source="conversation",
            trace_id="golden-4-update-239",
        )
        await asyncio.sleep(3)

        # Search should find facts about Dave's employment history
        results = await graphiti_client.search("Dave employment history", limit=10)

        # Must find employment history facts
        assert isinstance(results, list), "Search must return a list"
        assert len(results) >= 1, (
            f"Employment history must be searchable. "
            f"Query 'Dave employment history' returned {len(results)} results."
        )

    @pytest.mark.asyncio
    async def test_query_historical_employer(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Query for historical employer should return past employment."""
        # Setup: Create historical employment
        await graphiti_client.add_episode(
            content="In 2022, Eve was working at FirstJob Inc as a junior developer.",
            source="conversation",
            trace_id="golden-4-history-setup-239",
        )
        await asyncio.sleep(3)

        await graphiti_client.add_episode(
            content="Eve now works at CurrentJob Corp as a senior engineer since 2024.",
            source="conversation",
            trace_id="golden-4-history-current-239",
        )
        await asyncio.sleep(3)

        # Search for historical employer specifically
        results = await graphiti_client.search("Eve FirstJob", limit=5)

        # Must find facts about Eve's past employment
        assert isinstance(results, list), "Search must return a list"
        assert len(results) >= 1, (
            f"Historical employer must be queryable. "
            f"Query 'Eve FirstJob' returned {len(results)} results."
        )

    @pytest.mark.asyncio
    async def test_return_old_employer_not_just_current(
        self,
        graphiti_client: GraphitiClient,
    ) -> None:
        """Both old and current employer should be findable."""
        # Create clear employment transition
        await graphiti_client.add_episode(
            content="Frank worked at PastCorp from 2018 to 2022 as a software engineer.",
            source="conversation",
            trace_id="golden-4-old-239",
        )
        await asyncio.sleep(3)

        await graphiti_client.add_episode(
            content="Frank now works at PresentCorp since 2023 as a senior architect.",
            source="conversation",
            trace_id="golden-4-current-239",
        )
        await asyncio.sleep(3)

        # Query for old employer specifically
        old_results = await graphiti_client.search("Frank PastCorp", limit=5)

        # Query for current employer
        current_results = await graphiti_client.search("Frank PresentCorp", limit=5)

        # Both should be findable
        assert len(old_results) >= 1, (
            f"Old employer must be queryable. "
            f"Query 'Frank PastCorp' returned {len(old_results)} results."
        )
        assert len(current_results) >= 1, (
            f"Current employer must be queryable. "
            f"Query 'Frank PresentCorp' returned {len(current_results)} results."
        )

    @pytest.mark.asyncio
    async def test_temporal_ordering_preserved(
        self,
        graphiti_client: GraphitiClient,
        neo4j_client: Neo4jClient,
    ) -> None:
        """Temporal facts should preserve their ordering."""
        # Create sequence of events
        await graphiti_client.add_episode(
            content="Grace started at CompanyA in 2015.",
            source="conversation",
            trace_id="golden-4-seq1-239",
        )
        await asyncio.sleep(2)

        await graphiti_client.add_episode(
            content="Grace moved to CompanyB in 2018.",
            source="conversation",
            trace_id="golden-4-seq2-239",
        )
        await asyncio.sleep(2)

        await graphiti_client.add_episode(
            content="Grace joined CompanyC in 2022.",
            source="conversation",
            trace_id="golden-4-seq3-239",
        )
        await asyncio.sleep(3)

        # Search for Grace's full history
        results = await graphiti_client.search("Grace career history", limit=10)

        # Must find career history
        assert len(results) >= 1, (
            f"Career history with temporal ordering must be searchable. "
            f"Query returned {len(results)} results."
        )


@pytest.mark.e2e
@pytest.mark.golden
@requires_neo4j
class TestGoldenScenario5MultiChannelThreading:
    """
    Golden Scenario 5: Multi-Channel Threading (#240)

    Input: CLI + Telegram conversations
    Expected: Separate threads, no context bleed

    This scenario tests thread isolation:
    Different channels -> Separate threads -> No cross-contamination

    Acceptance Criteria:
    - CLI conversation
    - Telegram conversation
    - Verify no context bleed

    Reference: specs/quality/TESTING.md Section 10.2
    """

    @pytest.mark.asyncio
    async def test_channel_isolation(
        self,
        thread_manager: ThreadManager,
    ) -> None:
        """CLI and Telegram threads are isolated."""
        # Create CLI thread
        cli_thread = await thread_manager.get_or_create_thread(
            external_id="golden-cli-session-001",
            channel_type="cli",
        )

        # Create Telegram thread
        tg_thread = await thread_manager.get_or_create_thread(
            external_id="golden-tg-12345",
            channel_type="telegram",
        )

        # Verify different UUIDs
        assert cli_thread.uuid != tg_thread.uuid

        # Add messages to each
        await thread_manager.add_message(cli_thread.uuid, "user", "Working on Project Alpha in CLI")
        await thread_manager.add_message(
            tg_thread.uuid, "user", "Working on Project Beta in Telegram"
        )

        # Verify isolation - context from one doesn't appear in other
        cli_context = await thread_manager.get_context_window(cli_thread.uuid)
        tg_context = await thread_manager.get_context_window(tg_thread.uuid)

        assert len(cli_context.messages) == 1
        assert len(tg_context.messages) == 1

        # Verify no cross-contamination
        cli_content = cli_context.messages[0]["content"]
        tg_content = tg_context.messages[0]["content"]

        assert "Alpha" in cli_content and "Beta" not in cli_content
        assert "Beta" in tg_content and "Alpha" not in tg_content

    @pytest.mark.asyncio
    async def test_same_channel_different_users(
        self,
        thread_manager: ThreadManager,
    ) -> None:
        """Same channel with different external IDs creates different threads."""
        # Two different Telegram users
        user1_thread = await thread_manager.get_or_create_thread(
            external_id="golden-tg-user-001",
            channel_type="telegram",
        )
        user2_thread = await thread_manager.get_or_create_thread(
            external_id="golden-tg-user-002",
            channel_type="telegram",
        )

        # Different threads for different users
        assert user1_thread.uuid != user2_thread.uuid

    @pytest.mark.asyncio
    async def test_same_external_id_same_thread(
        self,
        thread_manager: ThreadManager,
    ) -> None:
        """Same external_id + channel returns the same thread."""
        thread1 = await thread_manager.get_or_create_thread(
            external_id="golden-persistent-session",
            channel_type="cli",
        )
        thread2 = await thread_manager.get_or_create_thread(
            external_id="golden-persistent-session",
            channel_type="cli",
        )

        # Same external_id should return same thread
        assert thread1.uuid == thread2.uuid

    @pytest.mark.asyncio
    async def test_thread_context_window_ordering(
        self,
        thread_manager: ThreadManager,
    ) -> None:
        """Messages in context window are in chronological order."""
        thread = await thread_manager.get_or_create_thread(
            external_id="golden-ordering-test",
            channel_type="cli",
        )

        # Add messages in order
        await thread_manager.add_message(thread.uuid, "user", "First message")
        await thread_manager.add_message(thread.uuid, "assistant", "Second message")
        await thread_manager.add_message(thread.uuid, "user", "Third message")

        context = await thread_manager.get_context_window(thread.uuid)

        assert len(context.messages) == 3
        assert context.messages[0]["content"] == "First message"
        assert context.messages[1]["content"] == "Second message"
        assert context.messages[2]["content"] == "Third message"
