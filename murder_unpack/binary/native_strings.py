"""Extract type information from NativeAOT binaries by scanning for strings.

Works on any platform's binary (PE, ELF, Mach-O) — just scans raw bytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedTypes:
    assets: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    state_machines: list[str] = field(default_factory=list)
    interactions: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.assets) + len(self.components) + len(self.systems) +
                len(self.services) + len(self.state_machines) +
                len(self.interactions) + len(self.other))


def extract_type_names(
    path: Path | str,
    namespace_prefix: str = "Road.",
) -> ExtractedTypes:
    """Extract .NET type names from a NativeAOT binary.

    NativeAOT binaries embed type name strings for reflection metadata,
    stack traces, and serialization. We scan for these patterns.

    Args:
        path: Path to the native binary (any platform)
        namespace_prefix: Namespace prefix to search for (default: "Road.")
    """
    data = Path(path).read_bytes()
    pattern = re.compile(
        namespace_prefix.encode("ascii").replace(b".", rb"\.") +
        rb"[A-Za-z_][A-Za-z0-9_.]*"
    )

    raw_matches: set[str] = set()
    for m in pattern.finditer(data):
        name = m.group().decode("ascii", errors="replace")
        if not name.endswith("."):
            raw_matches.add(name)

    result = ExtractedTypes()
    for name in sorted(raw_matches):
        if ".Assets." in name or name.endswith("Asset"):
            result.assets.append(name)
        elif ".Components." in name or name.endswith("Component"):
            result.components.append(name)
        elif ".Systems." in name or name.endswith("System"):
            result.systems.append(name)
        elif ".Services." in name or name.endswith("Service"):
            result.services.append(name)
        elif ".StateMachines." in name or name.endswith("StateMachine"):
            result.state_machines.append(name)
        elif ".Interactions." in name or name.endswith("Interaction"):
            result.interactions.append(name)
        else:
            result.other.append(name)

    return result
