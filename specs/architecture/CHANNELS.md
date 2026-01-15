# Klabautermann Communication Channels

**Version**: 1.0
**Purpose**: Multi-channel driver architecture for platform-independent interaction

---

## Overview

Klabautermann supports multiple communication channels through a **modular driver architecture**. Each channel (CLI, Telegram, Discord) is a "plug" that connects to the same Orchestrator, ensuring consistent behavior across platforms while handling platform-specific details.

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERFACES                           │
├─────────────┬─────────────┬─────────────┬──────────────────┤
│    CLI      │  Telegram   │   Discord   │     (Future)     │
│   Driver    │   Driver    │   Driver    │                  │
└──────┬──────┴──────┬──────┴──────┬──────┴──────────────────┘
       │             │             │
       └─────────────┼─────────────┘
                     │
            ┌────────▼────────┐
            │ StandardizedMessage │
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │   Orchestrator  │
            └─────────────────┘
```

---

## 1. Core Abstractions

### 1.1 StandardizedMessage

All incoming messages are converted to a common format:

```python
# klabautermann/core/models.py
from pydantic import BaseModel
from typing import Optional, Dict, Any

class StandardizedMessage(BaseModel):
    """Platform-agnostic message format"""
    thread_id: str           # Internal UUID for this conversation thread
    external_id: str         # Platform-specific ID (chat_id, session_id)
    user_id: str             # Platform user identifier
    content: str             # Message text
    timestamp: float         # Unix timestamp
    channel_type: str        # "cli", "telegram", "discord"
    metadata: Dict[str, Any] = {}  # Voice URLs, attachments, etc.

class StandardizedResponse(BaseModel):
    """Platform-agnostic response format"""
    content: str             # Response text
    metadata: Dict[str, Any] = {}  # Suggested actions, attachments, etc.
```

### 1.2 BaseChannel Interface

```python
# klabautermann/channels/base_channel.py
from abc import ABC, abstractmethod
from typing import Optional, Callable, Awaitable
from klabautermann.core.models import StandardizedMessage, StandardizedResponse
from klabautermann.memory.thread_manager import ThreadManager

class BaseChannel(ABC):
    """Abstract base for all communication channels"""

    def __init__(
        self,
        orchestrator: "Orchestrator",
        thread_manager: ThreadManager,
        config: dict
    ):
        self.orchestrator = orchestrator
        self.thread_manager = thread_manager
        self.config = config

    @abstractmethod
    async def start(self):
        """Initialize and start the channel (listen for messages)"""
        pass

    @abstractmethod
    async def stop(self):
        """Gracefully shutdown the channel"""
        pass

    @abstractmethod
    async def send_message(self, external_id: str, content: str, metadata: Optional[dict] = None):
        """Send a message to the platform"""
        pass

    @abstractmethod
    def format_incoming(self, raw_message: Any) -> StandardizedMessage:
        """Convert platform message to StandardizedMessage"""
        pass

    async def handle_message(self, raw_message: Any):
        """
        Main message handling flow:
        1. Format to StandardizedMessage
        2. Get or create thread
        3. Send to Orchestrator
        4. Send response back
        """
        # Convert to standard format
        message = self.format_incoming(raw_message)

        # Ensure thread exists
        thread_uuid = await self.thread_manager.get_or_create_thread(
            external_id=message.external_id,
            channel_type=message.channel_type,
            user_id=message.user_id
        )
        message.thread_id = thread_uuid

        # Add user message to thread
        await self.thread_manager.add_message(
            thread_uuid=thread_uuid,
            role="user",
            content=message.content,
            metadata=message.metadata
        )

        # Get response from Orchestrator
        response = await self.orchestrator.handle_user_input(
            thread_id=thread_uuid,
            text=message.content,
            channel_type=message.channel_type,
            metadata=message.metadata
        )

        # Add assistant response to thread
        await self.thread_manager.add_message(
            thread_uuid=thread_uuid,
            role="assistant",
            content=response.content
        )

        # Send response to platform
        await self.send_message(
            external_id=message.external_id,
            content=response.content,
            metadata=response.metadata
        )

        return response
