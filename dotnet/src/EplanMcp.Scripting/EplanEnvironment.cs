using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Eplan.EplApi.DataModel;
using Eplan.EplApi.HEServices;
using EplanMcp.Contracts;
using EplanMcp.Scripting.Core;

namespace EplanMcp.Scripting
{
    /// <summary>The script environment inside a running EPLAN session (add-in or bootstrap).</summary>
    public sealed class EplanEnvironment : IRunEnvironment
    {
        private readonly List<string> _searchDirs;

        public EplanEnvironment(string runtimeName, IEnumerable<string>? searchDirs = null)
        {
            RuntimeName = runtimeName;
            _searchDirs = (searchDirs ?? Array.Empty<string>()).ToList();
            var own = Compat.DirectoryOf(typeof(EplanEnvironment).Assembly);
            if (!string.IsNullOrEmpty(own)) _searchDirs.Add(own!);
        }

        public string RuntimeName { get; }

        public SnippetOptions Snippets => DefaultSnippets;

        /// <summary>Plain strings on purpose: reading them must not load any EPLAN assembly, so
        /// tooling outside EPLAN (the script compile check) can use them.</summary>
        public static readonly SnippetOptions DefaultSnippets = new SnippetOptions
        {
            ContextType = "EplanMcp.Scripting.ScriptContext",
            Usings = new[]
            {
                "System", "System.Linq", "System.Collections.Generic", "System.IO",
                "Eplan.EplApi.Base", "Eplan.EplApi.DataModel", "Eplan.EplApi.HEServices", "EplanMcp.Scripting", "EplanMcp.Eplan",
            },
        };

        public IEnumerable<string> ReferenceSearchDirs => _searchDirs;

        public IRunSession Open(RunRequest request) => new Session(request, ownLockingStep: RuntimeName != "addin");

        private sealed class Session : IRunSession
        {
            private readonly RunRequest _req;
            private readonly LockingStep? _locking;
            private Project? _project;
            private string[] _openBefore = Array.Empty<string>();
            private UndoStep? _undo;

            public Session(RunRequest req, bool ownLockingStep)
            {
                _req = req;
                // Every project access needs a LockingStep (else NoLockingStepException S063110).
                // Inside an EPLAN action (the add-in) EPLAN already holds one with automatic
                // locking; a nested LockingStep of ours switches EPLAN to manual locking and breaks
                // code that relies on the automatic kind (measured live). So only the bootstrap
                // path, which runs outside any action, takes its own.
                if (ownLockingStep) _locking = new LockingStep();
            }

            public Preflight Resolve(ScriptManifest manifest)
            {
                var pre = new Preflight();
                _openBefore = OpenProjectLinks();
                _project = ProjectResolver.Resolve(_req.Project, out var resolveError);
                if (_project == null && !string.IsNullOrEmpty(_req.Project))
                {
                    pre.Ok = false;
                    pre.Error = resolveError;
                    return pre;
                }
                if (_project == null && resolveError != null) pre.Warnings.Add(resolveError);
                pre.Project = _project?.ProjectLinkFilePath;
                return pre;
            }

            public void Authorize(ScriptManifest manifest, Preflight pre, string approvalHash) =>
                WriteGate.Decide(pre, pre.Project, _req, approvalHash);

            public object CreateContext(ScriptManifest manifest, Preflight pre, Budget budget, ProgressWriter progress, List<string> log) =>
                new ScriptContext(_project, new ScriptArgs(_req.Args), budget, progress, log, _req.DryRun, pre.WriteAllowed,
                    _req.RunId, _req.RunFolder);

            public string? BeginWrite(string description)
            {
                try
                {
                    _undo = new UndoManager().CreateUndoStep();
                    _undo.SetUndoDescription(description);
                    return description;
                }
                catch
                {
                    return null;   // undo is best effort; the run still goes ahead
                }
            }

            public string? Verify()
            {
                var after = OpenProjectLinks();
                if (!after.OrderBy(x => x).SequenceEqual(_openBefore.OrderBy(x => x), StringComparer.OrdinalIgnoreCase))
                    return "The script changed which projects are open (before: " + string.Join(", ", _openBefore.Select(Path.GetFileName)) +
                           "; after: " + string.Join(", ", after.Select(Path.GetFileName)) + "). Scripts must not open or close projects.";
                return null;
            }

            public void Dispose()
            {
                try { _undo?.CloseUndo(); } catch { }
                try { _undo?.Dispose(); } catch { }
                _locking?.Dispose();
            }

