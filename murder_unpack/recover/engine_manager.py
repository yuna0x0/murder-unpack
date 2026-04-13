"""Clone and manage Murder Engine versions from GitHub.

Includes version detection from exported game data by fingerprinting
the GameProfile fields present in game_config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

MURDER_REPO = "https://github.com/isadorasophia/murder.git"

# Default version when no fingerprint matches. The Murder Engine maintainer
# recommends building against main, and an unrecognized config likely means
# the game was built from a version newer than our fingerprint table.
_DEFAULT_VERSION = "main"

# Known version fingerprints, ordered oldest → newest.
# Each entry: (version, required_fields, excluded_fields)
# A config matches if ALL required fields are present and NONE of the excluded fields are.
_VERSION_FINGERPRINTS: list[tuple[str, set[str], set[str]]] = [
    ("rel/3.6", {"Fullscreen"}, {"EnforceResolution"}),
    ("rel/4.0", {"EnforceResolution"}, {"LocalizationPath"}),
    ("rel/5.0", {"EnforceResolution", "LocalizationPath"}, {"FeedbackUrl"}),
    ("rel/7.0", {"FeedbackUrl"}, {"PreloadTextures"}),
    ("rel/10.0", {"PreloadTextures"}, {"VideoPath", "DefaultPalette", "MinimumVelocityForSweep"}),
    ("rel/11.0", {"VideoPath", "DefaultPalette", "MinimumVelocityForSweep"}, set()),
]


def detect_engine_version(game_config: dict[str, Any]) -> str:
    """Detect the Murder Engine version from game_config fields.

    Murder Engine does not embed a version string in exported games.
    This function infers the version by fingerprinting which fields are
    present in the serialized GameProfile, since fields were added and
    removed across major releases.

    The fingerprint table covers rel/3.6 through rel/11.0. For configs
    that match our newest known fingerprint, we return that version.
    For configs that don't match any fingerprint (likely a newer release),
    we fetch the latest rel/ branch from GitHub.

    Returns a branch name (e.g., "rel/11.0", "rel/10.0").
    """
    keys = set(game_config.keys())

    if not keys:
        return _DEFAULT_VERSION

    # Walk fingerprints newest → oldest, return first match.
    # "Match" means all required fields present AND no excluded fields present.
    for version, required, excluded in reversed(_VERSION_FINGERPRINTS):
        if required.issubset(keys) and not excluded.intersection(keys):
            # rel/8.0–10.0 share the same GameProfile fields.
            # We can't distinguish them, so we default to rel/10.0.
            return version

    # No fingerprint matched. The game was likely built from a version
    # newer than our table. Default to main per Murder Engine convention.
    return _DEFAULT_VERSION


def list_versions() -> dict[str, list[str]]:
    """Fetch available branches and tags from the Murder engine repo.

    Returns dict with keys "branches" and "tags".
    """
    result = subprocess.run(
        ["git", "ls-remote", "--heads", "--tags", MURDER_REPO],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git ls-remote failed: {result.stderr}")

    branches: list[str] = []
    tags: list[str] = []

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        _, ref = line.split("\t", 1)
        if ref.startswith("refs/heads/"):
            branches.append(ref.removeprefix("refs/heads/"))
        elif ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref.removeprefix("refs/tags/"))

    return {"branches": sorted(branches), "tags": sorted(tags)}


def clone_engine(
    target_dir: Path | str,
    version: str = _DEFAULT_VERSION,
    depth: int | None = 1,
) -> Path:
    """Clone the Murder engine repo at a specific version.

    Args:
        target_dir: Directory where 'murder/' will be created
        version: Branch name, tag, or commit hash
        depth: Clone depth (None for full clone, needed for commit hashes)

    Returns:
        Path to the cloned murder/ directory
    """
    target_dir = Path(target_dir)
    murder_dir = target_dir / "murder"

    if murder_dir.exists():
        raise FileExistsError(f"Directory already exists: {murder_dir}")

    cmd = ["git", "clone"]
    if depth is not None:
        cmd.extend(["--depth", str(depth)])
    cmd.extend(["--branch", version, "--single-branch", MURDER_REPO, str(murder_dir)])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Git clone timed out")

    if result.returncode != 0:
        # Branch/tag clone failed — try as a commit hash (needs full clone)
        if depth is not None:
            cmd = ["git", "clone", MURDER_REPO, str(murder_dir)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(f"Git clone failed: {result.stderr}")
            # Checkout the specific commit
            subprocess.run(
                ["git", "checkout", version],
                cwd=murder_dir, capture_output=True, text=True,
            )
        else:
            raise RuntimeError(f"Git clone failed: {result.stderr}")

    # Initialize submodules (bang, gum)
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=murder_dir, capture_output=True, text=True, timeout=300,
    )

    return murder_dir
