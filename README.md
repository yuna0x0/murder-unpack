# murder-unpack

Decompile, unpack, recover, and repack toolkit for [Murder Engine](https://github.com/isadorasophia/murder) games.

Reverse-engineers exported Murder Engine games back into editor-openable projects. Extracts sprites, dialogues, world data, and more. Supports Windows, Linux, and macOS game builds.

## Features

- **Full project recovery** — Reconstructs a Murder Engine editor project from an exported game
- **Asset extraction** — Unpack all `.gz` data files into individual JSON assets
- **Sprite extraction** — Extract individual sprites from texture atlas sheets as PNG
- **Dialogue export** — Reconstruct `.gum` scripts (Murder's dialogue format) and export to markdown
- **Binary analysis** — Detect .NET deployment format (NativeAOT, single-file bundle, self-contained)
- **Bundle extraction** — Extract managed assemblies from .NET single-file bundles
- **C# stub generation** — Auto-generate typed C# classes from packed JSON data
- **Engine management** — Clone any Murder Engine version (branch/tag/commit)
- **Repacking** — Repack modified assets back into the game's `.gz` format
- **Plugin system** — Extend with drop-in `.py` files or pip-installable packages
- **Cross-platform** — Works on Windows, Linux, and macOS; handles all three platforms' binaries

## Quick Start

### Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Git (for engine cloning)

### Install

```bash
# With uv (recommended)
uv tool install murder-unpack

# Or from source
git clone https://github.com/yuna0x0/murder-unpack.git
cd murder-unpack
uv sync
```

### Basic Usage

```bash
# Show game info and asset counts
murder-unpack info "path/to/game"

# Extract all data, sprites, and dialogues
murder-unpack extract-all "path/to/game" output/

# List all assets (with optional filters)
murder-unpack list-assets "path/to/game" --type WorldAsset

# Recover into a full editor project
murder-unpack recover "path/to/game" recovered/ --engine-version main
```

## Commands

### Extraction

| Command | Description |
|---------|-------------|
| `info <game_dir>` | Show game info, asset counts, and atlas list |
| `extract-all <game_dir> <output_dir>` | Full extraction: data, sprites, dialogues, and localization |
| `extract-data <game_dir> <output_dir>` | Dump all `.gz` data files as plain JSON |
| `extract-sprites <game_dir> <output_dir>` | Extract sprites from atlas sheets as PNG |
| `extract-dialogue <game_dir> <output_dir>` | Export dialogues as `.gum` scripts, markdown, or both |
| `list-assets <game_dir>` | List assets with `--type` and `--name` filters |
| `decode-qoi <input.qoi.gz> <output.png>` | Convert a single QOI image to PNG |

### Recovery

| Command | Description |
|---------|-------------|
| `recover <game_dir> <output_dir>` | Full editor project recovery |
| `engine-versions` | List available Murder Engine branches and tags |
| `repack <project_dir> <output_dir>` | Repack modified assets back into `.gz` format |

#### Recovery Options

```bash
murder-unpack recover "path/to/game" recovered/ \
    --engine-version rel/11.0 \    # Branch, tag, or commit hash
    --game-name MyGame \           # Project name (auto-detected if omitted)
    --skip-engine \                # Don't clone engine (link manually)
    --engine-path /path/to/murder  # Use existing engine clone
    --no-stubs                     # Skip C# stub generation
```

### Binary Analysis

| Command | Description |
|---------|-------------|
| `analyze-binary <exe_path>` | Detect format, extract type names |

```bash
# Analyze and extract assemblies from a Windows build
murder-unpack analyze-binary game.exe \
    --extract-assemblies extracted/ \
    --decompile decompiled/
```

### Plugins

| Command | Description |
|---------|-------------|
| `plugins list` | List loaded plugins |
| `plugins dir` | Show plugin directories |

## How It Works

### Game Data Format

Murder Engine exports games as GZip-compressed JSON:

| File | Contents |
|------|----------|
| `preload_data.gz` | Preload assets + total data file count |
| `data0.gz` — `dataN.gz` | Up to 500 game assets per file |
| `sounds.gz` | FMOD audio bank paths |
| `atlas/*.json` | Sprite atlas metadata (UV coords, trim areas) |
| `atlas/*.qoi.gz` | Texture sheets in QOI format, gzipped |
| `game_config` | Game profile configuration (JSON) |

### Recovery Process

1. **Load** — Decompress all `.gz` files, parse JSON, index 5000+ assets
2. **Split** — Write each asset as an individual `.json` file in the correct editor directory
3. **Scaffold** — Generate `.sln`, `.csproj`, `Program.cs` matching the [hellomurder](https://github.com/isadorasophia/hellomurder) template
4. **Resources** — Copy atlas, fonts, shaders, sounds, images, video, FMOD libs, icons
5. **Dialogues** — Reconstruct `.gum` dialogue scripts from compiled CharacterAsset data
6. **Localization** — Export localization CSV files for each language (matching editor format)
7. **Stubs** — Auto-generate C# stub classes for game-specific types (e.g., `Road.Assets.*`)
8. **Engine** — Clone Murder Engine at the specified version with submodules

### Binary Detection

Supports all .NET deployment formats across all platforms:

| Format | Windows | Linux | macOS |
|--------|---------|-------|-------|
| NativeAOT | PE | ELF | Mach-O |
| Single-file bundle | PE | ELF | Mach-O |
| Self-contained | `.exe` + `coreclr.dll` | binary + `libcoreclr.so` | binary + `libcoreclr.dylib` |
| Framework-dependent | `.dll` + `.runtimeconfig.json` | same | same |

## Plugin System

### Drop-in Plugins

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

### Pip-installable Plugins

```toml
# In your plugin's pyproject.toml
[project.entry-points."murder_unpack.asset_handlers"]
my_handler = "my_plugin:MyHandler"

[project.entry-points."murder_unpack.commands"]
my_cmd = "my_plugin.cli:my_command"
```

## Development

```bash
git clone https://github.com/yuna0x0/murder-unpack.git
cd murder-unpack
uv sync
uv run murder-unpack --help

# Install with binary analysis support
uv sync --extra binary

# Run tests
uv run pytest
```

## License

[MIT](LICENSE) - yuna0x0
