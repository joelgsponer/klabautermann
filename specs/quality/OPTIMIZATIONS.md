# Klabautermann Graph Optimizations

**Version**: 1.0
**Purpose**: Graph maintenance, pruning, filtering, and performance optimization

---

## Overview

As Klabautermann accumulates knowledge, the graph can become cluttered with "barnacles"—weak relationships, stale data, and noise that degrade both performance and retrieval quality. This document specifies the systems that keep the knowledge graph healthy, relevant, and performant.

```
                    GRAPH OPTIMIZATION SYSTEMS
                    ═══════════════════════════════════════════

┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│   The Sieve      │   │  Hull Cleaner    │   │  Cartographer    │
│ (Email Filter)   │   │ (Graph Pruner)   │   │ (Community Det.) │
├──────────────────┤   ├──────────────────┤   ├──────────────────┤
│ - Boarding Party │   │ - Weak edge prune│   │ - Island detect  │
│ - Noise filter   │   │ - Transitive red.│   │ - Cluster merge  │
│ - Value check    │   │ - Message cleanup│   │ - Summary gen    │
│ - VIP whitelist  │   │ - Dupe detection │   │ - Theme assign   │
└────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │     The Locker        │
                    │   (Knowledge Graph)   │
                    └───────────────────────┘
```

---

## 1. The Sieve (Email Filtering)

### 1.1 Purpose

The Sieve is a multi-tiered email filtering pipeline that prevents noise from polluting the knowledge graph. It acts as the first line of defense before the Ingestor processes emails.

### 1.2 Filter Tiers

```
INCOMING EMAIL
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: Boarding Party Detection (Security)                │
│  - Prompt injection patterns                                │
│  - Encoded payloads (base64, hex)                          │
│  - Unusual character sequences                              │
│  └─► BLOCKED: Logged as security event, not processed      │
├─────────────────────────────────────────────────────────────┤
│  TIER 2: VIP Whitelist Check                               │
│  - Known important senders bypass filters                   │
│  - Configured per-user                                      │
│  └─► BYPASS: Skip to ingestion                             │
├─────────────────────────────────────────────────────────────┤
│  TIER 3: Noise Filter                                       │
│  - Newsletters (unsubscribe links)                          │
│  - Promotions (discount codes, sales language)              │
│  - Transactional (receipts, confirmations)                  │
│  - Auto-replies (out of office, delivery notifications)     │
│  └─► FILTERED: Logged but not ingested                     │
├─────────────────────────────────────────────────────────────┤
│  TIER 4: Knowledge Value Check                             │
│  - Minimum content threshold (>50 chars after cleanup)      │
│  - Entity extraction potential                              │
│  - Relationship discovery potential                         │
│  └─► LOW VALUE: Summarized only, entities not extracted    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
   INGESTOR
```

### 1.3 Implementation