```

---

## 2. CLI Driver

### 2.1 Purpose

The CLI driver is the primary development and testing interface. It runs in a terminal with stdin/stdout communication.

### 2.2 Implementation

```python
# klabautermann/channels/cli_driver.py
import asyncio
import sys
from datetime import datetime, timezone
from typing import Optional
from klabautermann.channels.base_channel import BaseChannel
from klabautermann.core.models import StandardizedMessage, StandardizedResponse
from klabautermann.core.logger import logger

class CLIDriver(BaseChannel):
    """Command-line interface driver"""

    def __init__(self, orchestrator, thread_manager, config: dict):
        super().__init__(orchestrator, thread_manager, config)
        self.session_id = config.get("session_id", "cli-default")
        self.running = False
        self.prompt = config.get("prompt", "You > ")

    async def start(self):
        """Start the CLI input loop"""
        self.running = True

        # Print welcome banner
        self._print_banner()

        logger.info(f"[CHART] CLI driver started with session: {self.session_id}")

        while self.running:
            try:
                # Get user input
                user_input = await self._async_input(self.prompt)

                if not user_input:
                    continue

                # Check for commands
                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                    continue

                # Process message
                await self.handle_message(user_input)

            except EOFError:
                # Ctrl+D pressed
                print("\nFair winds, Captain!")
                break
            except KeyboardInterrupt:
                # Ctrl+C pressed
                print("\n^C received. Type /quit to exit.")
            except Exception as e:
                logger.error(f"[STORM] CLI error: {e}")
                print(f"Error: {e}")

    async def stop(self):
        """Stop the CLI driver"""
        self.running = False
        logger.info("[CHART] CLI driver stopped")

    async def send_message(self, external_id: str, content: str, metadata: Optional[dict] = None):
        """Print response to terminal"""
        # Add visual separator
        print()
        print(f"Klabautermann > {content}")
        print()

    def format_incoming(self, raw_message: str) -> StandardizedMessage:
        """Convert raw input to StandardizedMessage"""
        return StandardizedMessage(
            thread_id="",  # Will be set by handle_message
            external_id=self.session_id,
            user_id="cli-user",
            content=raw_message,
            timestamp=datetime.now(timezone.utc).timestamp(),
            channel_type="cli",
            metadata={}
        )

    async def _async_input(self, prompt: str) -> str:
        """Async wrapper for input()"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: input(prompt))

    async def _handle_command(self, command: str):
        """Handle CLI commands"""
        cmd = command.lower().strip()

        if cmd == "/quit" or cmd == "/exit":
            print("Fair winds, Captain!")
            await self.stop()

        elif cmd == "/help":
            print("""
Available commands:
  /help     - Show this message
  /status   - Show system status
  /clear    - Clear conversation context
  /quit     - Exit the CLI
            """)

        elif cmd == "/status":
            # Get thread info
            thread_count = await self._get_active_thread_count()
            print(f"""
System Status:
  Session ID: {self.session_id}
  Active Threads: {thread_count}
  Channel: CLI
            """)

        elif cmd == "/clear":
            # Create new thread by changing session ID
            import uuid
            self.session_id = f"cli-{uuid.uuid4().hex[:8]}"
            print(f"Context cleared. New session: {self.session_id}")

        else:
            print(f"Unknown command: {command}. Type /help for available commands.")

    async def _get_active_thread_count(self) -> int:
        """Get count of active threads"""
        threads = await self.thread_manager.get_inactive_threads(cooldown_minutes=0)
        return len(threads)

    def _print_banner(self):
        """Print welcome banner"""
        banner = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ⚓ KLABAUTERMANN - Your Navigator Through the Storm ⚓   ║
║                                                           ║
║   Type your message and press Enter.                      ║
║   Type /help for available commands.                      ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
        """
        print(banner)
```

### 2.3 Usage

```bash
# Start the CLI
python -m klabautermann.channels.cli_driver

# Or via Docker
docker-compose up -d
docker attach klabautermann-app
```

---

## 3. Telegram Driver

### 3.1 Purpose

The Telegram driver enables mobile access with support for text, voice messages, and media.

### 3.2 Prerequisites

1. **Create a Telegram Bot** via @BotFather
2. **Get the Bot Token**
3. **Add to .env**: `TELEGRAM_BOT_TOKEN=...`

### 3.3 Implementation

```python
# klabautermann/channels/telegram_driver.py
import asyncio
import os
from datetime import datetime, timezone
from typing import Optional
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from klabautermann.channels.base_channel import BaseChannel
from klabautermann.core.models import StandardizedMessage, StandardizedResponse
from klabautermann.core.logger import logger

