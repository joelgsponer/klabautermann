#!/usr/bin/env python3
"""
Smoke test script for the Intelligent Researcher agent.

Usage:
    uv run scripts/test_researcher.py                    # Test imports only
    uv run scripts/test_researcher.py --query "..."      # Test with a query (uses .env)
"""

import argparse
import asyncio
import os
import sys
import time

from dotenv import load_dotenv


# Load .env file
load_dotenv()


def test_imports() -> bool:
    """Test that all imports work correctly."""
    print("Testing imports...")

    try:
        from klabautermann.agents.researcher import STRUCTURAL_QUERIES, Researcher

        print("  ✓ Researcher class imported")

        from klabautermann.agents.researcher_models import (
            ConfidenceLevel,
            GraphIntelligenceReport,
            RawSearchResult,
            SearchPlan,
            SearchStrategy,
            SearchTechnique,
        )

        print("  ✓ Pydantic models imported")

        from klabautermann.agents.researcher_prompts import PLANNING_PROMPT, SYNTHESIS_PROMPT

        print("  ✓ System prompts imported")

        # Verify structural queries exist
        assert "WORKS_AT" in STRUCTURAL_QUERIES
        assert "KNOWS" in STRUCTURAL_QUERIES
        assert "WORKS_AT_HISTORICAL" in STRUCTURAL_QUERIES
        print(f"  ✓ {len(STRUCTURAL_QUERIES)} structural queries defined")

        # Verify prompts have content
        assert len(PLANNING_PROMPT) > 1000
        assert len(SYNTHESIS_PROMPT) > 500
        print("  ✓ Prompts have content")

        # Test model instantiation
        strategy = SearchStrategy(
            technique=SearchTechnique.VECTOR,
            query="test",
            rationale="Test search",
        )
        assert strategy.limit == 10
        print("  ✓ SearchStrategy instantiation works")

        plan = SearchPlan(
            original_query="test query",
            strategies=[strategy],
            expected_result_type="info",
            zoom_level="micro",
        )
        assert len(plan.strategies) == 1
        print("  ✓ SearchPlan instantiation works")

        report = GraphIntelligenceReport(
            query="test",
            direct_answer="Test answer",
            confidence=0.8,
            confidence_level=ConfidenceLevel.HIGH,
            as_of_date="2026-01-16",
            result_count=5,
        )
        assert report.confidence == 0.8
        print("  ✓ GraphIntelligenceReport instantiation works")

        # Test researcher instantiation
        researcher = Researcher()
        assert researcher.planning_model == "claude-opus-4-5-20251101"
        assert researcher.strength_boost_factor == 0.3
        print("  ✓ Researcher instantiation works")

        # Test scoring algorithm
        result = RawSearchResult(
            content="Test",
            source_technique=SearchTechnique.STRUCTURAL,
            vector_score=0.8,
            relationship_strengths=[1.0],
        )
        score = researcher._calculate_result_score(result)
        expected = 0.8 * (1 + 1.0 * 0.3)  # 1.04
        assert abs(score - expected) < 0.001
        print(f"  ✓ Strength-aware scoring works (score={score:.3f})")

        print("\n✅ All import tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ Import test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_query(query: str) -> bool:
    """Test the researcher with an actual query (requires API key + Neo4j)."""
    print(f"\nTesting query: {query}")
    print("=" * 60)

    try:
        from klabautermann.agents.researcher import Researcher
        from klabautermann.core.models import AgentMessage
        from klabautermann.memory import GraphitiClient, Neo4jClient

        # Initialize and connect to backends
        print("Connecting to Neo4j...")
        neo4j = Neo4jClient()
        await neo4j.connect()
        print("  ✓ Neo4j connected")

        print("Connecting to Graphiti...")
        graphiti = GraphitiClient()
        await graphiti.connect()
        print("  ✓ Graphiti connected")

        # Create researcher with backends
        researcher = Researcher(
            graphiti=graphiti,
            neo4j=neo4j,
        )

        msg = AgentMessage(
            trace_id=f"test-{int(time.time())}",
            source_agent="orchestrator",
            target_agent="researcher",
            intent="search",
            payload={"query": query},
            timestamp=time.time(),
        )

        print("\nProcessing message (calling Opus for planning + synthesis)...")
        start = time.time()
        response = await researcher.process_message(msg)
        elapsed = time.time() - start

        if response:
            report = response.payload.get("report", {})
            print(f"\n📊 Results (in {elapsed:.2f}s):")
            print(f"   Direct Answer: {report.get('direct_answer', 'N/A')[:300]}")
            print(
                f"   Confidence: {report.get('confidence', 0):.2f} ({report.get('confidence_level', 'N/A')})"
            )
            print(
                f"   Techniques: {[t.value if hasattr(t, 'value') else t for t in report.get('search_techniques_used', [])]}"
            )
            print(f"   Results: {report.get('result_count', 0)}")

            if report.get("evidence"):
                print("   Evidence:")
                for e in report["evidence"][:3]:
                    print(f"     - {e.get('fact', '')[:100]}")

            if report.get("relationships"):
                print("   Relationships:")
                for r in report["relationships"][:3]:
                    print(
                        f"     - {r.get('source_name')} --[{r.get('relationship_type')}]--> {r.get('target_name')}"
                    )

            if report.get("related_queries"):
                print(f"   Related: {report['related_queries']}")

            if report.get("gaps_identified"):
                print(f"   Gaps: {report['gaps_identified']}")

            print("\n✅ Query test passed!")
            return True
        else:
            print("❌ No response received")
            return False

    except Exception as e:
        print(f"\n❌ Query test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        # Cleanup connections
        try:
            if "neo4j" in dir() and neo4j:
                await neo4j.close()
            if "graphiti" in dir() and graphiti:
                await graphiti.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the Intelligent Researcher")
    parser.add_argument("--query", "-q", help="Query to test (requires ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    # Always run import tests
    if not test_imports():
        return 1

    # Run query test if requested
    if args.query:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("\n⚠️  ANTHROPIC_API_KEY not set in .env - skipping query test")
            return 0
        if not asyncio.run(test_query(args.query)):
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
