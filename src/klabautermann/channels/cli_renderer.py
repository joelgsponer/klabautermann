"""
Rich-based CLI renderer for Klabautermann.

Provides styled terminal output with markdown rendering,
progress spinners, and nautical-themed formatting.

Reference: specs/architecture/CHANNELS.md, specs/branding/PERSONALITY.md
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.theme import Theme

from klabautermann.core.logger import restore_console_logging, suppress_console_logging


if TYPE_CHECKING:
    from collections.abc import Iterator

    from rich.status import Status


def _should_use_color() -> bool:
    """Determine if color output should be used.

    Respects NO_COLOR (https://no-color.org/) and FORCE_COLOR environment variables.
    Falls back to TTY detection.
    """
    # NO_COLOR takes precedence (accessibility standard)
    if os.getenv("NO_COLOR"):
        return False
    # FORCE_COLOR enables color even in non-TTY environments
    if os.getenv("FORCE_COLOR"):
        return True
    # Fall back to TTY detection
    return sys.stdout.isatty()


# Nautical color theme (deeper palette matching Go TUI)
NAUTICAL_THEME = Theme(
    {
        "info": "#3498db",  # WaveBlue
        "success": "#1abc9c",  # Seafoam
        "warning": "#f39c12",  # Amber
        "error": "#e74c3c bold",  # Coral
        "dim": "#95a5a6",  # Fog
        "prompt": "bold #3498db",
        "banner.title": "bold #3498db",
        "banner.subtitle": "#95a5a6",
        "banner.border": "#3498db",
        "entity.title": "bold cyan",
        "entity.name": "#f5f5dc",  # Sand
        "entity.label": "#95a5a6",  # Fog
    }
)

# Entity type icons
ENTITY_ICONS: dict[str, str] = {
    "Person": "👤",
    "Organization": "🏢",
    "Project": "📋",
    "Task": "✓",
    "Event": "📅",
    "Goal": "🎯",
    "Note": "📝",
    "Location": "📍",
    "Document": "📄",
}


class CLIRenderer:
    """
    Rich-based renderer for CLI output.

    Provides styled output for banners, messages, errors,
    and progress indicators with a nautical theme.
    """

    VERSION = "0.1.0"

    def __init__(self, no_spinner: bool = False) -> None:
        """Initialize renderer with nautical theme.

        Args:
            no_spinner: If True, disable animated spinner (for terminals with issues).
        """
        use_color = _should_use_color()
        # force_terminal ensures Rich doesn't disable features when stdout isn't a TTY
        # but FORCE_COLOR is set (e.g., in CI or when user knows terminal supports it)
        force_terminal = bool(os.getenv("FORCE_COLOR"))
        self.console = Console(
            theme=NAUTICAL_THEME,
            force_terminal=force_terminal,
            no_color=not use_color,
        )
        self.no_spinner = no_spinner

    def render_banner(self) -> None:
        """Display styled welcome banner."""
        banner_content = (
            f"[banner.title]KLABAUTERMANN[/] v{self.VERSION}\n"
            "[banner.subtitle]Your Personal Navigator[/]\n\n"
            '[dim]"A ship\'s only as good as her memory"[/]'
        )

        panel = Panel(
            banner_content,
            title="[bold]Ahoy, Captain![/]",
            border_style="banner.border",
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    def render_help(self) -> None:
        """Display styled help message."""
        help_md = """
## Commands

| Command | Description |
|---------|-------------|
| `[message]` | Chat with Klabautermann |
| `help` | Show this help |
| `exit` / `quit` | End the session |
| `/clear` | Clear screen and reset session |
| `/status` | Show system status |
| `/logs` | Toggle log output on/off |
| `/copy [N]` | Copy last N messages (default: 1) |
| `/export [N]` | Same as /copy (alias) |

### /copy Options

```
/copy           # Copy last message
/copy 5         # Copy last 5 messages
/copy 5 --format=markdown  # Markdown format (default)
/copy 5 --format=plain     # Plain text format
/copy 5 --format=json      # JSON format
```

Opens in neovim if available, or falls back to clipboard/file.

## Tips

- Tell me about people you meet: *"I met Sarah from Acme Corp"*
- Share your projects: *"I'm working on Project Lighthouse"*
- Ask questions: *"What do I know about Sarah?"*

*Full memory search and action execution coming in Sprint 2!*
"""
        self.console.print(Markdown(help_md))

    def render_user_input(self, content: str) -> None:
        """
        Echo user input with distinct styling.

        Args:
            content: User's input text.
        """
        self.console.print(f"[bold cyan]▶[/] [dim]{content}[/]")

    def render_response(self, content: str) -> None:
        """
        Render AI response with markdown formatting.

        Args:
            content: Response content (may contain markdown).
        """
        self.console.print()
        self.console.print(Markdown(content))
        self.console.print()
        # Add subtle separator for readability
        self.console.print(Rule(style="dim"))

    def render_error(self, message: str) -> None:
        """
        Display error message in red panel.

        Args:
            message: Error message to display.
        """
        panel = Panel(
            f"[error]{message}[/]",
            title="[error]Storm Warning[/]",
            border_style="red",
        )
        self.console.print(panel)

    def render_success(self, message: str) -> None:
        """
        Display success message.

        Args:
            message: Success message to display.
        """
        self.console.print(f"[success]{message}[/]")

    def render_info(self, message: str) -> None:
        """
        Display info message.

        Args:
            message: Info message to display.
        """
        self.console.print(f"[info]{message}[/]")

    def render_entities(self, entities: list[dict]) -> None:
        """
        Render entity panel showing recently mentioned entities.

        Displays up to 5 entities with their type icons in a styled panel.
        Matches the entity display pattern from the Go TUI.

        Args:
            entities: List of entity dicts with 'name' and 'labels' keys.
        """
        if not entities:
            return

        items: list[str] = []
        for entity in entities[:5]:
            labels = entity.get("labels", ["Entity"])
            # Skip Episodic nodes, use first non-Episodic label
            label = next((lbl for lbl in labels if lbl != "Episodic"), "Entity")
            icon = ENTITY_ICONS.get(label, "•")
            name = entity.get("name", "Unknown")
            items.append(f" {icon} [entity.name]{name}[/] [entity.label]({label})[/]")

        panel = Panel(
            "\n".join(items),
            title="[entity.title]Recent Entities[/]",
            border_style="cyan",
        )
        self.console.print(panel)

    def render_farewell(self) -> None:
        """Display farewell message."""
        self.console.print()
        self.console.print(
            Panel(
                "[dim]Fair winds and following seas, Captain.[/]",
                border_style="cyan",
            )
        )
        self.console.print()

    def clear(self) -> None:
        """Clear the terminal screen."""
        self.console.clear()

    @contextmanager
    def spinner(self, message: str = "Charting course...") -> Iterator[Status | None]:
        """
        Display a spinner while processing.

        Suppresses console logging during spinner to prevent ANSI escape
        code corruption when log output interleaves with spinner updates.

        Args:
            message: Message to display with spinner.

        Yields:
            Rich Status object for the spinner (or None if disabled).
        """
        if self.no_spinner:
            # Simple static message instead of animated spinner
            self.console.print(f"[dim]{message}[/]")
            yield None
            return

        suppress_console_logging()
        try:
            with self.console.status(
                f"[info]{message}[/]",
                spinner="dots",
                spinner_style="cyan",
            ) as status:
                yield status
        finally:
            restore_console_logging()

    def get_prompt_message(self) -> str:
        """
        Get the styled prompt string for input.

        Returns:
            Prompt string with styling markup.
        """
        return "[bold cyan]>[/] "

    def render_status(
        self,
        session_id: str,
        thread_id: str,
        is_connected: bool,
        agent_status: str,
        thread_count: int = 0,
        message_count: int = 0,
    ) -> None:
        """
        Display system status panel.

        Args:
            session_id: Current session identifier.
            thread_id: Current thread identifier.
            is_connected: Whether orchestrator is connected.
            agent_status: Status of the agent system.
            thread_count: Number of active threads.
            message_count: Total messages in current session.
        """
        connection_icon = "🟢" if is_connected else "🔴"
        connection_text = "Connected" if is_connected else "Disconnected"

        status_content = f"""
[info]Session ID:[/] [dim]{session_id}[/]
[info]Thread ID:[/] [dim]{thread_id}[/]
[info]Connection:[/] {connection_icon} {connection_text}
[info]Agent Status:[/] [dim]{agent_status}[/]
[info]Active Threads:[/] [dim]{thread_count}[/]
[info]Messages:[/] [dim]{message_count}[/]
""".strip()

        panel = Panel(
            status_content,
            title="[bold cyan]⚓ Ship Status[/]",
            border_style="cyan",
            padding=(0, 2),
        )
        self.console.print(panel)


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["ENTITY_ICONS", "NAUTICAL_THEME", "CLIRenderer"]
