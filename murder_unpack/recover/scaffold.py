"""Generate C# project scaffold for Murder Engine editor projects.

Generates .sln, .csproj, Program.cs, and game class files matching the
hellomurder template (https://github.com/isadorasophia/hellomurder).
The game .csproj includes resource copy directives, source generator
references (Bang.Generator, Murder.Serializer), and trimmer configuration.
"""

from __future__ import annotations

from pathlib import Path

# Murder engine .csproj relative paths (from project root)
MURDER_CSPROJ = "murder/src/Murder/Murder.csproj"
MURDER_EDITOR_CSPROJ = "murder/src/Murder.Editor/Murder.Editor.csproj"
BANG_GENERATOR_CSPROJ = "murder/bang/src/Bang.Generator/Bang.Generator.csproj"
MURDER_SERIALIZER_CSPROJ = "murder/src/Murder.Serializer/Murder.Serializer.csproj"


def generate_solution(project_dir: Path, game_name: str) -> None:
    """Generate the full project scaffold."""
    project_dir = Path(project_dir)

    _write_sln(project_dir, game_name)
    _write_game_csproj(project_dir, game_name)
    _write_editor_csproj(project_dir, game_name)
    _write_program_cs(project_dir, game_name)
    _write_game_architect(project_dir, game_name)
    _write_game_class(project_dir, game_name)


def _write_sln(project_dir: Path, game_name: str) -> None:
    sln_path = project_dir / f"{game_name}.sln"
    game_guid = "FAE04EC0-301F-11D3-BF4B-00C04F79EFBC"
    content = f"""\
Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
VisualStudioVersion = 17.0.31903.59
MinimumVisualStudioVersion = 10.0.40219.1
Project("{{{game_guid}}}") = "{game_name}", "src\\{game_name}\\{game_name}.csproj", "{{11111111-1111-1111-1111-111111111111}}"
EndProject
Project("{{{game_guid}}}") = "{game_name}.Editor", "src\\{game_name}.Editor\\{game_name}.Editor.csproj", "{{22222222-2222-2222-2222-222222222222}}"
EndProject
Global
\tGlobalSection(SolutionConfigurationPlatforms) = preSolution
\t\tDebug|Any CPU = Debug|Any CPU
\t\tRelease|Any CPU = Release|Any CPU
\tEndGlobalSection
\tGlobalSection(ProjectConfigurationPlatforms) = postSolution
\t\t{{11111111-1111-1111-1111-111111111111}}.Debug|Any CPU.ActiveCfg = Debug|Any CPU
\t\t{{11111111-1111-1111-1111-111111111111}}.Debug|Any CPU.Build.0 = Debug|Any CPU
\t\t{{22222222-2222-2222-2222-222222222222}}.Debug|Any CPU.ActiveCfg = Debug|Any CPU
\t\t{{22222222-2222-2222-2222-222222222222}}.Debug|Any CPU.Build.0 = Debug|Any CPU
\tEndGlobalSection
EndGlobal
"""
    sln_path.write_text(content, encoding="utf-8")


