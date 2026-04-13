// Per-type .NET decompiler using ICSharpCode.Decompiler.
// Designed to be invoked by murder-unpack for reliable, non-hanging decompilation.
//
// Usage: decompile-helper <assembly> <output-dir> [--refs <dir>] [--timeout <sec>] [--namespace <ns>]
//
// Decompiles each type individually with a per-type timeout.
// Outputs one .cs file per top-level type in namespace-based subdirectories.
// Prints JSON progress lines to stdout for the Python caller to parse.

using System.Diagnostics;
using System.Reflection.Metadata;
using System.Text;
using System.Text.Json;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.Metadata;
using ICSharpCode.Decompiler.TypeSystem;

var assemblyPath = args[0];
var outputDir = args[1];
var refsDir = (string?)null;
var perTypeTimeout = 30; // seconds
var namespaceFilter = (string?)null;

for (int i = 2; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--refs" when i + 1 < args.Length:
            refsDir = args[++i];
            break;
        case "--timeout" when i + 1 < args.Length:
            perTypeTimeout = int.Parse(args[++i]);
            break;
        case "--namespace" when i + 1 < args.Length:
            namespaceFilter = args[++i];
            break;
    }
}

Directory.CreateDirectory(outputDir);

// Set up the decompiler with reference assemblies.
// InitAccessors=false: emit `set` instead of `init` — avoids CS8852
// (init-only assignment outside object initializers, valid IL, invalid C#).
var settings = new DecompilerSettings(ICSharpCode.Decompiler.CSharp.LanguageVersion.CSharp11_0)
{
    ThrowOnAssemblyResolveErrors = false,
    RemoveDeadCode = false,
    RemoveDeadStores = false,
    InitAccessors = false,
};

var resolver = new UniversalAssemblyResolver(
    assemblyPath,
    throwOnError: false,
    targetFramework: null
);

if (refsDir != null)
{
    resolver.AddSearchDirectory(refsDir);
}

using var module = new PEFile(assemblyPath);
var decompiler = new CSharpDecompiler(module, resolver, settings);

// Collect top-level types to decompile
var types = decompiler.TypeSystem.MainModule.TopLevelTypeDefinitions
    .Where(t => !t.Name.StartsWith("<"))  // skip compiler-generated
    .Where(t => t.FullName != "<Module>")
    .Where(t => !t.Name.EndsWith("SourceGenerationContext"))  // skip STJ source-gen (regenerated at build)
    .Where(t => !t.Name.EndsWith("SerializerOptionsExtensions"))  // skip Murder.Serializer output
    .ToList();

if (namespaceFilter != null)
{
    types = types.Where(t => t.Namespace.StartsWith(namespaceFilter)).ToList();
}

var succeeded = 0;
var failed = 0;
var skipped = 0;
var total = types.Count;

Report("start", $"Decompiling {total} types from {Path.GetFileName(assemblyPath)}");

foreach (var type in types)
{
    var fullName = type.FullName;

    try
    {
        string? code = null;
        var cts = new CancellationTokenSource(TimeSpan.FromSeconds(perTypeTimeout));

        // Run decompilation on a background thread with timeout
        var task = Task.Run(() =>
        {
            return decompiler.DecompileTypeAsString(new FullTypeName(fullName));
        }, cts.Token);

        if (task.Wait(TimeSpan.FromSeconds(perTypeTimeout)))
        {
            code = task.Result;
        }
        else
        {
            Report("timeout", fullName);
            failed++;
            continue;
        }

        if (string.IsNullOrWhiteSpace(code))
        {
            skipped++;
            continue;
        }

        // Write to namespace-based path
        var relPath = fullName.Replace('.', Path.DirectorySeparatorChar) + ".cs";
        var outPath = Path.Combine(outputDir, relPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
        File.WriteAllText(outPath, code, Encoding.UTF8);

        succeeded++;
        Report("ok", fullName);
    }
    catch (Exception ex)
    {
        Report("error", $"{fullName}: {ex.Message}");
        failed++;
    }
}

Report("done", $"{succeeded} succeeded, {failed} failed, {skipped} skipped out of {total}");
return failed > total / 2 ? 1 : 0; // fail if more than half the types failed

void Report(string status, string message)
{
    var json = JsonSerializer.Serialize(new { status, message });
    Console.WriteLine(json);
    Console.Out.Flush();
}
