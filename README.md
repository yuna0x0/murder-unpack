# murder-unpack

Reverse-engineer exported [Murder Engine](https://github.com/isadorasophia/murder) games back into editor-openable projects. Extracts sprites, dialogues, world data, and more.

## Features

- **Project recovery** — Reconstruct a Murder Engine editor project from an exported game
- **Asset extraction** — Unpack `.gz` data files into individual JSON assets
- **Sprite extraction** — Extract individual sprites from texture atlas sheets as PNG
- **Dialogue export** — Reconstruct `.gum` scripts and export to markdown
- **Localization export** — Export localization CSV files matching Murder's editor format
- **Engine version detection** — Auto-detect engine version from game_config fingerprinting
- **Binary analysis** — Detect .NET deployment format (NativeAOT, single-file, self-contained)
- **C# stub generation** — Auto-generate typed C# classes from packed JSON data
- **Repacking** — Repack modified assets back into `.gz` format
- **Plugin system** — Extend with drop-in `.py` files or pip-installable packages

## Quick Start

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git (for engine cloning)
- .NET 8 SDK (for building recovered projects)

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
| `analyze-binary` | Detect .NET format, extract types from NativeAOT binaries |
| `plugins list` | List loaded plugins |
| `plugins dir` | Show plugin directories |

### Recovery Options

```bash
murder-unpack recover "path/to/game" recovered/ \
    --engine-version rel/11.0 \    # Override auto-detected version
    --game-name MyGame \           # Project name (auto-detected if omitted)
    --skip-engine \                # Don't clone engine
    --engine-path /path/to/murder  # Use existing engine
    --no-stubs                     # Skip C# stub generation
```

## Plugin System

Place `.py` files in `~/.murder-unpack/plugins/` or `./plugins/`:

```python
# plugins/my_handler.py
def register(registry):
    registry.asset_handlers["my_handler"] = MyHandler()

class MyHandler:
    name = "my_handler"
    asset_types = ["Custom.Assets.MyAsset"]

    def parse(self, asset_data):
        return asset_data

    def export(self, asset, output_path):
        output_path.write_text(str(asset))
```

Pip-installable plugins use entry points:

```toml
[project.entry-points."murder_unpack.asset_handlers"]
my_handler = "my_plugin:MyHandler"

[project.entry-points."murder_unpack.commands"]
my_cmd = "my_plugin.cli:my_command"
```

## Limitations

### Engine Version Detection

Murder Engine does not embed a version string in exported games. Version detection works by fingerprinting which fields are present in `game_config` — fields were added and removed across major releases. This means:

- Detection covers **rel/3.6 through rel/11.0**. Unrecognized configs fall back to `main` (per Murder Engine convention).
- Some version ranges are **indistinguishable** (e.g., rel/8.0, rel/9.0, and rel/10.0 share identical GameProfile fields — we default to rel/10.0).
- Use `--engine-version` to override if auto-detection picks the wrong version.

### NativeAOT Game Recovery

Games compiled with NativeAOT (like most shipped Murder Engine games) have their game logic baked into a native binary. Recovery can extract all **data and assets** but cannot recover:

- **Game-specific components** — ECS component structs with behavior logic (e.g., `Road.Components.*`). Generated stubs are empty placeholders that allow the project to compile but have no behavior.
- **Game-specific systems** — ECS systems that drive gameplay logic.
- **State machines, interactions, services** — All compiled game code.

The editor will open and you can browse assets, but world entities that depend on missing game logic may not render or behave correctly.

### Dialogue Reconstruction

`.gum` script reconstruction from compiled dialogue graphs is **best-effort**. Original formatting, comments, and some control flow nuances may differ from the source. The semantic content (text, choices, conditions, actions) is preserved.

### Repacking

The `repack` command produces `.gz` files compatible with Murder's format, but replacing files in a NativeAOT game binary requires additional patching that is not currently automated.

## Development

```bash
git clone https://github.com/yuna0x0/murder-unpack.git
cd murder-unpack
uv sync

# Run tests
uv run pytest
```

## License

[MIT](LICENSE) - yuna0x0
