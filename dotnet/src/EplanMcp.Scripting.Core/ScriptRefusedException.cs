using System;

namespace EplanMcp.Scripting.Core
{
    /// <summary>
    /// An expected refusal: a missing or wrong argument, an unknown page, a snapshot from another
    /// project. The run pipeline turns it into the result <c>{"error": message}</c> (which the
    /// server reports as <c>success: false</c>) instead of a failed run with a stack trace. Throw it
    /// only before the first write, so a refusal always means nothing was changed.
    /// </summary>
    public sealed class ScriptRefusedException : Exception
    {
        public ScriptRefusedException(string message) : base(message) { }
    }
}
