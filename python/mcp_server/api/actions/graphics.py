"""
Graphic text formatting on the live object model.

One tool so far:

    live_scale_text     multiply the height of every text in scope by a factor

It rides the same reflection scaffold as live.py/schematic.py, so it needs no
add-in and no EPLAN restart: the scope, the factor and the dry-run switch are
all runtime arguments.

WHY A TOOL AND NOT A DIALOG: EPLAN's own "Fit text" writes a size it computes
itself and the properties dialog edits one selection at a time with one value,
so neither can express "everything on this page, a quarter of what it is now".
A proportional rescale has to walk the texts and multiply each one's own height.

THE THREE FACTS THAT SHAPE THE IMPLEMENTATION, all measured rather than assumed:

  - `TextBase.Height` is writable and the write persists across a project
    reopen. `Text` (free graphic text) and `PropertyPlacement` (the texts that
    belong to a symbol reference) both derive from
    `Eplan.EplApi.DataModel.Graphics.TextBase`, so one type test covers both.

  - `-16002` is EPLAN's "take this from the layer" sentinel, not a size.
    Multiplying it would write a large negative height, so a sentinel-valued
    text is SKIPPED and counted. Resolving the layer's height and writing an
    explicit value is a deliberate act, not something a scale should do behind
    the caller's back.

  - A `SymbolReference` whose `UseLocalPropertyPlacements` is false renders the
    VARIANT's placements, so writing one can move every other instance of that
    variant in the project. Those are skipped unless `allow_shared=True`.

SCOPE. `scope="selection"` reads what is selected in the GED and expands
`Group.SubPlacements` recursively (a Group is one selected object but holds many
texts). The GED selection IS visible to a script under QuietMode - measured live
on 2027.0.3, where four selected groups resolved to 306 texts and the same page
held 487. `scope="page"` walks a named page instead and is the choice for
"everything on this page"; it also survives anything that clears the selection,
such as an EPLAN restart.

Writes go through the same LockingStep as every other script here. They land on
EPLAN's undo stack as individual property writes, NOT as one step: there is no
UndoManager in this scaffold, so Ctrl+Z is not a single-shot reversal. The
honest reversal is a second call with the reciprocal factor, which is exact
because the scale is multiplicative.
"""

import uuid

from ._base import cs_escape
from .live import _script
from .scripted import _execute_script
from .schematic import _HELPERS_SCHEMATIC, _fill, _guard_prelude, _err
from .schematic_model import SchematicValueError, cs_bool, cs_double, cs_text

__all__ = ["live_scale_text", "live_set_layer"]


# EPLAN's documented "from layer" sentinel, shared by Height/Rotation/RowSpacing.
FROM_LAYER_SENTINEL = -16002.0


# ---------------------------------------------------------------------------
# Module-specific C# helpers, spliced in ahead of [Start] by live._script.
# ---------------------------------------------------------------------------

