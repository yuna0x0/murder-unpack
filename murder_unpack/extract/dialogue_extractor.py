"""Extract and export dialogue trees from Murder Engine CharacterAssets."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_dialogues(
    db: Any,  # GameDatabase
    output_dir: Path | str,
) -> int:
    """Extract all CharacterAsset dialogues to readable markdown files.

    Returns count of exported characters.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    characters = db.get_by_type("Murder.Assets.CharacterAsset")
    count = 0

    for char in characters:
        name = char.get("Name", f"unknown_{count}")
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        out_path = output_dir / f"{safe_name}.md"

        lines = [f"# {name}\n"]
        guid = char.get("Guid", "")
        if guid:
            lines.append(f"**GUID:** `{guid}`\n")

        # Extract situations (dialogue trees)
        situations = char.get("Situations", char.get("situations", {}))
        if isinstance(situations, dict):
            for sit_id, situation in situations.items():
                _format_situation(lines, sit_id, situation)
        elif isinstance(situations, list):
            for i, situation in enumerate(situations):
                _format_situation(lines, str(i), situation)

        out_path.write_text("\n".join(lines), encoding="utf-8")
        count += 1

    return count


def _format_situation(lines: list[str], sit_id: str, situation: dict[str, Any]) -> None:
    """Format a single dialogue situation."""
    name = situation.get("Name", f"Situation {sit_id}")
    lines.append(f"\n## {name}\n")

    dialogs = situation.get("Dialogs", situation.get("dialogs", []))
    if not dialogs:
        # Try blocks format (Gum style)
        blocks = situation.get("Blocks", situation.get("blocks", []))
        for block in blocks:
            _format_block(lines, block)
        return

    for dialog in dialogs:
        _format_dialog(lines, dialog)

    edges = situation.get("Edges", situation.get("edges", {}))
    if edges:
        lines.append("\n### Edges\n")
        for edge_id, edge in edges.items() if isinstance(edges, dict) else enumerate(edges):
            kind = edge.get("Kind", edge.get("kind", "?"))
            blocks = edge.get("Blocks", edge.get("blocks", []))
            lines.append(f"- Edge {edge_id} ({kind}) → {blocks}")


def _format_block(lines: list[str], block: dict[str, Any]) -> None:
    """Format a dialogue block (Gum format)."""
    block_lines = block.get("Lines", block.get("lines", []))
    for line in block_lines:
        speaker = line.get("Speaker", line.get("speaker", ""))
        text = line.get("Text", line.get("text", ""))
        portrait = line.get("Portrait", line.get("portrait", ""))

        prefix = f"**{speaker}**" if speaker else "**???**"
        portrait_note = f" _{portrait}_" if portrait else ""
        lines.append(f"{prefix}{portrait_note}: {text}")

    actions = block.get("Actions", block.get("actions", []))
    for action in actions:
        lines.append(f"  > Action: `{action}`")

    is_choice = block.get("IsChoice", block.get("isChoice", False))
    if is_choice:
        lines.append("  *(choice)*")


def _format_dialog(lines: list[str], dialog: dict[str, Any]) -> None:
    """Format a dialog entry."""
    speaker = dialog.get("Speaker", "")
    text = dialog.get("Text", dialog.get("text", ""))
    portrait = dialog.get("Portrait", "")
    event = dialog.get("Event", "")

    if text:
        prefix = f"**{speaker}**" if speaker else "**???**"
        portrait_note = f" _{portrait}_" if portrait else ""
        lines.append(f"{prefix}{portrait_note}: {text}")

    if event:
        lines.append(f"  > Event: `{event}`")
