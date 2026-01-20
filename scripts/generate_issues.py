#!/usr/bin/env python3
"""Generate issues.json with 300 GitHub issues for Klabautermann."""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Issue:
    id: str
    title: str
    body: str
    labels: list[str]
    category: str
    priority: str
    complexity: str
    ai_first: bool = False
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "title": f"[{self.id}] {self.title}",
            "body": self.body,
            "labels": self.labels,
            "category": self.category,
            "priority": self.priority,
            "complexity": self.complexity,
            "ai_first": self.ai_first,
            "dependencies": self.dependencies,
        }


def make_body(
    summary: str,
    spec_ref: str,
    criteria: list[str],
    ai_first: bool = False,
    deps: list[str] | None = None,
) -> str:
    body = f"""## Summary

{summary}

## Spec Reference

`{spec_ref}`

## Acceptance Criteria

"""
    for c in criteria:
        body += f"- [ ] {c}\n"

    if ai_first:
        body += """
## AI-First Requirement

**This feature MUST use pure LLM intelligence.**
- No keyword matching
- No regex patterns
- Use Claude tool_use or semantic understanding
"""

    if deps:
        body += "\n## Dependencies\n\n"
        for d in deps:
            body += f"- Blocked by #{d}\n"

    body += "\n---\n*Generated from gap analysis*"
    return body


issues = []

# =============================================================================
# AGT-P: Primary Agents (25 issues)
# =============================================================================

# Orchestrator - 8 issues
issues.append(
    Issue(
        id="AGT-P-001",
        title="Remove keyword-based intent classification - use pure LLM",
        body=make_body(
            "The Orchestrator currently uses keyword lists (search_keywords, action_keywords) in config for intent classification. This must be replaced with pure LLM tool_use classification.",
            "specs/MAINAGENT.md Section 2.1",
            [
                "Remove intent_classification.search_keywords from config",
                "Remove intent_classification.action_keywords from config",
                "Implement Claude tool_use based classification",
                "Intent detection uses semantic understanding",
                "Tests verify LLM-based classification",
            ],
            ai_first=True,
        ),
        labels=["area/agents", "type/refactor", "priority/P0-critical", "complexity/L", "ai-first"],
        category="AGT-P",
        priority="P0",
        complexity="L",
        ai_first=True,
    )
)

