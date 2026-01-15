"""
Rich-based CLI renderer for Klabautermann.

Provides styled terminal output with markdown rendering,
progress spinners, and nautical-themed formatting.

Reference: specs/architecture/CHANNELS.md, specs/branding/PERSONALITY.md
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.theme import Theme


if TYPE_CHECKING:
    from collections.abc import Iterator

    from rich.status import Status


# Nautical color theme
NAUTICAL_THEME = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "dim": "dim white",
        "prompt": "bold cyan",
        "banner.title": "bold cyan",
        "banner.subtitle": "dim white",
        "banner.border": "cyan",
    }
)


class CLIRenderer:
    """
    Rich-based renderer for CLI output.

    Provides styled output for banners, messages, errors,
    and progress indicators with a nautical theme.
    """

    VERSION = "0.1.0"

    def __init__(self) -> None:
        """Initialize renderer with nautical theme."""
        self.console = Console(theme=NAUTICAL_THEME)

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
| `/clear` | Clear the screen |
| `/logs` | Toggle log output on/off |

## Tips

- Tell me about people you meet: *"I met Sarah from Acme Corp"*
- Share your projects: *"I'm working on Project Lighthouse"*
- Ask questions: *"What do I know about Sarah?"*

*Full memory search and action execution coming in Sprint 2!*
"""
        self.console.print(Markdown(help_md))

    def render_response(self, content: str) -> None:
        """
        Render AI response with markdown formatting.

        Args:
            content: Response content (may contain markdown).
        """
        self.console.print()
        self.console.print(Markdown(content))
        self.console.print()

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
    def spinner(self, message: str = "Charting course...") -> Iterator[Status]:
        """
        Display a spinner while processing.

        Args:
            message: Message to display with spinner.

        Yields:
            Rich Status object for the spinner.
        """
        with self.console.status(
            f"[info]{message}[/]",
            spinner="dots",
            spinner_style="cyan",
        ) as status:
            yield status

    def get_prompt_message(self) -> str:
        """
        Get the styled prompt string for input.

        Returns:
            Prompt string with styling markup.
        """
        return "[bold cyan]>[/] "


# ===========================================================================
# Export
# ===========================================================================

__all__ = ["NAUTICAL_THEME", "CLIRenderer"]
