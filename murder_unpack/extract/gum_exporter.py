"""Reconstruct .gum dialogue scripts from compiled CharacterAsset JSON.

Gum is Murder Engine's dialogue scripting language. The packed game data
contains the compiled graph form. This module traverses the block/edge
graph and reconstructs approximate .gum source syntax.

Note: This is a best-effort reconstruction. Some nuances (exact whitespace,
comments, original ordering of conditions) may differ from the original source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

EDGE_KIND_NEXT = 1
EDGE_KIND_CHOICE = 2
EDGE_KIND_RANDOM = 3
EDGE_KIND_HIGHEST_SCORE = 4
EDGE_KIND_IF_ELSE = 5

CRITERION_KIND = {0: "is", 1: "!=", 2: "<", 3: "<=", 4: ">", 5: ">="}
ACTION_KIND = {0: "=", 1: "+=", 2: "-=", 3: "c:"}


class GumExporter:
    """Reconstruct .gum scripts from compiled CharacterAsset dialogue data."""

    def __init__(self, lookup: Any = None) -> None:
        """Args:
            lookup: Optional LocalizationLookup for resolving text GUIDs
        """
        self._lookup = lookup

    def export_character(self, char: dict[str, Any]) -> str:
        """Export a CharacterAsset to .gum script format."""
        situations = char.get("allSituations", char.get("Situations", []))
        if isinstance(situations, dict):
            situations = list(situations.values())

        parts: list[str] = []
        for situation in situations:
            parts.append(self._export_situation(situation))

        return "\n".join(parts)

    def _export_situation(self, situation: dict[str, Any]) -> str:
        """Export a single situation to .gum syntax."""
        name = situation.get("Name", "Unnamed")
        lines: list[str] = [f"={name}"]

        dialogs = situation.get("Dialogs", [])
        edges = situation.get("Edges", {})

        if not dialogs:
            lines.append("    // (empty situation)")
            return "\n".join(lines) + "\n"

        # Build edge lookup: block_id -> Edge
        edge_map: dict[int, dict[str, Any]] = {}
        if isinstance(edges, dict):
            for block_id_str, edge in edges.items():
                edge_map[int(block_id_str)] = edge

        # Find root block (usually id 0)
        root_id = 0
        visited: set[int] = set()

        self._export_block_tree(lines, dialogs, edge_map, root_id, visited, indent=1)

        return "\n".join(lines) + "\n"

    def _export_block_tree(
        self,
        lines: list[str],
        dialogs: list[dict[str, Any]],
        edge_map: dict[int, dict[str, Any]],
        block_id: int,
        visited: set[int],
        indent: int,
    ) -> None:
        """Recursively export a block and its children."""
        if block_id in visited:
            return
        visited.add(block_id)

        block = self._find_block(dialogs, block_id)
        if block is None:
            return

        prefix = "    " * indent
        edge = edge_map.get(block_id)

        # Check edge kind to determine flow directive
        if edge:
            kind = edge.get("Kind", EDGE_KIND_NEXT)
            if kind == EDGE_KIND_RANDOM:
                lines.append(f"{prefix}@random")
            elif kind == EDGE_KIND_IF_ELSE:
                pass  # Conditions handle this

        # Get child block IDs from edge
        child_ids = []
        if edge:
            child_ids = edge.get("Dialogs", edge.get("Blocks", []))

        # Export requirements as conditions
        requirements = block.get("Requirements", [])
        if requirements:
            cond_str = self._format_requirements(requirements)
            lines.append(f"{prefix}({cond_str})")
            self._export_block_content(lines, block, indent + 1)
        else:
            self._export_block_content(lines, block, indent)

        # Export children
        for child_id in child_ids:
            child = self._find_block(dialogs, child_id)
            if child is None:
                continue

            child_reqs = child.get("Requirements", [])
            is_choice = child.get("IsChoice", False)

            if is_choice:
                # Choice blocks
                choice_lines = child.get("Lines", [])
                choice_text = self._resolve_line_text(choice_lines[0]) if choice_lines else "..."
                lines.append(f"{prefix}> {choice_text}")
                # Export choice body (remaining lines)
                if len(choice_lines) > 1:
                    for line in choice_lines[1:]:
                        text = self._resolve_line_text(line)
                        speaker = self._format_speaker_portrait(line)
                        if text:
                            lines.append(f"{prefix}    {speaker}{text}")
            elif child_reqs and edge and edge.get("Kind") == EDGE_KIND_IF_ELSE:
                # Else branch
                if child_id != child_ids[0]:
                    lines.append(f"{prefix}(...)")
                self._export_block_tree(lines, dialogs, edge_map, child_id, visited, indent)
            else:
                self._export_block_tree(lines, dialogs, edge_map, child_id, visited, indent)

    def _export_block_content(
        self,
        lines: list[str],
        block: dict[str, Any],
        indent: int,
    ) -> None:
        """Export the content of a single block (lines, actions, goto)."""
        prefix = "    " * indent
        play_until = block.get("PlayUntil", -1)
        chance = block.get("Chance", 1.0)
        block_lines = block.get("Lines", [])
        actions = block.get("Actions", [])
        goto = block.get("GoTo")
        is_exit = block.get("IsExit", False)

        # Line prefix based on play count
        line_marker = ""
        if play_until == 1:
            line_marker = "- "
        elif play_until > 1:
            line_marker = f"@{play_until} "

        # Chance prefix
        chance_str = ""
        if chance < 1.0:
            chance_str = f"%{int(chance * 100)} "

        # Export actions before lines
        for action in actions:
            action_str = self._format_action(action)
            if action_str:
                lines.append(f"{prefix}[{action_str}]")

        # Export dialogue lines
        for i, line in enumerate(block_lines):
            text = self._resolve_line_text(line)
            speaker = self._format_speaker_portrait(line)
            if text:
                marker = line_marker if i == 0 else ""
                chance_pfx = chance_str if i == 0 else ""
                lines.append(f"{prefix}{marker}{chance_pfx}{speaker}{text}")

        # Export goto
        if goto:
            lines.append(f"{prefix}-> {goto}")
        elif is_exit:
            lines.append(f"{prefix}-> exit!")

    def _find_block(self, dialogs: list[dict[str, Any]], block_id: int) -> dict[str, Any] | None:
        """Find a block by ID in the dialogs list."""
        for d in dialogs:
            if d.get("Id") == block_id:
                return d
        return None

    def _resolve_line_text(self, line: dict[str, Any]) -> str:
        """Resolve a line's text, using localization lookup if available."""
        text = line.get("Text", "")
        if self._lookup and isinstance(text, dict):
            return self._lookup.resolve_text(text)
        if isinstance(text, dict):
            return text.get("Id", "")
        return text

    def _format_speaker_portrait(self, line: dict[str, Any]) -> str:
        """Format speaker and portrait prefix."""
        speaker = line.get("Speaker", "")
        portrait = line.get("Portrait", "")

        if self._lookup and speaker:
            speaker = self._lookup.resolve_speaker(speaker)

        if not speaker:
            return ""
        if portrait:
            return f"{speaker}.{portrait}: "
        return f"{speaker}: "

    def _format_requirements(self, requirements: list[dict[str, Any]]) -> str:
        """Format requirement conditions as .gum syntax."""
        parts: list[str] = []
        for req in requirements:
            criterion = req.get("Criterion", req)
            fact = criterion.get("Fact", {})
            fact_name = fact.get("Name", fact.get("name", "?"))
            kind = criterion.get("Kind", 0)
            value = criterion.get("Value")

            op = CRITERION_KIND.get(kind, "is")
            if op == "is" and value is None:
                parts.append(fact_name)
            elif op == "is" and isinstance(value, bool):
                if not value:
                    parts.append(f"!{fact_name}")
                else:
                    parts.append(fact_name)
            else:
                parts.append(f"{fact_name} {op} {value}")

            # Logical connector
            node_kind = req.get("Kind", 0)
            if node_kind == 1:  # Or
                parts.append("or")

        # Filter out trailing "or"
        if parts and parts[-1] in ("and", "or"):
            parts.pop()

        return " and ".join(parts) if "or" not in parts else " ".join(parts)

    def _format_action(self, action: dict[str, Any]) -> str:
        """Format an action as .gum [action] syntax."""
        fact = action.get("Fact", {})
        fact_name = fact.get("Name", fact.get("name", "?"))
        kind = action.get("Kind", 0)
        value = action.get("Value")

        op = ACTION_KIND.get(kind, "=")
        if op == "c:":
            return f"c:{fact_name}"
        if value is not None:
            return f"{fact_name} {op} {value}"
        return f"{fact_name} {op} true"


def export_dialogues_gum(
    db: Any,
    output_dir: Path | str,
) -> int:
    """Export all CharacterAsset dialogues as .gum script files.

    Returns count of exported scripts.
    """
    from murder_unpack.extract.dialogue_extractor import LocalizationLookup

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lookup = LocalizationLookup(db)
    exporter = GumExporter(lookup)
    characters = db.get_by_type("Murder.Assets.CharacterAsset")
    count = 0

    for char in characters:
        name = char.get("Name", f"unknown_{count}")
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        out_path = output_dir / f"{safe_name}.gum"

        script = exporter.export_character(char)
        out_path.write_text(script, encoding="utf-8")
        count += 1

    return count