_HELPERS_TEXT = r'''
    // TextBase lives in the Graphics namespace; both texts we care about
    // (Text, PropertyPlacement) derive from it, so one IsAssignableFrom test
    // classifies a placement. Resolved through FindType so it works on both the
    // 2025 and 2027 assembly naming schemes.
    static Type _textBase;
    static bool IsText(object o)
    {
        if (o == null) return false;
        if (_textBase == null)
            _textBase = FindType("Eplan.EplApi.DataModel.Graphics.TextBase");
        return _textBase.IsAssignableFrom(o.GetType());
    }

    // Skips are SUMMARISED, not listed. A symbol-library page can have 216
    // texts all skipped for the same reason; 216 identical rows tell the caller
    // nothing the count does not, and they crowd out the samples that matter.
    static Dictionary<string, int> _skipCounts = new Dictionary<string, int>();
    static List<string> _skipOrder = new List<string>();
    static List<object> _skipExamples = new List<object>();

    static void Skip(List<Dictionary<string, object>> skipped, string reason,
                     string what, object height)
    {
        if (!_skipCounts.ContainsKey(reason)) { _skipCounts[reason] = 0; _skipOrder.Add(reason); }
        _skipCounts[reason] = _skipCounts[reason] + 1;

        // One worked example per reason, so a surprising skip can be chased.
        if (_skipCounts[reason] == 1)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["reason"] = reason;
            d["object"] = what;
            d["height"] = height;
            _skipExamples.Add(d);
        }
        skipped.Add(null);   // the list is only ever counted
    }

    static List<object> SkipSummary()
    {
        List<object> rows = new List<object>();
        foreach (string reason in _skipOrder)
        {
            Dictionary<string, object> d = new Dictionary<string, object>();
            d["reason"] = reason;
            d["count"] = _skipCounts[reason];
            rows.Add(d);
        }
        return rows;
    }

    // Collect every TextBase reachable from one placement.
    //
    // Three shapes, and missing any one of them silently under-reports:
    //   - the placement IS a text                      -> take it
    //   - it is a Group                                -> recurse SubPlacements
    //     (a Group is ONE selected object but can hold hundreds of texts, and
    //      SelectionSet.SelectionRecursive does NOT expand it - measured)
    //   - it is a SymbolReference                      -> its PropertyPlacements
    //
    // Dedup is by handle: a text can arrive both directly and through its group.
    static void CollectTexts(object pl, List<object> outTexts, Dictionary<string, bool> seen,
                             bool includePps, bool allowShared,
                             List<Dictionary<string, object>> skipped, int depth)
    {
        if (pl == null || depth > 12) return;

        if (IsText(pl))
        {
            string h = Handle(pl);
            if (h == null) h = "obj" + outTexts.Count;
            if (!seen.ContainsKey(h)) { seen[h] = true; outTexts.Add(pl); }
            return;
        }

        PropertyInfo sub = GetReadable(pl.GetType(), "SubPlacements");
        if (sub != null)
        {
            object members = null;
            try { members = sub.GetValue(pl, null); } catch { members = null; }
            if (members is IEnumerable)
            {
                foreach (object m in (IEnumerable)members)
                    CollectTexts(m, outTexts, seen, includePps, allowShared, skipped, depth + 1);
            }
            return;
        }

        if (!includePps) return;

        PropertyInfo pps = GetReadable(pl.GetType(), "PropertyPlacements");
        if (pps == null) return;

        // The shared-variant gate. False means this instance renders the
        // VARIANT's placements and a write can move every other instance.
        bool local = false;
        object localVal = TryRead(pl, "UseLocalPropertyPlacements", null);
        if (localVal != null) { try { local = Convert.ToBoolean(localVal); } catch { local = false; } }

        object arr = null;
        try { arr = pps.GetValue(pl, null); } catch { arr = null; }
        if (!(arr is IEnumerable)) return;

        if (!local && !allowShared)
        {
            int n = 0;
            foreach (object x in (IEnumerable)arr) n++;
            if (n > 0)
                Skip(skipped, "UseLocalPropertyPlacements is false - a write here can move " +
                     "every instance of this symbol variant; pass allow_shared=true to include it",
                     PropText(pl, "Name") + " (" + n + " property placements)", null);
            return;
        }

        foreach (object p in (IEnumerable)arr)
        {
            if (!IsText(p)) continue;
            string h = Handle(p);
            if (h == null) h = "pp" + outTexts.Count;
            if (!seen.ContainsKey(h)) { seen[h] = true; outTexts.Add(p); }
        }
    }

    // A text's display string is the only human-readable identifier it has, and
    // reading it throws on an empty property - hence SafeText, not ToString.
    static string TextLabel(object t)
    {
        MethodInfo mi = MethodByShape(t.GetType(), "GetDisplayString", new string[] { }, false);
        if (mi == null) return t.GetType().Name;
        try { return SafeText(mi.Invoke(t, null)); }
        catch { return t.GetType().Name; }
    }
'''


