"""Clone and manage Murder Engine versions from GitHub.

Includes version detection from exported game data by fingerprinting
the GameProfile fields present in game_config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

MURDER_REPO = "https://github.com/isadorasophia/murder.git"


def detect_engine_version(game_config: dict[str, Any]) -> str:
    """Detect the Murder Engine version from game_config fields.

    Uses a fingerprinting approach based on which fields are present/absent
    in the serialized GameProfile, as fields were added/removed across versions.

    Returns a branch name (e.g., "rel/11.0", "rel/9.0") or "main".
    """
    keys = set(game_config.keys())

    # rel/11.0+ : VideoPath, DefaultPalette, MinimumVelocityForSweep added;
    #             GameWidth/GameHeight/GameScale/FeedbackUrl removed
    if "VideoPath" in keys or "DefaultPalette" in keys or "MinimumVelocityForSweep" in keys:
        return "rel/11.0"

    # rel/8.0-10.0 : PreloadTextures added, FeedbackUrl still present
    if "PreloadTextures" in keys:
        # 8.0 vs 9.0/10.0: FixedUpdateFactor removed in 8.0+
        # 9.0 and 10.0 are identical in GameProfile — default to rel/10.0
        return "rel/10.0"

    # rel/7.0 : FeedbackUrl added, EnforceResolution/Fullscreen removed
    if "FeedbackUrl" in keys:
        return "rel/7.0"

    # rel/5.0 : LocalizationPath added, EnforceResolution still present
    if "LocalizationPath" in keys and "EnforceResolution" in keys:
        return "rel/5.0"

    # rel/4.0 : EnforceResolution, ScalingFilter, DefaultGridCellSize added
    if "EnforceResolution" in keys:
        return "rel/4.0"

    # rel/3.6 : baseline (Fullscreen present, no EnforceResolution)
    if "Fullscreen" in keys:
        return "rel/3.6"

    # Unknown — default to latest
    return "main"


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
    version: str = "main",
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