class TelegramDriver(BaseChannel):
    """Telegram bot driver using python-telegram-bot"""

    def __init__(self, orchestrator, thread_manager, config: dict):
        super().__init__(orchestrator, thread_manager, config)
        self.bot_token = config.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.app: Optional[Application] = None
        self.allowed_user_ids = config.get("allowed_user_ids", [])  # Empty = allow all

    async def start(self):
        """Initialize and start the Telegram bot"""
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        logger.info("[CHART] Starting Telegram driver...")

        # Build application
        self.app = Application.builder().token(self.bot_token).build()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.app.add_handler(MessageHandler(filters.VOICE, self._on_voice))

        # Start polling (no webhooks needed - simpler for headless Docker)
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

        logger.info("[BEACON] Telegram driver started successfully")

    async def stop(self):
        """Stop the Telegram bot"""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        logger.info("[CHART] Telegram driver stopped")

    async def send_message(self, external_id: str, content: str, metadata: Optional[dict] = None):
        """Send message to Telegram chat"""
        chat_id = int(external_id)
        await self.app.bot.send_message(
            chat_id=chat_id,
            text=content,
            parse_mode="Markdown"
        )

    def format_incoming(self, update: Update) -> StandardizedMessage:
        """Convert Telegram Update to StandardizedMessage"""
        message = update.message
        chat_id = str(message.chat_id)
        user_id = str(message.from_user.id)

        # Extract content based on message type
        if message.text:
            content = message.text
            metadata = {}
        elif message.voice:
            content = "[Voice message - transcription pending]"
            metadata = {
                "voice_file_id": message.voice.file_id,
                "duration": message.voice.duration,
                "mime_type": message.voice.mime_type
            }
        else:
            content = "[Unsupported message type]"
            metadata = {}

        return StandardizedMessage(
            thread_id="",  # Will be set by handle_message
            external_id=chat_id,
            user_id=user_id,
            content=content,
            timestamp=datetime.now(timezone.utc).timestamp(),
            channel_type="telegram",
            metadata=metadata
        )

    # Command handlers

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome = """
⚓ **Ahoy, Captain!**

I'm Klabautermann, your personal navigator through the information storm.

Tell me about people you meet, projects you're working on, or ask me to find something in The Locker (your knowledge graph).

Type /help for more information.
        """
        await update.message.reply_text(welcome, parse_mode="Markdown")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
**Available Commands:**

/start - Welcome message
/help - Show this help
/status - System status

**What I can do:**

• Remember people, projects, and events you tell me about
• Search your knowledge graph for information
• Draft emails and create calendar events
• Transcribe voice messages

Just chat naturally - I'll figure out the rest!
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        chat_id = str(update.message.chat_id)
        user_id = str(update.message.from_user.id)

        status = f"""
**System Status:**

• Channel: Telegram
• Chat ID: `{chat_id}`
• User ID: `{user_id}`
• Status: Online ⚓
        """
        await update.message.reply_text(status, parse_mode="Markdown")

    # Message handlers

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages"""
        user_id = update.message.from_user.id

        # Check authorization if configured
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            await update.message.reply_text(
                "⚓ Sorry, I don't recognize you. This bot is private."
            )
            return

        # Show typing indicator
        await update.message.chat.send_action("typing")

        # Process message
        try:
            await self.handle_message(update)
        except Exception as e:
            logger.error(f"[STORM] Telegram message handling error: {e}")
            await update.message.reply_text(
                "⚓ Hit some rough waters processing that. Please try again."
            )

    async def _on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming voice messages"""
        user_id = update.message.from_user.id

        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            await update.message.reply_text("⚓ Sorry, I don't recognize you.")
            return

        await update.message.chat.send_action("typing")

        try:
            # Download voice file
            voice = update.message.voice
            file = await context.bot.get_file(voice.file_id)

            # Download to temp file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                await file.download_to_drive(f.name)
                audio_path = f.name

            # Transcribe using Whisper
            transcription = await self._transcribe_audio(audio_path)

            # Clean up temp file
            os.unlink(audio_path)

            if not transcription:
                await update.message.reply_text(
                    "⚓ Couldn't make out what you said. Try again?"
                )
                return

            # Update the message content with transcription
            update.message.text = transcription
            message = self.format_incoming(update)
            message.content = transcription
            message.metadata["original_type"] = "voice"
            message.metadata["transcription"] = transcription

            # Process as text message
            await self.handle_message(update)

        except Exception as e:
            logger.error(f"[STORM] Voice processing error: {e}")
            await update.message.reply_text(
                "⚓ Had trouble with that voice message. Try typing instead?"
            )

    async def _transcribe_audio(self, audio_path: str) -> Optional[str]:
        """Transcribe audio using OpenAI Whisper"""
        import openai

        try:
            client = openai.AsyncOpenAI()
            with open(audio_path, "rb") as audio_file:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
            return transcript.text
        except Exception as e:
            logger.error(f"[STORM] Whisper transcription failed: {e}")
            return None


