# Refactor Orchestrator for Intent Classification

## Metadata
- **ID**: T020
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: completed
- **Assignee**: @backend-engineer

## Specs
- Primary: [AGENTS.md](../../specs/architecture/AGENTS.md) Section 1.1
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [x] T017 - Simple Orchestrator (Sprint 1)
- [x] T016 - Base Agent class

## Context
The Sprint 1 Orchestrator is a simple conversational loop. Sprint 2 requires it to classify user intent and delegate to specialized sub-agents. This refactor transforms the Orchestrator into the "CEO" that routes requests appropriately.

## Requirements
- [x] Refactor `src/klabautermann/agents/orchestrator.py`:

### Intent Classification
- [x] Implement `_classify_intent()` method
- [x] Detect search intents: "who", "what", "when", "where", "find", "tell me about"
- [x] Detect action intents: "send", "email", "schedule", "create", "draft"
- [x] Detect ingestion triggers: "I met", "I talked to", "I'm working on", new people/projects
- [x] Default to conversation for general chat

### Intent Model
- [x] Create `IntentClassification` Pydantic model (already existed in core/models.py)

### Search-First Rule
- [x] For factual questions, ALWAYS delegate to Researcher first (stub in place, T021 for full impl)
- [x] Never generate answers from training data for graph-stored facts (system prompt updated)
- [x] Return "I don't have that in The Locker" if search returns empty (in system prompt)

### System Prompt Update
- [x] Update system prompt to include intent classification rules
- [x] Include delegation behavior description
- [x] Add personality guidelines

## Acceptance Criteria
- [x] "Who is Sarah?" classified as SEARCH intent
- [x] "Send an email to John" classified as ACTION intent
- [x] "I met Tom from Google" triggers INGESTION
- [x] "Hello, how are you?" classified as CONVERSATION
- [x] Search-first rule enforced for factual questions
- [x] All intents logged with trace ID

## Development Notes

### Files Modified
- `src/klabautermann/agents/orchestrator.py` - Major refactor for intent classification
- `tests/unit/test_intent_classification.py` - New unit test file (26 tests)

### Implementation
1. Added `_classify_intent()` method with keyword-based classification
2. Added intent dispatch in `handle_user_input()` routing to appropriate handlers
3. Added handler stubs: `_handle_search()`, `_handle_action()`, `_handle_conversation()`
4. Added `_apply_personality()` method (pass-through for now, Bard integration in T021+)
5. Updated `SYSTEM_PROMPT` with intent classification rules and search-first principle
6. Added `ClassVar` annotations for keyword lists per linter requirements
7. Added background task set to properly manage fire-and-forget ingestion tasks

### Decisions Made
- **Keyword-based classification**: Fast and deterministic for common patterns. LLM fallback can be added in future iterations for ambiguous cases.
- **Handler stubs**: Search and action handlers are stubs that fall back to conversation. Full delegation to Researcher/Executor comes in T021.
- **Intent priority**: Search > Action > Ingestion > Conversation (first match wins)
- **Confidence scores**: 0.9 for keyword matches (SEARCH, ACTION), 0.8 for ingestion, 0.7 for conversation default

### Patterns Established
- Intent classification keywords as `ClassVar[list[str]]` class attributes
- Handler methods prefixed with `_handle_` for intent dispatch
- Background tasks stored in `_background_tasks` set with done callback for cleanup

### Testing
- 26 unit tests covering all intent types and edge cases
- Tests verify correct IntentType, confidence scores, and field population
- Case insensitivity tested
- Priority/first-match behavior tested

### Next Steps (T021)
- Implement `_dispatch_and_wait()` for synchronous agent delegation
- Wire up Researcher agent for SEARCH intents
- Wire up Executor agent for ACTION intents
- Add fire-and-forget dispatch to Ingestor for INGESTION intents
