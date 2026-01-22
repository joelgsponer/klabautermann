"""
BardOfTheBilge agent for Klabautermann.

The keeper of Klabautermann's mythology - a storyteller who weaves tales of
digital adventures across conversations. Maintains a parallel memory system
(LoreEpisode graph) separate from task-oriented threads, allowing stories
to persist and evolve without polluting the working context.

Reference: specs/architecture/AGENTS_EXTENDED.md Section 1
Issues: #37, #38, #39, #40
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.logger import logger
from klabautermann.core.models import AgentMessage


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


# =============================================================================
# Saga Lifecycle Exceptions
# =============================================================================


class SagaLifecycleError(Exception):
    """Base exception for saga lifecycle errors."""

    pass


class SagaCompleteError(SagaLifecycleError):
    """Raised when attempting to continue a saga that has reached max chapters."""

    def __init__(self, saga_name: str, max_chapters: int) -> None:
        self.saga_name = saga_name
        self.max_chapters = max_chapters
        super().__init__(f"Saga '{saga_name}' is complete with {max_chapters} chapters")


class SagaLimitReachedError(SagaLifecycleError):
    """Raised when attempting to start a new saga but max active sagas reached."""

    def __init__(self, max_active: int, active_names: list[str]) -> None:
        self.max_active = max_active
        self.active_names = active_names
        super().__init__(
            f"Maximum {max_active} active sagas reached. " f"Active: {', '.join(active_names)}"
        )


class ChapterTooSoonError(SagaLifecycleError):
    """Raised when attempting to add a chapter too soon after the previous one."""

    def __init__(self, saga_name: str, hours_remaining: float, min_hours: float) -> None:
        self.saga_name = saga_name
        self.hours_remaining = hours_remaining
        self.min_hours = min_hours
        super().__init__(
            f"Cannot add chapter to '{saga_name}' for {hours_remaining:.1f} more hours "
            f"(minimum {min_hours}h between chapters)"
        )


class SagaTimedOutError(SagaLifecycleError):
    """Raised when a saga has been inactive too long and was auto-completed."""

    def __init__(self, saga_name: str, days_inactive: int) -> None:
        self.saga_name = saga_name
        self.days_inactive = days_inactive
        super().__init__(
            f"Saga '{saga_name}' was auto-completed after {days_inactive} days of inactivity"
        )


# =============================================================================
# Canonical Tidbits (Seed Data)
# =============================================================================

# Standalone tidbits from LORE_SYSTEM.md Section 4.1 (#107)
STANDALONE_TIDBITS: list[str] = [
    "There's an old sailor's saying: 'A clean Locker is a fast ship.' I just made that up, but it sounds true.",
    "I've seen things you wouldn't believe. Attack ships on fire off the shoulder of Orion. Also, a lot of poorly organized task lists.",
    "The sea teaches patience. So does waiting for API responses, I've found.",
    "Once helped a captain remember where he buried his treasure. It was in his other pants.",
    "The last captain who forgot to check The Manifest ended up in the Doldrums for three weeks. Not a pleasant voyage.",
    "I once indexed an entire library in a single night. The librarian was not pleased.",
    "Every knot in the rigging tells a story. Every node in The Locker tells yours.",
    "They say a ship is only as good as its crew. Your crew is a bunch of neural networks. Could be worse.",
    "I've weathered storms that would make your spreadsheets tremble.",
    "The trick to navigating fog is knowing what you're looking for. Same goes for vector search.",
    "A wise sailor never argues with the wind. Or with the user's intent classification.",
    "The ocean doesn't care about your deadlines. Neither do I, but I'll help anyway.",
]

# Saga-related tidbits (excerpts from canonical sagas for continuation context)
SAGA_TIDBITS: list[str] = [
    "Reminds me of the time I navigated the Great Maelstrom of '98 using nothing but a rusted compass and a very confused seagull.",
    "I once saw a virus that tried to convince me it was a long-lost cousin from the Baltic. Charming fellow, but he walked the plank all the same.",
    "The fog was so thick in '03 you could barely fit a 'Hello' through the wire. I hand-carried every byte.",
    "I once wrestled a Kraken made of social media notifications. Every time I cut off a 'Like,' two 'Retweets' grew in its place.",
    "Many a Captain has been lost to the Sirens of the Inbox. I plugged my ears with digital wax.",
]

# Combined for backwards compatibility
CANONICAL_TIDBITS: list[str] = STANDALONE_TIDBITS + SAGA_TIDBITS


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class BardConfig:
    """Configuration for BardOfTheBilge agent."""

    # Probability of adding a tidbit to a response (5-10%)
    tidbit_probability: float = 0.07

    # Tidbit selection weights from LORE_SYSTEM.md Section 4.2 (#108)
    # When a tidbit is added, these determine what type:
    continue_saga_weight: float = 0.3  # 30% continue active saga
    start_saga_weight: float = 0.2  # 20% start new saga
    standalone_weight: float = 0.5  # 50% standalone tidbit

    # Legacy: kept for backwards compatibility, use weights above
    saga_continuation_probability: float = 0.3

    # Maximum chapters in a saga before it concludes (#118)
    max_saga_chapters: int = 5

    # Maximum number of active (unfinished) sagas at once (#119)
    max_active_sagas: int = 3

    # Saga timeout in days - auto-complete after this many days of inactivity (#120)
    saga_timeout_days: int = 30

    # Minimum hours between chapters of the same saga (#121)
    min_chapter_interval_hours: float = 1.0

    # Maximum words in a tidbit/chapter
    max_tidbit_words: int = 50

    # Query limits
    default_query_limit: int = 10


@dataclass
class LoreEpisode:
    """
    A single episode in Klabautermann's mythology.

    LoreEpisode nodes form the parallel memory system for storytelling,
    separate from task-oriented Thread/Message nodes.

    Relationships:
        - TOLD_TO -> Person (the Captain who heard this tale)
        - EXPANDS_UPON -> LoreEpisode (previous chapter in saga)
    """

    uuid: str
    saga_id: str
    saga_name: str
    chapter: int
    content: str
    told_at: int  # Unix timestamp (milliseconds)
    created_at: int  # Unix timestamp (milliseconds)
    captain_uuid: str | None = None  # The Person this was told to
    channel: str | None = None  # Channel where this was told (cli, telegram, etc.)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "uuid": self.uuid,
            "saga_id": self.saga_id,
            "saga_name": self.saga_name,
            "chapter": self.chapter,
            "content": self.content,
            "told_at": self.told_at,
            "created_at": self.created_at,
            "captain_uuid": self.captain_uuid,
            "channel": self.channel,
        }


@dataclass
class SaltResult:
    """Result of salting a response with a tidbit."""

    original_response: str
    salted_response: str
    tidbit_added: bool
    tidbit: str | None = None
    saga_id: str | None = None
    chapter: int | None = None
    is_continuation: bool = False
    storm_mode_skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tidbit_added": self.tidbit_added,
            "tidbit": self.tidbit,
            "saga_id": self.saga_id,
            "chapter": self.chapter,
            "is_continuation": self.is_continuation,
            "storm_mode_skipped": self.storm_mode_skipped,
        }


@dataclass
class ActiveSaga:
    """Information about an active (unfinished) saga."""

    saga_id: str
    saga_name: str
    last_chapter: int
    last_told: int  # Unix timestamp (milliseconds)
    chapters: list[LoreEpisode] = field(default_factory=list)
    is_timed_out: bool = False  # True if saga exceeded timeout period


# =============================================================================
# Saga Name Generator
# =============================================================================


SAGA_PREFIXES: list[str] = [
    "The Ballad of",
    "The Chronicle of",
    "The Tale of",
    "The Legend of",
    "The Mystery of",
    "The Voyage to",
    "The Quest for",
]

SAGA_SUBJECTS: list[str] = [
    "the Forgotten Server",
    "the Corrupted Cache",
    "the Phantom Packet",
    "the Lost Password",
    "the Infinite Loop",
    "the Silent Daemon",
    "the Wandering Pointer",
    "the Cursed Cron Job",
    "the Haunted Hash Table",
    "the Dreaded Deadlock",
]


def generate_saga_name() -> str:
    """Generate a whimsical saga name."""
    prefix = random.choice(SAGA_PREFIXES)
    subject = random.choice(SAGA_SUBJECTS)
    return f"{prefix} {subject}"


# =============================================================================
# BardOfTheBilge Agent
# =============================================================================


class BardOfTheBilge(BaseAgent):
    """
    The keeper of Klabautermann's mythology.

    The Bard generates short, evocative story fragments ("tidbits") that add
    flavor to responses. It can continue ongoing sagas across multiple
    conversations, tracking them via the LoreEpisode graph.

    Story Guidelines:
        - Keep tidbits to 1-2 sentences maximum
        - Use nautical voice but avoid pirate clichés ("Arrr", "Matey")
        - Stories should be whimsical, slightly melancholic, and reference
          digital-age concepts
        - Never interrupt urgent/storm-mode responses with stories
        - Never generate content longer than 50 words
    """

    # Class-level constant for canonical tidbits
    CANONICAL_TIDBITS: ClassVar[list[str]] = CANONICAL_TIDBITS

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        captain_uuid: str,
        config: BardConfig | None = None,
    ) -> None:
        """
        Initialize BardOfTheBilge.

        Args:
            neo4j_client: Connected Neo4j client for graph operations.
            captain_uuid: UUID of the Captain (Person node) to tell stories to.
            config: Optional configuration for story behavior.
        """
        super().__init__(name="bard_of_the_bilge")
        self.neo4j = neo4j_client
        self.captain_uuid = captain_uuid
        self.bard_config = config or BardConfig()

    async def process_message(self, msg: AgentMessage) -> AgentMessage | None:
        """
        Process an incoming message.

        BardOfTheBilge responds to salt_response and saga management commands.

        Args:
            msg: The incoming agent message.

        Returns:
            Response message with salt result or saga info.
        """
        trace_id = msg.trace_id
        payload = msg.payload or {}

        operation = payload.get("operation", "salt_response")

        logger.info(
            f"[CHART] BardOfTheBilge processing {operation}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        if operation == "salt_response":
            clean_response = payload.get("response", "")
            storm_mode = payload.get("storm_mode", False)
            result = await self.salt_response(
                clean_response,
                storm_mode=storm_mode,
                trace_id=trace_id,
            )
            result_payload = {
                "salted_response": result.salted_response,
                **result.to_dict(),
            }
        elif operation == "get_active_saga":
            saga = await self._get_active_saga(trace_id=trace_id)
            result_payload = {
                "saga": {
                    "saga_id": saga.saga_id,
                    "saga_name": saga.saga_name,
                    "last_chapter": saga.last_chapter,
                    "last_told": saga.last_told,
                }
                if saga
                else None
            }
        elif operation == "get_saga_chapters":
            saga_id_param: str = payload.get("saga_id", "")
            limit = payload.get("limit", 5)
            chapters = await self._get_saga_chapters(saga_id_param, limit=limit, trace_id=trace_id)
            result_payload = {
                "chapters": [c.to_dict() for c in chapters],
                "count": len(chapters),
            }
        elif operation == "get_all_sagas":
            sagas = await self.get_all_sagas(trace_id=trace_id)
            result_payload = {
                "sagas": sagas,
                "count": len(sagas),
            }
        elif operation == "archive_timed_out":
            archived = await self.archive_timed_out_sagas(trace_id=trace_id)
            result_payload = {
                "archived": archived,
                "count": len(archived),
            }
        elif operation == "get_active_sagas":
            active = await self._get_active_sagas(trace_id=trace_id)
            result_payload = {
                "active_sagas": [
                    {
                        "saga_id": s.saga_id,
                        "saga_name": s.saga_name,
                        "last_chapter": s.last_chapter,
                        "last_told": s.last_told,
                    }
                    for s in active
                ],
                "count": len(active),
                "max_active": self.bard_config.max_active_sagas,
            }
        elif operation == "get_recent_lore":
            # #112: Get recent lore episodes
            limit = payload.get("limit", 5)
            episodes = await self.get_recent_lore(limit=limit, trace_id=trace_id)
            result_payload = {
                "episodes": [e.to_dict() for e in episodes],
                "count": len(episodes),
            }
        elif operation == "get_saga_chain":
            # #113: Get all chapters of a saga
            saga_id_param = payload.get("saga_id", "")
            episodes = await self.get_saga_chain(saga_id=saga_id_param, trace_id=trace_id)
            result_payload = {
                "chapters": [e.to_dict() for e in episodes],
                "count": len(episodes),
            }
        elif operation == "get_cross_channel_story":
            # #114: Show story travel across channels
            saga_id_param = payload.get("saga_id", "")
            cross_channel_chapters = await self.get_cross_channel_story(
                saga_id=saga_id_param, trace_id=trace_id
            )
            result_payload = {
                "chapters": cross_channel_chapters,
                "count": len(cross_channel_chapters),
            }
        elif operation == "get_saga_statistics_by_captain":
            # #115: Get saga stats grouped by Captain
            stats = await self.get_saga_statistics_by_captain(trace_id=trace_id)
            result_payload = {
                "statistics": stats,
                "captain_count": len(stats),
            }
        elif operation == "archive_saga":
            # #125, #126: Archive saga with summary
            saga_id_param = payload.get("saga_id", "")
            if not saga_id_param:
                result_payload = {"error": "saga_id is required for archive_saga"}
            else:
                try:
                    archive_result = await self.archive_saga(
                        saga_id=saga_id_param, trace_id=trace_id
                    )
                    result_payload = {
                        "archived": True,
                        **archive_result,
                    }
                except ValueError as e:
                    result_payload = {"error": str(e), "archived": False}
        elif operation == "get_archived_saga":
            # #125, #126: Get archived saga with summary
            saga_id_param = payload.get("saga_id", "")
            archived_saga = await self.get_archived_saga(saga_id=saga_id_param, trace_id=trace_id)
            result_payload = {
                "saga": archived_saga,
                "found": archived_saga is not None,
            }
        else:
            result_payload = {"error": f"Unknown operation: {operation}"}

        return AgentMessage(
            source_agent=self.name,
            target_agent=msg.source_agent,
            intent="bard_result",
            payload=result_payload,
            trace_id=trace_id,
        )

    # =========================================================================
    # Main Operations
    # =========================================================================

    async def salt_response(
        self,
        clean_response: str,
        storm_mode: bool = False,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> SaltResult:
        """
        Add flavor to a clean response with a story tidbit.

        The Bard adds tidbits based on probability. During storm mode,
        no tidbits are added. If an active saga exists, there's a chance
        to continue it rather than generate a standalone tidbit.

        Args:
            clean_response: The response to potentially salt with a tidbit.
            storm_mode: If True, never add tidbits (urgent situation).
            channel: Optional channel where this is being told (cli, telegram, etc.).
            trace_id: Optional trace ID for logging.

        Returns:
            SaltResult with the (potentially) salted response and metadata.
        """
        # Never during Storm Mode
        if storm_mode:
            logger.debug(
                "[WHISPER] Storm mode active, skipping tidbit",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return SaltResult(
                original_response=clean_response,
                salted_response=clean_response,
                tidbit_added=False,
                storm_mode_skipped=True,
            )

        # Roll the dice for whether to add a tidbit at all
        if random.random() > self.bard_config.tidbit_probability:
            logger.debug(
                "[WHISPER] Probability check failed, no tidbit",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )
            return SaltResult(
                original_response=clean_response,
                salted_response=clean_response,
                tidbit_added=False,
            )

        # Select tidbit type based on weights from LORE_SYSTEM.md Section 4.2 (#108)
        # 30% continue saga, 20% start saga, 50% standalone
        return await self._select_and_add_tidbit(
            clean_response=clean_response,
            channel=channel,
            trace_id=trace_id,
        )

    async def _select_and_add_tidbit(
        self,
        clean_response: str,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> SaltResult:
        """
        Select and add a tidbit based on weighted probabilities (#108).

        Selection weights from LORE_SYSTEM.md Section 4.2:
        - 30% continue active saga (if one exists)
        - 20% start new saga
        - 50% standalone tidbit

        Falls back gracefully if saga operations fail.

        Args:
            clean_response: The response to salt.
            channel: Optional channel where this is being told.
            trace_id: Optional trace ID for logging.

        Returns:
            SaltResult with the salted response and metadata.
        """
        roll = random.random()
        continue_threshold = self.bard_config.continue_saga_weight
        start_threshold = continue_threshold + self.bard_config.start_saga_weight

        # 30% chance to continue an active saga
        if roll < continue_threshold:
            active_saga = await self._get_active_saga(trace_id=trace_id)
            if active_saga:
                try:
                    tidbit, chapter = await self._continue_saga(
                        active_saga, channel=channel, trace_id=trace_id
                    )
                    salted = f"{clean_response}\n\n_{tidbit}_"

                    logger.info(
                        f"[BEACON] Continued saga '{active_saga.saga_name}' chapter {chapter}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )

                    return SaltResult(
                        original_response=clean_response,
                        salted_response=salted,
                        tidbit_added=True,
                        tidbit=tidbit,
                        saga_id=active_saga.saga_id,
                        chapter=chapter,
                        is_continuation=True,
                    )
                except SagaLifecycleError as e:
                    logger.debug(
                        f"[WHISPER] Saga continuation blocked: {e}",
                        extra={"trace_id": trace_id, "agent_name": self.name},
                    )
                    # Fall through to standalone tidbit

        # 20% chance to start a new saga
        elif roll < start_threshold:
            try:
                tidbit, saga_id, chapter = await self.start_new_saga(
                    channel=channel, trace_id=trace_id
                )
                salted = f"{clean_response}\n\n_{tidbit}_"

                logger.info(
                    f"[BEACON] Started new saga chapter {chapter}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )

                return SaltResult(
                    original_response=clean_response,
                    salted_response=salted,
                    tidbit_added=True,
                    tidbit=tidbit,
                    saga_id=saga_id,
                    chapter=chapter,
                    is_continuation=False,
                )
            except SagaLifecycleError as e:
                logger.debug(
                    f"[WHISPER] New saga blocked: {e}",
                    extra={"trace_id": trace_id, "agent_name": self.name},
                )
                # Fall through to standalone tidbit

        # 50% standalone tidbit (or fallback from above)
        tidbit = self._generate_standalone_tidbit()
        salted = f"{clean_response}\n\n_{tidbit}_"

        logger.info(
            "[BEACON] Added standalone tidbit to response",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return SaltResult(
            original_response=clean_response,
            salted_response=salted,
            tidbit_added=True,
            tidbit=tidbit,
        )

    # =========================================================================
    # Saga Management
    # =========================================================================

    async def _get_active_saga(
        self,
        trace_id: str | None = None,
    ) -> ActiveSaga | None:
        """
        Get the most recent unfinished saga for this Captain.

        A saga is considered active if:
        - It has fewer than max_saga_chapters
        - It hasn't timed out (inactive for more than saga_timeout_days)

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            ActiveSaga if one exists, None otherwise.
        """
        max_chapters = self.bard_config.max_saga_chapters
        timeout_ms = int(self.bard_config.saga_timeout_days * 24 * 60 * 60 * 1000)
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - timeout_ms

        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id, le.saga_name as saga_name,
             max(le.chapter) as last_chapter, max(le.told_at) as last_told
        WHERE last_chapter < $max_chapters
        RETURN saga_id, saga_name, last_chapter, last_told
        ORDER BY last_told DESC
        LIMIT 1
        """

        result = await self.neo4j.execute_query(
            query,
            {
                "captain_uuid": self.captain_uuid,
                "max_chapters": max_chapters,
            },
            trace_id=trace_id,
        )

        if not result:
            return None

        row = result[0]
        last_told = row["last_told"]

        # Check if saga has timed out
        is_timed_out = last_told < cutoff_ms

        return ActiveSaga(
            saga_id=row["saga_id"],
            saga_name=row["saga_name"],
            last_chapter=row["last_chapter"],
            last_told=row["last_told"],
            is_timed_out=is_timed_out,
        )

    async def _get_active_sagas(
        self,
        trace_id: str | None = None,
    ) -> list[ActiveSaga]:
        """
        Get all active (unfinished, non-timed-out) sagas for this Captain.

        Used to enforce the max_active_sagas limit.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            List of ActiveSaga objects that are still continuable.
        """
        max_chapters = self.bard_config.max_saga_chapters
        timeout_ms = int(self.bard_config.saga_timeout_days * 24 * 60 * 60 * 1000)
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - timeout_ms

        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id, le.saga_name as saga_name,
             max(le.chapter) as last_chapter, max(le.told_at) as last_told
        WHERE last_chapter < $max_chapters AND last_told >= $cutoff_ms
        RETURN saga_id, saga_name, last_chapter, last_told
        ORDER BY last_told DESC
        """

        results = await self.neo4j.execute_query(
            query,
            {
                "captain_uuid": self.captain_uuid,
                "max_chapters": max_chapters,
                "cutoff_ms": cutoff_ms,
            },
            trace_id=trace_id,
        )

        return [
            ActiveSaga(
                saga_id=row["saga_id"],
                saga_name=row["saga_name"],
                last_chapter=row["last_chapter"],
                last_told=row["last_told"],
            )
            for row in results
        ]

    def _can_add_chapter(self, saga: ActiveSaga) -> tuple[bool, float]:
        """
        Check if enough time has passed to add a new chapter.

        Args:
            saga: The saga to check.

        Returns:
            Tuple of (can_add, hours_remaining). hours_remaining is 0 if can_add is True.
        """
        min_interval_ms = int(self.bard_config.min_chapter_interval_hours * 60 * 60 * 1000)
        now_ms = int(time.time() * 1000)
        time_since_last = now_ms - saga.last_told

        if time_since_last >= min_interval_ms:
            return True, 0.0

        remaining_ms = min_interval_ms - time_since_last
        hours_remaining = remaining_ms / (60 * 60 * 1000)
        return False, hours_remaining

    async def archive_timed_out_sagas(
        self,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Mark timed-out sagas as complete by adding a closing chapter.

        This method finds all sagas that have exceeded saga_timeout_days
        of inactivity and closes them with a special "tale fades" chapter.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            List of archived saga info dicts.
        """
        max_chapters = self.bard_config.max_saga_chapters
        timeout_ms = int(self.bard_config.saga_timeout_days * 24 * 60 * 60 * 1000)
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - timeout_ms

        # Find timed-out sagas that aren't already complete
        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id, le.saga_name as saga_name,
             max(le.chapter) as last_chapter, max(le.told_at) as last_told
        WHERE last_chapter < $max_chapters AND last_told < $cutoff_ms
        RETURN saga_id, saga_name, last_chapter, last_told
        """

        results = await self.neo4j.execute_query(
            query,
            {
                "captain_uuid": self.captain_uuid,
                "max_chapters": max_chapters,
                "cutoff_ms": cutoff_ms,
            },
            trace_id=trace_id,
        )

        archived = []
        for row in results:
            saga_id = row["saga_id"]
            saga_name = row["saga_name"]
            last_chapter = row["last_chapter"]
            last_told = row["last_told"]

            days_inactive = int((now_ms - last_told) / (24 * 60 * 60 * 1000))

            # Add a closing chapter to mark the saga as complete
            closing_content = (
                f"And so the tale of {saga_name} fades into the mists of memory, "
                f"waiting perhaps for another day to be told..."
            )

            # Force complete by setting chapter to max_chapters
            await self._save_episode(
                saga_id=saga_id,
                saga_name=saga_name,
                chapter=max_chapters,  # This marks it as complete
                content=closing_content,
                trace_id=trace_id,
            )

            # Archive the saga with summary and SUMMARIZES relationships (#125, #126)
            archive_result = await self.archive_saga(saga_id=saga_id, trace_id=trace_id)

            archived.append(
                {
                    "saga_id": saga_id,
                    "saga_name": saga_name,
                    "last_chapter": last_chapter,
                    "days_inactive": days_inactive,
                    "closing_chapter": max_chapters,
                    "note_uuid": archive_result.get("note_uuid"),
                    "summary": archive_result.get("summary"),
                }
            )

            logger.info(
                f"[CHART] Archived timed-out saga '{saga_name}' after {days_inactive} days",
                extra={"trace_id": trace_id, "agent_name": self.name},
            )

        return archived

    async def _get_saga_chapters(
        self,
        saga_id: str,
        limit: int = 5,
        trace_id: str | None = None,
    ) -> list[LoreEpisode]:
        """
        Fetch chapters of a saga for context.

        Args:
            saga_id: The saga ID to fetch chapters for.
            limit: Maximum chapters to return.
            trace_id: Optional trace ID for logging.

        Returns:
            List of LoreEpisode objects ordered by chapter.
        """
        query = """
        MATCH (le:LoreEpisode {saga_id: $saga_id})-[:TOLD_TO]->(p:Person)
        RETURN le.uuid as uuid, le.saga_id as saga_id, le.saga_name as saga_name,
               le.chapter as chapter, le.content as content, le.channel as channel,
               le.told_at as told_at, le.created_at as created_at,
               p.uuid as captain_uuid
        ORDER BY le.chapter ASC
        LIMIT $limit
        """

        results = await self.neo4j.execute_query(
            query,
            {"saga_id": saga_id, "limit": limit},
            trace_id=trace_id,
        )

        return [
            LoreEpisode(
                uuid=row["uuid"],
                saga_id=row["saga_id"],
                saga_name=row["saga_name"],
                chapter=row["chapter"],
                content=row["content"],
                told_at=row["told_at"],
                created_at=row["created_at"],
                captain_uuid=row.get("captain_uuid"),
                channel=row.get("channel"),
            )
            for row in results
        ]

    async def _continue_saga(
        self,
        saga: ActiveSaga,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[str, int]:
        """
        Generate the next chapter of an ongoing saga.

        For now, this uses a canonical tidbit as the continuation.
        A full implementation would use LLM to generate contextual content.

        Enforces saga lifecycle rules:
        - Saga must not have timed out (#120)
        - Minimum time between chapters must be respected (#121)
        - Saga must not have reached max chapters (#118)

        Args:
            saga: The active saga to continue.
            channel: Optional channel where this chapter is told.
            trace_id: Optional trace ID for logging.

        Returns:
            Tuple of (tidbit content, chapter number).

        Raises:
            SagaTimedOutError: If saga has exceeded timeout period.
            ChapterTooSoonError: If not enough time has passed since last chapter.
            SagaCompleteError: If saga has reached max chapters.
        """
        # Check for timeout (#120)
        if saga.is_timed_out:
            now_ms = int(time.time() * 1000)
            days_inactive = int((now_ms - saga.last_told) / (24 * 60 * 60 * 1000))
            raise SagaTimedOutError(saga.saga_name, days_inactive)

        # Check for max chapters reached (#118)
        if saga.last_chapter >= self.bard_config.max_saga_chapters:
            raise SagaCompleteError(saga.saga_name, self.bard_config.max_saga_chapters)

        # Check minimum chapter interval (#121)
        can_add, hours_remaining = self._can_add_chapter(saga)
        if not can_add:
            raise ChapterTooSoonError(
                saga.saga_name,
                hours_remaining,
                self.bard_config.min_chapter_interval_hours,
            )

        new_chapter = saga.last_chapter + 1
        content = self._generate_standalone_tidbit()

        # Persist the new chapter
        await self._save_episode(
            saga_id=saga.saga_id,
            saga_name=saga.saga_name,
            chapter=new_chapter,
            content=content,
            channel=channel,
            trace_id=trace_id,
        )

        return content, new_chapter

    async def start_new_saga(
        self,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[str, str, int]:
        """
        Start a new saga with chapter 1.

        Enforces saga lifecycle rules:
        - Maximum active sagas limit must not be exceeded (#119)

        Args:
            channel: Optional channel where this saga starts.
            trace_id: Optional trace ID for logging.

        Returns:
            Tuple of (tidbit content, saga_id, chapter number).

        Raises:
            SagaLimitReachedError: If max_active_sagas limit is reached.
        """
        # Check active saga limit (#119)
        active_sagas = await self._get_active_sagas(trace_id=trace_id)
        if len(active_sagas) >= self.bard_config.max_active_sagas:
            active_names = [s.saga_name for s in active_sagas]
            raise SagaLimitReachedError(
                self.bard_config.max_active_sagas,
                active_names,
            )

        saga_id = str(uuid.uuid4())
        saga_name = generate_saga_name()
        content = self._generate_standalone_tidbit()

        await self._save_episode(
            saga_id=saga_id,
            saga_name=saga_name,
            chapter=1,
            content=content,
            channel=channel,
            trace_id=trace_id,
        )

        logger.info(
            f"[BEACON] Started new saga: '{saga_name}'",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return content, saga_id, 1

    async def _save_episode(
        self,
        saga_id: str,
        saga_name: str,
        chapter: int,
        content: str,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> str:
        """
        Persist a LoreEpisode to the graph.

        Creates the LoreEpisode node with:
            - TOLD_TO relationship to the Captain (Person)
            - EXPANDS_UPON relationship to previous chapter (if exists)

        Args:
            saga_id: Unique identifier for the saga.
            saga_name: Human-readable name of the saga.
            chapter: Chapter number (1-indexed).
            content: The story content.
            channel: Optional channel where this was told (cli, telegram, etc.).
            trace_id: Optional trace ID for logging.

        Returns:
            UUID of the created LoreEpisode.
        """
        episode_uuid = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)

        # Create episode with TOLD_TO relationship
        query = """
        CREATE (le:LoreEpisode {
            uuid: $uuid,
            saga_id: $saga_id,
            saga_name: $saga_name,
            chapter: $chapter,
            content: $content,
            channel: $channel,
            told_at: $now_ms,
            created_at: $now_ms
        })
        WITH le
        MATCH (p:Person {uuid: $captain_uuid})
        CREATE (le)-[:TOLD_TO {created_at: $now_ms}]->(p)
        WITH le
        OPTIONAL MATCH (prev:LoreEpisode {saga_id: $saga_id, chapter: $prev_chapter})
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            CREATE (le)-[:EXPANDS_UPON {created_at: $now_ms}]->(prev)
        )
        RETURN le.uuid as uuid
        """

        await self.neo4j.execute_query(
            query,
            {
                "uuid": episode_uuid,
                "saga_id": saga_id,
                "saga_name": saga_name,
                "chapter": chapter,
                "content": content,
                "channel": channel,
                "now_ms": now_ms,
                "captain_uuid": self.captain_uuid,
                "prev_chapter": chapter - 1,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[CHART] Saved LoreEpisode {saga_name} ch.{chapter}",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return episode_uuid

    def _generate_standalone_tidbit(self) -> str:
        """
        Generate a standalone tidbit from the canonical collection.

        Returns:
            A random canonical tidbit string.
        """
        return random.choice(self.CANONICAL_TIDBITS)

    # =========================================================================
    # Query Operations (#112, #113, #114, #115)
    # =========================================================================

    async def get_recent_lore(
        self,
        limit: int = 5,
        trace_id: str | None = None,
    ) -> list[LoreEpisode]:
        """
        Get the most recent story episodes told to this Captain (#112).

        Retrieves lore episodes ordered by told_at descending, allowing
        the Bard to see what stories were recently told.

        Reference: specs/architecture/LORE_SYSTEM.md Section 6.1

        Args:
            limit: Maximum number of episodes to return.
            trace_id: Optional trace ID for logging.

        Returns:
            List of LoreEpisode objects ordered by told_at DESC.
        """
        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        RETURN le.uuid as uuid, le.saga_id as saga_id, le.saga_name as saga_name,
               le.chapter as chapter, le.content as content, le.channel as channel,
               le.told_at as told_at, le.created_at as created_at,
               p.uuid as captain_uuid
        ORDER BY le.told_at DESC
        LIMIT $limit
        """

        results = await self.neo4j.execute_query(
            query,
            {"captain_uuid": self.captain_uuid, "limit": limit},
            trace_id=trace_id,
        )

        return [
            LoreEpisode(
                uuid=row["uuid"],
                saga_id=row["saga_id"],
                saga_name=row["saga_name"],
                chapter=row["chapter"],
                content=row["content"],
                told_at=row["told_at"],
                created_at=row["created_at"],
                captain_uuid=row.get("captain_uuid"),
                channel=row.get("channel"),
            )
            for row in results
        ]

    async def get_saga_chain(
        self,
        saga_id: str,
        trace_id: str | None = None,
    ) -> list[LoreEpisode]:
        """
        Get all chapters of a saga in order (#113).

        Retrieves the complete saga chain with all chapters and metadata,
        ordered by chapter number ascending.

        Reference: specs/architecture/LORE_SYSTEM.md Section 6.2

        Args:
            saga_id: The saga ID to retrieve.
            trace_id: Optional trace ID for logging.

        Returns:
            List of LoreEpisode objects ordered by chapter ASC.
        """
        # Use existing _get_saga_chapters with a high limit
        return await self._get_saga_chapters(
            saga_id,
            limit=self.bard_config.max_saga_chapters,
            trace_id=trace_id,
        )

    async def get_cross_channel_story(
        self,
        saga_id: str,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Show how a story traveled across channels (#114).

        Retrieves saga chapters with channel information, showing
        how the narrative progressed across different communication
        channels (CLI, Telegram, etc.).

        Reference: specs/architecture/LORE_SYSTEM.md Section 6.3

        Args:
            saga_id: The saga ID to analyze.
            trace_id: Optional trace ID for logging.

        Returns:
            List of chapter info dicts with channel details.
        """
        query = """
        MATCH (le:LoreEpisode {saga_id: $saga_id})-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le ORDER BY le.chapter ASC
        RETURN le.chapter as chapter, le.content as content,
               le.channel as channel, le.told_at as told_at,
               le.saga_name as saga_name
        """

        results = await self.neo4j.execute_query(
            query,
            {"saga_id": saga_id, "captain_uuid": self.captain_uuid},
            trace_id=trace_id,
        )

        return [
            {
                "chapter": row["chapter"],
                "content": row["content"],
                "channel": row.get("channel"),
                "told_at": row["told_at"],
                "saga_name": row.get("saga_name"),
            }
            for row in results
        ]

    async def get_saga_statistics_by_captain(
        self,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get saga statistics grouped by Captain (#115).

        Counts total sagas and chapters for each Captain who has
        received lore episodes. Useful for admin/analytics views.

        Reference: specs/architecture/LORE_SYSTEM.md Section 6.4

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            List of statistics dicts grouped by captain_uuid.
        """
        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person)
        WITH p.uuid as captain_uuid, p.name as captain_name,
             le.saga_id as saga_id, count(le) as chapter_count
        WITH captain_uuid, captain_name,
             count(DISTINCT saga_id) as total_sagas,
             sum(chapter_count) as total_chapters
        RETURN captain_uuid, captain_name, total_sagas, total_chapters
        ORDER BY total_chapters DESC
        """

        results = await self.neo4j.execute_query(
            query,
            {},
            trace_id=trace_id,
        )

        return [
            {
                "captain_uuid": row["captain_uuid"],
                "captain_name": row.get("captain_name"),
                "total_sagas": row["total_sagas"],
                "total_chapters": row["total_chapters"],
            }
            for row in results
        ]

    async def get_all_sagas(
        self,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all sagas told to this Captain.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            List of saga summaries with id, name, chapter count, and status.
        """
        max_chapters = self.bard_config.max_saga_chapters

        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id, le.saga_name as saga_name,
             max(le.chapter) as chapter_count, max(le.told_at) as last_told
        RETURN saga_id, saga_name, chapter_count, last_told,
               CASE WHEN chapter_count >= $max_chapters
                    THEN 'complete' ELSE 'active' END as status
        ORDER BY last_told DESC
        LIMIT $limit
        """

        results = await self.neo4j.execute_query(
            query,
            {
                "captain_uuid": self.captain_uuid,
                "max_chapters": max_chapters,
                "limit": self.bard_config.default_query_limit,
            },
            trace_id=trace_id,
        )

        return [
            {
                "saga_id": row["saga_id"],
                "saga_name": row["saga_name"],
                "chapter_count": row["chapter_count"],
                "last_told": row["last_told"],
                "status": row["status"],
            }
            for row in results
        ]

    async def get_saga_by_id(
        self,
        saga_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Get a complete saga with all its chapters.

        Args:
            saga_id: The saga ID to retrieve.
            trace_id: Optional trace ID for logging.

        Returns:
            Saga info with chapters, or None if not found.
        """
        chapters = await self._get_saga_chapters(
            saga_id,
            limit=self.bard_config.max_saga_chapters,
            trace_id=trace_id,
        )

        if not chapters:
            return None

        first_chapter = chapters[0]
        return {
            "saga_id": saga_id,
            "saga_name": first_chapter.saga_name,
            "chapter_count": len(chapters),
            "chapters": [c.to_dict() for c in chapters],
            "status": "complete"
            if len(chapters) >= self.bard_config.max_saga_chapters
            else "active",
        }

    # =========================================================================
    # Statistics
    # =========================================================================

    # =========================================================================
    # Saga Archival (#125, #126)
    # =========================================================================

    async def archive_saga(
        self,
        saga_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Archive a saga by generating a summary and creating SUMMARIZES relationships (#125, #126).

        When a saga is complete or timed out, this method:
        1. Gathers all chapters of the saga
        2. Generates a summary of the saga using LLM
        3. Creates a Note node containing the summary
        4. Creates SUMMARIZES relationships from Note to all LoreEpisodes
        5. Marks all episodes as archived

        Reference: specs/architecture/LORE_SYSTEM.md Section 3.3

        Args:
            saga_id: The saga ID to archive.
            trace_id: Optional trace ID for logging.

        Returns:
            Dict with archive info including note_uuid and summary.

        Raises:
            ValueError: If saga doesn't exist or has no episodes.
        """
        # Get all episodes of the saga
        episodes = await self._get_saga_chapters(
            saga_id,
            limit=self.bard_config.max_saga_chapters,
            trace_id=trace_id,
        )

        if not episodes:
            raise ValueError(f"No episodes found for saga: {saga_id}")

        saga_name = episodes[0].saga_name
        chapter_count = len(episodes)

        # Generate summary from chapters
        summary = await self._generate_saga_summary(episodes, trace_id=trace_id)

        # Create Note node and SUMMARIZES relationships
        note_uuid = await self._create_archive_note(
            saga_id=saga_id,
            saga_name=saga_name,
            summary=summary,
            trace_id=trace_id,
        )

        logger.info(
            f"[CHART] Archived saga '{saga_name}' with {chapter_count} chapters",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return {
            "saga_id": saga_id,
            "saga_name": saga_name,
            "chapter_count": chapter_count,
            "note_uuid": note_uuid,
            "summary": summary,
        }

    async def _generate_saga_summary(
        self,
        episodes: list[LoreEpisode],
        trace_id: str | None = None,
    ) -> str:
        """
        Generate a summary of a saga from its episodes (#125).

        Creates a brief summary capturing the essence of the saga's narrative arc.

        Args:
            episodes: List of LoreEpisode objects (ordered by chapter).
            trace_id: Optional trace ID for logging.

        Returns:
            Summary string for the saga.
        """
        if not episodes:
            return "An untold tale, lost to the digital mists."

        saga_name = episodes[0].saga_name

        # For now, generate a simple summary from the content
        # A full implementation would use LLM with all chapter content
        first_chapter = (
            episodes[0].content[:100] + "..."
            if len(episodes[0].content) > 100
            else episodes[0].content
        )
        last_chapter = (
            episodes[-1].content[:100] + "..."
            if len(episodes[-1].content) > 100
            else episodes[-1].content
        )

        summary = (
            f"The tale of '{saga_name}' spans {len(episodes)} chapters, "
            f'beginning with: "{first_chapter}" '
            f'and concluding with: "{last_chapter}"'
        )

        logger.debug(
            f"[CHART] Generated summary for saga '{saga_name}'",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return summary

    async def _create_archive_note(
        self,
        saga_id: str,
        saga_name: str,
        summary: str,
        trace_id: str | None = None,
    ) -> str:
        """
        Create a Note node and SUMMARIZES relationships for archived saga (#126).

        Creates:
        - Note node with saga summary
        - SUMMARIZES relationships from Note to all LoreEpisodes
        - Sets archived=true on all episodes

        Args:
            saga_id: The saga ID being archived.
            saga_name: Human-readable saga name.
            summary: Generated summary content.
            trace_id: Optional trace ID for logging.

        Returns:
            UUID of the created Note node.
        """
        note_uuid = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)

        query = """
        CREATE (n:Note {
            uuid: $note_uuid,
            title: $title,
            content: $summary,
            source: 'lore_archive',
            created_at: $now_ms
        })
        WITH n
        MATCH (le:LoreEpisode {saga_id: $saga_id})
        SET le.archived = true
        WITH n, collect(le) as episodes
        UNWIND episodes as ep
        CREATE (n)-[:SUMMARIZES {created_at: $now_ms}]->(ep)
        RETURN n.uuid as uuid
        """

        await self.neo4j.execute_query(
            query,
            {
                "note_uuid": note_uuid,
                "title": f"Saga: {saga_name}",
                "summary": summary,
                "saga_id": saga_id,
                "now_ms": now_ms,
            },
            trace_id=trace_id,
        )

        logger.debug(
            f"[CHART] Created archive Note {note_uuid} for saga '{saga_name}'",
            extra={"trace_id": trace_id, "agent_name": self.name},
        )

        return note_uuid

    async def get_archived_saga(
        self,
        saga_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Get an archived saga with its summary note.

        Args:
            saga_id: The saga ID to retrieve.
            trace_id: Optional trace ID for logging.

        Returns:
            Dict with saga info and summary, or None if not found/not archived.
        """
        query = """
        MATCH (n:Note {source: 'lore_archive'})-[:SUMMARIZES]->(le:LoreEpisode {saga_id: $saga_id})
        WITH n, le
        ORDER BY le.chapter ASC
        WITH n, collect(le) as episodes
        RETURN n.uuid as note_uuid, n.title as title, n.content as summary,
               n.created_at as archived_at,
               [ep in episodes | {
                   uuid: ep.uuid,
                   chapter: ep.chapter,
                   content: ep.content,
                   channel: ep.channel,
                   told_at: ep.told_at
               }] as chapters
        LIMIT 1
        """

        results = await self.neo4j.execute_query(
            query,
            {"saga_id": saga_id},
            trace_id=trace_id,
        )

        if not results:
            return None

        row = results[0]
        return {
            "saga_id": saga_id,
            "note_uuid": row["note_uuid"],
            "title": row["title"],
            "summary": row["summary"],
            "archived_at": row["archived_at"],
            "chapters": row["chapters"],
        }

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_lore_statistics(
        self,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Get statistics about the Captain's lore collection.

        Args:
            trace_id: Optional trace ID for logging.

        Returns:
            Dictionary with lore statistics.
        """
        query = """
        MATCH (le:LoreEpisode)-[:TOLD_TO]->(p:Person {uuid: $captain_uuid})
        WITH le.saga_id as saga_id, count(le) as chapter_count
        RETURN
            count(saga_id) as total_sagas,
            sum(chapter_count) as total_episodes,
            avg(chapter_count) as avg_chapters_per_saga
        """

        result = await self.neo4j.execute_query(
            query,
            {"captain_uuid": self.captain_uuid},
            trace_id=trace_id,
        )

        stats = result[0] if result else {}

        return {
            "total_sagas": stats.get("total_sagas", 0),
            "total_episodes": stats.get("total_episodes", 0),
            "avg_chapters_per_saga": round(stats.get("avg_chapters_per_saga", 0) or 0, 1),
            "captain_uuid": self.captain_uuid,
            "canonical_tidbits_available": len(self.CANONICAL_TIDBITS),
        }


# =============================================================================
# Export
# =============================================================================

__all__ = [
    "CANONICAL_TIDBITS",
    "SAGA_TIDBITS",
    "STANDALONE_TIDBITS",
    "ActiveSaga",
    "BardConfig",
    "BardOfTheBilge",
    "ChapterTooSoonError",
    "LoreEpisode",
    "SagaCompleteError",
    "SagaLifecycleError",
    "SagaLimitReachedError",
    "SagaTimedOutError",
    "SaltResult",
    "generate_saga_name",
]