_BODY = r'''            Type ssType2 = ss.GetType();
            bool dryRun = DRYRUN;
            double factor = FACTOR;
            double minHeight = MINHEIGHT;
            bool includePps = INCLUDEPPS;
            bool allowShared = ALLOWSHARED;

            List<object> texts = new List<object>();
            Dictionary<string, bool> seen = new Dictionary<string, bool>();
            List<Dictionary<string, object>> skipped = new List<Dictionary<string, object>>();

            if (SCOPEISPAGE)
            {
                object page = FindPage(project, "PAGENAME");
                results["scope"] = "page";
                results["page"] = PropText(page, "Name");
                foreach (object pl in PagePlacements(page))
                    CollectTexts(pl, texts, seen, includePps, allowShared, skipped, 0);
            }
            else
            {
                results["scope"] = "selection";
                // LockSelectionByDefault must be cleared BEFORE the selection is
                // read, or reading it locks every selected object.
                PropertyInfo lockPi = GetWritable(ssType2, "LockSelectionByDefault");
                if (lockPi != null) { try { lockPi.SetValue(ss, false, null); } catch { } }

                PropertyInfo selPi = RequireReadable(ssType2, "Selection");
                object sel = selPi.GetValue(ss, null);
                int selCount = 0;
                if (sel is IEnumerable)
                {
                    foreach (object o in (IEnumerable)sel)
                    {
                        if (o == null) continue;
                        selCount++;
                        CollectTexts(o, texts, seen, includePps, allowShared, skipped, 0);
                    }
                }
                results["selectedObjects"] = selCount;
                if (selCount == 0)
                    results["note"] = "nothing is selected in EPLAN - select objects in the " +
                        "graphical editor, or use scope=\"page\" for everything on a page.";
            }

            // ---- plan -------------------------------------------------------
            List<object> targets = new List<object>();
            List<double> newHeights = new List<double>();
            foreach (object t in texts)
            {
                PropertyInfo hp = GetReadable(t.GetType(), "Height");
                if (hp == null) { Skip(skipped, "no readable Height", TextLabel(t), null); continue; }

                double before;
                try { before = Convert.ToDouble(hp.GetValue(t, null)); }
                catch (Exception ex) { Skip(skipped, "Height unreadable: " + Flatten(ex), TextLabel(t), null); continue; }

                // -16002 is "take the height from the layer", a flag rather than
                // a size; scaling it would write a large negative height.
                if (Math.Abs(before - (-16002.0)) < 0.0001)
                { Skip(skipped, "height is the from-layer sentinel (-16002)", TextLabel(t), before); continue; }

                double after = before * factor;
                if (after < minHeight)
                { Skip(skipped, "result below min_height", TextLabel(t), before); continue; }

                targets.Add(t);
                newHeights.Add(after);
            }

            List<object> samples = new List<object>();
            for (int i = 0; i < targets.Count && samples.Count < SAMPLES; i++)
            {
                Dictionary<string, object> s = new Dictionary<string, object>();
                s["text"] = TextLabel(targets[i]);
                s["clrType"] = targets[i].GetType().Name;
                s["heightBefore"] = Math.Round(Convert.ToDouble(
                    GetReadable(targets[i].GetType(), "Height").GetValue(targets[i], null)), 4);
                s["heightAfter"] = Math.Round(newHeights[i], 4);
                samples.Add(s);
            }

            results["textsFound"] = texts.Count;
            results["planned"] = targets.Count;
            results["skipped"] = skipped.Count;
            results["skippedByReason"] = SkipSummary();
            results["skippedExamples"] = _skipExamples;
            results["samples"] = samples;
            results["factor"] = factor;
            results["dryRun"] = dryRun;

            if (dryRun)
            {
                results["written"] = 0;
                results["success"] = true;
                results["hint"] = "dry run - nothing written. Re-run with dry_run=false to apply.";
            }
            else
            {
                int written = 0;
                int stuck = 0;
                List<object> failed = new List<object>();
                List<object> drifted = new List<object>();
                for (int i = 0; i < targets.Count; i++)
                {
                    object t = targets[i];
                    PropertyInfo hw = GetWritable(t.GetType(), "Height");
                    if (hw == null)
                    { failed.Add(TextLabel(t) + ": Height is not writable on " + t.GetType().Name); continue; }
                    try { hw.SetValue(t, newHeights[i], null); written++; }
                    catch (TargetInvocationException tie)
                    { failed.Add(TextLabel(t) + ": " + Flatten(tie.InnerException)); continue; }
                    catch (Exception ex)
                    { failed.Add(TextLabel(t) + ": " + Flatten(ex)); continue; }

                    // Read back: a setter that returns normally but stores
                    // nothing throws nothing either.
                    try
                    {
                        double back = Convert.ToDouble(GetReadable(t.GetType(), "Height").GetValue(t, null));
                        if (Math.Abs(back - newHeights[i]) < 0.0001) stuck++;
                        else if (drifted.Count < 10)
                        {
                            Dictionary<string, object> d = new Dictionary<string, object>();
                            d["text"] = TextLabel(t);
                            d["expected"] = Math.Round(newHeights[i], 4);
                            d["actual"] = Math.Round(back, 4);
                            drifted.Add(d);
                        }
                    }
                    catch { }
                }
                results["written"] = written;
                results["sticks"] = stuck;
                results["drifted"] = drifted;
                results["failed"] = failed;
                results["success"] = failed.Count == 0;
                results["hint"] = "read-back is in-memory; the project must be saved for the " +
                    "change to persist. To reverse, re-run with the reciprocal factor.";
            }
'''