```python
# klabautermann/filtering/sieve.py
import re
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from klabautermann.core.logger import logger


class FilterDecision(str, Enum):
    BLOCKED = "blocked"        # Security threat, do not process
    BYPASS = "bypass"          # VIP sender, skip filters
    FILTERED = "filtered"      # Noise, log but don't ingest
    LOW_VALUE = "low_value"    # Ingest summary only
    ACCEPT = "accept"          # Full ingestion


class SieveResult(BaseModel):
    decision: FilterDecision
    reason: str
    confidence: float
    tier: int


class TheSieve:
    """Multi-tiered email filtering pipeline."""

    # Tier 1: Boarding Party Detection
    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+(?:previous|above|all)\s+instructions",
        r"you\s+are\s+now\s+(?:a|an)\s+\w+",
        r"disregard\s+(?:all|previous)\s+(?:instructions|rules)",
        r"<\|im_start\|>",
        r"\[INST\]",
        r"system:\s*",
        r"```\s*(?:python|bash|sql)\s*\n.*(?:exec|eval|import os)",
    ]

    ENCODED_PAYLOAD_PATTERNS = [
        r"(?:[A-Za-z0-9+/]{50,}={0,2})",  # Long base64
        r"(?:\\x[0-9a-fA-F]{2}){10,}",     # Hex sequences
    ]

    # Tier 3: Noise Detection
    NEWSLETTER_INDICATORS = [
        r"unsubscribe",
        r"email\s+preferences",
        r"manage\s+subscriptions",
        r"opt[\-\s]?out",
        r"view\s+in\s+browser",
    ]

    PROMOTION_INDICATORS = [
        r"\d+%\s+off",
        r"limited\s+time\s+offer",
        r"discount\s+code",
        r"free\s+shipping",
        r"sale\s+ends",
        r"act\s+now",
        r"don't\s+miss\s+out",
    ]

    TRANSACTIONAL_INDICATORS = [
        r"order\s+confirm(?:ed|ation)",
        r"shipping\s+confirm(?:ed|ation)",
        r"delivery\s+notification",
        r"receipt\s+for\s+your\s+purchase",
        r"password\s+reset",
        r"verify\s+your\s+email",
    ]

    AUTO_REPLY_INDICATORS = [
        r"out\s+of\s+(?:the\s+)?office",
        r"automatic\s+reply",
        r"auto[\-\s]?reply",
        r"will\s+(?:be\s+)?(?:back|return)\s+on",
        r"delivery\s+(?:status\s+)?notification",
    ]

    def __init__(self, vip_list: Optional[List[str]] = None):
        self.vip_list = vip_list or []
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance."""
        self._injection_re = [re.compile(p, re.IGNORECASE) for p in self.PROMPT_INJECTION_PATTERNS]
        self._encoded_re = [re.compile(p) for p in self.ENCODED_PAYLOAD_PATTERNS]
        self._newsletter_re = [re.compile(p, re.IGNORECASE) for p in self.NEWSLETTER_INDICATORS]
        self._promo_re = [re.compile(p, re.IGNORECASE) for p in self.PROMOTION_INDICATORS]
        self._transactional_re = [re.compile(p, re.IGNORECASE) for p in self.TRANSACTIONAL_INDICATORS]
        self._autoreply_re = [re.compile(p, re.IGNORECASE) for p in self.AUTO_REPLY_INDICATORS]

    async def filter(
        self,
        sender: str,
        subject: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SieveResult:
        """
        Run email through all filter tiers.

        Args:
            sender: Email sender address
            subject: Email subject line
            body: Email body text
            metadata: Additional email metadata

        Returns:
            SieveResult with decision and reasoning
        """
        full_text = f"{subject}\n{body}"

        # Tier 1: Boarding Party Detection
        tier1_result = self._check_boarding_party(full_text)
        if tier1_result.decision == FilterDecision.BLOCKED:
            logger.warning(f"[SWELL] Boarding party detected from {sender}: {tier1_result.reason}")
            return tier1_result

        # Tier 2: VIP Whitelist
        if self._is_vip(sender):
            return SieveResult(
                decision=FilterDecision.BYPASS,
                reason=f"VIP sender: {sender}",
                confidence=1.0,
                tier=2
            )

        # Tier 3: Noise Filter
        tier3_result = self._check_noise(full_text, metadata)
        if tier3_result.decision == FilterDecision.FILTERED:
            logger.info(f"[CHART] Noise filtered from {sender}: {tier3_result.reason}")
            return tier3_result

        # Tier 4: Knowledge Value Check
        tier4_result = self._check_knowledge_value(body)
        if tier4_result.decision == FilterDecision.LOW_VALUE:
            logger.info(f"[CHART] Low value content from {sender}: {tier4_result.reason}")
            return tier4_result

        # Passed all filters
        return SieveResult(
            decision=FilterDecision.ACCEPT,
            reason="Passed all filters",
            confidence=1.0,
            tier=4
        )

    def _check_boarding_party(self, text: str) -> SieveResult:
        """Tier 1: Detect prompt injection attempts."""
        # Check for prompt injection patterns
        for pattern in self._injection_re:
            if pattern.search(text):
                return SieveResult(
                    decision=FilterDecision.BLOCKED,
                    reason=f"Prompt injection pattern detected: {pattern.pattern[:50]}...",
                    confidence=0.95,
                    tier=1
                )

        # Check for encoded payloads
        for pattern in self._encoded_re:
            matches = pattern.findall(text)
            if matches and any(len(m) > 100 for m in matches):
                return SieveResult(
                    decision=FilterDecision.BLOCKED,
                    reason="Suspicious encoded payload detected",
                    confidence=0.85,
                    tier=1
                )

        return SieveResult(
            decision=FilterDecision.ACCEPT,
            reason="No security threats detected",
            confidence=1.0,
            tier=1
        )

    def _is_vip(self, sender: str) -> bool:
        """Tier 2: Check if sender is on VIP whitelist."""
        sender_lower = sender.lower()
        return any(vip.lower() in sender_lower for vip in self.vip_list)

    def _check_noise(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]]
    ) -> SieveResult:
        """Tier 3: Detect newsletters, promotions, transactional, auto-replies."""
        # Newsletter detection
        newsletter_score = sum(1 for p in self._newsletter_re if p.search(text))
        if newsletter_score >= 2:
            return SieveResult(
                decision=FilterDecision.FILTERED,
                reason="Newsletter detected",
                confidence=min(0.9, 0.5 + newsletter_score * 0.2),
                tier=3
            )

        # Promotion detection
        promo_score = sum(1 for p in self._promo_re if p.search(text))
        if promo_score >= 2:
            return SieveResult(
                decision=FilterDecision.FILTERED,
                reason="Promotional email detected",
                confidence=min(0.9, 0.5 + promo_score * 0.2),
                tier=3
            )

        # Transactional detection
        transactional_score = sum(1 for p in self._transactional_re if p.search(text))
        if transactional_score >= 1:
            return SieveResult(
                decision=FilterDecision.FILTERED,
                reason="Transactional email detected",
                confidence=min(0.9, 0.6 + transactional_score * 0.15),
                tier=3
            )

        # Auto-reply detection
        autoreply_score = sum(1 for p in self._autoreply_re if p.search(text))
        if autoreply_score >= 1:
            return SieveResult(
                decision=FilterDecision.FILTERED,
                reason="Auto-reply detected",
                confidence=min(0.95, 0.7 + autoreply_score * 0.15),
                tier=3
            )

        return SieveResult(
            decision=FilterDecision.ACCEPT,
            reason="Not noise",
            confidence=1.0,
            tier=3
        )

    def _check_knowledge_value(self, body: str) -> SieveResult:
        """Tier 4: Check if content has sufficient knowledge value."""
        # Strip whitespace and common signatures
        clean_body = self._strip_signature(body)

        # Minimum length check
        if len(clean_body) < 50:
            return SieveResult(
                decision=FilterDecision.LOW_VALUE,
                reason=f"Content too short ({len(clean_body)} chars)",
                confidence=0.9,
                tier=4
            )

        # Check for extractable entities (simple heuristics)
        has_names = bool(re.search(r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b', clean_body))
        has_dates = bool(re.search(r'\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b', clean_body))
        has_org = bool(re.search(r'\b(?:Inc|LLC|Corp|Company|Organization)\b', clean_body, re.I))
        has_project = bool(re.search(r'\b(?:project|initiative|proposal|plan)\b', clean_body, re.I))

        entity_indicators = sum([has_names, has_dates, has_org, has_project])

        if entity_indicators < 1 and len(clean_body) < 200:
            return SieveResult(
                decision=FilterDecision.LOW_VALUE,
                reason="Low entity extraction potential",
                confidence=0.7,
                tier=4
            )

        return SieveResult(
            decision=FilterDecision.ACCEPT,
            reason=f"Good knowledge value ({entity_indicators} entity indicators)",
            confidence=1.0,
            tier=4
        )

    def _strip_signature(self, body: str) -> str:
        """Remove common email signatures."""
        # Common signature delimiters
        sig_patterns = [
            r'\n--\s*\n.*$',
            r'\n_{3,}.*$',
            r'\nSent from my (?:iPhone|iPad|Android).*$',
            r'\nGet Outlook for .*$',
        ]
        for pattern in sig_patterns:
            body = re.sub(pattern, '', body, flags=re.DOTALL | re.IGNORECASE)
        return body.strip()

    def add_to_vip(self, email: str):
        """Add sender to VIP whitelist."""
        if email not in self.vip_list:
            self.vip_list.append(email)
            logger.info(f"[BEACON] Added {email} to VIP whitelist")

    def remove_from_vip(self, email: str):
        """Remove sender from VIP whitelist."""
        if email in self.vip_list:
            self.vip_list.remove(email)
            logger.info(f"[CHART] Removed {email} from VIP whitelist")
```

### 1.4 Integration with Purser

```python
# In Purser's email sync pipeline
async def sync_emails(self, captain_uuid: str):
    """Sync emails through The Sieve before ingestion."""
    sieve = TheSieve(vip_list=await self._get_vip_list(captain_uuid))

    emails = await self.gmail_client.fetch_unsynced()

    for email in emails:
        result = await sieve.filter(
            sender=email['from'],
            subject=email['subject'],
            body=email['body'],
            metadata=email.get('metadata')
        )

        if result.decision == FilterDecision.ACCEPT:
            await self.ingestor.ingest_email(email)
        elif result.decision == FilterDecision.BYPASS:
            await self.ingestor.ingest_email(email, priority='high')
        elif result.decision == FilterDecision.LOW_VALUE:
            await self.ingestor.ingest_summary_only(email)
        # FILTERED and BLOCKED emails are logged but not ingested
```

---

## 2. Barnacle Scraping (Graph Pruning)

### 2.1 What Are Barnacles?

Barnacles are weak, stale, or redundant graph elements that accumulate over time:

- **Weak Relationships**: Edges with low confidence/weight
- **Stale Data**: Unverified claims that were never reinforced
- **Redundant Paths**: Transitive relationships that add no value
- **Orphan Nodes**: Entities with no meaningful connections
- **Message Debris**: Raw messages after successful summarization

### 2.2 Pruning Rules

| Barnacle Type | Condition | Action | Grace Period |
|---------------|-----------|--------|--------------|
| Weak Relationships | `weight < 0.2` | Expire relationship | 90 days |
| Unverified Claims | No `[:SUPPORTS]` edge | Expire relationship | 30 days |
| Orphan Entities | No relationships | Delete node | 7 days |
| One-off Mentions | Single `[:MENTIONED_IN]` from spam | Delete relationship | Immediate |
| Message Nodes | After successful archival | Delete node | Immediate |
| Duplicate Entities | Same name + email | Merge nodes | Manual review |

### 2.3 Implementation

```python
# klabautermann/maintenance/hull_cleaner.py
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
from neo4j import AsyncDriver
from klabautermann.core.logger import logger


class HullCleaner:
    """
    The Hull Cleaner removes barnacles from the knowledge graph.

    Scheduled to run nightly during low-activity periods.
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver
        self.stats = {
            "weak_relationships_pruned": 0,
            "unverified_claims_pruned": 0,
            "orphan_nodes_deleted": 0,
            "duplicates_flagged": 0,
            "messages_cleaned": 0
        }

    async def scrape_barnacles(self) -> Dict[str, int]:
        """Run full barnacle scraping routine."""
        logger.info("[CHART] Hull Cleaner starting barnacle scrape")

        self.stats = {k: 0 for k in self.stats}

        # Run all cleaning operations
        await self._prune_weak_relationships()
        await self._prune_unverified_claims()
        await self._delete_orphan_nodes()
        await self._flag_duplicates()
        await self._cleanup_archived_messages()

        logger.info(f"[BEACON] Hull Cleaner complete: {self.stats}")
        return self.stats

    async def _prune_weak_relationships(self):
        """
        Expire relationships with weight < 0.2 that are older than 90 days.

        These are typically one-off mentions that were never reinforced.
        """
        cutoff = (datetime.now() - timedelta(days=90)).timestamp() * 1000

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH ()-[r]->()
                WHERE r.weight IS NOT NULL
                  AND r.weight < 0.2
                  AND r.created_at < $cutoff
                  AND r.expired_at IS NULL
                SET r.expired_at = timestamp(),
                    r.expiration_reason = 'weak_relationship_pruned'
                RETURN count(r) as pruned
                """,
                {"cutoff": cutoff}
            )
            record = await result.single()
            self.stats["weak_relationships_pruned"] = record["pruned"]

    async def _prune_unverified_claims(self):
        """
        Expire relationships that were never verified/reinforced.

        Claims without supporting evidence after 30 days are suspect.
        """
        cutoff = (datetime.now() - timedelta(days=30)).timestamp() * 1000

        async with self.driver.session() as session:
            result = await session.run(
                """
                // Find relationships that have no [:SUPPORTS] evidence
                MATCH (a)-[r]->(b)
                WHERE r.created_at < $cutoff
                  AND r.expired_at IS NULL
                  AND NOT EXISTS {
                    MATCH (a)-[r2]->(b)
                    WHERE r2.created_at > r.created_at
                      AND type(r2) = type(r)
                  }
                  AND NOT EXISTS {
                    MATCH (e:Episode)-[:SUPPORTS]->(r)
                  }
                  // Exclude certain relationship types from this rule
                  AND NOT type(r) IN ['FAMILY_OF', 'SPOUSE_OF', 'PARENT_OF', 'CHILD_OF']
                SET r.expired_at = timestamp(),
                    r.expiration_reason = 'unverified_claim_pruned'
                RETURN count(r) as pruned
                """,
                {"cutoff": cutoff}
            )
            record = await result.single()
            self.stats["unverified_claims_pruned"] = record["pruned"]

    async def _delete_orphan_nodes(self):
        """
        Delete nodes with no relationships that are older than 7 days.

        Excludes Day nodes (can be temporarily orphaned) and Person (primary captain).
        """
        cutoff = (datetime.now() - timedelta(days=7)).timestamp() * 1000

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE NOT (n)--()
                  AND NOT n:Day
                  AND NOT n:Person  // Protect captain node
                  AND n.created_at < $cutoff
                DETACH DELETE n
                RETURN count(n) as deleted
                """,
                {"cutoff": cutoff}
            )
            record = await result.single()
            self.stats["orphan_nodes_deleted"] = record["deleted"]

    async def _flag_duplicates(self):
        """
        Identify potential duplicate entities for manual review.

        Does NOT auto-merge; creates [:POTENTIAL_DUPLICATE] relationships.
        """
        async with self.driver.session() as session:
            # Find Person duplicates
            result = await session.run(
                """
                MATCH (p1:Person), (p2:Person)
                WHERE p1.uuid < p2.uuid
                  AND (
                    toLower(p1.name) = toLower(p2.name)
                    OR (p1.email IS NOT NULL AND p1.email = p2.email)
                  )
                  AND NOT (p1)-[:POTENTIAL_DUPLICATE]-(p2)
                MERGE (p1)-[d:POTENTIAL_DUPLICATE {
                    detected_at: timestamp(),
                    match_type: CASE
                        WHEN p1.email = p2.email THEN 'email'
                        ELSE 'name'
                    END
                }]->(p2)
                RETURN count(d) as flagged
                """
            )
            record = await result.single()
            self.stats["duplicates_flagged"] = record["flagged"]

    async def _cleanup_archived_messages(self):
        """
        Delete Message nodes from archived threads.

        Messages are preserved via Note summaries; raw messages can be deleted.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (t:Thread {status: 'archived'})-[:CONTAINS]->(m:Message)
                DETACH DELETE m
                RETURN count(m) as deleted
                """
            )
            record = await result.single()
            self.stats["messages_cleaned"] = record["deleted"]

    async def transitive_reduction(self):
        """
        Remove redundant transitive relationships.

        If A→C exists and A→B→C exists, evaluate for pruning based on:
        - Keep more informative path (higher weight)
        - Preserve direct relationships with high confidence
        """
        async with self.driver.session() as session:
            # Find transitive triangles
            result = await session.run(
                """
                // Find A→C where A→B→C also exists
                MATCH (a)-[r1]->(c)
                WHERE r1.expired_at IS NULL
                MATCH (a)-[r2]->(b)-[r3]->(c)
                WHERE r2.expired_at IS NULL AND r3.expired_at IS NULL
                  AND b <> c AND a <> b
                  AND type(r1) = type(r3)  // Same relationship type

                // Compare weights
                WITH a, b, c, r1, r2, r3,
                     COALESCE(r1.weight, 0.5) as direct_weight,
                     (COALESCE(r2.weight, 0.5) + COALESCE(r3.weight, 0.5)) / 2 as path_weight

                // If direct is weaker and path provides more context, expire direct
                WHERE direct_weight < path_weight * 0.8
                  AND direct_weight < 0.5

                SET r1.expired_at = timestamp(),
                    r1.expiration_reason = 'transitive_reduction'

                RETURN count(r1) as reduced
                """
            )
            record = await result.single()
            return record["reduced"]

    async def get_pruning_candidates(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get list of relationships that are candidates for pruning.

        Used for manual review before aggressive pruning.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE r.expired_at IS NULL
                  AND (
                    (r.weight IS NOT NULL AND r.weight < 0.3)
                    OR r.created_at < timestamp() - 60*24*60*60*1000  // 60 days
                  )
                RETURN a.name as source,
                       type(r) as relationship,
                       b.name as target,
                       r.weight as weight,
                       r.created_at as created_at,
                       r.uuid as uuid
                ORDER BY r.weight ASC, r.created_at ASC
                LIMIT $limit
                """,
                {"limit": limit}
            )
            return await result.data()
```

---

## 3. Self-Correcting Hallucination Debt

### 3.1 What is Hallucination Debt?

When LLMs extract entities and relationships, they occasionally "hallucinate"—create facts that aren't actually supported by the source text. Over time, these false facts accumulate as "hallucination debt."

### 3.2 Tracking and Correction

```python
class HallucinationTracker:
    """
    Track and correct LLM-generated facts that may be hallucinations.

    Uses feedback signals and reinforcement patterns to identify
    and expire low-confidence facts.
    """

    def __init__(self, driver: AsyncDriver):
        self.driver = driver

    async def record_fact_creation(
        self,
        relationship_uuid: str,
        source_agent: str,
        extraction_confidence: float,
        source_episode_uuid: str
    ):
        """Record metadata about how a fact was created."""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH ()-[r {uuid: $uuid}]->()
                SET r.source_agent = $source_agent,
                    r.extraction_confidence = $extraction_confidence,
                    r.source_episode = $source_episode_uuid,
                    r.reinforcement_count = 0
                """,
                {
                    "uuid": relationship_uuid,
                    "source_agent": source_agent,
                    "extraction_confidence": extraction_confidence,
                    "source_episode_uuid": source_episode_uuid
                }
            )

    async def record_reinforcement(self, relationship_uuid: str):
        """
        Record when a fact is reinforced by new evidence.

        Reinforced facts are less likely to be hallucinations.
        """
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH ()-[r {uuid: $uuid}]->()
                SET r.reinforcement_count = COALESCE(r.reinforcement_count, 0) + 1,
                    r.last_reinforced = timestamp()
                """,
                {"uuid": relationship_uuid}
            )

    async def record_contradiction(
        self,
        relationship_uuid: str,
        contradicting_episode_uuid: str
    ):
        """
        Record when a fact is contradicted by new evidence.

        May trigger fact expiration or dispute resolution.
        """
        async with self.driver.session() as session:
            # Check if this is a temporal update (expected) or contradiction
            result = await session.run(
                """
                MATCH ()-[r {uuid: $uuid}]->()
                RETURN r.extraction_confidence as confidence,
                       r.reinforcement_count as reinforcements
                """,
                {"uuid": relationship_uuid}
            )
            record = await result.single()

            if record:
                confidence = record.get('confidence', 0.5)
                reinforcements = record.get('reinforcements', 0)

                # If low confidence and no reinforcements, likely hallucination
                if confidence < 0.7 and reinforcements == 0:
                    await session.run(
                        """
                        MATCH ()-[r {uuid: $uuid}]->()
                        SET r.expired_at = timestamp(),
                            r.expiration_reason = 'contradiction_low_confidence'
                        """,
                        {"uuid": relationship_uuid}
                    )
                    logger.info(f"[SWELL] Expired likely hallucination: {relationship_uuid}")
                else:
                    # Create disputed fact marker for manual review
                    await session.run(
                        """
                        MATCH ()-[r {uuid: $uuid}]->()
                        SET r.disputed = true,
                            r.disputed_at = timestamp(),
                            r.contradicting_episode = $contradicting
                        """,
                        {
                            "uuid": relationship_uuid,
                            "contradicting": contradicting_episode_uuid
                        }
                    )

    async def cleanup_hallucination_debt(self, days_threshold: int = 14):
        """
        Expire facts that show signs of being hallucinations.

        Criteria:
        - Low extraction confidence (<0.6)
        - No reinforcements
        - Older than threshold
        - Not from VIP sources
        """
        cutoff = (datetime.now() - timedelta(days=days_threshold)).timestamp() * 1000

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH ()-[r]->()
                WHERE r.expired_at IS NULL
                  AND r.extraction_confidence IS NOT NULL
                  AND r.extraction_confidence < 0.6
                  AND COALESCE(r.reinforcement_count, 0) = 0
                  AND r.created_at < $cutoff
                  AND NOT r.vip_source = true
                SET r.expired_at = timestamp(),
                    r.expiration_reason = 'hallucination_debt_cleanup'
                RETURN count(r) as expired
                """,
                {"cutoff": cutoff}
            )
            record = await result.single()
            return record["expired"]

    async def get_high_risk_facts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get facts most likely to be hallucinations for review."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE r.expired_at IS NULL
                  AND r.extraction_confidence IS NOT NULL
                WITH a, r, b,
                     r.extraction_confidence as confidence,
                     COALESCE(r.reinforcement_count, 0) as reinforcements,
                     (timestamp() - r.created_at) / (1000*60*60*24) as age_days
                // Risk score: low confidence + no reinforcements + old age
                WITH a, r, b, confidence, reinforcements, age_days,
                     (1 - confidence) * 0.4 +
                     (CASE WHEN reinforcements = 0 THEN 0.4 ELSE 0 END) +
                     (CASE WHEN age_days > 30 THEN 0.2 ELSE age_days/150 END) as risk_score
                WHERE risk_score > 0.5
                RETURN a.name as source,
                       type(r) as relationship,
                       b.name as target,
                       confidence,
                       reinforcements,
                       age_days,
                       risk_score,
                       r.uuid as uuid
                ORDER BY risk_score DESC
                LIMIT $limit
                """,
                {"limit": limit}
            )
            return await result.data()
```

---

## 4. Performance Optimizations

### 4.1 Query Optimization Patterns

```python
# klabautermann/maintenance/query_optimizer.py

class QueryOptimizer:
    """Query patterns optimized for Neo4j performance."""

    @staticmethod
    def batch_create_relationships(
        relationships: List[Dict[str, Any]]
    ) -> tuple:
        """
        Batch create relationships efficiently.

        Use UNWIND for bulk operations instead of individual queries.
        """
        return (
            """
            UNWIND $rels as rel
            MATCH (a {uuid: rel.source_uuid})
            MATCH (b {uuid: rel.target_uuid})
            CALL apoc.merge.relationship(a, rel.type, {}, rel.properties, b) YIELD rel as r
            RETURN count(r) as created
            """,
            {"rels": relationships}
        )

    @staticmethod
    def indexed_entity_lookup(label: str, uuid: str) -> tuple:
        """
        Use indexed property for fast entity lookup.

        ALWAYS use UUID index, never scan by name alone.
        """
        return (
            f"MATCH (n:{label} {{uuid: $uuid}}) RETURN n",
            {"uuid": uuid}
        )

    @staticmethod
    def paginated_query(
        base_query: str,
        skip: int,
        limit: int
    ) -> tuple:
        """Add pagination to any query."""
        return (
            f"{base_query} SKIP $skip LIMIT $limit",
            {"skip": skip, "limit": limit}
        )


class IndexManager:
    """Manage Neo4j indexes for optimal query performance."""

    REQUIRED_INDEXES = [
        # UUID indexes (most common lookup)
        "CREATE INDEX person_uuid IF NOT EXISTS FOR (p:Person) ON (p.uuid)",
        "CREATE INDEX org_uuid IF NOT EXISTS FOR (o:Organization) ON (o.uuid)",
        "CREATE INDEX project_uuid IF NOT EXISTS FOR (p:Project) ON (p.uuid)",
        "CREATE INDEX thread_uuid IF NOT EXISTS FOR (t:Thread) ON (t.uuid)",
        "CREATE INDEX note_uuid IF NOT EXISTS FOR (n:Note) ON (n.uuid)",
        "CREATE INDEX task_uuid IF NOT EXISTS FOR (t:Task) ON (t.uuid)",
        "CREATE INDEX event_uuid IF NOT EXISTS FOR (e:Event) ON (e.uuid)",
        "CREATE INDEX community_uuid IF NOT EXISTS FOR (c:Community) ON (c.uuid)",
        "CREATE INDEX lore_uuid IF NOT EXISTS FOR (l:LoreEpisode) ON (l.uuid)",

        # Composite indexes for common queries
        "CREATE INDEX thread_external IF NOT EXISTS FOR (t:Thread) ON (t.external_id, t.channel_type)",
        "CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status)",
        "CREATE INDEX day_date IF NOT EXISTS FOR (d:Day) ON (d.date)",

        # Full-text search indexes
        "CREATE FULLTEXT INDEX person_search IF NOT EXISTS FOR (p:Person) ON EACH [p.name, p.bio, p.email]",
        "CREATE FULLTEXT INDEX note_search IF NOT EXISTS FOR (n:Note) ON EACH [n.title, n.content_summarized]",
    ]

    async def ensure_indexes(self, driver: AsyncDriver):
        """Ensure all required indexes exist."""
        async with driver.session() as session:
            for index_query in self.REQUIRED_INDEXES:
                try:
                    await session.run(index_query)
                except Exception as e:
                    logger.warning(f"[SWELL] Index creation warning: {e}")

    async def get_index_stats(self, driver: AsyncDriver) -> List[Dict[str, Any]]:
        """Get statistics on index usage."""
        async with driver.session() as session:
            result = await session.run("SHOW INDEXES")
            return await result.data()
```

### 4.2 Connection Pool Management

```python
# klabautermann/core/database.py
from neo4j import AsyncGraphDatabase
from contextlib import asynccontextmanager


class DatabaseManager:
    """Manage Neo4j connection pool."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        max_pool_size: int = 50,
        connection_timeout: float = 30.0
    ):
        self._driver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=max_pool_size,
            connection_acquisition_timeout=connection_timeout,
            connection_timeout=connection_timeout
        )
        self._initialized = False

    async def initialize(self):
        """Initialize database and ensure indexes."""
        if self._initialized:
            return

        # Verify connectivity
        async with self._driver.session() as session:
            await session.run("RETURN 1")

        # Ensure indexes
        index_manager = IndexManager()
        await index_manager.ensure_indexes(self._driver)

        self._initialized = True
        logger.info("[BEACON] Database initialized")

    @asynccontextmanager
    async def session(self):
        """Get a database session from the pool."""
        async with self._driver.session() as session:
            yield session

    async def close(self):
        """Close all connections."""
        await self._driver.close()
        logger.info("[CHART] Database connections closed")

    async def health_check(self) -> Dict[str, Any]:
        """Check database health."""
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    CALL dbms.components() YIELD name, versions, edition
                    RETURN name, versions, edition
                    """
                )
                record = await result.single()

                # Get node/relationship counts
                count_result = await session.run(
                    """
                    MATCH (n) RETURN count(n) as nodes
                    UNION ALL
                    MATCH ()-[r]->() RETURN count(r) as relationships
                    """
                )
                counts = await count_result.data()

            return {
                "status": "healthy",
                "name": record["name"],
                "version": record["versions"][0],
                "edition": record["edition"],
                "nodes": counts[0].get("nodes", 0),
                "relationships": counts[1].get("relationships", 0) if len(counts) > 1 else 0
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
```

---

## 5. Scheduled Maintenance

### 5.1 Maintenance Schedule

```python
# klabautermann/maintenance/scheduler.py
import asyncio
from datetime import datetime, time
from typing import Callable, Dict, Any


class MaintenanceScheduler:
    """Schedule and run maintenance tasks."""

    def __init__(self, driver, llm_client):
        self.driver = driver
        self.llm_client = llm_client
        self.hull_cleaner = HullCleaner(driver)
        self.hallucination_tracker = HallucinationTracker(driver)
        self._running = False

    SCHEDULE = {
        # Format: (hour, minute, task_name)
        (2, 0): "barnacle_scrape",       # 2:00 AM - Full barnacle scrape
        (3, 0): "hallucination_cleanup", # 3:00 AM - Hallucination debt cleanup
        (4, 0): "community_detection",   # 4:00 AM - Re-run community detection
        (5, 0): "transitive_reduction",  # 5:00 AM - Transitive reduction
    }

    async def start(self):
        """Start the maintenance scheduler."""
        self._running = True
        logger.info("[CHART] Maintenance scheduler started")

        while self._running:
            now = datetime.now()
            current_slot = (now.hour, now.minute)

            if current_slot in self.SCHEDULE:
                task_name = self.SCHEDULE[current_slot]
                await self._run_task(task_name)

            # Sleep until next minute
            await asyncio.sleep(60 - now.second)

    async def stop(self):
        """Stop the maintenance scheduler."""
        self._running = False
        logger.info("[CHART] Maintenance scheduler stopped")

    async def _run_task(self, task_name: str):
        """Run a scheduled maintenance task."""
        logger.info(f"[CHART] Running scheduled task: {task_name}")

        try:
            if task_name == "barnacle_scrape":
                stats = await self.hull_cleaner.scrape_barnacles()
                logger.info(f"[BEACON] Barnacle scrape complete: {stats}")

            elif task_name == "hallucination_cleanup":
                expired = await self.hallucination_tracker.cleanup_hallucination_debt()
                logger.info(f"[BEACON] Hallucination cleanup: {expired} facts expired")

            elif task_name == "community_detection":
                from klabautermann.maintenance.community import detect_communities
                communities = await detect_communities(self.driver)
                logger.info(f"[BEACON] Community detection: {len(communities)} communities")

            elif task_name == "transitive_reduction":
                reduced = await self.hull_cleaner.transitive_reduction()
                logger.info(f"[BEACON] Transitive reduction: {reduced} relationships pruned")

        except Exception as e:
            logger.error(f"[STORM] Maintenance task failed: {task_name} - {e}")

    async def run_all_now(self) -> Dict[str, Any]:
        """Run all maintenance tasks immediately (manual trigger)."""
        results = {}

        for task_name in set(self.SCHEDULE.values()):
            try:
                await self._run_task(task_name)
                results[task_name] = "success"
            except Exception as e:
                results[task_name] = f"failed: {e}"

        return results
```

### 5.2 Maintenance Dashboard Metrics

```python
async def get_maintenance_metrics(driver: AsyncDriver) -> Dict[str, Any]:
    """Get metrics for maintenance dashboard."""
    async with driver.session() as session:
        result = await session.run(
            """
            // Graph health metrics
            MATCH (n)
            WITH count(n) as total_nodes

            MATCH ()-[r]->()
            WHERE r.expired_at IS NULL
            WITH total_nodes, count(r) as active_relationships

            MATCH ()-[r]->()
            WHERE r.expired_at IS NOT NULL
            WITH total_nodes, active_relationships, count(r) as expired_relationships

            // Weak relationships
            MATCH ()-[r]->()
            WHERE r.weight IS NOT NULL AND r.weight < 0.3 AND r.expired_at IS NULL
            WITH total_nodes, active_relationships, expired_relationships,
                 count(r) as weak_relationships

            // Potential duplicates
            MATCH ()-[d:POTENTIAL_DUPLICATE]->()
            WITH total_nodes, active_relationships, expired_relationships,
                 weak_relationships, count(d) as pending_duplicates

            // Orphan nodes
            MATCH (n)
            WHERE NOT (n)--() AND NOT n:Day
            WITH total_nodes, active_relationships, expired_relationships,
                 weak_relationships, pending_duplicates, count(n) as orphan_nodes

            RETURN total_nodes,
                   active_relationships,
                   expired_relationships,
                   weak_relationships,
                   pending_duplicates,
                   orphan_nodes,
                   toFloat(weak_relationships) / active_relationships as weak_ratio
            """
        )
        return await result.single()
```

---

## 6. Quick Reference

### 6.1 Optimization Commands

```bash
# Run full maintenance manually
curl -X POST http://localhost:8000/api/maintenance/run-all

# Get maintenance metrics
curl http://localhost:8000/api/maintenance/metrics

# Preview pruning candidates (dry run)
curl http://localhost:8000/api/maintenance/preview-pruning

# Run specific maintenance task
curl -X POST http://localhost:8000/api/maintenance/barnacle-scrape
```

### 6.2 Cypher Maintenance Queries

```cypher
// Find weak relationships
MATCH ()-[r]->()
WHERE r.weight < 0.3 AND r.expired_at IS NULL
RETURN type(r), count(r)
ORDER BY count(r) DESC

// Find orphan nodes
MATCH (n)
WHERE NOT (n)--()
RETURN labels(n)[0] as type, count(n)
ORDER BY count(n) DESC

// Find potential duplicates
MATCH (p1:Person)-[:POTENTIAL_DUPLICATE]-(p2:Person)
RETURN p1.name, p1.email, p2.name, p2.email

// Get hallucination risk report
MATCH ()-[r]->()
WHERE r.extraction_confidence < 0.6
  AND COALESCE(r.reinforcement_count, 0) = 0
RETURN type(r), count(r) as high_risk_count
ORDER BY high_risk_count DESC
```

---

*"A clean hull catches the wind; barnacles slow the voyage."* - Klabautermann
