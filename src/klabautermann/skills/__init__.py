"""
Skills package for Klabautermann.

Provides skill discovery, loading, and orchestrator integration using
the standard Claude Code SKILL.md format with custom klabautermann-* fields.

Usage:
    from klabautermann.skills import SkillLoader, SkillDiscovery

    loader = SkillLoader()
    skills = loader.load_all()

    # AI-first skill discovery (recommended)
    discovery = SkillDiscovery(loader)
    skill = await discovery.discover_skill("Who is Sarah?", trace_id)

    # Legacy pattern-based matching (deprecated)
    planner = SkillAwarePlanner(loader)
    task = planner.match_and_convert("Who is Sarah?", trace_id)
"""

from klabautermann.skills.discovery import SkillDiscovery
from klabautermann.skills.loader import SkillLoader
from klabautermann.skills.models import (
    KlabautermannSkillConfig,
    LoadedSkill,
    PayloadField,
    SkillMetadata,
)
from klabautermann.skills.planner import SkillAwarePlanner


__all__ = [
    "KlabautermannSkillConfig",
    "LoadedSkill",
    "PayloadField",
    "SkillAwarePlanner",
    "SkillDiscovery",
    "SkillLoader",
    "SkillMetadata",
]
