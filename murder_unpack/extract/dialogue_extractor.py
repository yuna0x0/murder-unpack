"""Extract and export dialogue trees from Murder Engine CharacterAssets.

Murder's dialogue system uses localized string references:
- CharacterAsset.allSituations → dialogue tree structure
- Lines[].Text.Id → GUID referencing a localized string
- LocalizationAsset.resources → GUID → actual text
- Speaker GUIDs → RoadSpeakerAsset/CharacterAsset for character names
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

EDGE_KINDS = {0: "Next", 1: "Next", 2: "Choice", 3: "Random", 4: "HighestScore", 5: "IfElse"}


class LocalizationLookup:
    """Resolves localized string GUIDs to actual text."""

    def __init__(self, db: Any) -> None:
        self._strings: dict[str, str] = {}
        self._speakers: dict[str, str] = {}
        self._build(db)

    def _build(self, db: Any) -> None:
        # Build string lookup from all localization assets (prefer English)
        locs = db.get_by_type("Murder.Assets.Localization.LocalizationAsset")
        # Sort: "Resources" (English, no suffix) first
        locs.sort(key=lambda l: (l.get("Name", "") != "Resources", l.get("Name", "")))

        for loc in locs:
            for entry in loc.get("resources", []):
                guid = entry.get("Guid", "")
                text = entry.get("String", "")
                if guid and text and guid not in self._strings:
                    self._strings[guid] = text

        # Build speaker name lookup
        for speaker in db.get_by_type("Road.Assets.RoadSpeakerAsset"):
            guid = speaker.get("Guid", "")
            name = speaker.get("Name", "")
            if guid and name:
                self._speakers[guid] = name

        for speaker in db.get_by_type("Murder.Assets.Dialogs.SpeakerAsset"):
            guid = speaker.get("Guid", "")
            name = speaker.get("Name", "")
            if guid and name:
                self._speakers[guid] = name

        # Also index CharacterAssets by Owner GUID for speaker resolution
        for char in db.get_by_type("Murder.Assets.CharacterAsset"):
            owner = char.get("Owner", "")
            name = char.get("Name", "")
            if owner and name and owner != "00000000-0000-0000-0000-000000000000":
                self._speakers[owner] = name

    def resolve_text(self, text_ref: Any) -> str:
        """Resolve a Text field which can be a string, dict with Id, or None."""
        if text_ref is None:
            return ""
        if isinstance(text_ref, str):
            return self._strings.get(text_ref, text_ref)
        if isinstance(text_ref, dict):
            guid = text_ref.get("Id", "")
            return self._strings.get(guid, f"[{guid}]") if guid else ""
        return str(text_ref)

    def resolve_speaker(self, speaker_ref: Any) -> str:
        """Resolve a speaker GUID to a name."""
        if speaker_ref is None:
            return ""
        if isinstance(speaker_ref, str):
            return self._speakers.get(speaker_ref, speaker_ref[:8] if speaker_ref else "")
        if isinstance(speaker_ref, dict):
            guid = speaker_ref.get("Id", speaker_ref.get("Guid", ""))
            return self._speakers.get(guid, guid[:8] if guid else "")
        return str(speaker_ref)


def extract_dialogues(
    db: Any,  # GameDatabase
    output_dir: Path | str,
) -> int:
    """Extract all CharacterAsset dialogues to readable markdown files.

    Resolves localized string references to actual text using the English
    localization asset.

    Returns count of exported characters.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lookup = LocalizationLookup(db)
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

        owner = char.get("Owner", "")
        if owner and owner != "00000000-0000-0000-0000-000000000000":
            speaker_name = lookup.resolve_speaker(owner)
            lines.append(f"**Speaker:** {speaker_name}\n")

        # Extract situations from allSituations (the actual field name)
        situations = char.get("allSituations", char.get("Situations", char.get("situations", [])))
        if isinstance(situations, list):
            for situation in situations:
                _format_situation(lines, situation, lookup)
        elif isinstance(situations, dict):
            for sit_id, situation in situations.items():
                _format_situation(lines, situation, lookup)

        out_path.write_text("\n".join(lines), encoding="utf-8")
        count += 1

    return count


def _format_situation(
    lines: list[str],
    situation: dict[str, Any],
    lookup: LocalizationLookup,
) -> None:
    """Format a single dialogue situation with resolved text."""
    name = situation.get("Name", "Unnamed")
    sit_id = situation.get("Id", "?")
    lines.append(f"\n## {name} (id: {sit_id})\n")

    dialogs = situation.get("Dialogs", situation.get("dialogs", []))
    edges = situation.get("Edges", situation.get("edges", {}))

    for dialog in dialogs:
        dialog_id = dialog.get("Id", "?")
        is_choice = dialog.get("IsChoice", False)
        is_exit = dialog.get("IsExit", False)

        dialog_lines = dialog.get("Lines", [])
        requirements = dialog.get("Requirements", [])

        if not dialog_lines and not requirements and not is_choice:
            continue

        marker = ""
        if is_choice:
            marker = " *(choice)*"
        if is_exit:
            marker += " *(exit)*"

        if dialog_lines or is_choice:
            lines.append(f"### Dialog {dialog_id}{marker}\n")

        if requirements:
            lines.append(f"*Requirements: {len(requirements)} condition(s)*\n")

        for line_entry in dialog_lines:
            text = lookup.resolve_text(line_entry.get("Text"))
            speaker = lookup.resolve_speaker(line_entry.get("Speaker", ""))
            portrait = line_entry.get("Portrait", "")
            event = line_entry.get("Event", "")

            if text:
                prefix = f"**{speaker}**" if speaker else ">"
                portrait_note = f" _{portrait}_" if portrait else ""
                lines.append(f"{prefix}{portrait_note}: {text}\n")

            if event:
                lines.append(f"  > Event: `{event}`\n")

    # Format edges
    if edges:
        edge_lines = []
        for edge_id, edge in (edges.items() if isinstance(edges, dict) else enumerate(edges)):
            kind_num = edge.get("Kind", 0)
            kind = EDGE_KINDS.get(kind_num, f"Unknown({kind_num})")
            targets = edge.get("Dialogs", edge.get("Blocks", []))
            if targets:
                edge_lines.append(f"- Dialog {edge_id} →({kind})→ Dialog {targets}")
        if edge_lines:
            lines.append("**Flow:**\n")
            lines.extend(edge_lines)
            lines.append("")