# Run standalone for testing
async def main():
    from klabautermann.agents.orchestrator import Orchestrator
    from klabautermann.memory.thread_manager import ThreadManager
    from neo4j import AsyncGraphDatabase

    # Setup
    driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    )
    thread_manager = ThreadManager(driver)
    orchestrator = Orchestrator(...)  # Initialize with proper config

    telegram = TelegramDriver(
        orchestrator=orchestrator,
        thread_manager=thread_manager,
        config={"bot_token": os.getenv("TELEGRAM_BOT_TOKEN")}
    )

    await telegram.start()

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await telegram.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### 3.4 Configuration

```yaml
# config/channels/telegram.yaml
bot_token: ${TELEGRAM_BOT_TOKEN}
allowed_user_ids: []  # Empty = allow all, or [123456789, 987654321]
enable_voice: true
voice_model: whisper-1
max_message_length: 4096
typing_indicator: true
```

---

## 4. Thread Isolation

### 4.1 Why Thread Isolation Matters

Each channel conversation must be independent:
- CLI conversation about "Project A"
- Telegram conversation about "Project B"
- Asking "What project am I working on?" should give different answers

### 4.2 Thread ID Mapping

| Channel | External ID Source | Thread Mapping |
|---------|-------------------|----------------|
| CLI | Session ID (configurable) | `cli-{session_id}` → Thread UUID |
| Telegram | Chat ID | `telegram-{chat_id}` → Thread UUID |
| Discord | Channel ID | `discord-{channel_id}` → Thread UUID |

### 4.3 Implementation

```python
# Thread creation ensures isolation
thread_uuid = await thread_manager.get_or_create_thread(
    external_id=f"{channel_type}-{chat_id}",  # Unique per channel+conversation
    channel_type=channel_type,
    user_id=user_id
)

# Context retrieval is scoped to thread
context = await thread_manager.get_context(thread_uuid, limit=15)
```

---

## 5. Multi-Channel Deployment

### 5.1 Docker Compose Configuration

```yaml
# docker-compose.yml
services:
  klabautermann-app:
    build: .
    env_file: .env
    environment:
      - ENABLE_CLI=true
      - ENABLE_TELEGRAM=true
    depends_on:
      - neo4j
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    stdin_open: true   # For CLI
    tty: true          # For CLI

  neo4j:
    image: neo4j:5.26
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
    volumes:
      - neo4j_data:/data

volumes:
  neo4j_data:
```

### 5.2 Channel Manager

```python
# klabautermann/channels/manager.py
import asyncio
from typing import Dict
from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.channels.telegram_driver import TelegramDriver
from klabautermann.core.logger import logger

class ChannelManager:
    """Manages multiple communication channels"""

    def __init__(self, orchestrator, thread_manager, config: dict):
        self.orchestrator = orchestrator
        self.thread_manager = thread_manager
        self.config = config
        self.channels: Dict[str, BaseChannel] = {}

    async def start_all(self):
        """Start all enabled channels"""
        tasks = []

        if self.config.get("enable_cli", True):
            cli = CLIDriver(
                self.orchestrator,
                self.thread_manager,
                self.config.get("cli", {})
            )
            self.channels["cli"] = cli
            tasks.append(cli.start())
            logger.info("[CHART] CLI channel enabled")

        if self.config.get("enable_telegram", False):
            telegram = TelegramDriver(
                self.orchestrator,
                self.thread_manager,
                self.config.get("telegram", {})
            )
            self.channels["telegram"] = telegram
            tasks.append(telegram.start())
            logger.info("[CHART] Telegram channel enabled")

        # Start all channels concurrently
        await asyncio.gather(*tasks)

    async def stop_all(self):
        """Stop all channels gracefully"""
        for name, channel in self.channels.items():
            logger.info(f"[CHART] Stopping {name} channel...")
            await channel.stop()

        logger.info("[BEACON] All channels stopped")
```