issues.append(
    Issue(
        id="AGT-P-002",
        title="Implement true multi-model orchestration",
        body=make_body(
            "Orchestrator should dynamically select models based on task complexity. Currently uses single Sonnet model for everything.",
            "specs/MAINAGENT.md Section 5.1",
            [
                "Implement model selection logic",
                "Use Haiku for simple tasks (search, classification)",
                "Use Sonnet for complex reasoning",
                "Add model usage metrics",
                "Config allows model overrides per agent",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-003",
        title="Add proactive morning briefing generation",
        body=make_body(
            "Orchestrator should generate proactive morning briefings summarizing schedule, tasks, and alerts.",
            "specs/PRD.md Section 7.3",
            [
                "Implement morning briefing generation",
                "Include today's calendar events",
                "Include high-priority tasks",
                "Include any overnight alerts",
                "Trigger at configurable time (default 7:00)",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-004",
        title="Implement Storm Mode detection and response",
        body=make_body(
            "When high task density is detected, switch to terse, action-focused responses.",
            "specs/PRD.md Section 8.4",
            [
                "Detect high task density (>5 urgent tasks)",
                "Switch response style to terse mode",
                "Reduce tidbit probability to 0",
                "Add storm_mode flag to context",
                "Revert to normal mode when density drops",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P2-medium", "complexity/M"],
        category="AGT-P",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-005",
        title="Add conversation memory compression",
        body=make_body(
            "Implement memory compression for long conversations to stay within context limits.",
            "specs/MEMORY.md",
            [
                "Detect when context window approaches limit",
                "Compress older messages into summary",
                "Preserve key facts and entities",
                "Maintain conversation coherence",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P2-medium", "complexity/L"],
        category="AGT-P",
        priority="P2",
        complexity="L",
    )
)

issues.append(
    Issue(
        id="AGT-P-006",
        title="Implement task deduplication across channels",
        body=make_body(
            "Detect and deduplicate tasks mentioned across different channels.",
            "specs/CHANNELS.md Section 4",
            [
                "Track tasks by content hash",
                "Detect similar tasks across threads",
                "Merge duplicate tasks",
                "Preserve original channel references",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P2-medium", "complexity/M"],
        category="AGT-P",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-007",
        title="Add user preference learning",
        body=make_body(
            "Learn user preferences from interactions and apply them to responses.",
            "specs/ONTOLOGY.md Section 1.2 (Preference)",
            [
                "Track user preference signals",
                "Store preferences in Preference nodes",
                "Apply preferences to response generation",
                "Support preference override commands",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P3-low", "complexity/L"],
        category="AGT-P",
        priority="P3",
        complexity="L",
    )
)

issues.append(
    Issue(
        id="AGT-P-008",
        title="Implement response streaming",
        body=make_body(
            "Stream responses to channels instead of waiting for complete generation.",
            "specs/CHANNELS.md",
            [
                "Implement streaming in Orchestrator",
                "Update CLI driver for streaming",
                "Update API server for WebSocket streaming",
                "Handle streaming errors gracefully",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P3-low", "complexity/M"],
        category="AGT-P",
        priority="P3",
        complexity="M",
    )
)

# Ingestor - 4 issues
issues.append(
    Issue(
        id="AGT-P-009",
        title="Add LLM-based entity pre-extraction",
        body=make_body(
            "Ingestor should use Haiku for pre-extraction before Graphiti, validating entities against ontology.",
            "specs/AGENTS.md Section 2.1",
            [
                "Implement Haiku-based extraction",
                "Extract entities before Graphiti call",
                "Validate against ontology schema",
                "Pass validated entities to Graphiti",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-010",
        title="Implement custom ontology validation",
        body=make_body(
            "Validate extracted entities against the Klabautermann ontology before ingestion.",
            "specs/ONTOLOGY.md Section 7",
            [
                "Load ontology schema from spec",
                "Validate entity types",
                "Validate relationship types",
                "Validate property constraints",
                "Log validation failures",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-011",
        title="Add confidence scoring to extracted entities",
        body=make_body(
            "Assign confidence scores to extracted entities for quality filtering.",
            "specs/AGENTS.md",
            [
                "Calculate confidence score per entity",
                "Store confidence on relationship properties",
                "Filter low-confidence extractions",
                "Flag uncertain entities for user validation",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P2-medium", "complexity/S"],
        category="AGT-P",
        priority="P2",
        complexity="S",
    )
)

issues.append(
    Issue(
        id="AGT-P-012",
        title="Support batch episode ingestion",
        body=make_body(
            "Enable ingestion of multiple episodes in a single batch call.",
            "specs/MEMORY.md",
            [
                "Implement batch_add_episodes method",
                "Process episodes in parallel where possible",
                "Maintain transaction consistency",
                "Return batch results summary",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P3-low", "complexity/S"],
        category="AGT-P",
        priority="P3",
        complexity="S",
    )
)

# Researcher - 7 issues
issues.append(
    Issue(
        id="AGT-P-013",
        title="Add structural traversal queries (REPORTS_TO chains)",
        body=make_body(
            "Implement Cypher queries for structural graph traversal like reporting chains.",
            "specs/RESEARCHER.md Section 2.4",
            [
                "Implement REPORTS_TO chain traversal",
                "Support configurable depth limits",
                "Return structured hierarchy results",
                "Add tests for traversal queries",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-014",
        title="Implement time-filtered temporal queries",
        body=make_body(
            "Support temporal queries like 'Who did X work for last year?'",
            "specs/RESEARCHER.md Section 2.5",
            [
                "Parse temporal expressions from queries",
                "Filter relationships by created_at/expired_at",
                "Support relative time expressions",
                "Return historical data correctly",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-015",
        title="Add Island search (Knowledge Island exploration)",
        body=make_body(
            "Enable searching within specific Knowledge Islands (communities).",
            "specs/RESEARCHER.md Section 2.6",
            [
                "Implement island-scoped search",
                "Support island name in search params",
                "Combine with vector search",
                "Return island context in results",
            ],
            deps=["AGT-S-033"],  # Requires Cartographer
        ),
        labels=["area/agents", "type/feature", "priority/P2-medium", "complexity/M"],
        category="AGT-P",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-016",
        title="Implement zoom level mechanics for retrieval",
        body=make_body(
            "Support macro/meso/micro zoom levels for multi-level retrieval.",
            "specs/AGENTS_EXTENDED.md Section 4.4",
            [
                "Implement macro level (Community search)",
                "Implement meso level (Project/Note search)",
                "Implement micro level (Entity search)",
                "Auto-detect appropriate zoom level",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P2-medium", "complexity/M"],
        category="AGT-P",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-017",
        title="Add semantic ranking improvements",
        body=make_body(
            "Improve semantic ranking of search results using reranking.",
            "specs/RESEARCHER.md",
            [
                "Implement result reranking",
                "Use cross-encoder for fine-grained ranking",
                "Weight graph relationships in ranking",
                "Add diversity to top results",
            ],
        ),
        labels=["area/agents", "type/enhancement", "priority/P2-medium", "complexity/M"],
        category="AGT-P",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-018",
        title="LLM query intent understanding (no pattern matching)",
        body=make_body(
            "Query intent detection must use pure LLM understanding, not keyword patterns.",
            "specs/AGENTS_EXTENDED.md Section 4.4",
            [
                "Remove keyword-based zoom detection",
                "Use LLM to understand query intent",
                "Determine search scope semantically",
                "Tests verify no pattern matching",
            ],
            ai_first=True,
        ),
        labels=["area/agents", "type/refactor", "priority/P0-critical", "complexity/M", "ai-first"],
        category="AGT-P",
        priority="P0",
        complexity="M",
        ai_first=True,
    )
)

issues.append(
    Issue(
        id="AGT-P-019",
        title="Add cross-thread context retrieval",
        body=make_body(
            "Enable retrieval of context from related threads.",
            "specs/MEMORY.md",
            [
                "Detect related threads by entity overlap",
                "Retrieve relevant context from other threads",
                "Maintain thread isolation for direct context",
                "Add cross-thread links to results",
            ],
        ),
        labels=["area/agents", "type/feature", "priority/P3-low", "complexity/L"],
        category="AGT-P",
        priority="P3",
        complexity="L",
    )
)

# Executor - 4 issues
issues.append(
    Issue(
        id="AGT-P-020",
        title="Implement email reply-to-thread functionality",
        body=make_body(
            "Enable replying to email threads instead of only creating new emails.",
            "specs/MCP.md",
            [
                "Implement reply_to_email method",
                "Maintain thread references (In-Reply-To)",
                "Support quoted replies",
                "Tests verify threading works",
            ],
        ),
        labels=["area/agents", "area/mcp", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-021",
        title="Add calendar event update and delete",
        body=make_body(
            "Support updating and deleting calendar events.",
            "specs/MCP.md",
            [
                "Implement update_event method",
                "Implement delete_event method",
                "Support partial updates",
                "Handle conflict on update",
            ],
        ),
        labels=["area/agents", "area/mcp", "type/feature", "priority/P1-high", "complexity/M"],
        category="AGT-P",
        priority="P1",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="AGT-P-022",
        title="Implement recurring events support",
        body=make_body(
            "Support creation and management of recurring calendar events.",
            "specs/MCP.md",
            [
                "Parse recurrence patterns from natural language",
                "Create recurring events via API",
                "Support daily, weekly, monthly patterns",
                "Handle recurrence exceptions",
            ],
        ),
        labels=["area/agents", "area/mcp", "type/feature", "priority/P2-medium", "complexity/L"],
        category="AGT-P",
        priority="P2",
        complexity="L",
    )
)

issues.append(
    Issue(
        id="AGT-P-023",
        title="Add attendee management for calendar events",
        body=make_body(
            "Support adding, removing, and managing event attendees.",
            "specs/MCP.md",
            [
                "Implement add_attendees method",
                "Implement remove_attendees method",
                "Send invitations via Calendar API",
                "Track attendee responses",
            ],
        ),
        labels=["area/agents", "area/mcp", "type/feature", "priority/P2-medium", "complexity/M"],
        category="AGT-P",
        priority="P2",
        complexity="M",
    )
)

# Archivist and Scribe - 2 issues
issues.append(
    Issue(
        id="AGT-P-024",
        title="Wire deduplication module to Archivist",
        body=make_body(
            "The deduplication module exists but is not integrated into the Archivist workflow.",
            "specs/AGENTS.md Section 3.4",
            [
                "Import deduplication module in Archivist",
                "Call dedup during archival",
                "Flag potential duplicates",
                "Suggest merges to user",
            ],
        ),
        labels=["area/agents", "area/memory", "type/feature", "priority/P1-high", "complexity/S"],
        category="AGT-P",
        priority="P1",
        complexity="S",
    )
)

issues.append(
    Issue(
        id="AGT-P-025",
        title="Add dynamic personality voice to Scribe",
        body=make_body(
            "Scribe currently uses a template for journal entries. Should generate dynamic personality.",
            "specs/AGENTS.md Section 3.5",
            [
                "Use LLM for journal voice generation",
                "Apply Klabautermann personality",
                "Vary tone based on day's events",
                "Include appropriate nautical metaphors",
            ],
        ),
        labels=["area/agents", "type/enhancement", "priority/P2-medium", "complexity/S"],
        category="AGT-P",
        priority="P2",
        complexity="S",
    )
)

# =============================================================================
# AGT-S: Secondary Agents (60 issues)
# =============================================================================

# Bard of the Bilge (12)
for i, (title, desc, criteria) in enumerate(
    [
        (
            "Create BardOfTheBilge agent skeleton",
            "Create the basic agent class and register with system.",
            [
                "Create agents/bard.py",
                "Extend BaseAgent",
                "Register in main.py",
                "Add config/agents/bard.yaml",
            ],
        ),
        (
            "Implement LoreEpisode node model",
            "Define the LoreEpisode Pydantic model and Neo4j schema.",
            [
                "Add LoreEpisode to core/models.py",
                "Add LORE_EPISODE to NodeLabel enum",
                "Create constraint and index",
            ],
        ),
        (
            "Implement TOLD_TO relationship",
            "Link LoreEpisodes to the Captain (Person).",
            [
                "Add TOLD_TO to RelationType enum",
                "Create relationship in Bard queries",
                "Test relationship creation",
            ],
        ),
        (
            "Implement EXPANDS_UPON relationship",
            "Chain saga chapters together.",
            ["Add EXPANDS_UPON to RelationType", "Link consecutive chapters", "Query saga chains"],
        ),
        (
            "Create SagaManager class",
            "Manage saga lifecycle (start, continue, complete, archive).",
            [
                "Implement get_active_sagas",
                "Implement continue_saga",
                "Implement start_new_saga",
                "Implement archive_saga",
            ],
        ),
        (
            "Add CANONICAL_SAGAS seed data",
            "Include the canonical story database from spec.",
            [
                "Add great-maelstrom saga",
                "Add kraken-scroll saga",
                "Add sirens-inbox saga",
                "Add 2+ more sagas",
            ],
        ),
        (
            "Add STANDALONE_TIDBITS collection",
            "Include standalone tidbits for random selection.",
            ["Add 12+ standalone tidbits", "Match spec examples", "Ensure nautical voice"],
        ),
        (
            "Implement tidbit selection logic",
            "Select between saga continuation, new saga, or standalone.",
            ["30% chance continue saga", "20% chance start saga", "50% standalone tidbit"],
        ),
        (
            "Integrate Bard with Orchestrator",
            "Call Bard.salt_response from Orchestrator.",
            [
                "Add salt_response call in response flow",
                "Pass storm_mode flag",
                "Respect tidbit_probability config",
            ],
        ),
        (
            "Add cross-channel saga persistence",
            "Stories follow Captain across CLI/Telegram.",
            [
                "Query by captain_uuid not thread_id",
                "Track channel in LoreEpisode",
                "Test cross-channel continuity",
            ],
        ),
        (
            "Implement saga timeout handling",
            "Auto-complete sagas after 30 days.",
            ["Detect timed-out sagas", "Generate conclusion chapter", "Archive completed sagas"],
        ),
        (
            "Add Bard unit tests",
            "Test saga management and tidbit selection.",
            [
                "Test saga creation",
                "Test saga continuation",
                "Test cross-channel persistence",
                "Test selection logic",
            ],
        ),
    ],
    start=1,
):
    issues.append(
        Issue(
            id=f"AGT-S-{i:03d}",
            title=title,
            body=make_body(desc, "specs/architecture/AGENTS_EXTENDED.md Section 1", criteria),
            labels=[
                "area/agents",
                "area/lore",
                "type/feature",
                f"priority/P{'1-high' if i <= 4 else '2-medium'}",
                "complexity/M",
            ],
            category="AGT-S",
            priority="P1" if i <= 4 else "P2",
            complexity="M",
        )
    )

# Purser - 10 issues
for i, (title, desc, criteria) in enumerate(
    [
        (
            "Create Purser agent skeleton",
            "Create the Purser class for state synchronization.",
            [
                "Create agents/purser.py",
                "Extend BaseAgent",
                "Register in main.py",
                "Add config/agents/purser.yaml",
            ],
        ),
        (
            "Implement Gmail delta-sync",
            "Sync new emails since last sync timestamp.",
            [
                "Track last_sync timestamp",
                "Fetch emails after last_sync",
                "Update sync timestamp on completion",
            ],
        ),
        (
            "Implement Calendar delta-sync",
            "Sync calendar events since last sync.",
            ["Track calendar last_sync", "Fetch events in range", "Detect updated/deleted events"],
        ),
        (
            "Create TheSieve email filter class",
            "Filter emails for noise and injection attacks.",
            [
                "Implement noise pattern detection",
                "Implement injection pattern detection",
                "Return EmailManifest with is_manifest_worthy",
            ],
        ),
        (
            "Implement VIP whitelist",
            "Allow certain senders to bypass TheSieve.",
            [
                "Load VIP list from config",
                "Check sender against whitelist",
                "Skip filtering for VIPs",
            ],
        ),
        (
            "Add external_id duplicate tracking",
            "Prevent re-ingesting already synced items.",
            [
                "Store external_id in Resource nodes",
                "Check before ingestion",
                "Handle updates vs creates",
            ],
        ),
        (
            "Implement scheduled sync job",
            "Run sync every 15 minutes via scheduler.",
            [
                "Register Purser with scheduler",
                "Add sync_interval config",
                "Handle sync failures gracefully",
            ],
        ),
        (
            "Add expired event detection",
            "Mark deleted external events as expired.",
            [
                "Detect events deleted externally",
                "Set expired_at on Event nodes",
                "Log expired events",
            ],
        ),
        (
            "Implement sync health monitoring",
            "Track sync success/failure metrics.",
            ["Count successful syncs", "Count failed syncs", "Expose metrics endpoint"],
        ),
        (
            "Add Purser unit tests",
            "Test sync and filtering logic.",
            ["Test delta-sync", "Test TheSieve filtering", "Test duplicate detection"],
        ),
    ],
    start=13,
):
    issues.append(
        Issue(
            id=f"AGT-S-{i:03d}",
            title=title,
            body=make_body(desc, "specs/architecture/AGENTS_EXTENDED.md Section 2", criteria),
            labels=[
                "area/agents",
                "area/mcp",
                "type/feature",
                f"priority/P{'1-high' if i <= 16 else '2-medium'}",
                "complexity/M",
            ],
            category="AGT-S",
            priority="P1" if i <= 16 else "P2",
            complexity="M",
        )
    )

# First Officer (10)
for i, (title, desc, criteria) in enumerate(
    [
        (
            "Create OfficerOfTheWatch agent skeleton",
            "Create the proactive alert agent.",
            ["Create agents/officer.py", "Extend BaseAgent", "Register in main.py"],
        ),
        (
            "Implement deadline warning alerts",
            "Alert when tasks are due within 24 hours.",
            [
                "Query tasks with approaching due_date",
                "Generate WARNING alerts",
                "Respect quiet mode",
            ],
        ),
        (
            "Implement meeting reminder alerts",
            "Alert 15 minutes before meetings.",
            ["Query upcoming events", "Generate INFO alerts", "Include event details"],
        ),
        (
            "Implement schedule conflict detection",
            "Detect overlapping calendar events.",
            ["Query for time overlaps", "Generate WARNING alerts", "Suggest resolution"],
        ),
        (
            "Implement overdue task alerts",
            "Alert when tasks are past due.",
            ["Query overdue tasks", "Generate ERROR alerts", "Prioritize by task priority"],
        ),
        (
            "Add morning briefing generation",
            "Generate daily morning summary.",
            ["Aggregate today's schedule", "Include urgent tasks", "Apply personality voice"],
        ),
        (
            "Implement Deep Work / Quiet Watch mode",
            "Suppress non-critical alerts during focus time.",
            [
                "Detect focus calendar blocks",
                "Set quiet_mode flag",
                "Only allow CRITICAL alerts through",
            ],
        ),
        (
            "Add alert debouncing",
            "Don't re-send same alert within time window.",
            ["Track sent alerts", "Check last_sent timestamp", "Configurable debounce window"],
        ),
        (
            "Integrate with Channel Manager",
            "Send alerts to all active channels.",
            [
                "Get active channels from manager",
                "Format alerts per channel",
                "Handle send failures",
            ],
        ),
        (
            "Add Officer unit tests",
            "Test alert generation and filtering.",
            ["Test deadline alerts", "Test quiet mode", "Test debouncing"],
        ),
    ],
    start=23,
):
    issues.append(
        Issue(
            id=f"AGT-S-{i:03d}",
            title=title,
            body=make_body(desc, "specs/architecture/AGENTS_EXTENDED.md Section 3", criteria),
            labels=[
                "area/agents",
                "type/feature",
                f"priority/P{'1-high' if i <= 26 else '2-medium'}",
                "complexity/M",
            ],
            category="AGT-S",
            priority="P1" if i <= 26 else "P2",
            complexity="M",
        )
    )

# Cartographer - 10 issues
for i, (title, desc, criteria) in enumerate(
    [
        (
            "Create Cartographer agent skeleton",
            "Create community detection agent.",
            ["Create agents/cartographer.py", "Extend BaseAgent", "Register in main.py"],
        ),
        (
            "Implement graph projection for GDS",
            "Create in-memory graph for algorithms.",
            [
                "Call gds.graph.project",
                "Include relevant node types",
                "Include relevant relationship types",
            ],
        ),
        (
            "Implement Louvain community detection",
            "Run Louvain algorithm on projected graph.",
            ["Call gds.louvain.stream", "Collect community memberships", "Filter by minimum size"],
        ),
        (
            "Create Community node model",
            "Define Community/KnowledgeIsland node.",
            ["Add Community to models.py", "Add to NodeLabel enum", "Create constraint and index"],
        ),
        (
            "Implement PART_OF_ISLAND relationship",
            "Link nodes to their communities.",
            [
                "Add PART_OF_ISLAND to RelationType",
                "Store membership weight",
                "Store detected_at timestamp",
            ],
        ),
        (
            "Add theme classification",
            "Classify communities by theme (work, family, etc.).",
            ["Analyze member node types", "Assign theme label", "Support multiple themes"],
        ),
        (
            "Implement community summary generation",
            "Generate AI summaries for islands.",
            ["Gather community members", "Generate summary with LLM", "Store in Community.summary"],
        ),
        (
            "Add scheduled community detection",
            "Run weekly via scheduler.",
            ["Register with scheduler", "Run Sunday midnight", "Handle algorithm failures"],
        ),
        (
            "Implement island search support",
            "Enable Researcher to search within islands.",
            [
                "Add island_uuid parameter to search",
                "Filter results by community",
                "Return island context",
            ],
        ),
        (
            "Add Cartographer unit tests",
            "Test community detection.",
            ["Test graph projection", "Test community creation", "Test summary generation"],
        ),
    ],
    start=33,
):
    issues.append(
        Issue(
            id=f"AGT-S-{i:03d}",
            title=title,
            body=make_body(desc, "specs/architecture/AGENTS_EXTENDED.md Section 4", criteria),
            labels=[
                "area/agents",
                "area/memory",
                "type/feature",
                "priority/P2-medium",
                "complexity/L",
            ],
            category="AGT-S",
            priority="P2",
            complexity="L",
        )
    )

# Hull Cleaner (10)
for i, (title, desc, criteria) in enumerate(
    [
        (
            "Create HullCleaner agent skeleton",
            "Create graph maintenance agent.",
            ["Create agents/hull_cleaner.py", "Extend BaseAgent", "Register in main.py"],
        ),
        (
            "Implement weak relationship detection",
            "Find relationships with low weight and old age.",
            [
                "Query relationships with weight < 0.2",
                "Filter by age > 90 days",
                "Return pruning candidates",
            ],
        ),
        (
            "Implement relationship pruning",
            "Delete weak relationships.",
            ["Support dry-run mode", "Log all deletions", "Create audit entries"],
        ),
        (
            "Implement orphan message detection",
            "Find messages not in any thread.",
            ["Query unlinked Message nodes", "Return orphan list"],
        ),
        (
            "Implement orphan removal",
            "Delete orphan nodes.",
            ["Support dry-run mode", "Log deletions", "Create audit entries"],
        ),
        (
            "Implement duplicate entity detection",
            "Find potential duplicate Person/Org nodes.",
            ["Use Levenshtein similarity", "Threshold > 0.85 similarity", "Return duplicate pairs"],
        ),
        (
            "Implement entity merge",
            "Merge duplicate entities using APOC.",
            ["Use apoc.refactor.mergeNodes", "Preserve all relationships", "Log merge operations"],
        ),
        (
            "Implement transitive redundancy detection",
            "Find redundant transitive paths.",
            [
                "Detect A->B->C with direct A->C",
                "Evaluate for pruning",
                "Consider relationship weights",
            ],
        ),
        (
            "Add pruning audit log",
            "Persist audit trail of all pruning.",
            ["Create AuditEntry model", "Store in AuditLog nodes", "Support audit queries"],
        ),
        (
            "Add HullCleaner unit tests",
            "Test pruning logic.",
            ["Test weak rel detection", "Test duplicate detection", "Test merge operations"],
        ),
    ],
    start=43,
):
    issues.append(
        Issue(
            id=f"AGT-S-{i:03d}",
            title=title,
            body=make_body(desc, "specs/architecture/AGENTS_EXTENDED.md Section 5", criteria),
            labels=[
                "area/agents",
                "area/memory",
                "type/feature",
                "priority/P2-medium",
                "complexity/M",
            ],
            category="AGT-S",
            priority="P2",
            complexity="M",
        )
    )

# Quartermaster - 8 issues
for i, (title, desc, criteria) in enumerate(
    [
        (
            "Implement A/B testing for prompts",
            "Support prompt variants with selection logic.",
            [
                "Add prompt_variants to AgentConfig",
                "Implement variant selection",
                "Track variant usage",
            ],
        ),
        (
            "Add model switching capability",
            "Allow runtime model changes.",
            [
                "Support model override per request",
                "Validate model availability",
                "Track model usage",
            ],
        ),
        (
            "Implement prompt performance tracking",
            "Track metrics per prompt variant.",
            ["Measure response quality", "Track latency per variant", "Store metrics in graph"],
        ),
        (
            "Add config validation webhook",
            "Notify on config changes.",
            ["Call observers on change", "Validate new config", "Rollback on validation failure"],
        ),
        (
            "Implement feature flags",
            "Support feature flag configuration.",
            ["Add feature_flags to config", "Check flags at runtime", "Support gradual rollout"],
        ),
        (
            "Add experiment reporting",
            "Generate A/B test reports.",
            ["Aggregate variant metrics", "Calculate statistical significance", "Export reports"],
        ),
        (
            "Implement config rollback",
            "Revert to previous config version.",
            ["Track config versions", "Implement rollback command", "Validate before apply"],
        ),
        (
            "Add Quartermaster tests",
            "Test config management.",
            ["Test hot reload", "Test variant selection", "Test validation"],
        ),
    ],
    start=53,
):
    issues.append(
        Issue(
            id=f"AGT-S-{i:03d}",
            title=title,
            body=make_body(desc, "specs/architecture/AGENTS_EXTENDED.md Section 6", criteria),
            labels=["area/agents", "area/infra", "type/feature", "priority/P3-low", "complexity/M"],
            category="AGT-S",
            priority="P3",
            complexity="M",
        )
    )

# =============================================================================
# LORE: Lore System (30 issues)
# =============================================================================

lore_issues = [
    (
        "LORE-001",
        "Add LoreEpisode node type to ontology",
        "Add the LoreEpisode node definition.",
        "specs/architecture/LORE_SYSTEM.md Section 2.1",
        [
            "Add LoreEpisode to NodeLabel enum",
            "Add LoreEpisodeNode Pydantic model",
            "Create uuid constraint",
            "Create saga_id index",
        ],
    ),
    (
        "LORE-002",
        "Implement TOLD_TO relationship",
        "Link stories to the Captain.",
        "specs/architecture/LORE_SYSTEM.md Section 2.2",
        ["Add TOLD_TO to RelationType", "Create relationship in Bard", "Query stories by Captain"],
    ),
    (
        "LORE-003",
        "Implement EXPANDS_UPON relationship",
        "Chain saga chapters.",
        "specs/architecture/LORE_SYSTEM.md Section 2.2",
        [
            "Add EXPANDS_UPON to RelationType",
            "Link consecutive chapters",
            "Support saga chain queries",
        ],
    ),
    (
        "LORE-004",
        "Implement SAGA_STARTED_BY relationship",
        "Track saga initiators.",
        "specs/architecture/LORE_SYSTEM.md Section 2.2",
        [
            "Add SAGA_STARTED_BY to RelationType",
            "Link first chapter to Captain",
            "Query saga origins",
        ],
    ),
    (
        "LORE-005",
        "Create SagaManager class",
        "Manage saga lifecycle.",
        "specs/architecture/LORE_SYSTEM.md Section 3.3",
        [
            "get_active_sagas method",
            "continue_saga method",
            "start_new_saga method",
            "archive_saga method",
        ],
    ),
    (
        "LORE-006",
        "Add The Great Maelstrom saga",
        "Include canonical saga from spec.",
        "specs/architecture/LORE_SYSTEM.md Section 4.1",
        ["Add all 5 chapters", "Match spec content exactly", "Set theme: origin"],
    ),
    (
        "LORE-007",
        "Add The Kraken of Infinite Scroll saga",
        "Include canonical saga.",
        "specs/architecture/LORE_SYSTEM.md Section 4.1",
        ["Add all 5 chapters", "Match spec content", "Set theme: battle"],
    ),
    (
        "LORE-008",
        "Add The Sirens of the Inbox saga",
        "Include canonical saga.",
        "specs/architecture/LORE_SYSTEM.md Section 4.1",
        ["Add all 5 chapters", "Set theme: warning"],
    ),
    (
        "LORE-009",
        "Add The Ghost Ship saga",
        "Include canonical saga.",
        "specs/architecture/LORE_SYSTEM.md Section 4.1",
        ["Add all 5 chapters", "Set theme: melancholy"],
    ),
    (
        "LORE-010",
        "Add The Lighthouse of Passwords saga",
        "Include canonical saga.",
        "specs/architecture/LORE_SYSTEM.md Section 4.1",
        ["Add all 5 chapters", "Set theme: humor"],
    ),
    (
        "LORE-011",
        "Add standalone tidbits collection",
        "Include standalone tidbits.",
        "specs/architecture/LORE_SYSTEM.md Section 4.1",
        ["Add 12+ tidbits from spec", "Ensure nautical voice", "No pirate cliches"],
    ),
    (
        "LORE-012",
        "Implement tidbit selection algorithm",
        "Select tidbits based on probability.",
        "specs/architecture/LORE_SYSTEM.md Section 4.2",
        ["30% continue saga", "20% start saga", "50% standalone", "Respect storm mode"],
    ),
    (
        "LORE-013",
        "Integrate salt_response with Orchestrator",
        "Call Bard from response flow.",
        "specs/architecture/LORE_SYSTEM.md Section 5.1",
        ["Add salt_response call", "Pass storm_mode", "Pass captain_uuid"],
    ),
    (
        "LORE-014",
        "Add saga progress to daily reflection",
        "Include lore in Scribe output.",
        "specs/architecture/LORE_SYSTEM.md Section 5.2",
        ["Query today's lore episodes", "Format saga progress", "Include in journal"],
    ),
    (
        "LORE-015",
        "Implement Captain-context storage",
        "Stories follow Captain, not thread.",
        "specs/architecture/LORE_SYSTEM.md Section 1.2",
        ["Query by captain_uuid", "Not by thread_uuid", "Cross-channel persistence"],
    ),
    (
        "LORE-016",
        "Add get recent lore query",
        "Retrieve recent story episodes.",
        "specs/architecture/LORE_SYSTEM.md Section 6.1",
        ["Cypher query for recent lore", "Limit to N episodes", "Order by told_at DESC"],
    ),
    (
        "LORE-017",
        "Add get saga chain query",
        "Retrieve all chapters of a saga.",
        "specs/architecture/LORE_SYSTEM.md Section 6.2",
        ["Cypher query for saga chain", "Order by chapter ASC", "Include all metadata"],
    ),
    (
        "LORE-018",
        "Add cross-channel story query",
        "Show story travel across channels.",
        "specs/architecture/LORE_SYSTEM.md Section 6.3",
        ["Query saga with channel info", "Show channel per chapter"],
    ),
    (
        "LORE-019",
        "Add saga statistics query",
        "Count sagas and chapters.",
        "specs/architecture/LORE_SYSTEM.md Section 6.4",
        ["Count total sagas", "Count total chapters", "Group by Captain"],
    ),
    (
        "LORE-020",
        "Create bard.yaml config file",
        "Add Bard configuration.",
        "specs/architecture/LORE_SYSTEM.md Section 7.1",
        ["Set model to haiku", "Set tidbit_probability", "Set saga_rules"],
    ),
    (
        "LORE-021",
        "Add personality.lore config",
        "Configure lore in personality.",
        "specs/architecture/LORE_SYSTEM.md Section 7.2",
        ["enabled flag", "tidbit_frequency", "display_format"],
    ),
    (
        "LORE-022",
        "Implement max chapters per saga",
        "Enforce 5 chapter limit.",
        "specs/architecture/LORE_SYSTEM.md Section 3.2",
        ["Check chapter count", "Raise SagaCompleteError", "Auto-archive at max"],
    ),
    (
        "LORE-023",
        "Implement max active sagas",
        "Enforce 3 active saga limit.",
        "specs/architecture/LORE_SYSTEM.md Section 3.2",
        ["Check active count", "Archive oldest if over", "Log archival"],
    ),
    (
        "LORE-024",
        "Implement saga timeout",
        "Auto-complete after 30 days.",
        "specs/architecture/LORE_SYSTEM.md Section 3.2",
        ["Check last_told timestamp", "Generate conclusion", "Archive timed-out sagas"],
    ),
    (
        "LORE-025",
        "Implement min time between chapters",
        "Enforce 1 hour minimum.",
        "specs/architecture/LORE_SYSTEM.md Section 3.2",
        ["Check last chapter time", "Skip if too recent", "Log skip reason"],
    ),
    (
        "LORE-026",
        "Add test_saga_continuation",
        "Unit test for saga continuation.",
        "specs/architecture/LORE_SYSTEM.md Section 8.1",
        ["Start saga", "Continue chapter", "Verify chain"],
    ),
    (
        "LORE-027",
        "Add test_cross_channel_persistence",
        "Test stories across channels.",
        "specs/architecture/LORE_SYSTEM.md Section 8.1",
        ["Tell on CLI", "Continue on Telegram", "Verify same saga"],
    ),
    (
        "LORE-028",
        "Add E2E cross-conversation saga test",
        "Golden scenario for lore.",
        "specs/architecture/LORE_SYSTEM.md Section 8.2",
        ["CLI: start saga", "Telegram: continue", "CLI: retrieve and continue"],
    ),
    (
        "LORE-029",
        "Add saga summary generation",
        "Generate summary when archiving.",
        "specs/architecture/LORE_SYSTEM.md Section 3.3",
        ["Gather all chapters", "Generate summary with LLM", "Store in Note node"],
    ),
    (
        "LORE-030",
        "Add SUMMARIZES relationship for lore",
        "Link Note to archived episodes.",
        "specs/architecture/LORE_SYSTEM.md Section 3.3",
        ["Create Note on archive", "Link to all episodes", "Mark episodes archived"],
    ),
]

for id, title, desc, spec, criteria in lore_issues:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, spec, criteria),
            labels=["area/lore", "type/feature", "priority/P2-medium", "complexity/M"],
            category="LORE",
            priority="P2",
            complexity="M",
        )
    )

# =============================================================================
# CHAN: Channels (35 issues)
# =============================================================================

# CLI gaps (2)
issues.append(
    Issue(
        id="CHAN-001",
        title="Implement /status command in CLI",
        body=make_body(
            "Add /status command to show system status.",
            "specs/architecture/CHANNELS.md Section 2.2",
            [
                "Show session ID",
                "Show active thread count",
                "Show agent status",
                "Show connection status",
            ],
        ),
        labels=["area/channels", "type/feature", "priority/P1-high", "complexity/XS"],
        category="CHAN",
        priority="P1",
        complexity="XS",
    )
)

issues.append(
    Issue(
        id="CHAN-002",
        title="Fix /clear to reset session context",
        body=make_body(
            "Currently /clear only clears screen. Should also reset orchestrator context.",
            "specs/architecture/CHANNELS.md Section 2.2",
            [
                "Clear screen",
                "Create new session ID",
                "Reset thread context",
                "Notify user of reset",
            ],
        ),
        labels=["area/channels", "type/bug", "priority/P2-medium", "complexity/XS"],
        category="CHAN",
        priority="P2",
        complexity="XS",
    )
)

# Telegram - 15 issues
telegram_issues = [
    (
        "CHAN-003",
        "Create TelegramDriver class skeleton",
        "Base implementation extending BaseChannel.",
        ["Create telegram_driver.py", "Extend BaseChannel", "Implement abstract methods"],
    ),
    (
        "CHAN-004",
        "Add Telegram bot token configuration",
        "Support token from env and config.",
        ["Load TELEGRAM_BOT_TOKEN", "Validate token on start", "Log connection status"],
    ),
    (
        "CHAN-005",
        "Implement /start command",
        "Welcome message for Telegram.",
        ["Register CommandHandler", "Send welcome message", "Include help instructions"],
    ),
    (
        "CHAN-006",
        "Implement /help command",
        "Help message for Telegram.",
        ["Register CommandHandler", "List available commands", "Explain capabilities"],
    ),
    (
        "CHAN-007",
        "Implement /status command",
        "System status for Telegram.",
        ["Show chat ID", "Show user ID", "Show connection status"],
    ),
    (
        "CHAN-008",
        "Implement text message handling",
        "Process incoming text messages.",
        ["Register MessageHandler", "Convert to StandardizedMessage", "Route to Orchestrator"],
    ),
    (
        "CHAN-009",
        "Implement voice message handling",
        "Process voice messages.",
        ["Detect voice messages", "Download voice file", "Send to transcription"],
    ),
    (
        "CHAN-010",
        "Integrate Whisper transcription",
        "Transcribe voice to text.",
        ["Call OpenAI Whisper API", "Handle transcription errors", "Update message content"],
    ),
    (
        "CHAN-011",
        "Implement user whitelist",
        "Restrict bot to allowed users.",
        ["Load allowed_user_ids", "Check on message receive", "Reject unauthorized users"],
    ),
    (
        "CHAN-012",
        "Add typing indicators",
        "Show typing during processing.",
        ["Send typing action", "Maintain during LLM call", "Clear on response"],
    ),
    (
        "CHAN-013",
        "Implement Markdown formatting",
        "Format responses for Telegram.",
        ["Use parse_mode='Markdown'", "Escape special characters", "Handle formatting errors"],
    ),
    (
        "CHAN-014",
        "Implement thread isolation",
        "Separate threads per chat.",
        ["Map chat_id to thread_uuid", "Maintain context separation", "Test isolation"],
    ),
    (
        "CHAN-015",
        "Create config/channels/telegram.yaml",
        "Telegram configuration file.",
        ["bot_token reference", "allowed_user_ids list", "enable_voice flag"],
    ),
    (
        "CHAN-016",
        "Add Telegram integration tests",
        "Test Telegram message flow.",
        ["Mock Telegram API", "Test message handling", "Test voice handling"],
    ),
    (
        "CHAN-017",
        "Add Telegram E2E test scenario",
        "End-to-end Telegram test.",
        ["Start bot", "Send message", "Verify response"],
    ),
]

for i, (id, title, desc, criteria) in enumerate(telegram_issues):
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/CHANNELS.md Section 3", criteria),
            labels=[
                "area/channels",
                "type/feature",
                f"priority/P{'1-high' if i < 8 else '2-medium'}",
                "complexity/M",
            ],
            category="CHAN",
            priority="P1" if i < 8 else "P2",
            complexity="M",
        )
    )

# Discord - 5 issues
discord_issues = [
    (
        "CHAN-018",
        "Create DiscordDriver class skeleton",
        "Base Discord bot implementation.",
        ["Create discord_driver.py", "Use discord.py", "Extend BaseChannel"],
    ),
    (
        "CHAN-019",
        "Implement guild management",
        "Support guild configuration.",
        ["Load guild_id from config", "Validate guild access", "Handle permissions"],
    ),
    (
        "CHAN-020",
        "Implement slash commands",
        "Discord slash command handlers.",
        ["Register /help command", "/status command", "Sync commands on start"],
    ),
    (
        "CHAN-021",
        "Implement rich embeds",
        "Format responses as Discord embeds.",
        ["Create embed builder", "Include branding colors", "Support markdown in embeds"],
    ),
    (
        "CHAN-022",
        "Implement role-based auth",
        "Restrict by Discord roles.",
        ["Load allowed_roles", "Check user roles", "Reject unauthorized"],
    ),
]

for id, title, desc, criteria in discord_issues:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/CHANNELS.md Section 6.1", criteria),
            labels=["area/channels", "type/feature", "priority/P2-medium", "complexity/L"],
            category="CHAN",
            priority="P2",
            complexity="L",
        )
    )

# Channel Manager (9)
manager_issues = [
    (
        "CHAN-023",
        "Create ChannelManager class",
        "Orchestrate multiple channels.",
        ["Create channels/manager.py", "Track active channels", "Support start_all/stop_all"],
    ),
    (
        "CHAN-024",
        "Implement multi-channel startup",
        "Start enabled channels concurrently.",
        ["Check enable_* flags", "Create channel instances", "Start with asyncio.gather"],
    ),
    (
        "CHAN-025",
        "Implement health monitoring",
        "Track channel health status.",
        ["Periodic health checks", "Track last_message times", "Detect disconnections"],
    ),
    (
        "CHAN-026",
        "Implement graceful shutdown",
        "Clean shutdown of all channels.",
        ["Stop in reverse order", "Wait for pending messages", "Log shutdown status"],
    ),
    (
        "CHAN-027",
        "Add channel status endpoint",
        "API endpoint for channel status.",
        ["/channels/status endpoint", "Return channel health", "Include message counts"],
    ),
    (
        "CHAN-028",
        "Implement channel restart",
        "Restart failed channels.",
        ["Detect channel failure", "Attempt restart", "Notify on failure"],
    ),
    (
        "CHAN-029",
        "Add rate limiting per channel",
        "Prevent abuse.",
        ["Track messages per user", "Enforce rate limits", "Configurable per channel"],
    ),
    (
        "CHAN-030",
        "Implement cross-channel messaging",
        "Send alerts to all channels.",
        ["Broadcast method", "Format per channel", "Track delivery"],
    ),
    (
        "CHAN-031",
        "Add ChannelManager unit tests",
        "Test channel orchestration.",
        ["Test startup", "Test shutdown", "Test health monitoring"],
    ),
]

for id, title, desc, criteria in manager_issues:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/CHANNELS.md Section 5.2", criteria),
            labels=["area/channels", "type/feature", "priority/P1-high", "complexity/M"],
            category="CHAN",
            priority="P1",
            complexity="M",
        )
    )

# Add remaining channel issues to reach 35
issues.append(
    Issue(
        id="CHAN-032",
        title="Implement input sanitization for all channels",
        body=make_body(
            "Sanitize input to prevent injection and limit length.",
            "specs/architecture/CHANNELS.md Section 8.3",
            ["Remove injection attempts", "Limit message length", "Log sanitization events"],
        ),
        labels=["area/channels", "type/feature", "priority/P1-high", "complexity/S"],
        category="CHAN",
        priority="P1",
        complexity="S",
    )
)

issues.append(
    Issue(
        id="CHAN-033",
        title="Add channel metrics collection",
        body=make_body(
            "Collect metrics for channel usage.",
            "specs/architecture/CHANNELS.md",
            ["Message counts", "Response latencies", "Error rates", "Export to Prometheus"],
        ),
        labels=[
            "area/channels",
            "area/infra",
            "type/feature",
            "priority/P2-medium",
            "complexity/M",
        ],
        category="CHAN",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="CHAN-034",
        title="Implement message queue for channel resilience",
        body=make_body(
            "Queue messages when Orchestrator is busy.",
            "specs/architecture/CHANNELS.md",
            ["Implement message queue", "Process in order", "Handle queue overflow"],
        ),
        labels=["area/channels", "type/feature", "priority/P2-medium", "complexity/M"],
        category="CHAN",
        priority="P2",
        complexity="M",
    )
)

issues.append(
    Issue(
        id="CHAN-035",
        title="Add channel integration test suite",
        body=make_body(
            "Comprehensive integration tests for channels.",
            "specs/architecture/CHANNELS.md Section 7",
            ["CLI integration tests", "Thread isolation test", "Multi-channel test"],
        ),
        labels=["area/channels", "area/testing", "type/test", "priority/P1-high", "complexity/M"],
        category="CHAN",
        priority="P1",
        complexity="M",
    )
)

# =============================================================================
# ONT: Ontology (25 issues)
# =============================================================================

# Personal Life Entities (8)
ontology_entities = [
    (
        "ONT-001",
        "Add Hobby node type",
        "Leisure activities and interests.",
        ["Add to NodeLabel enum", "Create Pydantic model", "Add constraint/index"],
    ),
    (
        "ONT-002",
        "Add HealthMetric node type",
        "Health tracking data points.",
        ["Add to NodeLabel enum", "Support type/value/unit", "Add recorded_at index"],
    ),
    (
        "ONT-003",
        "Add Pet node type",
        "Animal companions.",
        ["Add to NodeLabel enum", "Include species/breed", "Add adoption_date"],
    ),
    (
        "ONT-004",
        "Add Milestone node type",
        "Personal achievements.",
        ["Add to NodeLabel enum", "Include significance", "Add achieved_at index"],
    ),
    (
        "ONT-005",
        "Add Routine node type",
        "Recurring activities.",
        ["Add to NodeLabel enum", "Include frequency", "Track is_active"],
    ),
    (
        "ONT-006",
        "Add Preference node type",
        "Likes and dislikes.",
        ["Add to NodeLabel enum", "Include sentiment", "Support strength scoring"],
    ),
    (
        "ONT-007",
        "Add Community node type",
        "Knowledge Islands.",
        ["Add to NodeLabel enum", "Include theme/summary", "Track node_count"],
    ),
    (
        "ONT-008",
        "Add LoreEpisode node type",
        "Story chapters.",
        ["Add to NodeLabel enum", "Include saga_id/chapter", "Track told_at"],
    ),
]

for id, title, desc, criteria in ontology_entities:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/ONTOLOGY.md Section 1.2", criteria),
            labels=["area/ontology", "type/feature", "priority/P1-high", "complexity/S"],
            category="ONT",
            priority="P1",
            complexity="S",
        )
    )

# Relationships - 16 issues
ontology_rels = [
    (
        "ONT-009",
        "Add FAMILY_OF relationship",
        "Generic family relationship.",
        ["Add to RelationType", "Include role property", "Support temporal"],
    ),
    (
        "ONT-010",
        "Add SPOUSE_OF relationship",
        "Marriage/partnership.",
        ["Add to RelationType", "Include married_at", "Support temporal"],
    ),
    (
        "ONT-011",
        "Add PARENT_OF relationship",
        "Parent-child link.",
        ["Add to RelationType", "Directional", "Support adoption"],
    ),
    (
        "ONT-012",
        "Add CHILD_OF relationship",
        "Child-parent link.",
        ["Add to RelationType", "Inverse of PARENT_OF"],
    ),
    (
        "ONT-013",
        "Add SIBLING_OF relationship",
        "Sibling link.",
        ["Add to RelationType", "Bidirectional semantics"],
    ),
    (
        "ONT-014",
        "Add FRIEND_OF relationship",
        "Friendship.",
        ["Add to RelationType", "Include since/strength", "Support temporal"],
    ),
    (
        "ONT-015",
        "Add PRACTICES relationship",
        "Person practices Hobby.",
        ["Add to RelationType", "Include skill_level", "Support temporal"],
    ),
    (
        "ONT-016",
        "Add OWNS relationship",
        "Person owns Pet.",
        ["Add to RelationType", "Include since", "Support temporal"],
    ),
    (
        "ONT-017",
        "Add RECORDED relationship",
        "Person recorded HealthMetric.",
        ["Add to RelationType", "Link to Day node"],
    ),
    (
        "ONT-018",
        "Add ACHIEVES relationship",
        "Person achieved Milestone.",
        ["Add to RelationType", "Link to achieved_at"],
    ),
    (
        "ONT-019",
        "Add FOLLOWS_ROUTINE relationship",
        "Person follows Routine.",
        ["Add to RelationType", "Include streak count", "Support temporal"],
    ),
    (
        "ONT-020",
        "Add PREFERS relationship",
        "Person has Preference.",
        ["Add to RelationType", "Simple link"],
    ),
    (
        "ONT-021",
        "Add PART_OF_ISLAND relationship",
        "Node belongs to Community.",
        ["Add to RelationType", "Include weight", "Track detected_at"],
    ),
    (
        "ONT-022",
        "Add EXPANDS_UPON relationship",
        "Lore chapter chain.",
        ["Add to RelationType", "Link episodes"],
    ),
    (
        "ONT-023",
        "Add TOLD_TO relationship",
        "Lore told to Person.",
        ["Add to RelationType", "Captain-context"],
    ),
    (
        "ONT-024",
        "Add SAGA_STARTED_BY relationship",
        "Saga initiated by Captain.",
        ["Add to RelationType", "First chapter only"],
    ),
]

for id, title, desc, criteria in ontology_rels:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/ONTOLOGY.md Section 2", criteria),
            labels=["area/ontology", "type/feature", "priority/P2-medium", "complexity/S"],
            category="ONT",
            priority="P2",
            complexity="S",
        )
    )

# Database setup (1)
issues.append(
    Issue(
        id="ONT-025",
        title="Add database setup migration for personal life entities",
        body=make_body(
            "Create constraints, indexes, and vector indexes for new entity types.",
            "specs/architecture/ONTOLOGY.md Section 4",
            [
                "Create uniqueness constraints",
                "Create property existence constraints",
                "Create full-text indexes",
                "Create temporal indexes",
            ],
        ),
        labels=["area/ontology", "area/memory", "type/feature", "priority/P1-high", "complexity/M"],
        category="ONT",
        priority="P1",
        complexity="M",
    )
)

# =============================================================================
# MEM: Memory (20 issues)
# =============================================================================

memory_issues = [
    (
        "MEM-001",
        "Implement macro zoom level search",
        "Search at Community/Island level.",
        ["Query Community nodes", "Return summaries", "Aggregate results"],
    ),
    (
        "MEM-002",
        "Implement meso zoom level search",
        "Search at Project/Note level.",
        ["Query Project and Note nodes", "Balance detail/overview"],
    ),
    (
        "MEM-003",
        "Implement micro zoom level search",
        "Search at Entity level.",
        ["Default search behavior", "Return individual entities"],
    ),
    (
        "MEM-004",
        "Implement auto zoom detection (AI-first)",
        "Detect zoom from query semantically.",
        ["No keyword matching", "Use LLM understanding", "Return zoom level"],
        True,
    ),
    (
        "MEM-005",
        "Wire deduplication module",
        "Integrate dedup into active workflow.",
        ["Import in Archivist", "Call during archival", "Log duplicates found"],
    ),
    (
        "MEM-006",
        "Implement orphan message cleanup",
        "Find and remove orphan messages.",
        ["Query unlinked Messages", "Remove in scheduled job", "Log removals"],
    ),
    (
        "MEM-007",
        "Implement entity merge utility",
        "Merge duplicate entities.",
        ["Take source and target UUIDs", "Transfer relationships", "Delete source"],
    ),
    (
        "MEM-008",
        "Add temporal spine queries",
        "Query events by Day.",
        ["Find entities by date", "Support date ranges", "Link through OCCURRED_ON"],
    ),
    (
        "MEM-009",
        "Implement relationship weight decay",
        "Decay unused relationship weights.",
        ["Track last_accessed", "Decay over time", "Prune when too low"],
    ),
    (
        "MEM-010",
        "Add context window statistics",
        "Track context usage.",
        ["Count tokens per context", "Track compression ratio", "Log overflow events"],
    ),
    (
        "MEM-011",
        "Implement semantic caching",
        "Cache similar queries.",
        ["Hash query embeddings", "Store results", "TTL expiration"],
    ),
    (
        "MEM-012",
        "Add graph statistics endpoint",
        "API for graph metrics.",
        ["Node counts by type", "Relationship counts", "Total graph size"],
    ),
    (
        "MEM-013",
        "Implement context relevance scoring",
        "Score context items by relevance.",
        ["Compute relevance scores", "Sort by relevance", "Truncate lowest"],
    ),
    (
        "MEM-014",
        "Add thread summary caching",
        "Cache thread summaries.",
        ["Store summary on creation", "Invalidate on new message", "Return cached summary"],
    ),
    (
        "MEM-015",
        "Implement relationship traversal optimization",
        "Optimize common traversals.",
        ["Add traversal hints", "Use relationship indexes", "Benchmark improvements"],
    ),
    (
        "MEM-016",
        "Add memory health monitoring",
        "Track memory system health.",
        ["Connection status", "Query latencies", "Error rates"],
    ),
    (
        "MEM-017",
        "Implement backup snapshot",
        "Create graph backup.",
        ["Export to JSON", "Include all nodes/rels", "Store with timestamp"],
    ),
    (
        "MEM-018",
        "Add restore from backup",
        "Restore graph from backup.",
        ["Import from JSON", "Clear existing data option", "Validate consistency"],
    ),
    (
        "MEM-019",
        "Implement query timeout handling",
        "Handle long-running queries.",
        ["Set query timeout", "Return partial results", "Log timeout events"],
    ),
    (
        "MEM-020",
        "Add memory unit tests",
        "Test memory operations.",
        ["Test search", "Test ingestion", "Test deduplication"],
    ),
]

for i, item in enumerate(memory_issues):
    if len(item) == 4:
        id, title, desc, criteria = item
        ai_first = False
    else:
        id, title, desc, criteria, ai_first = item

    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/MEMORY.md", criteria, ai_first=ai_first),
            labels=[
                "area/memory",
                "type/feature",
                f"priority/P{'1-high' if i < 8 else '2-medium'}",
                "complexity/M",
            ]
            + (["ai-first"] if ai_first else []),
            category="MEM",
            priority="P1" if i < 8 else "P2",
            complexity="M",
            ai_first=ai_first,
        )
    )

# =============================================================================
# MCP: MCP/Integrations (20 issues)
# =============================================================================

mcp_issues = [
    (
        "MCP-001",
        "Implement email reply-to-thread",
        "Reply to existing email threads.",
        ["Get thread ID from email", "Set In-Reply-To header", "Maintain thread context"],
    ),
    (
        "MCP-002",
        "Implement email attachment handling",
        "Support email attachments.",
        ["Read attachments from email", "Save to local storage", "Include in ingestion"],
    ),
    (
        "MCP-003",
        "Implement calendar event update",
        "Update existing events.",
        ["Get event by ID", "Update properties", "Handle conflicts"],
    ),
    (
        "MCP-004",
        "Implement calendar event delete",
        "Delete calendar events.",
        ["Get event by ID", "Confirm deletion", "Handle recurring"],
    ),
    (
        "MCP-005",
        "Implement recurring events support",
        "Create and manage recurring events.",
        ["Parse recurrence rules", "Create RRULE", "Handle exceptions"],
    ),
    (
        "MCP-006",
        "Implement attendee management",
        "Add/remove event attendees.",
        ["Add attendees method", "Remove attendees method", "Send invitations"],
    ),
    (
        "MCP-007",
        "Wire filesystem MCP server",
        "Enable filesystem operations.",
        ["Start filesystem server", "Configure allowed paths", "Test file operations"],
    ),
    (
        "MCP-008",
        "Implement OAuth refresh handling",
        "Auto-refresh expired tokens.",
        ["Detect expired token", "Refresh automatically", "Retry failed request"],
    ),
    (
        "MCP-009",
        "Implement MCP rate limiting",
        "Prevent API abuse.",
        ["Track API calls", "Enforce rate limits", "Queue excess requests"],
    ),
    (
        "MCP-010",
        "Add email search with pagination",
        "Support large result sets.",
        ["Implement pagination", "Return page tokens", "Handle large mailboxes"],
    ),
    (
        "MCP-011",
        "Implement email label management",
        "Add/remove Gmail labels.",
        ["Add label method", "Remove label method", "Create custom labels"],
    ),
    (
        "MCP-012",
        "Add calendar free slot finder",
        "Find available meeting times.",
        ["Query busy times", "Calculate free slots", "Return suggestions"],
    ),
    (
        "MCP-013",
        "Implement email draft management",
        "Save and edit drafts.",
        ["Create draft", "Update draft", "Send draft"],
    ),
    (
        "MCP-014",
        "Add calendar event search",
        "Search events by query.",
        ["Search by title", "Search by date range", "Return matching events"],
    ),
    (
        "MCP-015",
        "Implement email thread summarization",
        "Summarize email threads.",
        ["Fetch thread messages", "Generate summary", "Return key points"],
    ),
    (
        "MCP-016",
        "Add shared calendar support",
        "Support shared calendars.",
        ["List shared calendars", "Create events on shared", "Respect permissions"],
    ),
    (
        "MCP-017",
        "Implement contact integration",
        "Sync with Google Contacts.",
        ["Fetch contacts", "Create Person nodes", "Update on sync"],
    ),
    (
        "MCP-018",
        "Add MCP connection pooling",
        "Reuse MCP connections.",
        ["Pool connections", "Handle reconnection", "Track pool health"],
    ),
    (
        "MCP-019",
        "Implement MCP error recovery",
        "Handle MCP failures gracefully.",
        ["Detect failures", "Retry with backoff", "Notify on persistent failure"],
    ),
    (
        "MCP-020",
        "Add MCP integration tests",
        "Test MCP operations.",
        ["Mock MCP servers", "Test Gmail operations", "Test Calendar operations"],
    ),
]

for i, (id, title, desc, criteria) in enumerate(mcp_issues):
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/architecture/MCP.md", criteria),
            labels=[
                "area/mcp",
                "type/feature",
                f"priority/P{'1-high' if i < 10 else '2-medium'}",
                "complexity/M",
            ],
            category="MCP",
            priority="P1" if i < 10 else "P2",
            complexity="M",
        )
    )

# =============================================================================
# TEST: Testing (35 issues)
# =============================================================================

# Infrastructure - 10 issues
test_infra = [
    (
        "TEST-001",
        "Fix test suite import errors",
        "Tests fail on import due to missing deps.",
        ["Fix pydantic import", "Fix graphiti import", "All tests collect successfully"],
    ),
    (
        "TEST-002",
        "Configure pytest-asyncio properly",
        "Async tests not running correctly.",
        ["Set asyncio_mode=auto", "Fix event loop warnings", "Async fixtures work"],
    ),
    (
        "TEST-003",
        "Create agent fixtures",
        "Shared fixtures for agent tests.",
        ["Mock Orchestrator", "Mock Ingestor", "Mock Researcher"],
    ),
    (
        "TEST-004",
        "Create mock Graphiti client",
        "Mock for testing ingestion.",
        ["Implement mock search", "Implement mock add_episode", "Return test data"],
    ),
    (
        "TEST-005",
        "Create mock MCP servers",
        "Mock Gmail and Calendar.",
        ["Mock gmail_search", "Mock calendar_create", "Configurable responses"],
    ),
    (
        "TEST-006",
        "Create mock Neo4j client",
        "Mock for testing graph ops.",
        ["Mock execute_query", "Return test results", "Track query calls"],
    ),
    (
        "TEST-007",
        "Add test coverage configuration",
        "Enable coverage reporting.",
        ["Configure pytest-cov", "Set coverage thresholds", "Exclude test files"],
    ),
    (
        "TEST-008",
        "Create thread manager fixtures",
        "Test fixtures for threads.",
        ["Create test threads", "Add test messages", "Cleanup after tests"],
    ),
    (
        "TEST-009",
        "Create channel test fixtures",
        "Test fixtures for channels.",
        ["Mock CLI input", "Mock Telegram update", "Standardize responses"],
    ),
    (
        "TEST-010",
        "Add CI test runner configuration",
        "Configure tests for CI.",
        ["Parallel test execution", "Test result artifacts", "Failure notifications"],
    ),
]

for i, (id, title, desc, criteria) in enumerate(test_infra):
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/quality/TESTING.md", criteria),
            labels=[
                "area/testing",
                "type/chore",
                f"priority/P{'0-critical' if i == 0 else '1-high'}",
                "complexity/M",
            ],
            category="TEST",
            priority="P0" if i == 0 else "P1",
            complexity="M",
        )
    )

# Golden Scenarios (5)
golden_scenarios = [
    (
        "TEST-011",
        "E2E: New Contact golden scenario",
        "Test contact ingestion.",
        ["Input contact info", "Verify Person created", "Verify Org created", "Verify WORKS_AT"],
    ),
    (
        "TEST-012",
        "E2E: Contextual Retrieval golden scenario",
        "Test memory search.",
        ["Ask about previous topic", "Verify thread found", "Verify summary generated"],
    ),
    (
        "TEST-013",
        "E2E: Blocked Task golden scenario",
        "Test task dependencies.",
        ["Create blocked task", "Verify BLOCKS relationship", "Query blocked tasks"],
    ),
    (
        "TEST-014",
        "E2E: Temporal Time-Travel golden scenario",
        "Test historical queries.",
        ["Change employer", "Query historical employer", "Return old employer"],
    ),
    (
        "TEST-015",
        "E2E: Multi-Channel Threading golden scenario",
        "Test channel isolation.",
        ["CLI conversation", "Telegram conversation", "Verify no context bleed"],
    ),
]

for id, title, desc, criteria in golden_scenarios:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/quality/TESTING.md Section 10.2", criteria),
            labels=["area/testing", "type/test", "priority/P1-high", "complexity/L"],
            category="TEST",
            priority="P1",
            complexity="L",
        )
    )

# Unit tests (10)
unit_tests = [
    (
        "TEST-016",
        "Unit: Orchestrator intent classification",
        "Test intent detection.",
        ["Test SEARCH intent", "Test ACTION intent", "Test INGESTION intent"],
    ),
    (
        "TEST-017",
        "Unit: Ingestor cleaning",
        "Test input cleaning.",
        ["Test role prefix removal", "Test roleplay marker removal", "Test system mention removal"],
    ),
    (
        "TEST-018",
        "Unit: Researcher hybrid search",
        "Test search fusion.",
        ["Test vector search", "Test entity search", "Test result fusion"],
    ),
    (
        "TEST-019",
        "Unit: Executor email handlers",
        "Test email operations.",
        ["Test search builder", "Test composer", "Test formatter"],
    ),
    (
        "TEST-020",
        "Unit: Executor calendar handlers",
        "Test calendar operations.",
        ["Test time parser", "Test conflict checker", "Test formatter"],
    ),
    (
        "TEST-021",
        "Unit: Archivist summarization",
        "Test thread summarization.",
        ["Test summary generation", "Test Note creation", "Test pruning"],
    ),
    (
        "TEST-022",
        "Unit: Scribe journal generation",
        "Test journal creation.",
        ["Test analytics gathering", "Test journal creation", "Test Day linking"],
    ),
    (
        "TEST-023",
        "Unit: Thread manager operations",
        "Test thread management.",
        ["Test create thread", "Test add message", "Test get context"],
    ),
    (
        "TEST-024",
        "Unit: Deduplication detection",
        "Test duplicate finding.",
        ["Test similarity calculation", "Test duplicate detection", "Test merge suggestions"],
    ),
    (
        "TEST-025",
        "Unit: Skills loader",
        "Test skill loading.",
        ["Test YAML parsing", "Test skill discovery", "Test validation"],
    ),
]

for id, title, desc, criteria in unit_tests:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/quality/TESTING.md", criteria),
            labels=["area/testing", "type/test", "priority/P1-high", "complexity/M"],
            category="TEST",
            priority="P1",
            complexity="M",
        )
    )

# Integration tests (10)
integration_tests = [
    (
        "TEST-026",
        "Integration: Orchestrator to Ingestor",
        "Test fire-and-forget.",
        ["Send ingestion request", "Verify Graphiti called", "Verify no blocking"],
    ),
    (
        "TEST-027",
        "Integration: Orchestrator to Researcher",
        "Test dispatch-and-wait.",
        ["Send search request", "Verify results returned", "Test timeout handling"],
    ),
    (
        "TEST-028",
        "Integration: Orchestrator to Executor",
        "Test action dispatch.",
        ["Send action request", "Verify MCP called", "Verify result synthesis"],
    ),
    (
        "TEST-029",
        "Integration: Archivist to Thread",
        "Test archival flow.",
        ["Mark thread archiving", "Run archival", "Verify summary created"],
    ),
    (
        "TEST-030",
        "Integration: Scribe to Day nodes",
        "Test journal linking.",
        ["Generate journal", "Verify Day exists", "Verify OCCURRED_ON"],
    ),
    (
        "TEST-031",
        "Integration: CLI to Orchestrator",
        "Test CLI message flow.",
        ["Send CLI message", "Verify Orchestrator receives", "Verify response returned"],
    ),
    (
        "TEST-032",
        "Integration: Memory to Graph",
        "Test Neo4j operations.",
        ["Write to graph", "Read from graph", "Verify consistency"],
    ),
    (
        "TEST-033",
        "Integration: Skills to Executor",
        "Test skill execution.",
        ["Parse skill payload", "Route to Executor", "Execute action"],
    ),
    (
        "TEST-034",
        "Integration: Context to Response",
        "Test context injection.",
        ["Build enriched context", "Generate response", "Verify context used"],
    ),
    (
        "TEST-035",
        "Integration: Full v2 workflow",
        "Test Think-Dispatch-Synthesize.",
        ["User input", "Planning", "Dispatch", "Synthesis"],
    ),
]

for id, title, desc, criteria in integration_tests:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/quality/TESTING.md", criteria),
            labels=["area/testing", "type/test", "priority/P1-high", "complexity/L"],
            category="TEST",
            priority="P1",
            complexity="L",
        )
    )

# =============================================================================
# INFRA: Infrastructure (25 issues)
# =============================================================================

# CI/CD - 12 issues
cicd_issues = [
    (
        "INFRA-001",
        "Create .github/workflows directory",
        "Initialize GitHub Actions.",
        ["Create directory", "Add .gitkeep if empty"],
    ),
    (
        "INFRA-002",
        "Create ci.yml workflow",
        "Main CI pipeline.",
        ["Trigger on push/PR", "Run lint, type-check, test", "Report status"],
    ),
    (
        "INFRA-003",
        "Create lint job",
        "Run ruff linting.",
        ["Install ruff", "Run ruff check", "Fail on errors"],
    ),
    (
        "INFRA-004",
        "Create type-check job",
        "Run mypy.",
        ["Install mypy", "Run mypy check", "Report type errors"],
    ),
    (
        "INFRA-005",
        "Create test job",
        "Run pytest.",
        ["Install test deps", "Run pytest", "Upload results"],
    ),
    (
        "INFRA-006",
        "Create coverage job",
        "Track code coverage.",
        ["Run pytest-cov", "Upload to codecov", "Enforce minimum"],
    ),
    (
        "INFRA-007",
        "Create dependency check job",
        "Audit dependencies.",
        ["Run pip audit", "Check for vulnerabilities", "Report findings"],
    ),
    (
        "INFRA-008",
        "Add dependabot.yml",
        "Auto-update dependencies.",
        ["Configure for pip", "Weekly schedule", "Auto-merge patches"],
    ),
    (
        "INFRA-009",
        "Create release workflow",
        "Automate releases.",
        ["Trigger on tag", "Build package", "Publish to PyPI"],
    ),
    (
        "INFRA-010",
        "Add branch protection rules",
        "Protect main branch.",
        ["Require PR reviews", "Require CI pass", "No force push"],
    ),
    (
        "INFRA-011",
        "Create Docker build workflow",
        "Build and push images.",
        ["Build Docker image", "Push to registry", "Tag with version"],
    ),
    (
        "INFRA-012",
        "Add PR template",
        "Standard PR description.",
        ["Summary section", "Testing checklist", "Related issues"],
    ),
]

for i, (id, title, desc, criteria) in enumerate(cicd_issues):
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/infrastructure/DEPLOYMENT.md", criteria),
            labels=[
                "area/infra",
                "type/chore",
                f"priority/P{'0-critical' if i < 2 else '1-high'}",
                "complexity/S",
            ],
            category="INFRA",
            priority="P0" if i < 2 else "P1",
            complexity="S",
        )
    )

# Docker - 8 issues
docker_issues = [
    (
        "INFRA-013",
        "Optimize Dockerfile for production",
        "Multi-stage build.",
        ["Add builder stage", "Minimize final image", "Remove dev deps"],
    ),
    (
        "INFRA-014",
        "Add health check to container",
        "Docker health check.",
        ["Add HEALTHCHECK instruction", "Check API endpoint", "Set intervals"],
    ),
    (
        "INFRA-015",
        "Create backup script",
        "Backup Neo4j data.",
        ["Export graph data", "Compress backup", "Rotate old backups"],
    ),
    (
        "INFRA-016",
        "Create restore script",
        "Restore from backup.",
        ["Import graph data", "Verify integrity", "Handle conflicts"],
    ),
    (
        "INFRA-017",
        "Add docker-compose.prod.yml",
        "Production compose file.",
        ["Remove dev volumes", "Set production env", "Configure resources"],
    ),
    (
        "INFRA-018",
        "Implement log rotation",
        "Rotate application logs.",
        ["Configure logrotate", "Set retention period", "Compress old logs"],
    ),
    (
        "INFRA-019",
        "Add container resource limits",
        "Set memory/CPU limits.",
        ["Set memory limit", "Set CPU limit", "Handle OOM"],
    ),
    (
        "INFRA-020",
        "Create development docker-compose",
        "Dev-friendly compose.",
        ["Mount source code", "Hot reload", "Debug ports"],
    ),
]

for id, title, desc, criteria in docker_issues:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/infrastructure/DEPLOYMENT.md", criteria),
            labels=["area/infra", "type/chore", "priority/P2-medium", "complexity/M"],
            category="INFRA",
            priority="P2",
            complexity="M",
        )
    )

