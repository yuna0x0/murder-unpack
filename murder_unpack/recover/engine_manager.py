"""Clone and manage Murder Engine versions from GitHub."""

from __future__ import annotations

import subprocess
from pathlib import Path

MURDER_REPO = "https://github.com/isadorasophia/murder.git"


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