---

## 6. Future Channels

### 6.1 Discord Driver (Planned)

```python
# klabautermann/channels/discord_driver.py (stub)
class DiscordDriver(BaseChannel):
    """Discord bot driver using discord.py"""

    def __init__(self, orchestrator, thread_manager, config: dict):
        super().__init__(orchestrator, thread_manager, config)
        self.bot_token = config.get("bot_token") or os.getenv("DISCORD_BOT_TOKEN")
        self.guild_id = config.get("guild_id")

    # Thread mapping: Discord Channel ID → Thread
    # DM conversations use user ID as channel ID
```

### 6.2 Web Interface (Planned)

```python
# klabautermann/channels/web_driver.py (stub)
class WebDriver(BaseChannel):
    """Web-based chat interface via WebSocket"""

    def __init__(self, orchestrator, thread_manager, config: dict):
        super().__init__(orchestrator, thread_manager, config)
        self.host = config.get("host", "0.0.0.0")
        self.port = config.get("port", 8080)

    # FastAPI + WebSocket for real-time chat
    # Session ID from JWT token or cookie
```

---

## 7. Testing Channels

### 7.1 Unit Tests

```python
# tests/unit/test_channels.py
import pytest
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.core.models import StandardizedMessage

def test_cli_format_incoming():
    driver = CLIDriver(None, None, {"session_id": "test-session"})
    msg = driver.format_incoming("Hello, Klabautermann!")

    assert msg.content == "Hello, Klabautermann!"
    assert msg.channel_type == "cli"
    assert msg.external_id == "test-session"

def test_telegram_format_incoming():
    # Mock Telegram Update object
    ...
```

### 7.2 Integration Tests

```python
# tests/integration/test_thread_isolation.py
import pytest

@pytest.mark.asyncio
async def test_multi_channel_thread_isolation(thread_manager):
    """Verify CLI and Telegram threads are separate"""

    # Create CLI thread
    cli_thread = await thread_manager.get_or_create_thread(
        external_id="cli-test-session",
        channel_type="cli",
        user_id="cli-user"
    )

    # Create Telegram thread
    tg_thread = await thread_manager.get_or_create_thread(
        external_id="telegram-123456",
        channel_type="telegram",
        user_id="tg-user"
    )

    # Verify they're different
    assert cli_thread != tg_thread

    # Add message to CLI
    await thread_manager.add_message(cli_thread, "user", "Working on Project A")

    # Add message to Telegram
    await thread_manager.add_message(tg_thread, "user", "Working on Project B")

    # Verify context is isolated
    cli_context = await thread_manager.get_context(cli_thread)
    tg_context = await thread_manager.get_context(tg_thread)

    assert "Project A" in cli_context[0]["content"]
    assert "Project B" in tg_context[0]["content"]
```

---

## 8. Security Considerations

### 8.1 User Authentication

| Channel | Auth Method |
|---------|-------------|
| CLI | Local access (assumed trusted) |
| Telegram | User ID whitelist (optional) |
| Discord | Role-based access |

### 8.2 Rate Limiting

```python
from datetime import datetime, timedelta
from collections import defaultdict

class RateLimiter:
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = timedelta(seconds=window_seconds)
        self.requests = defaultdict(list)

    def is_allowed(self, user_id: str) -> bool:
        now = datetime.now()
        cutoff = now - self.window

        # Clean old requests
        self.requests[user_id] = [
            t for t in self.requests[user_id] if t > cutoff
        ]

        # Check limit
        if len(self.requests[user_id]) >= self.max_requests:
            return False

        self.requests[user_id].append(now)
        return True
```

### 8.3 Input Sanitization

```python
def sanitize_input(content: str) -> str:
    """Basic input sanitization"""
    # Remove potential injection attempts
    content = content.replace("```", "")

    # Limit length
    max_length = 4000
    if len(content) > max_length:
        content = content[:max_length] + "..."

    return content.strip()
```

---

*"Every port speaks a different tongue, but The Locker understands them all."* - Klabautermann
