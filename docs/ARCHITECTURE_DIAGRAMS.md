# Architecture Diagrams

Visual diagrams of Klabautermann's architecture using Mermaid for GitHub rendering.

## System Overview

```mermaid
flowchart TB
    subgraph Channels["Communication Layer"]
        CLI[CLI Channel]
        TG[Telegram Channel]
    end

    subgraph Orchestration["Orchestration Layer"]
        ORCH[Orchestrator<br/>Claude Opus 4.5]
    end

    subgraph Agents["Agent Layer"]
        direction LR
        ING[Ingestor<br/>Haiku]
        RES[Researcher<br/>Haiku]
        EXEC[Executor<br/>Sonnet]
        ARCH[Archivist<br/>Haiku]
        SCR[Scribe<br/>Haiku]
    end

    subgraph Memory["Memory Layer"]
        NEO4J[(Neo4j<br/>Knowledge Graph)]
        GRAPHITI[Graphiti<br/>Temporal Memory]
    end

    subgraph External["External Services"]
        GMAIL[Gmail MCP]
        CAL[Calendar MCP]
    end

    CLI --> ORCH
    TG --> ORCH
    ORCH --> ING
    ORCH --> RES
    ORCH --> EXEC
    ORCH --> ARCH
    ORCH --> SCR
    ING --> GRAPHITI
    RES --> GRAPHITI
    ARCH --> GRAPHITI
    SCR --> GRAPHITI
    GRAPHITI --> NEO4J
    EXEC --> GMAIL
    EXEC --> CAL
```

## Message Flow

```mermaid
sequenceDiagram
    participant U as User
    participant C as Channel
    participant O as Orchestrator
    participant I as Ingestor
    participant R as Researcher
    participant E as Executor
    participant G as Knowledge Graph

    U->>C: "I met Sarah from Acme"
    C->>O: Forward message
    O->>O: Classify intent (INGESTION)
    O->>I: Ingest message (async)
    I->>G: Extract & store entities
    O->>R: Find related context
    R->>G: Query graph
    G-->>R: Return results
    R-->>O: Context summary
    O-->>C: Response with confirmation
    C-->>U: "I've noted Sarah from Acme"
```

## Intent Classification Flow

```mermaid
flowchart LR
    MSG[User Message] --> CLASS{LLM Classification}
    CLASS -->|SEARCH| RES[Researcher]
    CLASS -->|ACTION| EXEC[Executor]
    CLASS -->|INGESTION| ING[Ingestor]
    CLASS -->|CONVERSATION| CONV[Direct Response]

    RES --> SYNTH[Synthesize Response]
    EXEC --> SYNTH
    ING --> SYNTH
    CONV --> SYNTH
    SYNTH --> RESP[Final Response]
```

## Agent Responsibilities

```mermaid
mindmap
  root((Klabautermann))
    Orchestrator
      Intent Classification
      Task Planning
      Response Synthesis
      Context Management
    Ingestor
      Entity Extraction
      Relationship Detection
      Graph Updates
    Researcher
      Query Planning
      Graph Search
      Result Ranking
    Executor
      Email Actions
      Calendar Actions
      MCP Tool Calls
    Archivist
      Thread Summarization
      Deduplication
    Scribe
      Daily Journals
      Pattern Detection
```

## Data Flow

```mermaid
flowchart TB
    subgraph Input["Input Sources"]
        USER[User Messages]
        EMAIL[Email Sync]
        CAL[Calendar Sync]
    end

    subgraph Processing["Processing Pipeline"]
        PARSE[Parse & Classify]
        EXTRACT[Entity Extraction]
        RELATE[Relationship Detection]
    end

    subgraph Storage["Storage Layer"]
        ENTITIES[(Entities)]
        EDGES[(Relationships)]
        EPISODES[(Episodes)]
    end

    subgraph Query["Query Pipeline"]
        PLAN[Query Planning]
        SEARCH[Vector + Graph Search]
        RANK[Result Ranking]
    end

    USER --> PARSE
    EMAIL --> PARSE
    CAL --> PARSE
    PARSE --> EXTRACT
    EXTRACT --> RELATE
    RELATE --> ENTITIES
    RELATE --> EDGES
    RELATE --> EPISODES

    QUERY[User Query] --> PLAN
    PLAN --> SEARCH
    SEARCH --> ENTITIES
    SEARCH --> EDGES
    SEARCH --> EPISODES
    SEARCH --> RANK
    RANK --> RESULT[Results]
```

## Entity Types (Ontology)

```mermaid
erDiagram
    Person ||--o{ WorksAt : "employment"
    Person ||--o{ Thread : "participates"
    Person ||--o{ Task : "assigned"
    Organization ||--o{ WorksAt : "employer"
    Thread ||--o{ Episode : "contains"
    Task ||--o{ BlockedBy : "dependencies"
    Day ||--o{ Episode : "events"
    Topic ||--o{ MentionedIn : "references"

    Person {
        string name
        string email
        string role
    }
    Organization {
        string name
        string industry
    }
    Thread {
        string channel
        datetime created
    }
    Task {
        string title
        string status
        datetime due
    }
    Topic {
        string name
        string description
    }
```

## Deployment Architecture

```mermaid
flowchart TB
    subgraph Docker["Docker Compose"]
        APP[Klabautermann App]
        NEO[Neo4j 5.26]
    end

    subgraph External["External APIs"]
        ANTHROPIC[Anthropic API]
        GOOGLE[Google Workspace]
    end

    subgraph Storage["Persistent Storage"]
        NEOVOL[(Neo4j Data)]
        LOGS[(Log Files)]
    end

    APP --> NEO
    APP --> ANTHROPIC
    APP --> GOOGLE
    NEO --> NEOVOL
    APP --> LOGS
```

## See Also

- [Full Agent Specification](../specs/architecture/AGENTS.md)
- [Memory Architecture](../specs/architecture/MEMORY.md)
- [Ontology Definition](../specs/architecture/ONTOLOGY.md)
- [MCP Integration](../specs/architecture/MCP.md)
