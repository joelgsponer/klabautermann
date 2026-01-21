"""
Application settings and configuration.

Provides typed access to environment variables and default values.
Uses a simple singleton pattern for settings access.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """
    Application settings loaded from environment variables.

    All settings have sensible defaults for development.
    """

    model_config = ConfigDict(frozen=True)

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Model selection
    primary_model: str = "claude-sonnet-4-20250514"
    fast_model: str = "claude-3-5-haiku-20241022"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""

    # Feature flags
    debug: bool = False
    disable_ingestion: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment variables."""
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            primary_model=os.getenv("ORCHESTRATOR_MODEL", "claude-sonnet-4-20250514"),
            fast_model=os.getenv("HAIKU_MODEL", "claude-3-5-haiku-20241022"),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_username=os.getenv("NEO4J_USERNAME", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
            debug=os.getenv("DEBUG", "false").lower() == "true",
            disable_ingestion=os.getenv("DISABLE_INGESTION", "false").lower() == "true",
        )


# Singleton instance cache
_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get application settings.

    Returns a cached singleton instance loaded from environment.
    """
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    """Reset settings cache (for testing)."""
    global _settings
    _settings = None


__all__ = ["Settings", "get_settings", "reset_settings"]