def _write_game_csproj(project_dir: Path, game_name: str) -> None:
    game_dir = project_dir / "src" / game_name
    game_dir.mkdir(parents=True, exist_ok=True)

    # Relative paths from src/GameName/ to project root
    murder_ref = f"../../{MURDER_CSPROJ}"
    bang_ref = f"../../{BANG_GENERATOR_CSPROJ}"
    bang_analyzers_ref = "../../murder/bang/src/Bang.Analyzers/Bang.Analyzers.csproj"
    serializer_ref = f"../../{MURDER_SERIALIZER_CSPROJ}"

    content = f"""\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <PublishAot>true</PublishAot>
    <IsTrimmable>false</IsTrimmable>
    <JsonSerializerIsReflectionEnabledByDefault>false</JsonSerializerIsReflectionEnabledByDefault>
    <ErrorOnDuplicatePublishOutputFiles>false</ErrorOnDuplicatePublishOutputFiles>
    <GeneratorParentAssembly>Murder</GeneratorParentAssembly>
  </PropertyGroup>

  <!-- Copy resources and packed data to build output -->
  <ItemGroup>
    <Content Include="resources\\**" CopyToOutputDirectory="PreserveNewest" LinkBase="resources" />
    <Content Include="packed\\**" CopyToOutputDirectory="PreserveNewest" TargetPath="resources\\%(RecursiveDir)\\%(Filename)%(Extension)" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="{murder_ref}" />
    <ProjectReference Condition="'$(Configuration)' == 'Debug'" Include="{bang_analyzers_ref}">
      <ReferenceOutputAssembly>false</ReferenceOutputAssembly>
      <OutputItemType>Analyzer</OutputItemType>
    </ProjectReference>
    <ProjectReference Include="{bang_ref}">
      <ReferenceOutputAssembly>true</ReferenceOutputAssembly>
      <OutputItemType>Analyzer</OutputItemType>
    </ProjectReference>
    <CompilerVisibleProperty Include="GeneratorParentAssembly" />
    <ProjectReference Include="{serializer_ref}">
      <ReferenceOutputAssembly>true</ReferenceOutputAssembly>
      <OutputItemType>Analyzer</OutputItemType>
    </ProjectReference>
  </ItemGroup>

  <ItemGroup>
    <TrimmerRootAssembly Include="Bang" />
    <TrimmerRootAssembly Include="Murder" />
    <TrimmerRootAssembly Include="MonoGame.Framework" />
    <TrimmerRootAssembly Include="{game_name}" />
  </ItemGroup>
</Project>
"""
    (game_dir / f"{game_name}.csproj").write_text(content, encoding="utf-8")


def _write_editor_csproj(project_dir: Path, game_name: str) -> None:
    editor_dir = project_dir / "src" / f"{game_name}.Editor"
    editor_dir.mkdir(parents=True, exist_ok=True)

    murder_editor_ref = f"../../{MURDER_EDITOR_CSPROJ}"
    game_ref = f"../{game_name}/{game_name}.csproj"

    content = f"""\
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>WinExe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <PublishReadyToRun>false</PublishReadyToRun>
    <TieredCompilation>false</TieredCompilation>
    <DefineConstants>$(DefineConstants);EDITOR</DefineConstants>
  </PropertyGroup>

  <ItemGroup>
    <ProjectReference Include="{murder_editor_ref}" />
    <ProjectReference Include="{game_ref}" />
  </ItemGroup>
</Project>
"""
    (editor_dir / f"{game_name}.Editor.csproj").write_text(content, encoding="utf-8")


def _write_program_cs(project_dir: Path, game_name: str) -> None:
    editor_dir = project_dir / "src" / f"{game_name}.Editor"
    content = f"""\
using Murder.Editor;

namespace {game_name}.Editor;

public static class Program
{{
    [STAThread]
    static void Main()
    {{
        using var editor = new Architect(new {game_name}Architect());
        editor.Run();
    }}
}}
"""
    (editor_dir / "Program.cs").write_text(content, encoding="utf-8")


def _write_game_architect(project_dir: Path, game_name: str) -> None:
    editor_dir = project_dir / "src" / f"{game_name}.Editor"
    content = f"""\
using Murder.Editor;

namespace {game_name}.Editor;

public class {game_name}Architect : {game_name}Game, IMurderArchitect
{{
}}
"""
    (editor_dir / f"{game_name}Architect.cs").write_text(content, encoding="utf-8")


def _write_game_class(project_dir: Path, game_name: str) -> None:
    game_dir = project_dir / "src" / game_name
    content = f"""\
using Bang;
using Murder;
using Murder.Serialization;
using System.Text.Json;

namespace {game_name};

public class {game_name}Game : IMurderGame
{{
    public string Name => "{game_name}";

    public JsonSerializerOptions Options => {game_name}SerializerOptionsExtensions.Options;

    public ComponentsLookup ComponentsLookup => new {game_name}ComponentsLookup();

    public int GetDefaultFont() => 0;
}}

/// <summary>
/// Minimal components lookup stub.
/// Extends MurderComponentsLookup so all Murder engine components are registered.
/// The Bang.Generator source generator will create the real implementation
/// with proper component type mappings when custom components are defined.
/// </summary>
public class {game_name}ComponentsLookup : MurderComponentsLookup
{{
}}
"""
    (game_dir / f"{game_name}Game.cs").write_text(content, encoding="utf-8")
