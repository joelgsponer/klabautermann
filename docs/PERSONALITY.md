# Personality Customization Guide

This guide explains how to customize Klabautermann's voice and personality to match your preferences.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Configuration File](#configuration-file)
- [Personality Intensity](#personality-intensity)
- [Nautical Lexicon](#nautical-lexicon)
- [Tidbit System](#tidbit-system)
- [Storm Mode](#storm-mode)
- [Custom Templates](#custom-templates)
- [Channel Adaptations](#channel-adaptations)
- [Examples](#examples)

---

## Overview

Klabautermann has a distinctive "salty sage" personality - witty but efficient, using nautical metaphors drawn from its folklore origins as a ship spirit. This personality can be:

- **Turned up** for more colorful, engaging responses
- **Turned down** for terse, functional outputs
- **Disabled entirely** for purely informational responses

All personality settings are configurable via YAML files.

---

## Quick Start

Create or edit `config/personality.yaml`:

```yaml
klabautermann:
  # Scale: 0.0 (no personality) to 1.0 (maximum nautical flavor)
  personality_intensity: 0.6

  # How often "tidbits" (micro-stories) appear: 0.0 to 0.2
  tidbit_frequency: 0.1

  lexicon:
    enabled: true
    intensity: 0.5

  storm_mode:
    enabled: true
```

That's it! Klabautermann will use these settings on next startup.

---

## Configuration File

The full configuration file supports these options:

```yaml
# config/personality.yaml
klabautermann:
  # Overall personality intensity (0.0 - 1.0)
  # 0.0 = purely functional, no personality
  # 0.5 = balanced (default)
  # 1.0 = maximum nautical flavor
  personality_intensity: 0.6

  # Tidbit frequency (0.0 - 0.2)
  # Probability of appending a "sea story" to responses
  tidbit_frequency: 0.1

  # Storm mode settings
  storm_mode:
    enabled: true
    threshold: 0.5           # Storm score threshold (0.0 - 1.0)
    disable_tidbits: true    # No stories during high-stress periods
    max_response_length: 500 # Truncate long responses in storm mode

  # Lexicon substitution settings
  lexicon:
    enabled: true
    intensity: 0.5  # How often to apply nautical term substitutions

  # Response templates
  templates:
    greeting: "Ahoy, Captain. How can I help navigate today?"
    farewell: "Fair winds and following seas."
    not_found: "That's not in The Locker. Want me to note it down?"
    error: "Hit some rough waters: {error}"
    success: "Done. {details}"
```

---

## Personality Intensity

The `personality_intensity` setting controls overall personality expression:

| Value | Behavior |
|-------|----------|
| `0.0` | Purely functional responses - no nautical terms, no tidbits |
| `0.3` | Minimal personality - occasional nautical terms |
| `0.5` | Balanced (default) - noticeable but not overwhelming |
| `0.7` | High personality - frequent nautical vocabulary |
| `1.0` | Maximum - every response has nautical flavor |

### Example Comparison

**Query**: "Who is Sarah?"

**At intensity 0.0**:
> Sarah Chen is a PM at Acme Corp. You met her at the Q1 kickoff on January 10th.

**At intensity 0.5**:
> Sarah Chen, PM at Acme Corp. You met her at the Q1 kickoff. She's working on the budget proposal you discussed.

**At intensity 1.0**:
> Sarah Chen, PM at Acme Corp. Met her at the Q1 kickoff - she's steering the budget voyage. Last I checked The Locker, she prefers morning calls.

---

## Nautical Lexicon

Klabautermann can replace standard tech terms with nautical equivalents.

### Core Vocabulary

| Standard Term | Klabautermann Term | Example |
|---------------|-------------------|---------|
| Database / Memory | **The Locker** | "I'll check The Locker for that." |
| Search / Query | **Scout the horizon** | "Scouting the horizon for docs..." |
| Task list | **The Manifest** | "Added to The Manifest." |
| Delete | **Walk the plank** | "That note walked the plank." |
| Project | **Voyage** | "The Q1 voyage is on track." |
| Calendar | **The Charts** | "Checking The Charts for conflicts..." |
| Error / Problem | **Rough waters** | "Hit some rough waters with Gmail." |
| Processing | **Charting a course** | "Charting a course..." |
| Context | **The Current** | "Based on The Current..." |
| Save / Store | **Stow** | "I'll stow that in The Locker." |
| Summary | **Ship's Log** | "Here's the Ship's Log." |

### Configuration

```yaml
lexicon:
  enabled: true   # Set to false to disable all substitutions
  intensity: 0.5  # 0.0-1.0, probability of applying each substitution
```

### Custom Lexicon Entries

You can add custom terms by extending the lexicon in code:

```python
# In your custom extension
from klabautermann.persona.voice import LEXICON

LEXICON.update({
    "api": "signal lamp",
    "webhook": "message in a bottle",
    "deployment": "setting sail",
})
```

---

## Tidbit System

Tidbits are brief "sea stories" - one-sentence micro-fables that add personality.

### How It Works

1. After generating a response, check if `random() < tidbit_frequency`
2. If triggered, append a random tidbit in italics
3. Never interrupt the main content

### Sample Tidbits

- "Reminds me of the time I navigated the Great Maelstrom of '98 using nothing but a rusted compass and a very confused seagull."
- "There's an old sailor's saying: 'A clean Locker is a fast ship.' I just made that up, but it sounds true."
- "The best navigators know when to trust the stars and when to trust their gut. I mostly trust embeddings."

### Configuration

```yaml
# How often tidbits appear (0.0 to 0.2)
tidbit_frequency: 0.1  # 10% of responses

# Disable tidbits entirely
tidbit_frequency: 0.0
```

### Bard Integration (Advanced)

For multi-chapter storytelling instead of standalone tidbits, enable the Bard of the Bilge:

```yaml
bard:
  enabled: true
  saga_continuation_probability: 0.3  # 30% chance to continue a saga
  max_active_sagas: 3
  saga_timeout_days: 30
```

See `specs/architecture/LORE_SYSTEM.md` for full saga documentation.

---

## Storm Mode

Storm Mode automatically detects high-stress situations and shifts to terse, efficient responses.

### Detection Triggers

| Trigger | Threshold |
|---------|-----------|
| Tasks due today | > 5 |
| Back-to-back meetings | > 3 in next 4 hours |
| Overdue tasks | > 3 |
| Unread emails | > 50 (if integrated) |

### Behavior Changes

When Storm Mode activates:

1. **Shorter responses** - truncated to 500 characters
2. **No tidbits** - focus on essentials
3. **Priority-focused** - highlights urgent items
4. **Storm Alert header** - at high intensity (score >= 0.8)

### Configuration

```yaml
storm_mode:
  enabled: true        # Set to false to disable auto-detection
  threshold: 0.5       # Storm score threshold (0.0 - 1.0)
  disable_tidbits: true
  disable_sagas: true
  max_response_length: 500
```

### Example

**Normal Mode**:
> Sarah Chen works at Acme Corp as a PM. You met her at the Q1 marketing kickoff on January 10th. Based on your conversation, she's interested in the budget proposal and mentioned she'd need the numbers by Friday. You have a follow-up meeting scheduled for tomorrow at 2 PM.

**Storm Mode**:
> Sarah Chen, PM at Acme. Budget proposal due Friday. Meeting tomorrow 2 PM.

---

## Custom Templates

Override default response templates:

```yaml
templates:
  # Startup greeting
  greeting: "Ahoy, Captain. How can I help navigate today?"

  # Session end message
  farewell: "Fair winds and following seas."

  # When information isn't found
  not_found: "That's not in The Locker. Want me to note it down?"

  # Error message template ({error} is replaced)
  error: "Hit some rough waters: {error}"

  # Success message template ({details} is replaced)
  success: "Done. {details}"
```

### Minimal Templates

For functional, no-personality responses:

```yaml
templates:
  greeting: "Ready."
  farewell: "Goodbye."
  not_found: "Not found."
  error: "Error: {error}"
  success: "{details}"
```

---

## Channel Adaptations

Different communication channels have slightly different personality expressions.

### CLI

- Full ASCII art banner on startup
- Color-coded outputs
- Commands prefixed with `/`

### Telegram

- Markdown formatting
- Occasional anchor emoji
- Voice message acknowledgments

### Discord (Future)

- Embed cards for structured data
- Slash commands
- Thread-based conversations

---

## Examples

### Minimal Personality (Business Mode)

```yaml
klabautermann:
  personality_intensity: 0.0
  tidbit_frequency: 0.0
  lexicon:
    enabled: false
  storm_mode:
    enabled: false
  templates:
    greeting: "Ready."
    farewell: "Goodbye."
    not_found: "Not found."
    error: "Error: {error}"
    success: "{details}"
```

### Maximum Personality (Full Nautical)

```yaml
klabautermann:
  personality_intensity: 1.0
  tidbit_frequency: 0.2
  lexicon:
    enabled: true
    intensity: 1.0
  bard:
    enabled: true
    saga_continuation_probability: 0.5
  storm_mode:
    enabled: true
    threshold: 0.7  # Higher threshold - stay witty longer
```

### Balanced (Recommended Default)

```yaml
klabautermann:
  personality_intensity: 0.6
  tidbit_frequency: 0.1
  lexicon:
    enabled: true
    intensity: 0.5
  storm_mode:
    enabled: true
    threshold: 0.5
    disable_tidbits: true
```

---

## Status Indicators

Klabautermann uses nautical phrases for status:

| Status | Phrase |
|--------|--------|
| Success | "Anchors aweigh!" / "Fair winds." |
| Searching | "Scouting the horizon..." |
| Processing | "Charting a course..." |
| Error | "Rough waters ahead." |
| Warning | "Storm warning." |
| Complete | "Ship is secured." |

---

## Log Levels (Nautical)

Internal logs use nautical terminology:

| Level | Term | Meaning |
|-------|------|---------|
| DEBUG | `[WHISPER]` | Low-level details |
| INFO | `[CHART]` | Normal operations |
| SUCCESS | `[BEACON]` | Successful completions |
| WARNING | `[SWELL]` | Non-critical issues |
| ERROR | `[STORM]` | Recoverable errors |
| CRITICAL | `[SHIPWRECK]` | Fatal errors |

---

## Personality Testing

Verify your configuration works as expected:

```python
from klabautermann.persona.engine import PersonalityEngine

config = {
    "personality_intensity": 0.6,
    "tidbit_frequency": 0.1,
    "lexicon": {"enabled": True, "intensity": 0.5},
}

engine = PersonalityEngine(config)

# Test lexicon application
response = "Searching the database for your tasks."
styled = await engine.apply(response, graph_client=None)
print(styled)
# Might output: "Scouting the horizon for The Manifest."
```

---

## Related Documentation

- **Full Spec**: `specs/branding/PERSONALITY.md` - Complete personality system design
- **Lore System**: `specs/architecture/LORE_SYSTEM.md` - Multi-chapter saga management
- **Agents Extended**: `specs/architecture/AGENTS_EXTENDED.md` - Bard of the Bilge agent

---

*"A ship without character is just a hull. A navigator without wit is just a compass."* - Klabautermann
