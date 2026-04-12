"""Protocol classes defining plugin interfaces.

Plugins can implement these protocols without inheriting — just provide
the right attributes and methods (structural typing via Protocol).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AssetHandler(Protocol):
    """Custom asset type handler for parsing and exporting game-specific assets."""

    name: str
    asset_types: list[str]  # $type strings this handler can process

    def parse(self, asset_data: dict[str, Any]) -> dict[str, Any]:
        """Parse raw asset dict into a structured format."""
        ...

    def export(self, asset: dict[str, Any], output_path: Path) -> None:
        """Export a parsed asset to a file."""
        ...


@runtime_checkable
class Extractor(Protocol):
    """Custom extraction format for exporting game data."""

    name: str
    format_id: str  # e.g. "csv", "yaml", "custom_format"

    def extract(self, asset: dict[str, Any], output_path: Path) -> None:
        """Extract/convert an asset to this format."""
        ...


@runtime_checkable
class PipelineHook(Protocol):
    """Hook into the recovery/extraction pipeline at defined stages."""

    stage: str  # "pre_extract", "post_extract", "pre_recover", "post_recover"

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute the hook, returning (possibly modified) context."""
        ...


@runtime_checkable
class Command(Protocol):
    """Custom CLI subcommand added by a plugin."""

    name: str
    help: str

    def run(self, **kwargs: Any) -> None:
        """Execute the command."""
        ...