# Monitoring - 5 issues
monitoring_issues = [
    (
        "INFRA-021",
        "Add Prometheus metrics export",
        "Export application metrics.",
        ["Add prometheus-client", "Export agent metrics", "Export API metrics"],
    ),
    (
        "INFRA-022",
        "Add structured logging",
        "JSON log format.",
        ["Configure JSON formatter", "Include trace IDs", "Include timestamps"],
    ),
    (
        "INFRA-023",
        "Implement distributed tracing",
        "Trace requests across agents.",
        ["Generate trace IDs", "Propagate through calls", "Export to collector"],
    ),
    (
        "INFRA-024",
        "Create Grafana dashboard",
        "Visualize metrics.",
        ["Agent performance panel", "API latency panel", "Error rate panel"],
    ),
    (
        "INFRA-025",
        "Add alerting rules",
        "Alert on issues.",
        ["High error rate alert", "High latency alert", "Connection failure alert"],
    ),
]

for id, title, desc, criteria in monitoring_issues:
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/infrastructure/DEPLOYMENT.md", criteria),
            labels=["area/infra", "type/feature", "priority/P2-medium", "complexity/M"],
            category="INFRA",
            priority="P2",
            complexity="M",
        )
    )

# =============================================================================
# DOC: Documentation (15 issues)
# =============================================================================

