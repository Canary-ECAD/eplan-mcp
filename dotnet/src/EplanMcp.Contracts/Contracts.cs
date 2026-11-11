using System.Collections.Generic;

namespace EplanMcp.Contracts
{
    /// <summary>Version numbers both sides check before anything runs.</summary>
    public static class Protocol
    {
        /// <summary>Wire protocol of <see cref="RunRequest"/> / <see cref="RunResult"/>. Bump on any
        /// breaking change; the server refuses a host outside its supported range.</summary>
        public const int Version = 1;

        /// <summary>Features a host advertises in <see cref="HelloResult.Features"/>.</summary>
        public static readonly string[] Features =
        {
            "compile_only", "snippets", "diagnostics_hints", "progress", "cancel", "budget",
            "audit", "scratch_marker", "safety_analyzer", "undo_step",
        };
    }

    /// <summary>One script run, written by the server as JSON (snake_case) next to the result path.</summary>
    public sealed class RunRequest
    {
        public int Protocol { get; set; }
        public string RunId { get; set; } = "";

        /// <summary>Script source. Either a full compilation unit with a static <c>Run</c> method, or a
        /// statement body ("snippet") that is wrapped into one.</summary>
        public string Source { get; set; } = "";

        /// <summary>Saved script file the source came from, or null for ad-hoc code. Only saved
        /// scripts may write to a real (non-scratch) project.</summary>
        public string? ScriptPath { get; set; }

        /// <summary>Display name used in diagnostics and the audit log.</summary>
        public string SourceName { get; set; } = "script.cs";

        public Dictionary<string, object?> Args { get; set; } = new Dictionary<string, object?>();

        /// <summary>The arguments as canonical JSON text (sorted keys, no spaces). When set, the host
        /// uses THIS for the script's arguments, and it is part of the approval hash.</summary>
        public string? ArgsCanonical { get; set; }

        /// <summary>Project link file (.elk) or project name to act on. Null: the focused project,
        /// else the only open one.</summary>
        public string? Project { get; set; }

        public bool CompileOnly { get; set; }
        public bool DryRun { get; set; }

        /// <summary>Real-project writes need all of: this flag, a saved script, canonical arguments
        /// (<see cref="ArgsCanonical"/>), and <see cref="Confirm"/> equal to the start of the approval
        /// hash (source + helpers + args + target project + dry_run) a compile_only run of the same
        /// request returned and the user approved.</summary>
        public bool AllowRealProject { get; set; }
        public string? Confirm { get; set; }

        public double BudgetSeconds { get; set; } = 120;

        /// <summary>Extra C# source files compiled with the script (helper libraries).</summary>
        public List<string> HelperSources { get; set; } = new List<string>();

        /// <summary>Extra assemblies to reference by path.</summary>
        public List<string> References { get; set; } = new List<string>();

        /// <summary>Folder for this run's progress, heartbeat, cancel and large-result files.</summary>
        public string RunFolder { get; set; } = "";
    }

    public sealed class Diagnostic
    {
        public string Id { get; set; } = "";
        public string Severity { get; set; } = "error";
        public string File { get; set; } = "";
        public int Line { get; set; }
        public int Col { get; set; }
        public string Message { get; set; } = "";
        public string? Snippet { get; set; }
        public string? Hint { get; set; }
    }

    /// <summary>The single result envelope every runtime writes.</summary>
    public sealed class RunResult
    {
        public int Protocol { get; set; } = Contracts.Protocol.Version;
        public string CoreVersion { get; set; } = "";
        public string Runtime { get; set; } = "";
        public string RunId { get; set; } = "";
        public bool Ok { get; set; }

        /// <summary>Where it stopped: request, compile, guard, run, unload, done.</summary>
        public string Phase { get; set; } = "request";
        public string? Error { get; set; }
        public List<Diagnostic> Diagnostics { get; set; } = new List<Diagnostic>();
        public object? Result { get; set; }

        /// <summary>Set when the result was too large to inline; the JSON is in this file.</summary>
        public string? ResultFile { get; set; }
        public bool Truncated { get; set; }
        public List<string> Log { get; set; } = new List<string>();
        public List<string> Warnings { get; set; } = new List<string>();
        public string? Project { get; set; }
        public bool WriteAllowed { get; set; }
        public string? WriteGate { get; set; }
        public string? UndoDescription { get; set; }
        public string? SourceHash { get; set; }

        /// <summary>Hash of source + helpers + canonical args + the resolved target project + the
        /// dry_run flag; its first 16 hex digits are the confirm code for a real-project write.</summary>
        public string? ApprovalHash { get; set; }
        public bool? Unloaded { get; set; }

        /// <summary>False when the audit start line could not be written. A run that would write
        /// to a real (non-scratch) project is refused then; other runs go ahead with a warning.</summary>
        public bool? AuditOk { get; set; }
        public long DurationMs { get; set; }
        public ScriptManifest? Manifest { get; set; }
    }

    /// <summary>Parsed <c>// @key value</c> header of a script file.</summary>
    public sealed class ScriptManifest
    {
        public string? Tool { get; set; }
        public string? Desc { get; set; }
        public int Schema { get; set; } = 1;
        public string? Requires { get; set; }
        public bool Writes { get; set; }
        public bool Unsafe { get; set; }

        /// <summary>session | offline | either | gui.</summary>
        public string Needs { get; set; } = "session";
        public List<ScriptArg> Args { get; set; } = new List<ScriptArg>();
    }

    public sealed class ScriptArg
    {
        public string Name { get; set; } = "";

        /// <summary>string | int | number | bool | list | enum.</summary>
        public string Type { get; set; } = "string";
        public bool Required { get; set; }
        public string? Default { get; set; }
        public List<string>? Choices { get; set; }
        public string? Description { get; set; }
    }

    public sealed class HelloResult
    {
        public int Protocol { get; set; } = Contracts.Protocol.Version;
        public string CoreVersion { get; set; } = "";
        public string Runtime { get; set; } = "";
        public string[] Features { get; set; } = Contracts.Protocol.Features;
        public string? EplanVersion { get; set; }
        public string? License { get; set; }
        public string? RoslynVersion { get; set; }
        public int ProcessId { get; set; }
        public string[] OpenProjects { get; set; } = new string[0];
        public string? Error { get; set; }
    }
}
