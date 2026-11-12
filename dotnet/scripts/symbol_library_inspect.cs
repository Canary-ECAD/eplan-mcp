// @tool     symbol_library_inspect
// @desc     Reads a symbol library (opened read-only): its symbols, one variant's connection points and counts, or a symbol's property arrangements.
// @schema   1
// @arg      library  string  required   Registered library name, or a path to its .slk / .sdb
// @arg      mode     enum(symbols,variant,arrangements) default=symbols
// @arg      symbol   string  optional   Symbol name (modes variant and arrangements)
// @arg      variant  int     optional   Variant index (mode variant; default 0)
// @writes   false
// @needs    session
using EplanMcp.Eplan;
using EplanMcp.Scripting;

public static class Script
{
    public static object Run(ScriptContext ctx) =>
        SymbolLibraries.Inspect(ctx.Args.Require("library"), ctx.Args.String("mode", "symbols")!,
            ctx.Args.String("symbol"), (int)ctx.Args.Int("variant", 0));
}
