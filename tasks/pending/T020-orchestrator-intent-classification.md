# Refactor Orchestrator for Intent Classification

## Metadata
- **ID**: T020
- **Priority**: P0
- **Category**: subagent
- **Effort**: L
- **Status**: pending
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
- [ ] Refactor `src/klabautermann/agents/orchestrator.py`:

### Intent Classification
- [ ] Implement `_classify_intent()` method
- [ ] Detect search intents: "who", "what", "when", "where", "find", "tell me about"
- [ ] Detect action intents: "send", "email", "schedule", "create", "draft"
- [ ] Detect ingestion triggers: "I met", "I talked to", "I'm working on", new people/projects
- [ ] Default to conversation for general chat

### Intent Model
- [ ] Create `IntentClassification` Pydantic model:
  ```python
  class IntentType(str, Enum):
      SEARCH = "search"
      ACTION = "action"
      INGESTION = "ingestion"
      CONVERSATION = "conversation"

  class IntentClassification(BaseModel):
      type: IntentType
      confidence: float
      query: Optional[str] = None  # For search
      action: Optional[str] = None  # For action
      context_query: Optional[str] = None  # For action context lookup
  ```

### Search-First Rule
- [ ] For factual questions, ALWAYS delegate to Researcher first
- [ ] Never generate answers from training data for graph-stored facts
- [ ] Return "I don't have that in The Locker" if search returns empty

### System Prompt Update
- [ ] Update system prompt to include intent classification rules
- [ ] Include delegation behavior description
- [ ] Add personality guidelines

## Acceptance Criteria
- [ ] "Who is Sarah?" classified as SEARCH intent
- [ ] "Send an email to John" classified as ACTION intent
- [ ] "I met Tom from Google" triggers INGESTION
- [ ] "Hello, how are you?" classified as CONVERSATION
- [ ] Search-first rule enforced for factual questions
- [ ] All intents logged with trace ID

## Implementation Notes

```python
class Orchestrator(BaseAgent):
    """The CEO: routes intents, delegates to sub-agents, synthesizes responses."""

    async def handle_user_input(self, thread_id: str, text: str) -> str:
        """Main entry point for user messages."""
        trace_id = str(uuid.uuid4())

        # 1. Load thread context
        context = await self.memory.get_thread_context(thread_id, limit=15)

        # 2. Classify intent
        intent = await self._classify_intent(text, context, trace_id)
        logger.info(
            f"[CHART] Intent classified",
            extra={"trace_id": trace_id, "intent": intent.type, "confidence": intent.confidence}
        )

        # 3. Dispatch based on intent (delegation comes in T021)
        if intent.type == IntentType.SEARCH:
            # Will delegate to Researcher in T021
            response = await self._handle_search(intent, context, trace_id)
        elif intent.type == IntentType.ACTION:
            # Will delegate to Executor in T021
            response = await self._handle_action(intent, context, trace_id)
        elif intent.type == IntentType.INGESTION:
            # Will fire-and-forget to Ingestor in T021
            response = await self._handle_conversation(text, context, trace_id)
        else:
            response = await self._handle_conversation(text, context, trace_id)

        # 4. Apply personality
        return await self._apply_personality(response, trace_id)

    async def _classify_intent(
        self, text: str, context: list, trace_id: str
    ) -> IntentClassification:
        """Classify user intent using keyword matching and LLM fallback."""
        text_lower = text.lower()

        # Quick keyword checks
        search_keywords = ["who is", "what is", "when did", "where is", "find", "tell me about", "remind me"]
        action_keywords = ["send", "email", "schedule", "create", "draft", "book", "set up"]
        ingest_keywords = ["i met", "i talked to", "i'm working on", "i learned", "i just"]

        for kw in search_keywords:
            if kw in text_lower:
                return IntentClassification(type=IntentType.SEARCH, confidence=0.9, query=text)

        for kw in action_keywords:
            if kw in text_lower:
                return IntentClassification(type=IntentType.ACTION, confidence=0.9, action=text)

        for kw in ingest_keywords:
            if kw in text_lower:
                return IntentClassification(type=IntentType.INGESTION, confidence=0.8)

        # Default to conversation
        return IntentClassification(type=IntentType.CONVERSATION, confidence=0.7)
```

The intent classification uses keyword matching for speed. In future iterations, we can add LLM-based classification for ambiguous cases.
