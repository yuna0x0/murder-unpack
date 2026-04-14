"""Neo City Express (LDGame) -- decompiler fixes.

Game: Neo City Express (Murder Engine, LDGame namespace)
Source: https://github.com/isadorasophia/neocityexpress
Engine commit: 745810cf (murder repo, May 1 2023)

These fixes address decompiler artifacts specific to this game.
The engine version is provided via GameFix.engine_version; the fixes
here handle only decompiler output issues at that exact engine version.
"""

from __future__ import annotations

from pathlib import Path

from murder_unpack.fixes import GameFix, Replacement


def _custom_fixes(decompiled_dir: Path) -> int:
    """Add missing using directives for types the decompiler didn't resolve."""
    import re

    fixes = 0

    _USING_FIXES: list[tuple[str, str]] = [
        ("KeyboardAxis", "using Murder.Core.Input;"),
        ("OptionsInfo", "using Murder.Core.Input;"),
    ]

    for cs_file in decompiled_dir.rglob("*.cs"):
        try:
            src = cs_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        new_src = src
        for type_name, using_stmt in _USING_FIXES:
            if type_name in new_src and using_stmt not in new_src:
                last_using = -1
                for m in re.finditer(r"^using [^;]+;\s*$", new_src, re.MULTILINE):
                    last_using = m.end()
                if last_using >= 0:
                    new_src = new_src[:last_using] + using_stmt + "\n" + new_src[last_using:]

        if new_src != src:
            cs_file.write_text(new_src, encoding="utf-8")
            fixes += 1

    return fixes