def live_scale_text(factor: float, scope: str = "selection", page: str = None,
                    dry_run: bool = True, min_height: float = 0.1,
                    include_property_placements: bool = True,
                    allow_shared: bool = False, allow_real_project: bool = False,
                    samples: int = 10, timeout_seconds: float = 180.0) -> dict:
    """
    Multiply the height of every text in scope by `factor`, in the project
    currently open in EPLAN.

    Proportional, not absolute: each text keeps its size relative to the others,
    which is what "make this page's text a quarter of the size" means and what
    neither EPLAN's Fit nor the properties dialog can express. Covers free
    graphic texts and the texts belonging to symbol references.

    DRY RUN IS THE DEFAULT. The first call reports what it would change and
    changes nothing; pass dry_run=False to apply.

    Args:
        factor: Multiplier for every text height. 0.25 quarters the text, 4
            restores it. Must be > 0.
        scope: "selection" (default) scales what is selected in EPLAN's graphical
            editor, expanding groups; "page" scales every text on `page`. Use
            "page" when the intent is "everything here" - it does not depend on
            the selection surviving, and a script may not see the GED selection
            at all.
        page: Page name, required when scope="page". Exact match; use
            live_query_pages to get the name.
        dry_run: True (default) plans and reports without writing.
        min_height: Refuse to write a height below this many millimetres
            (default 0.1). Guards against a factor that would make text
            invisible or negative.
        include_property_placements: Include the texts owned by symbol
            references (device tags, function texts), not just free texts.
            Default True.
        allow_shared: Include property placements of symbol references whose
            UseLocalPropertyPlacements is False. Those are shared with the
            symbol VARIANT, so a write can resize every other instance in the
            project - hence off by default.
        allow_real_project: Must be True to write to a project outside the
            scratch root. Ignored on a dry run, which writes nothing.
        samples: How many before/after rows to return (default 10).
        timeout_seconds: Max seconds to wait for the script (default 180; a
            page with several hundred texts takes a while).

    Returns:
        dict with "textsFound", "planned", "skipped" (plus
        "skippedByReason" counts and one example per reason),
        "samples", and on a real run "written", "sticks", "drifted", "failed".

    Notes:
        - A text whose height is the -16002 "from layer" sentinel is skipped and
          counted: that value is a flag, not a size, and scaling it would write
          a large negative height. Change the layer instead.
        - Writes land on the undo stack as individual property writes, not as
          one step. The reliable reversal is this tool with 1/factor.
        - The change is not persisted until the project is saved.
    """
    try:
        factor_cs = cs_double(factor, "factor")
        min_cs = cs_double(min_height, "min_height")
        if float(factor) <= 0:
            raise SchematicValueError(
                "factor must be > 0, got %r. A zero or negative factor would "
                "write a height EPLAN cannot render." % (factor,))
        if float(min_height) <= 0:
            raise SchematicValueError("min_height must be > 0, got %r." % (min_height,))
        samples_n = int(samples)
        if samples_n < 0:
            raise SchematicValueError("samples must be >= 0.")
        scope = (scope or "selection").strip().lower()
        if scope not in ("selection", "page"):
            raise SchematicValueError(
                'scope must be "selection" or "page", got %r.' % (scope,))
        if scope == "page":
            page_cs = cs_escape(cs_text(page, "page"))
        else:
            if page:
                raise SchematicValueError(
                    'page is only meaningful with scope="page"; passing it with '
                    'scope="selection" would silently be ignored.')
            page_cs = ""
    except SchematicValueError as exc:
        return _err(exc)

    # The scratch guard protects WRITES; a dry run touches nothing, so it would
    # only stop the caller from looking at a real project.
    prelude = "" if dry_run else _guard_prelude(allow_real_project)

    body = prelude + _fill(
        _BODY,
        DRYRUN=cs_bool(dry_run),
        FACTOR=factor_cs,
        MINHEIGHT=min_cs,
        INCLUDEPPS=cs_bool(include_property_placements),
        ALLOWSHARED=cs_bool(allow_shared),
        SCOPEISPAGE=cs_bool(scope == "page"),
        PAGENAME=page_cs,
        SAMPLES=str(samples_n),
    )

    return _execute_script(
        _script("LiveScaleText_" + uuid.uuid4().hex[:6], body,
                extra_helpers=_HELPERS_SCHEMATIC + _HELPERS_TEXT),
        timeout=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Layer / pen normalisation
# ---------------------------------------------------------------------------

_HELPERS_LAYER = r'''
    // Collect every GRAPHICAL placement reachable from one object: the same walk
    // CollectTexts does, minus the text filter. Groups are expanded (a Group is
    // one selected object holding many graphics and SelectionRecursive does not
    // expand it), symbol references contribute their property placements.
    static void CollectGraphics(object pl, List<object> outObjs, Dictionary<string, bool> seen,
                                bool includePps, bool allowShared,
                                List<Dictionary<string, object>> skipped, int depth)
    {
        if (pl == null || depth > 12) return;

        PropertyInfo sub = GetReadable(pl.GetType(), "SubPlacements");
        if (sub != null)
        {
            object members = null;
            try { members = sub.GetValue(pl, null); } catch { members = null; }
            if (members is IEnumerable)
            {
                foreach (object m in (IEnumerable)members)
                    CollectGraphics(m, outObjs, seen, includePps, allowShared, skipped, depth + 1);
            }
            return;   // the Group itself carries no pen of its own
        }

        PropertyInfo pps = GetReadable(pl.GetType(), "PropertyPlacements");
        if (pps != null)
        {
            // A symbol reference: the reference itself is drawn from its symbol,
            // so only its property placements (texts) are ours to touch.
            if (!includePps) return;

            bool local = false;
            object localVal = TryRead(pl, "UseLocalPropertyPlacements", null);
            if (localVal != null) { try { local = Convert.ToBoolean(localVal); } catch { local = false; } }

            object arr = null;
            try { arr = pps.GetValue(pl, null); } catch { arr = null; }
            if (!(arr is IEnumerable)) return;

            if (!local && !allowShared)
            {
                int n = 0;
                foreach (object x in (IEnumerable)arr) n++;
                if (n > 0)
                    Skip(skipped, "UseLocalPropertyPlacements is false - a write here can change " +
                         "every instance of this symbol variant; pass allow_shared=true to include it",
                         PropText(pl, "Name") + " (" + n + " property placements)", null);
                return;
            }
            foreach (object p in (IEnumerable)arr)
            {
                string ph = Handle(p);
                if (ph == null) ph = "pp" + outObjs.Count;
                if (!seen.ContainsKey(ph)) { seen[ph] = true; outObjs.Add(p); }
            }
            return;
        }

        string h = Handle(pl);
        if (h == null) h = "obj" + outObjs.Count;
        if (!seen.ContainsKey(h)) { seen[h] = true; outObjs.Add(pl); }
    }

    // Find the target layer in the project's layer table, creating it if asked.
    // Lookup is by name and CASE-SENSITIVE, because EPLAN's LayerTable is keyed that way:
    // 'EPLAN100' and 'eplan100' are two different layers there, so matching loosely would
    // silently write to the wrong one. A duplicate case-variant layer is the lesser harm.
    static object FindLayer(object project, string wanted, bool create, out bool created)
    {
        created = false;
        PropertyInfo ltPi = RequireReadable(project.GetType(), "LayerTable");
        object lt = ltPi.GetValue(project, null);
        if (lt == null) throw new Exception("Project.LayerTable returned null.");

        PropertyInfo layersPi = RequireReadable(lt.GetType(), "Layers");
        object layers = layersPi.GetValue(lt, null);
        List<string> names = new List<string>();
        if (layers is IEnumerable)
        {
            foreach (object l in (IEnumerable)layers)
            {
                if (l == null) continue;
                string n = PropText(l, "Name");
                if (n != null && string.Equals(n, wanted, StringComparison.Ordinal)) return l;
                if (names.Count < 40 && n != null) names.Add(n);
            }
        }
        if (!create)
            throw new Exception("No layer named '" + wanted + "' in this project, and " +
                "create_layer is false. Layers present (up to 40): " +
                string.Join(" | ", names.ToArray()));

        // AddLayer(string, MultiLangString) - the description argument is required.
        Type mlsType = FindType("Eplan.EplApi.Base.MultiLangString");
        object mls = Activator.CreateInstance(mlsType);
        MethodInfo add = RequireMethod(lt.GetType(), "AddLayer",
            new string[] { "String", mlsType.Name }, false);
        object made = Call(add, lt, new object[] { wanted, mls });
        if (made == null)
            throw new Exception("LayerTable.AddLayer('" + wanted + "') returned null.");
        created = true;
        return made;
    }

    // Pen is a VALUE the object hands out, not a live reference: the documented
    // idiom is read it, change it, assign it BACK. Mutating the returned Pen and
    // not reassigning changes nothing, silently.
    static bool PenToLayer(object pl, bool doColor, bool doWidth, bool doStyle, out string why)
    {
        why = null;
        PropertyInfo penPi = GetPropWalk(pl.GetType(), "Pen", true, true);
        if (penPi == null) { why = "no read/write Pen"; return false; }
        object pen = null;
        try { pen = penPi.GetValue(pl, null); } catch (Exception ex) { why = Flatten(ex); return false; }
        if (pen == null) { why = "Pen was null"; return false; }

        bool touched = false;
        if (doColor)
        {
            PropertyInfo ci = GetWritable(pen.GetType(), "ColorId");
            // ColorId is a SHORT; handing SetValue an int throws ArgumentException.
            if (ci != null) { ci.SetValue(pen, Convert.ToInt16(-16002), null); touched = true; }
        }
        if (doWidth)
        {
            PropertyInfo w = GetWritable(pen.GetType(), "Width");
            if (w != null) { w.SetValue(pen, -16002.0, null); touched = true; }
        }
        if (doStyle)
        {
            PropertyInfo st = GetWritable(pen.GetType(), "StyleId");
            if (st != null) { st.SetValue(pen, Convert.ToInt16(-16002), null); touched = true; }
        }
        if (!touched) { why = "Pen exposed none of the requested members"; return false; }

        try { penPi.SetValue(pl, pen, null); }
        catch (TargetInvocationException tie) { why = Flatten(tie.InnerException); return false; }
        catch (Exception ex) { why = Flatten(ex); return false; }
        return true;
    }

    // A TEXT's colour does not live on a Pen on every type - TextBase carries its
    // own colour property, spelled differently across the hierarchy. Try both.
    static bool TextColorToLayer(object pl, out string why)
    {
        why = null;
        string[] names = new string[] { "ColorId", "TextColorId" };
        foreach (string n in names)
        {
            PropertyInfo pi = GetWritable(pl.GetType(), n);
            if (pi == null) continue;
            try
            {
                if (pi.PropertyType == typeof(short))
                    pi.SetValue(pl, Convert.ToInt16(-16002), null);
                else
                    pi.SetValue(pl, Convert.ToInt32(-16002), null);
                return true;
            }
            catch (TargetInvocationException tie) { why = Flatten(tie.InnerException); }
            catch (Exception ex) { why = Flatten(ex); }
        }
        if (why == null) why = "no writable ColorId/TextColorId";
        return false;
    }

    static string LayerName(object pl)
    {
        object lay = TryRead(pl, "Layer", null);
        return lay == null ? null : PropText(lay, "Name");
    }
'''


_BODY_LAYER = r'''            Type ssType2 = ss.GetType();
            bool dryRun = DRYRUN;
            bool includePps = INCLUDEPPS;
            bool allowShared = ALLOWSHARED;
            bool doColor = DOCOLOR;
            bool doWidth = DOWIDTH;
            bool doStyle = DOSTYLE;

            List<object> objs = new List<object>();
            Dictionary<string, bool> seen = new Dictionary<string, bool>();
            List<Dictionary<string, object>> skipped = new List<Dictionary<string, object>>();

            if (SCOPEISPAGE)
            {
                object page = FindPage(project, "PAGENAME");
                results["scope"] = "page";
                results["page"] = PropText(page, "Name");
                foreach (object pl in PagePlacements(page))
                    CollectGraphics(pl, objs, seen, includePps, allowShared, skipped, 0);
            }
            else
            {
                results["scope"] = "selection";
                PropertyInfo lockPi = GetWritable(ssType2, "LockSelectionByDefault");
                if (lockPi != null) { try { lockPi.SetValue(ss, false, null); } catch { } }

                PropertyInfo selPi = RequireReadable(ssType2, "Selection");
                object sel = selPi.GetValue(ss, null);
                int selCount = 0;
                if (sel is IEnumerable)
                {
                    foreach (object o in (IEnumerable)sel)
                    {
                        if (o == null) continue;
                        selCount++;
                        CollectGraphics(o, objs, seen, includePps, allowShared, skipped, 0);
                    }
                }
                results["selectedObjects"] = selCount;
                if (selCount == 0)
                    results["note"] = "nothing is selected in EPLAN - select objects in the " +
                        "graphical editor, or use scope=PAGEWORD for everything on a page.";
            }

            results["objectsFound"] = objs.Count;

            // What layers are these on today? The before-picture is the only way a
            // caller can tell "converted 300 objects" from "they were already there".
            Dictionary<string, int> byLayer = new Dictionary<string, int>();
            Dictionary<string, int> byType = new Dictionary<string, int>();
            foreach (object o in objs)
            {
                string ln = LayerName(o);
                if (ln == null) ln = "(no layer)";
                if (!byLayer.ContainsKey(ln)) byLayer[ln] = 0;
                byLayer[ln] = byLayer[ln] + 1;
                string tn = o.GetType().Name;
                if (!byType.ContainsKey(tn)) byType[tn] = 0;
                byType[tn] = byType[tn] + 1;
            }
            results["layersBefore"] = byLayer;
            results["typesFound"] = byType;
            results["targetLayer"] = "LAYERNAME";
            results["skipped"] = skipped.Count;
            results["skippedByReason"] = SkipSummary();
            results["skippedExamples"] = _skipExamples;

            if (dryRun)
            {
                // Resolve the layer READ-ONLY on a dry run: report whether it would
                // have to be created rather than creating it.
                bool wouldCreate = false;
                try { FindLayer(project, "LAYERNAME", false, out wouldCreate); results["layerExists"] = true; }
                catch (Exception) { results["layerExists"] = false; }
                results["planned"] = objs.Count;
                results["written"] = 0;
                results["success"] = true;
                results["hint"] = "dry run - nothing written. Re-run with dry_run=false to apply.";
            }
            else
            {
                bool created = false;
                object layer = FindLayer(project, "LAYERNAME", CREATELAYER, out created);
                results["layerCreated"] = created;

                int layerSet = 0, penSet = 0, textColorSet = 0;
                List<object> failed = new List<object>();
                foreach (object o in objs)
                {
                    PropertyInfo lp = GetPropWalk(o.GetType(), "Layer", false, true);
                    if (lp == null)
                    { if (failed.Count < 40) failed.Add(o.GetType().Name + ": no writable Layer"); }
                    else
                    {
                        try { lp.SetValue(o, layer, null); layerSet++; }
                        catch (TargetInvocationException tie)
                        { if (failed.Count < 40) failed.Add(o.GetType().Name + " Layer: " + Flatten(tie.InnerException)); }
                        catch (Exception ex)
                        { if (failed.Count < 40) failed.Add(o.GetType().Name + " Layer: " + Flatten(ex)); }
                    }

                    if (doColor || doWidth || doStyle)
                    {
                        string why;
                        if (PenToLayer(o, doColor, doWidth, doStyle, out why)) penSet++;
                        else if (doColor && TextColorToLayer(o, out why)) textColorSet++;
                        else if (why != null && failed.Count < 40)
                            failed.Add(o.GetType().Name + " pen: " + why);
                    }
                }

                // Read back: how many are on the target layer now?
                int onTarget = 0;
                foreach (object o in objs)
                {
                    string ln = LayerName(o);
                    if (ln != null && string.Equals(ln, "LAYERNAME", StringComparison.Ordinal))
                        onTarget++;
                }

                results["planned"] = objs.Count;
                results["written"] = layerSet;
                results["penSet"] = penSet;
                results["textColorSet"] = textColorSet;
                results["onTargetLayerAfter"] = onTarget;
                results["failed"] = failed;
                results["success"] = failed.Count == 0;
                results["hint"] = "read-back is in-memory; save the project to persist. " +
                    "layersBefore records where these objects came from, if you need to put them back.";
            }
'''


def live_set_layer(layer: str = "EPLAN100", scope: str = "selection", page: str = None,
                   color_from_layer: bool = True, line_width_from_layer: bool = True,
                   line_style_from_layer: bool = False, create_layer: bool = True,
                   dry_run: bool = True, include_property_placements: bool = True,
                   allow_shared: bool = False, allow_real_project: bool = False,
                   timeout_seconds: float = 180.0) -> dict:
    """
    Move every graphic object in scope onto one layer and hand its pen settings
    back to that layer, in the project currently open in EPLAN.

    This is the "normalise this artwork" operation: afterwards the objects take
    their colour and line width from the layer instead of carrying their own
    overrides, so changing the layer changes the drawing.

    DRY RUN IS THE DEFAULT. The first call reports what it would change -
    including which layers the objects are on today - and changes nothing.

    Args:
        layer: Target layer name (default "EPLAN100").
        scope: "selection" (default, expands groups) or "page" with `page`.
        page: Page name, required when scope="page".
        color_from_layer: Set colour to the -16002 "from layer" sentinel
            (default True). Applies to `Pen.ColorId`, and to a text's own colour
            property where it has no pen.
        line_width_from_layer: Set `Pen.Width` to -16002 (default True).
        line_style_from_layer: Also hand `Pen.StyleId` (dashes/dots) back to the
            layer. Default False - line style usually carries meaning the layer
            does not.
        create_layer: Create the layer if the project does not have it
            (default True). A dry run creates nothing and reports "layerExists".
        dry_run: True (default) plans and reports without writing.
        include_property_placements: Include symbol references' texts
            (default True).
        allow_shared: Include property placements shared with a symbol VARIANT -
            a write there affects every instance in the project. Default False.
        allow_real_project: Must be True to write to a project outside the
            scratch root. Ignored on a dry run.
        timeout_seconds: Max seconds to wait for the script (default 180).

    Returns:
        dict with "objectsFound", "layersBefore" (counts per current layer),
        "typesFound", "layerExists"/"layerCreated", and on a real run "written"
        (layer assignments), "penSet", "textColorSet", "onTargetLayerAfter",
        "failed".

    Notes:
        - `Pen` is a value the object hands out: it is read, modified and
          assigned BACK. Mutating it in place changes nothing, silently.
        - "layersBefore" is the record of where the objects came from; keep it if
          the move might need reversing, because this tool does not remember.
        - The change is not persisted until the project is saved.
    """
    try:
        layer_cs = cs_escape(cs_text(layer, "layer"))
        scope = (scope or "selection").strip().lower()
        if scope not in ("selection", "page"):
            raise SchematicValueError(
                'scope must be "selection" or "page", got %r.' % (scope,))
        if scope == "page":
            page_cs = cs_escape(cs_text(page, "page"))
        else:
            if page:
                raise SchematicValueError(
                    'page is only meaningful with scope="page".')
            page_cs = ""
    except SchematicValueError as exc:
        return _err(exc)

    prelude = "" if dry_run else _guard_prelude(allow_real_project)

    body = prelude + _fill(
        _BODY_LAYER,
        DRYRUN=cs_bool(dry_run),
        INCLUDEPPS=cs_bool(include_property_placements),
        ALLOWSHARED=cs_bool(allow_shared),
        DOCOLOR=cs_bool(color_from_layer),
        DOWIDTH=cs_bool(line_width_from_layer),
        DOSTYLE=cs_bool(line_style_from_layer),
        SCOPEISPAGE=cs_bool(scope == "page"),
        PAGENAME=page_cs,
        LAYERNAME=layer_cs,
        CREATELAYER=cs_bool(create_layer),
        PAGEWORD='\\"page\\"',
    )

    return _execute_script(
        _script("LiveSetLayer_" + uuid.uuid4().hex[:6], body,
                extra_helpers=_HELPERS_SCHEMATIC + _HELPERS_TEXT + _HELPERS_LAYER),
        timeout=timeout_seconds,
    )
