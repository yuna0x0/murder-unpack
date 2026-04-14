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

# Known version fingerprints, ordered oldest -> newest.
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


def detect_engine_version(
    game_config: dict[str, Any],
    assembly_name: str | None = None,
    db: "GameDatabase | None" = None,
    game_dir: "Path | None" = None,
) -> str:
    """Detect the Murder Engine version from game data.

    Detection order:
    1. Per-game fix registry (exact engine commit for known games)
    2. GameProfile field fingerprinting (release branch for unknown games)

    Murder Engine does not embed a version string in exported games.
    For known games, the fix registry provides the exact engine commit.
    For unknown games, we infer the release branch by fingerprinting
    which fields are present in the serialized GameProfile.

    Returns a branch name, tag, or commit hash.
    """
    from murder_unpack.fixes import get_registry

    # Check per-game registry first
    known = get_registry().detect_engine_version(
        db=db, game_dir=game_dir, assembly_name=assembly_name,
    )
    if known:
        return known

    # Fall back to fingerprinting
    keys = set(game_config.keys())

    if not keys:
        return _DEFAULT_VERSION

    # Walk fingerprints newest -> oldest, return first match.
    for version, required, excluded in reversed(_VERSION_FINGERPRINTS):
        if required.issubset(keys) and not excluded.intersection(keys):
            return version

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
    repo: str | None = None,
) -> Path:
    """Clone the Murder engine repo at a specific version.

    Args:
        target_dir: Directory where 'murder/' will be created
        version: Branch name, tag, or commit hash
        depth: Clone depth (None for full clone, needed for commit hashes)
        repo: Git URL override (defaults to official Murder Engine repo)

    Returns:
        Path to the cloned murder/ directory
    """
    repo_url = repo or MURDER_REPO
    target_dir = Path(target_dir)
    murder_dir = target_dir / "murder"

    if murder_dir.exists():
        raise FileExistsError(f"Directory already exists: {murder_dir}")

    # Detect if version looks like a commit hash (hex, 7+ chars)
    is_hash = len(version) >= 7 and all(c in "0123456789abcdef" for c in version.lower())

    if is_hash:
        # Commit hashes need a full clone (not shallow) then checkout.
        # Use --no-checkout to avoid wasting time on default branch files.
        cmd = ["git", "clone", "--no-checkout", repo_url, str(murder_dir)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Git clone timed out")
        if result.returncode != 0:
            raise RuntimeError(f"Git clone failed: {result.stderr}")
        # Fetch the specific commit if not reachable (e.g. from a non-default branch)
        subprocess.run(
            ["git", "fetch", "origin", version],
            cwd=murder_dir, capture_output=True, text=True, timeout=120,
        )
        result = subprocess.run(
            ["git", "checkout", version],
            cwd=murder_dir, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Git checkout {version} failed: {result.stderr}")
    else:
        cmd = ["git", "clone"]
        if depth is not None:
            cmd.extend(["--depth", str(depth)])
        cmd.extend(["--branch", version, "--single-branch", repo_url, str(murder_dir)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Git clone timed out")
        if result.returncode != 0:
            raise RuntimeError(f"Git clone failed: {result.stderr}")

    # Initialize submodules (bang, gum)
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=murder_dir, capture_output=True, text=True, timeout=300,
    )

    return murder_dir