doc_issues = [
    (
        "DOC-001",
        "Create QUICKSTART.md",
        "Quick setup guide.",
        ["Prerequisites", "Installation steps", "First run", "Troubleshooting"],
    ),
    (
        "DOC-002",
        "Create Telegram setup guide",
        "Telegram bot setup.",
        ["Create bot via BotFather", "Get token", "Configure env", "Test connection"],
    ),
    (
        "DOC-003",
        "Create API documentation",
        "Document REST/WebSocket API.",
        ["Endpoint list", "Request/response formats", "Authentication", "Examples"],
    ),
    (
        "DOC-004",
        "Create troubleshooting guide",
        "Common issues and fixes.",
        ["Connection issues", "Authentication errors", "Performance issues", "FAQ"],
    ),
    (
        "DOC-005",
        "Update architecture diagrams",
        "Visual documentation.",
        ["System overview", "Agent communication", "Data flow", "Deployment"],
    ),
    (
        "DOC-006",
        "Create contributor guide",
        "How to contribute.",
        ["Development setup", "Code style", "PR process", "Testing guidelines"],
    ),
    (
        "DOC-007",
        "Document skill creation",
        "How to create new skills.",
        ["Skill structure", "YAML format", "Integration", "Examples"],
    ),
    (
        "DOC-008",
        "Create Cypher query cookbook",
        "Common queries.",
        ["Search queries", "Traversal queries", "Temporal queries", "Analytics"],
    ),
    (
        "DOC-009",
        "Document configuration options",
        "All config options.",
        ["Agent configs", "Channel configs", "MCP configs", "Examples"],
    ),
    (
        "DOC-010",
        "Create deployment guide",
        "Production deployment.",
        ["Docker deployment", "Environment setup", "Scaling", "Monitoring"],
    ),
    (
        "DOC-011",
        "Document personality customization",
        "Customize Klabautermann voice.",
        ["Personality config", "Lexicon customization", "Tidbit probability"],
    ),
    (
        "DOC-012",
        "Create security guide",
        "Security best practices.",
        ["Credential management", "OAuth setup", "Prompt injection prevention"],
    ),
    (
        "DOC-013",
        "Document testing approach",
        "How to test.",
        ["Unit tests", "Integration tests", "E2E tests", "Mocking"],
    ),
    (
        "DOC-014",
        "Create changelog",
        "Track changes.",
        ["Initial version", "Version format", "Breaking changes"],
    ),
    (
        "DOC-015",
        "Update README with current status",
        "Accurate README.",
        ["Current features", "Installation", "Usage", "Contributing"],
    ),
]

