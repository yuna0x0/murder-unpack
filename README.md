# murder-unpack

Reverse-engineer exported [Murder Engine](https://github.com/isadorasophia/murder) games back into editor-openable projects. Extracts sprites, dialogues, world data, and more.

## Features

- **Project recovery** — Reconstruct a Murder Engine editor project from an exported game
- **C# decompilation** — Full source recovery from managed single-file bundles via ilspycmd
- **C# stub generation** — Fallback: auto-generate typed C# classes from packed JSON data (NativeAOT games)
- **Asset extraction** — Unpack `.gz` data files into individual JSON assets
- **Sprite extraction** — Extract individual sprites from texture atlas sheets as PNG
- **Dialogue export** — Reconstruct `.gum` scripts and export to markdown
- **Localization export** — Export localization CSV files matching Murder's editor format
- **Engine version detection** — Auto-detect engine version from game_config fingerprinting
- **Binary analysis** — Detect .NET deployment format (NativeAOT, single-file, self-contained) with managed assembly detection
- **ARM64 Windows support** — Auto-configures x64 build workaround for Murder.FNA
- **Repacking** — Repack modified assets back into `.gz` format
- **Plugin system** — Extend with drop-in `.py` files or pip-installable packages

## Quick Start

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git (for engine cloning)
- .NET 8 SDK (for building recovered projects)
- [ilspycmd](https://github.com/icsharpcode/ILSpy) (optional, for C# decompilation): `dotnet tool install -g ilspycmd`

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
| `analyze-binary` | Detect .NET format, managed assembly detection, extract types |
| `plugins list` | List loaded plugins |
| `plugins dir` | Show plugin directories |

### Recovery Options

```bash
murder-unpack recover "path/to/game" recovered/ \
    --engine-version rel/11.0 \    # Override auto-detected version
    --game-name MyGame \           # Project name (default: original assembly name)
    --skip-engine \                # Don't clone engine
    --engine-path /path/to/murder  # Use existing engine
    --no-stubs \                   # Skip C# stub/decompilation
    --decompile-timeout 1200       # ilspycmd timeout in seconds (default: 600)
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

### C# Source Recovery

Recovery automatically detects the game's .NET deployment format and chooses the best strategy:

- **Managed single-file bundles** — Full C# source recovery via ilspycmd decompilation. The game assembly is extracted from the bundle, decompiled, and placed in the project. Requires `ilspycmd` (`dotnet tool install -g ilspycmd`). If ilspycmd is not installed or decompilation fails/times out, recovery falls back to stub generation.
- **NativeAOT binaries** — Game logic is baked into a native binary and cannot be decompiled. Recovery generates empty C# stubs from packed JSON data that allow the project to compile but have no behavior. Systems, state machines, interactions, and services are not recoverable.

Use `--decompile-timeout` to increase the timeout for ilspycmd if it runs slow on your machine (default: 600 seconds).

The recovery process patches the engine to warn instead of crash when referencing missing assets, so the editor remains usable. However, world entities that depend on missing game logic may not render or behave correctly.

### Dialogue Reconstruction

`.gum` script reconstruction from compiled dialogue graphs is **best-effort**. Original formatting, comments, and some control flow nuances may differ from the source. The semantic content (text, choices, conditions, actions) is preserved.

### Repacking

The `repack` command produces `.gz` files compatible with Murder's format, but replacing files in a NativeAOT game binary requires additional patching that is not currently automated.

## Development

```bash
git clone https://github.com/yuna0x0/murder-unpack.git
cd murder-unpack
uv sync
```

## License

[MIT](LICENSE) - yuna0x0
