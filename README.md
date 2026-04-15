# murder-unpack

Reverse-engineer exported [Murder Engine](https://github.com/isadorasophia/murder) games back into editor-openable projects. Extracts sprites, dialogues, world data, and more.

## Features

- **Project recovery** — Reconstruct a Murder Engine editor project from an exported game
- **C# decompilation** — Full source recovery from managed single-file bundles via bundled per-type decompiler (ilspycmd fallback)
- **C# stub generation** — Fallback: auto-generate typed C# classes from packed JSON data (NativeAOT games)
- **Per-game fixes** — Auto-detected decompiler artifact fixes with extensible registry
- **Asset extraction** — Unpack `.gz` data files into individual JSON assets
- **Sprite extraction** — Extract individual sprites from texture atlas sheets as PNG
- **Dialogue export** — Reconstruct `.gum` scripts and export to markdown
- **Localization export** — Export localization CSV files matching Murder's editor format
- **Engine version detection** — Per-game lookup for known games, fingerprint detection for unknown games
- **macOS .app support** — All commands accept `.app` bundle paths directly
- **Binary analysis** — Detect .NET deployment format (NativeAOT, single-file, self-contained)
- **Repacking** — Repack modified assets back into `.gz` format
- **Plugin system** — Extend with drop-in `.py` files or pip-installable packages

## Quick Start

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git (for engine cloning)
- .NET SDK matching the game's engine version (net7.0 or net8.0; for building recovered projects and the bundled decompiler)

### Install

```bash
# With uv (recommended)
uv tool install murder-unpack

# Or from source
git clone https://github.com/yuna0x0/murder-unpack.git
cd murder-unpack
uv sync
```

### Usage

```bash
# Show game info and detected engine version
murder-unpack info "path/to/game"

# Extract all data, sprites, dialogues, and localization
murder-unpack extract-all "path/to/game" output/

# Recover into a full editor project
murder-unpack recover "path/to/game" recovered/

# List assets with optional filters
murder-unpack list-assets "path/to/game" --type WorldAsset
```

## Commands

| Command | Description |
|---------|-------------|
| `info` | Show game info, asset counts, detected engine version |
| `extract-all` | Full extraction: data, sprites, dialogues, localization |
| `extract-data` | Dump all `.gz` data files as plain JSON |
| `extract-sprites` | Extract sprites from atlas sheets as PNG |
| `extract-dialogue` | Export dialogues as `.gum` scripts, markdown, or both |
| `list-assets` | List assets with `--type` and `--name` filters |
| `decode-qoi` | Convert a single QOI image to PNG |
| `recover` | Full editor project recovery |
| `engine-versions` | List available Murder Engine branches and tags |
| `repack` | Repack modified assets back into `.gz` format |
| `analyze-binary` | Detect .NET format, extract types, decompile |
| `plugins` | List loaded plugins and plugin directories |

### Recovery Options

```bash
murder-unpack recover "path/to/game" recovered/ \
    --engine-version rel/11.0 \    # Override auto-detected version (branch/tag/commit)
    --engine-repo https://...  \   # Use a fork or custom engine repo
    --game-name MyGame \           # Project name (auto-detected)
    --engine-path /path/to/murder  # Use existing engine clone
    --skip-engine \                # Don't clone engine
    --no-stubs \                   # Skip C# stub/decompilation
    --decompile-timeout 1200       # Decompilation timeout (default: 600)
    --game-fix neverway            # Per-game fix (auto-detected, 'none' to skip)
```

## Per-Game Fixes

Decompiled code sometimes has game-specific issues that can't be fixed generically (lost tuple element names, readonly field assignments, duplicate local functions). The fix registry auto-detects the game and applies known fixes.

Detection uses: assembly name, game namespace, Steam App ID, or game_config `$type`. Each game fix can also provide the exact engine commit for accurate recovery.

### Adding a fix for a new game

Create `murder_unpack/fixes/my_game.py`:

```python
from murder_unpack.fixes import GameFix, Replacement

FIX = GameFix(
    id="my-game",
    name="My Game",
    assembly_names=["MyGame"],
    steam_app_ids=["123456"],
    engine_version="abc123...",  # exact engine commit (optional)
    replacements=[
        Replacement(
            file_glob="**/SomeFile.cs",
            old="broken code",
            new="fixed code",
            description="CS1234: description of the issue",
        ),
    ],
)
```

Register in `murder_unpack/fixes/__init__.py`:

```python
def _load_builtin_fixes() -> None:
    from murder_unpack.fixes import my_game
    _registry.register(my_game.FIX)
```

Or register via plugin:

```python
def register(registry):
    from murder_unpack.fixes import get_registry
    get_registry().register(my_fix)
```

## Plugin System

Plugins extend murder-unpack with custom asset handlers, extractors, commands, and hooks.

**Drop-in plugins** — Place `.py` files in `~/.murder-unpack/plugins/` or `./plugins/`:

```python
# plugins/my_plugin.py
def register(registry):
    registry.asset_handlers["my_handler"] = MyHandler()

class MyHandler:
    name = "my_handler"
    asset_types = ["Custom.Assets.MyAsset"]

    def export(self, asset, output_path):
        output_path.write_text(str(asset))
```

**Pip-installable plugins** — Use entry points in `pyproject.toml`:

```toml
[project.entry-points."murder_unpack.asset_handlers"]
my_handler = "my_plugin:MyHandler"

[project.entry-points."murder_unpack.commands"]
my_cmd = "my_plugin.cli:my_command"
```

**Available extension points:** `asset_handlers`, `extractors`, `commands`, `hooks` (`pre_extract`, `post_extract`, `pre_recover`, `post_recover`)

## Limitations

### C# Source Recovery

- **Managed single-file bundles** — Full source recovery via bundled decompile-helper (per-type decompilation with timeouts). Falls back to ilspycmd, then to stub generation.
- **NativeAOT binaries** — Cannot be decompiled. Recovery generates C# stubs for compilation but without behavior.

With full decompilation, the recovery uses the decompiled game class directly and applies targeted compatibility fixes: `init` → `set` on engine types that cause CS8852 errors (detected via trial build), `readonly` removal on class fields for JSON deserialization, and `JsonStringEnumConverter` for string-based enum keys.

### Engine Version Detection

For known games, the fix registry provides the exact engine commit. For unknown games, fingerprint detection covers **rel/3.6 through rel/11.0** (some ranges are indistinguishable, e.g. rel/8.0-10.0 default to rel/10.0). Use `--engine-version` to override with a branch, tag, or commit hash.

### Dialogue Reconstruction

`.gum` script reconstruction from compiled dialogue graphs is best-effort. Semantic content is preserved; original formatting may differ.

## Development

```bash
git clone https://github.com/yuna0x0/murder-unpack.git
cd murder-unpack
uv sync
```

## AI Disclosure

AI was used to assist in the creation of some of this tool's base code.

## License

[MIT](LICENSE) - yuna0x0