for i, (id, title, desc, criteria) in enumerate(doc_issues):
    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/", criteria),
            labels=[
                "area/docs",
                "type/chore",
                f"priority/P{'1-high' if i < 5 else '2-medium'}",
                "complexity/S",
            ],
            category="DOC",
            priority="P1" if i < 5 else "P2",
            complexity="S",
        )
    )

# =============================================================================
# SKILL: Skills Framework (10 issues)
# =============================================================================

skill_issues = [
    (
        "SKILL-001",
        "Create schedule-meeting skill",
        "Schedule calendar meetings.",
        ["SKILL.md definition", "Payload schema", "Executor integration", "Tests"],
    ),
    (
        "SKILL-002",
        "Create search-contacts skill",
        "Search for people.",
        ["SKILL.md definition", "Researcher integration", "Return formatted results"],
    ),
    (
        "SKILL-003",
        "Create create-note skill",
        "Create knowledge notes.",
        ["SKILL.md definition", "Ingestor integration", "Link to entities"],
    ),
    (
        "SKILL-004",
        "Create add-task skill",
        "Add tasks to graph.",
        ["SKILL.md definition", "Task node creation", "Support dependencies"],
    ),
    (
        "SKILL-005",
        "Create summarize-thread skill",
        "Summarize conversations.",
        ["SKILL.md definition", "Archivist integration", "Return summary"],
    ),
    (
        "SKILL-006",
        "Implement natural language skill discovery",
        "Find skills from description.",
        ["No pattern matching", "LLM understanding", "Return best match"],
        True,
    ),
    (
        "SKILL-007",
        "Implement skill chaining",
        "Execute multiple skills.",
        ["Chain definition", "Sequential execution", "Pass context between"],
    ),
    (
        "SKILL-008",
        "Add skill validation",
        "Validate skill definitions.",
        ["Schema validation", "Dependency checking", "Error messages"],
    ),
    (
        "SKILL-009",
        "Create skill documentation generator",
        "Auto-generate skill docs.",
        ["Parse SKILL.md", "Generate usage docs", "Include examples"],
    ),
    (
        "SKILL-010",
        "Add skill unit tests",
        "Test skill framework.",
        ["Test loading", "Test execution", "Test chaining"],
    ),
]

for i, item in enumerate(skill_issues):
    if len(item) == 4:
        id, title, desc, criteria = item
        ai_first = False
    else:
        id, title, desc, criteria, ai_first = item

    issues.append(
        Issue(
            id=id,
            title=title,
            body=make_body(desc, "specs/", criteria, ai_first=ai_first),
            labels=[
                "area/skills",
                "type/feature",
                f"priority/P{'1-high' if i < 4 else '2-medium'}",
                "complexity/M",
            ]
            + (["ai-first"] if ai_first else []),
            category="SKILL",
            priority="P1" if i < 4 else "P2",
            complexity="M",
            ai_first=ai_first,
        )
    )

if __name__ == "__main__":
    output = {"issues": [i.to_dict() for i in issues]}

    script_dir = Path(__file__).parent
    output_path = script_dir / "issues.json"

    with output_path.open("w") as f:
        json.dump(output, f, indent=2)

    print(f"Generated {len(issues)} issues to {output_path}")

    categories = Counter(i.category for i in issues)
    print("\nCategory breakdown:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")

    priorities = Counter(i.priority for i in issues)
    print("\nPriority breakdown:")
    for pri, count in sorted(priorities.items()):
        print(f"  {pri}: {count}")
