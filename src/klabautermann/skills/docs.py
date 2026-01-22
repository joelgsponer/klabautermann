"""
Skill documentation generator.

Generates human-readable documentation from SKILL.md files, including
usage examples, parameter descriptions, and integration details.

Usage:
    from klabautermann.skills.docs import SkillDocsGenerator, generate_skill_docs

    # Generate docs for all skills
    generator = SkillDocsGenerator(loader)
    docs = generator.generate_all()

    # Generate docs for a single skill
    doc = generator.generate(skill)
    print(doc.to_markdown())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from klabautermann.core.logger import logger


if TYPE_CHECKING:
    from klabautermann.skills.loader import SkillLoader
    from klabautermann.skills.models import LoadedSkill


@dataclass
class SkillParameter:
    """Documentation for a single skill parameter."""

    name: str
    type: str
    required: bool
    default: str | None
    description: str | None

    def to_markdown(self) -> str:
        """Format as markdown table row."""
        required_str = "Yes" if self.required else "No"
        default_str = f"`{self.default}`" if self.default is not None else "-"
        desc = self.description or "-"
        return f"| `{self.name}` | `{self.type}` | {required_str} | {default_str} | {desc} |"


@dataclass
class SkillDoc:
    """Generated documentation for a single skill."""

    name: str
    description: str
    model: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    user_invocable: bool = True
    task_type: str | None = None
    agent: str | None = None
    blocking: bool = True
    parameters: list[SkillParameter] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)
    body_sections: dict[str, str] = field(default_factory=dict)
    path: Path | None = None

    def to_markdown(self) -> str:
        """Generate markdown documentation for the skill."""
        lines = []

        # Header
        lines.append(f"# {self.name}")
        lines.append("")
        lines.append(self.description)
        lines.append("")

        # Quick reference
        lines.append("## Quick Reference")
        lines.append("")
        lines.append("| Property | Value |")
        lines.append("|----------|-------|")
        if self.model:
            lines.append(f"| Model | `{self.model}` |")
        if self.allowed_tools:
            tools_str = ", ".join(f"`{t}`" for t in self.allowed_tools)
            lines.append(f"| Allowed Tools | {tools_str} |")
        lines.append(f"| User Invocable | {'Yes' if self.user_invocable else 'No'} |")
        if self.task_type:
            lines.append(f"| Task Type | `{self.task_type}` |")
        if self.agent:
            lines.append(f"| Agent | `{self.agent}` |")
        lines.append(f"| Blocking | {'Yes' if self.blocking else 'No'} |")
        lines.append("")

        # Trigger phrases
        if self.trigger_phrases:
            lines.append("## How to Use")
            lines.append("")
            lines.append("Trigger this skill by saying:")
            lines.append("")
            for phrase in self.trigger_phrases:
                lines.append(f'- "{phrase}"')
            lines.append("")

        # Parameters
        if self.parameters:
            lines.append("## Parameters")
            lines.append("")
            lines.append("| Name | Type | Required | Default | Description |")
            lines.append("|------|------|----------|---------|-------------|")
            for param in self.parameters:
                lines.append(param.to_markdown())
            lines.append("")

        # Body sections (Instructions, Examples, etc.)
        for section_name, section_content in self.body_sections.items():
            lines.append(f"## {section_name}")
            lines.append("")
            lines.append(section_content)
            lines.append("")

        # Footer
        if self.path:
            lines.append("---")
            lines.append(f"*Source: `{self.path}`*")

        return "\n".join(lines)

    def to_html(self) -> str:
        """Generate HTML documentation for the skill."""
        import html

        def md_to_html(text: str) -> str:
            """Simple markdown to HTML conversion."""
            # Escape HTML
            text = html.escape(text)
            # Code blocks
            text = text.replace("```\n", "<pre><code>").replace("\n```", "</code></pre>")
            # Inline code
            import re

            text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
            # Bold
            text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
            # Lists
            lines = text.split("\n")
            in_list = False
            result = []
            for line in lines:
                if line.startswith("- "):
                    if not in_list:
                        result.append("<ul>")
                        in_list = True
                    result.append(f"<li>{line[2:]}</li>")
                else:
                    if in_list:
                        result.append("</ul>")
                        in_list = False
                    result.append(line)
            if in_list:
                result.append("</ul>")
            return "\n".join(result)

        html_parts = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            f"<title>{html.escape(self.name)} - Skill Documentation</title>",
            "<style>",
            "body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
            "h1 { border-bottom: 2px solid #333; padding-bottom: 10px; }",
            "h2 { color: #555; margin-top: 30px; }",
            "table { border-collapse: collapse; width: 100%; margin: 15px 0; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "th { background-color: #f5f5f5; }",
            "code { background-color: #f5f5f5; padding: 2px 5px; border-radius: 3px; }",
            "pre { background-color: #f5f5f5; padding: 15px; border-radius: 5px; overflow-x: auto; }",
            "pre code { background: none; padding: 0; }",
            ".trigger { background-color: #e8f4e8; padding: 10px; border-left: 4px solid #4a4; margin: 5px 0; }",
            "</style>",
            "</head>",
            "<body>",
            f"<h1>{html.escape(self.name)}</h1>",
            f"<p>{html.escape(self.description)}</p>",
            "<h2>Quick Reference</h2>",
            "<table>",
            "<tr><th>Property</th><th>Value</th></tr>",
        ]

        if self.model:
            html_parts.append(
                f"<tr><td>Model</td><td><code>{html.escape(self.model)}</code></td></tr>"
            )
        if self.allowed_tools:
            tools = ", ".join(f"<code>{html.escape(t)}</code>" for t in self.allowed_tools)
            html_parts.append(f"<tr><td>Allowed Tools</td><td>{tools}</td></tr>")
        html_parts.append(
            f"<tr><td>User Invocable</td><td>{'Yes' if self.user_invocable else 'No'}</td></tr>"
        )
        if self.task_type:
            html_parts.append(
                f"<tr><td>Task Type</td><td><code>{html.escape(self.task_type)}</code></td></tr>"
            )
        if self.agent:
            html_parts.append(
                f"<tr><td>Agent</td><td><code>{html.escape(self.agent)}</code></td></tr>"
            )
        html_parts.append(f"<tr><td>Blocking</td><td>{'Yes' if self.blocking else 'No'}</td></tr>")
        html_parts.append("</table>")

        if self.trigger_phrases:
            html_parts.append("<h2>How to Use</h2>")
            html_parts.append("<p>Trigger this skill by saying:</p>")
            for phrase in self.trigger_phrases:
                html_parts.append(f'<div class="trigger">"{html.escape(phrase)}"</div>')

        if self.parameters:
            html_parts.append("<h2>Parameters</h2>")
            html_parts.append("<table>")
            html_parts.append(
                "<tr><th>Name</th><th>Type</th><th>Required</th><th>Default</th><th>Description</th></tr>"
            )
            for param in self.parameters:
                req = "Yes" if param.required else "No"
                default = (
                    f"<code>{html.escape(str(param.default))}</code>" if param.default else "-"
                )
                desc = html.escape(param.description or "-")
                html_parts.append(
                    f"<tr><td><code>{html.escape(param.name)}</code></td>"
                    f"<td><code>{html.escape(param.type)}</code></td>"
                    f"<td>{req}</td><td>{default}</td><td>{desc}</td></tr>"
                )
            html_parts.append("</table>")

        for section_name, section_content in self.body_sections.items():
            html_parts.append(f"<h2>{html.escape(section_name)}</h2>")
            html_parts.append(f"<div>{md_to_html(section_content)}</div>")

        if self.path:
            html_parts.append("<hr>")
            html_parts.append(f"<p><em>Source: <code>{html.escape(str(self.path))}</code></em></p>")

        html_parts.extend(["</body>", "</html>"])

        return "\n".join(html_parts)


class SkillDocsGenerator:
    """
    Generates documentation from loaded skill definitions.

    Parses skill metadata, parameters, and body sections to produce
    structured documentation in markdown or HTML format.
    """

    def __init__(self, loader: SkillLoader) -> None:
        """
        Initialize documentation generator.

        Args:
            loader: SkillLoader with skills to document.
        """
        self.loader = loader

    def generate(self, skill: LoadedSkill) -> SkillDoc:
        """
        Generate documentation for a single skill.

        Args:
            skill: Loaded skill to document.

        Returns:
            SkillDoc with structured documentation.
        """
        # Extract parameters from payload schema
        parameters = []
        if skill.klabautermann.payload_schema:
            for name, field_def in skill.klabautermann.get_payload_fields().items():
                parameters.append(
                    SkillParameter(
                        name=name,
                        type=field_def.type,
                        required=field_def.required,
                        default=str(field_def.default) if field_def.default is not None else None,
                        description=field_def.description,
                    )
                )

        # Extract allowed tools
        allowed_tools = []
        if skill.metadata.allowed_tools:
            if isinstance(skill.metadata.allowed_tools, str):
                allowed_tools = [t.strip() for t in skill.metadata.allowed_tools.split(",")]
            else:
                allowed_tools = list(skill.metadata.allowed_tools)

        # Extract trigger phrases from description
        trigger_phrases = self._extract_trigger_phrases(skill.description)

        # Parse body sections
        body_sections = self._parse_body_sections(skill.body)

        return SkillDoc(
            name=skill.name,
            description=skill.description,
            model=skill.metadata.model,
            allowed_tools=allowed_tools,
            user_invocable=skill.metadata.user_invocable,
            task_type=skill.klabautermann.task_type,
            agent=skill.klabautermann.agent,
            blocking=skill.klabautermann.blocking,
            parameters=parameters,
            trigger_phrases=trigger_phrases,
            body_sections=body_sections,
            path=skill.path,
        )

    def generate_all(self) -> dict[str, SkillDoc]:
        """
        Generate documentation for all loaded skills.

        Returns:
            Dict mapping skill name to SkillDoc.
        """
        self.loader.load_all()
        docs = {}

        for skill_name in self.loader.list_skills():
            skill = self.loader.get(skill_name)
            if skill:
                docs[skill_name] = self.generate(skill)
                logger.debug(
                    "[WHISPER] Generated docs for skill",
                    extra={"skill": skill_name},
                )

        logger.info(
            "[CHART] Generated skill documentation",
            extra={"count": len(docs)},
        )
        return docs

    def generate_index(self, docs: dict[str, SkillDoc] | None = None) -> str:
        """
        Generate an index page listing all skills.

        Args:
            docs: Pre-generated docs, or None to generate fresh.

        Returns:
            Markdown index page.
        """
        if docs is None:
            docs = self.generate_all()

        lines = [
            "# Skill Reference",
            "",
            "Available skills in Klabautermann.",
            "",
            "## Skills",
            "",
            "| Skill | Description | Agent | User Invocable |",
            "|-------|-------------|-------|----------------|",
        ]

        for name in sorted(docs.keys()):
            doc = docs[name]
            agent = doc.agent or "-"
            invocable = "Yes" if doc.user_invocable else "No"
            # Truncate description for table
            desc = doc.description[:60] + "..." if len(doc.description) > 60 else doc.description
            lines.append(f"| [{name}](#{name}) | {desc} | {agent} | {invocable} |")

        lines.append("")
        lines.append("---")
        lines.append("")

        # Add individual skill docs
        for name in sorted(docs.keys()):
            doc = docs[name]
            lines.append(doc.to_markdown())
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _extract_trigger_phrases(self, description: str) -> list[str]:
        """
        Extract trigger phrases from skill description.

        Looks for quoted strings after phrases like "Use when" or "say".

        Args:
            description: Skill description text.

        Returns:
            List of extracted trigger phrases.
        """
        import re

        phrases = []

        # Look for quoted strings
        quoted = re.findall(r'"([^"]+)"', description)
        phrases.extend(quoted)

        # Also look for phrases after "say", "ask", etc.
        patterns = [
            r"(?:say|ask|type)\s+['\"]([^'\"]+)['\"]",
            r"(?:say|ask|type)\s+(\w+(?:\s+\w+){0,5})",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            phrases.extend(matches)

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for phrase in phrases:
            if phrase.lower() not in seen:
                seen.add(phrase.lower())
                unique.append(phrase)

        return unique

    def _parse_body_sections(self, body: str) -> dict[str, str]:
        """
        Parse markdown body into named sections.

        Args:
            body: Markdown body text.

        Returns:
            Dict mapping section name to content.
        """
        import re

        sections = {}
        current_section = None
        current_content: list[str] = []

        for line in body.split("\n"):
            # Check for section header (## or #)
            header_match = re.match(r"^#{1,2}\s+(.+)$", line)
            if header_match:
                # Save previous section
                if current_section:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = header_match.group(1)
                current_content = []
            elif current_section:
                current_content.append(line)

        # Save last section
        if current_section:
            sections[current_section] = "\n".join(current_content).strip()

        return sections


# ===========================================================================
# Convenience Functions
# ===========================================================================


def generate_skill_docs(
    loader: SkillLoader,
    output_dir: Path | None = None,
    format: str = "markdown",
) -> dict[str, SkillDoc]:
    """
    Generate documentation for all skills.

    Args:
        loader: SkillLoader with skills to document.
        output_dir: Optional directory to write docs to.
        format: Output format ("markdown" or "html").

    Returns:
        Dict mapping skill name to SkillDoc.
    """
    generator = SkillDocsGenerator(loader)
    docs = generator.generate_all()

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write individual skill docs
        for name, doc in docs.items():
            if format == "html":
                filepath = output_dir / f"{name}.html"
                filepath.write_text(doc.to_html(), encoding="utf-8")
            else:
                filepath = output_dir / f"{name}.md"
                filepath.write_text(doc.to_markdown(), encoding="utf-8")

        # Write index
        index_content = generator.generate_index(docs)
        index_path = output_dir / ("index.html" if format == "html" else "index.md")
        index_path.write_text(index_content, encoding="utf-8")

        logger.info(
            "[CHART] Wrote skill documentation",
            extra={"output_dir": str(output_dir), "count": len(docs)},
        )

    return docs


def generate_skill_doc(skill: LoadedSkill) -> SkillDoc:
    """
    Generate documentation for a single skill.

    Args:
        skill: Loaded skill to document.

    Returns:
        SkillDoc with structured documentation.
    """
    # Create a minimal loader just for the generator interface
    from klabautermann.skills.loader import SkillLoader

    generator = SkillDocsGenerator(SkillLoader())
    return generator.generate(skill)
