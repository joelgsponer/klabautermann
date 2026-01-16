# Researcher Zoom Level Support

## Metadata
- **ID**: T057
- **Priority**: P1
- **Category**: subagent
- **Effort**: M
- **Status**: completed

## Specs
- Primary: [MAINAGENT.md](../../specs/MAINAGENT.md) Section 5.2
- Related: [MEMORY.md](../../specs/architecture/MEMORY.md) Section 9

## Dependencies
- [x] T052 - Context Retrieval Cypher Queries (island queries)

## Context
Extend the Researcher agent to support zoom levels (MACRO, MESO, MICRO) for different query granularities. This enables the orchestrator to request appropriate detail levels.

## Requirements
- [x] Add `zoom_level` parameter to Researcher's search interface
- [x] Implement `ZoomLevel` enum: `MACRO`, `MESO`, `MICRO`, `AUTO`
- [x] MACRO: Return Knowledge Island summaries (Community nodes)
- [x] MESO: Return Note/Project context (mid-level)
- [x] MICRO: Return entity facts (current behavior)
- [x] AUTO: Detect zoom level from query text (existing `_classify_search_type` pattern)
- [x] Update `SearchResponse` to include `zoom_level` in response

## Acceptance Criteria
- [x] `zoom_level=macro` returns Community summaries
- [x] `zoom_level=meso` returns Note/Project results
- [x] `zoom_level=micro` returns entity facts (backward compatible)
- [x] `zoom_level=auto` correctly detects level from query
- [x] Response includes which zoom level was used
- [x] Existing search behavior unchanged when zoom_level not specified

## Implementation Notes
Add to `src/klabautermann/agents/researcher.py`:

```python
class ZoomLevel(str, Enum):
    MACRO = "macro"   # Knowledge Islands
    MESO = "meso"     # Notes, Projects
    MICRO = "micro"   # Entity facts
    AUTO = "auto"     # Auto-detect

# Detection patterns (from MEMORY.md):
MACRO_INDICATORS = ["overview", "summary", "themes", "big picture", "main areas"]
MESO_INDICATORS = ["project", "status", "progress", "discussed", "meeting", "notes"]
MICRO_INDICATORS = ["who", "what", "when", "where", "exactly", "specific", "email"]
```

## Development Notes

### Implementation
**Files Modified**:
- `/home/klabautermann/klabautermann3/src/klabautermann/agents/researcher.py`
  - Added `ZoomLevel` enum with AUTO, MACRO, MESO, MICRO levels
  - Added zoom level detection patterns (MACRO_INDICATORS, MESO_INDICATORS, MICRO_INDICATORS)
  - Implemented `_detect_zoom_level()` method with weighted scoring
  - Implemented `_search_macro()` to query Community nodes (Knowledge Islands)
  - Implemented `_search_meso()` to query Note and Project nodes
  - Implemented `_search_micro()` as wrapper around existing semantic search
  - Added `search_with_zoom()` method for zoom-aware searching
  - Updated `process_message()` to support optional zoom_level parameter
  - Updated `SearchResponse` model to include `zoom_level` field
  - Updated `_create_response()` to include zoom_level in payload
  - Added `ZoomLevel` to exports

- `/home/klabautermann/klabautermann3/tests/unit/test_researcher.py`
  - Added comprehensive test suite for zoom level functionality:
    - `TestZoomLevelDetection` class with 9 tests for auto-detection
    - `TestZoomLevelSearches` class with 9 tests for zoom-specific searches
  - All 54 tests passing

### Decisions Made

1. **Weighted Scoring for Auto-Detection**: Used weighted scoring (2x for macro/meso indicators) to prioritize context-specific keywords over generic question words like "what" or "who".

2. **Smart Micro Indicator Filtering**: Generic question words are not counted as micro indicators if macro or meso indicators are already present. This prevents "What's the status of my project?" from being classified as MICRO when it should be MESO.

3. **Backward Compatibility**: When no zoom_level is specified in the payload, the Researcher uses existing behavior (SearchType classification). This ensures zero breaking changes for existing code.

4. **MACRO Search Implementation**: Queries Community nodes with pending task counts, ordered by priority. Returns island summaries formatted for high-level overview.

5. **MESO Search Implementation**: Combines Graphiti search (for Notes) with direct Neo4j Project queries. Searches both by vector similarity and text matching on project names/descriptions.

6. **MICRO Search**: Uses existing `_semantic_search()` method to maintain consistency with current entity retrieval behavior.

### Patterns Established

1. **Zoom Level API Contract**: Orchestrator can send `zoom_level` in payload as string ("macro", "meso", "micro", "auto") and receives zoom_level in response.

2. **Auto-Detection Algorithm**:
   - Count indicators for each level
   - Give higher weight (2x) to context-specific indicators
   - Ignore generic question words when context exists
   - Return highest scoring level

3. **Search Method Pattern**: Each zoom level has its own `_search_<level>()` method that returns a `SearchResponse` with the appropriate `zoom_level` set.

### Testing

**Tests Added** (18 new tests):
- Zoom level detection for MACRO queries (overview, themes, priorities)
- Zoom level detection for MESO queries (project, status, progress)
- Zoom level detection for MICRO queries (specific facts, email, who/what/when)
- MACRO search returns Community/Island summaries
- MESO search returns Notes and Projects
- MICRO search returns entity facts
- Auto-detection correctly identifies all three levels
- Explicit zoom level specification works
- process_message handles zoom_level parameter
- Backward compatibility maintained

**All Tests Passing**: 54/54 tests pass, including all existing tests and new zoom level tests.

### Issues Encountered

1. **Initial Detection Too Aggressive on MICRO**: First implementation gave too much weight to generic question words like "what", causing MESO/MACRO queries to be misclassified as MICRO.

   **Solution**: Added smart filtering to skip generic question words when context-specific indicators (macro/meso) are already present.

2. **Test Failures on Detection**: 4 tests initially failed because the detection algorithm was too simplistic.

   **Solution**: Refined the weighted scoring system to give 2x weight to macro/meso indicators and implemented conditional logic for micro indicators.

### Integration Notes

This implementation is ready for integration with the Orchestrator (MAINAGENT.md Section 5.2). The Orchestrator can now:

1. Request specific zoom levels: `{"query": "...", "zoom_level": "macro"}`
2. Let Researcher auto-detect: `{"query": "...", "zoom_level": "auto"}` (or omit zoom_level)
3. Check which level was used via response payload: `response.payload["zoom_level"]`

Next tasks that depend on this:
- T058+ (if any): Orchestrator integration to use zoom levels in context building
- Future: Add vector search on Note content for better MESO retrieval
