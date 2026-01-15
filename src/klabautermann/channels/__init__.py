"""
Channels module - Communication interfaces for Klabautermann.

Contains:
- base_channel: Abstract base class for all channels
- cli_driver: Command-line interface with Rich rendering
- cli_renderer: Rich-based terminal output formatting

Future channels (Sprint 4+):
- telegram_driver: Telegram bot interface
- discord_driver: Discord bot interface
"""

from klabautermann.channels.base_channel import BaseChannel
from klabautermann.channels.cli_driver import CLIDriver
from klabautermann.channels.cli_renderer import CLIRenderer


__all__ = ["BaseChannel", "CLIDriver", "CLIRenderer"]