            private static string[] OpenProjectLinks()
            {
                try
                {
                    // A project without a link path still counts: as "<unnamed>" it is never a
                    // scratch clone, so it closes the write gate instead of slipping past it.
                    return new ProjectManager().OpenProjects
                        .Select(p => string.IsNullOrEmpty(p.ProjectLinkFilePath) ? "<unnamed:" + p.ProjectName + ">" : p.ProjectLinkFilePath)
                        .ToArray();
                }
                catch
                {
                    return Array.Empty<string>();
                }
            }
        }
    }

    /// <summary>
    /// Which project a run acts on: the <c>project</c> argument among the open projects, else the
    /// focused one, else the only open one. Never opens a project and never shows a dialog. The
    /// argument is matched, in this order, as the link-file path, the full project path without
    /// .elk (ProjectFullName), the project name, then the link file's name; an exact (case-sensitive)
    /// match beats a case-insensitive one, and two projects matching equally well is an error.
    /// </summary>
    public static class ProjectResolver
    {
        public static Project? Resolve(string? wanted, out string? error)
        {
            error = null;
            Project[] open;
            try { open = new ProjectManager().OpenProjects; }
            catch (Exception e) { error = "Could not list open projects: " + e.Message; return null; }

            if (!string.IsNullOrWhiteSpace(wanted))
            {
                var keys = open.Select(p => (project: p, names: new[]
                {
                    Safe(() => p.ProjectLinkFilePath), Safe(() => p.ProjectFullName), Safe(() => p.ProjectName),
                    Path.GetFileNameWithoutExtension(Safe(() => p.ProjectLinkFilePath)),
                })).ToList();
                int index = Pick(keys.Select(k => k.names).ToList(), wanted!.Trim(), out var ambiguous);
                if (ambiguous != null)
                {
                    error = $"Project '{wanted}' matches several open projects ({ambiguous}); pass the full .elk path.";
                    return null;
                }
                if (index < 0)
                    error = $"Project '{wanted}' is not open. Open projects: " +
                            (open.Length == 0 ? "none" : string.Join(", ", open.Select(p => p.ProjectLinkFilePath)));
                return index < 0 ? null : keys[index].project;
            }

            try
            {
                var sel = new SelectionSet { LockSelectionByDefault = false };   // must be cleared before reading
                var focused = sel.GetCurrentProject(false);                      // false: never a dialog
                if (focused != null) return focused;
            }
            catch { }

            if (open.Length == 1) return open[0];
            if (open.Length > 1)
                error = "Several projects are open and none is focused; pass 'project'. Open: " + string.Join(", ", open.Select(p => p.ProjectLinkFilePath));
            return null;
        }

        /// <summary>The index of the one candidate whose names match <paramref name="wanted"/> best:
        /// by name kind (link path, full name, name, file name; paths are compared as full paths),
        /// exact case before any case. -1 when none matches; <paramref name="ambiguous"/> lists the
        /// tied candidates when the best match is not unique.</summary>
        public static int Pick(IReadOnlyList<string[]> candidates, string wanted, out string? ambiguous)
        {
            ambiguous = null;
            int kinds = candidates.Count == 0 ? 0 : candidates.Max(c => c.Length);
            for (int kind = 0; kind < kinds; kind++)
            {
                bool isPath = kind < 2;
                foreach (var cmp in new[] { StringComparison.Ordinal, StringComparison.OrdinalIgnoreCase })
                {
                    var hits = Enumerable.Range(0, candidates.Count)
                        .Where(i => kind < candidates[i].Length && Same(candidates[i][kind], wanted, isPath, cmp)).ToList();
                    if (hits.Count == 1) return hits[0];
                    if (hits.Count > 1)
                    {
                        ambiguous = string.Join(", ", hits.Select(i => candidates[i][0]));
                        return -1;
                    }
                }
            }
            return -1;
        }

        private static bool Same(string? have, string wanted, bool isPath, StringComparison cmp)
        {
            if (string.IsNullOrEmpty(have)) return false;
            if (string.Equals(have, wanted, cmp)) return true;
            if (!isPath) return false;
            try { return string.Equals(Path.GetFullPath(have), Path.GetFullPath(wanted), cmp); }
            catch { return false; }
        }

        private static string Safe(Func<string?> read)
        {
            try { return read() ?? ""; } catch { return ""; }
        }
    }
}