FIX = GameFix(
    id="ldgame",
    name="Neo City Express",
    assembly_names=["LDGame"],
    game_namespaces=["LDGame"],
    game_config_types=[
        "LDGame.Assets.LDGameProfile, LDGame",
        "LDGame.Assets.LDGameProfile",
    ],
    # Nearest public engine commit to the released game binary (May 2023).
    # The game was built from a private engine build; this is the closest
    # public commit (has MediumFont, IMonoRenderSystem, NowUnescaled).
    # ISoundPlayer overloads and doLineWrapping fixes compensate for
    # differences between this commit and the private build.
    engine_version="745810cfdaedcfe140137f920e83e9ccb2c362d9",
    replacements=[
        # ShowSenderOfSituation is a game-specific attribute that doesn't
        # exist in the engine. The decompiler pulled it from the game DLL
        # but it wasn't decompiled. Safe to remove.
        Replacement(
            file_glob="**/*.cs",
            old="\t[ShowSenderOfSituation]\n",
            new="",
            description="Remove missing ShowSenderOfSituation attribute",
        ),
        # KeyboarLayouts (sic) is a game-specific enum not in the engine.
        # GamePreferences.Layout and SetNextLayout are also game-specific.
        # Order matters: remove prefix first, then insert enum stub.
        Replacement(
            file_glob="**/LDGame.cs",
            old="GamePreferences.KeyboarLayouts",
            new="KeyboarLayouts",
            description="Remove GamePreferences prefix for KeyboarLayouts",
        ),
        Replacement(
            file_glob="**/LDGame.cs",
            old="public static void RegisterWASD(KeyboarLayouts layout)",
            new="public enum KeyboarLayouts { QWERTY, AZERTY, DVORAK, COLEMAK }\n\n\tpublic static void RegisterWASD(KeyboarLayouts layout)",
            description="Stub KeyboarLayouts enum (game-specific, not in engine)",
        ),
        # GamePreferences.Layout doesn't exist in engine -- it was a
        # game-specific property. Cast to the game subclass.
        # Use global:: to avoid namespace/class ambiguity.
        Replacement(
            file_glob="**/*.cs",
            old="Game.Preferences.Layout",
            new="((global::LDGame.Data.LdGamePreferences)Game.Preferences).Layout",
            description="Cast to game-specific preferences for Layout",
        ),
        Replacement(
            file_glob="**/*.cs",
            old="Game.Preferences.SetNextLayout()",
            new="((global::LDGame.Data.LdGamePreferences)Game.Preferences).SetNextLayout()",
            description="Cast to game-specific preferences for SetNextLayout",
        ),
        # MainMenuStateMachine also references GamePreferences.KeyboarLayouts
        Replacement(
            file_glob="**/MainMenuStateMachine.cs",
            old="GamePreferences.KeyboarLayouts",
            new="global::LDGame.LDGame.KeyboarLayouts",
            description="Resolve KeyboarLayouts in MainMenuStateMachine",
        ),
        # LdGamePreferences: Layout/SetNextLayout are game-specific.
        # Add them as properties/methods on the subclass.
        Replacement(
            file_glob="**/LdGamePreferences.cs",
            old="public class LdGamePreferences : GamePreferences\n{\n\tpublic int _layout;",
            new="public class LdGamePreferences : GamePreferences\n{\n\tpublic int _layout;\n\n\tpublic global::LDGame.LDGame.KeyboarLayouts Layout => (global::LDGame.LDGame.KeyboarLayouts)_layout;\n\n\tpublic global::LDGame.LDGame.KeyboarLayouts SetNextLayout()\n\t{\n\t\t_layout = (_layout + 1) % 4;\n\t\treturn Layout;\n\t}",
            description="Add Layout property and SetNextLayout method",
        ),
        Replacement(
            file_glob="**/LdGamePreferences.cs",
            old="LDGame.RegisterWASD(base.Layout);",
            new="LDGame.RegisterWASD(Layout);",
            description="Use local Layout property instead of base.Layout",
        ),
        # PlayerInput.ClearAxis doesn't exist in this engine version.
        # Stub as no-op extension method.
        Replacement(
            file_glob="**/LDGame.cs",
            old="\t\tGame.Input.ClearAxis(100);\n\t\tGame.Input.ClearAxis(101);",
            new="\t\t// ClearAxis not available in this engine version",
            description="Stub ClearAxis (game-specific, not in engine)",
        ),
        # ISoundPlayer.PlayEvent(SoundEventId, bool) -- the game adds
        # a third parameter not in the interface
        Replacement(
            file_glob="**/LDGameSoundPlayer.cs",
            old="public ValueTask PlayEvent(SoundEventId id, bool isLoop, bool stopLastMusic = true)",
            new="public ValueTask PlayEvent(SoundEventId id, bool isLoop) => PlayEvent(id, isLoop, true);\n\n\tpublic ValueTask PlayEvent(SoundEventId id, bool isLoop, bool stopLastMusic = true)",
            description="Add missing ISoundPlayer.PlayEvent(SoundEventId, bool) overload",
        ),
        # ISoundPlayer.PlayStreaming(SoundEventId) -- the game has
        # PlayStreaming(SoundEventId, bool) but the engine interface
        # requires a single-arg overload
        Replacement(
            file_glob="**/LDGameSoundPlayer.cs",
            old="public ValueTask PlayStreaming(SoundEventId id, bool stopLastMusic = true)",
            new="public ValueTask PlayStreaming(SoundEventId id) => PlayStreaming(id, true);\n\n\tpublic ValueTask PlayStreaming(SoundEventId id, bool stopLastMusic = true)",
            description="Add missing ISoundPlayer.PlayStreaming(SoundEventId) overload",
        ),
        # PixelFont.Draw doesn't have doLineWrapping parameter.
        # Remove the named arg -- it's the last parameter.
        Replacement(
            file_glob="**/*.cs",
            old=", doLineWrapping: false)",
            new=")",
            description="Remove doLineWrapping named arg (not in engine)",
        ),
        # DrawInfo.Color is init-only -- decompiler emits assignment
        # outside initializer. Use object initializer syntax.
        Replacement(
            file_glob="**/DrowsySystem.cs",
            old="DrawInfo drawInfo = new DrawInfo();\n\t\t\tdrawInfo.Color = Color.Black;\n\t\t\tDrawInfo drawInfo2 = drawInfo;",
            new="DrawInfo drawInfo2 = new DrawInfo() { Color = Color.Black };",
            description="Use object initializer for init-only DrawInfo.Color",
        ),
    ],
    custom_fix=_custom_fixes,
)
