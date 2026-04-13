"""Neverway Prologue — decompiler and runtime fixes.

Game: Neverway Prologue (Murder Engine, Road namespace)
"""

from murder_unpack.fixes import GameFix, Replacement

FIX = GameFix(
    id="neverway",
    name="Neverway Prologue",
    assembly_names=["Neverway"],
    game_namespaces=["Road"],
    game_config_types=["Road.Assets.RoadGameProfile"],
    replacements=[
        # CS1061: Tuple element name lost — decompiler outputs (QuestAsset, int)
        # but code accesses .Quest which was a named tuple element
        Replacement(
            file_glob="**/RoadSaveData.cs",
            old="orderby -kv.Quest.Priority\n\t\t\tselect kv.Quest.Guid",
            new="orderby -kv.Item1.Priority\n\t\t\tselect kv.Item1.Guid",
            description="CS1061: lost tuple element name .Quest → .Item1",
        ),
        # CS0128: Duplicate local function from coroutine decompilation
        Replacement(
            file_glob="**/DisassembleBlueprintStateMachine.cs",
            old="customDraw.Destroy();\n\t\t\t\t}\n\t\t\t\tIEnumerator<Wait> DestroyAndPopItems()",
            new="customDraw.Destroy();\n\t\t\t\t}\n\t\t\t\tIEnumerator<Wait> DestroyAndPopItems2()",
            description="CS0128: duplicate local function name",
        ),
        # CS0191: readonly field assigned in init→set property setter
        Replacement(
            file_glob="**/Inventory/Item.cs",
            old="private readonly Portrait _smallInventoryPortrait;",
            new="private Portrait _smallInventoryPortrait;",
            description="CS0191: readonly field assigned outside constructor",
        ),
        # Runtime: Steamworks.NET may fail to load without Steam installed.
        # Make field lazy so type-load doesn't crash.
        Replacement(
            file_glob="**/RoadGame.cs",
            old="private static readonly ThirdPartyManager _thirdPartyManager = new ThirdPartyManager();",
            new="private static ThirdPartyManager? _thirdPartyManager;",
            description="Runtime: lazy ThirdPartyManager + remove readonly (CS0198)",
        ),
        Replacement(
            file_glob="**/RoadGame.cs",
            old="\t\t_thirdPartyManager.Initialize();",
            new="\t\ttry { _thirdPartyManager = new ThirdPartyManager(); _thirdPartyManager.Initialize(); }\n\t\tcatch (System.Exception ex) when (ex is System.IO.FileNotFoundException or System.TypeLoadException or System.DllNotFoundException) { _thirdPartyManager = null; }",
            description="Runtime: graceful Steam init when Steamworks.NET unavailable",
        ),
        Replacement(
            file_glob="**/RoadGame.cs",
            old="\t\t_thirdPartyManager.Update();",
            new="\t\t_thirdPartyManager?.Update();",
            description="Runtime: null-safe Steam update",
        ),
        Replacement(
            file_glob="**/RoadGame.cs",
            old="\t\t_thirdPartyManager.Exit();",
            new="\t\t_thirdPartyManager?.Exit();",
            description="Runtime: null-safe Steam exit",
        ),
    ],
)
