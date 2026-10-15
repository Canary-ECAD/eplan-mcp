# Moving a main function, clearing function text (Session 2026-10-14)

Two bulk DataModel writes, measured live on EPLAN 2027 (.NET 8 API) through an
in-process add-in. The scripted `eplan_execute_custom_script` route would need
the same calls through reflection (see `llm.md` §6). Every write was first run
on a disposable clone. Each run was judged by a full-project PDF export before
and after, compared as extracted text runs and as a pixel diff.

## 1. Clearing function text (FUNC_TEXT, 20011)

The goal was to clear the manual function text on overlay-style functions,
where the text belongs to another function with the same device tag.

```csharp
f.SmartLock();
f.Properties.FUNC_TEXT.Set(new MultiLangString());
```

- Read the text back as `FUNC_TEXT.ToMultiLangString().GetAsString()`. That
  form includes every language, so a text held only in a non-default language
  still counts.
- Before you clear, check two things. Is the function its device's **main**
  function? Reports such as the device list take function text from the main
  function. Does any `PropertyPlacement` on it display 20011 or 20031? If both
  answers are no, the clear does not change the printed pages. Measured: 625
  functions cleared, 0 text runs changed in the PDF.
- Check whether the text exists anywhere else first. In the measured project,
  about a third of the cleared texts existed only on those functions. Save the
  old values before you write.
- Text inside macros comes back on the next macro update. Clear it in the
  macro project too, then regenerate the macros.

## 2. Moving the main function to a new unplaced function

The goal: each device's main function is either on a panel layout page or
unplaced. A main function placed on a schematic page gets a new **unplaced**
twin. The twin takes every property, the parts, and the main role. The placed
function stays where it is as an auxiliary function.

```csharp
using (new LockingStep())
{
    // Lock EVERY function with this device tag, and each one's parts, first.
    foreach (var d in sameDeviceTag)
    {
        d.SmartLock();
        foreach (var ar in d.ArticleReferences) ar.SmartLock();
    }

    var nf = Function.Create(old.FunctionDefinition, project); // unplaced
    nf.SmartLock();
    nf.Name = old.Name;                // sets the device tag

    foreach (var pv in old.Properties.ExistingValues)
    {
        if (pv.Id.AsInt == 20006) continue;          // read-only, see below
        try { pv.CopyTo(nf.Properties[pv.Id]); continue; } catch { }
        try { nf.Properties[pv.Id] = pv; } catch { /* derived id: report it */ }
    }

    old.IsMainFunction = false;
    nf.IsMainFunction = true;
    foreach (var ar in old.ArticleReferences) old.RemoveArticleReference(ar);
    // then AddArticleReference(partNr, variant, count) on nf for each missing part
}
```

What bit:

| Symptom | Cause | Fix |
|---|---|---|
| `SettingValueFailedException: S511113` when you write 20006 | `FUNC_FULLDEVICETAG` is read-only | Set `Function.Name`. The structure segments follow the name. |
| `LockingException ... Object ID 28/17/...` when you switch `IsMainFunction` | EPLAN rewrites the other functions of the device, and their parts, when the main role moves | Lock every function with the same device tag, and their `ArticleReferences`, before the first write |
| Half-built function left over after a failed copy | `Function.Create` succeeded, then a later step threw | Call `nf.Remove()` in the catch, before you change anything on the old function |

### Which properties differ after the copy

Compare old and new by value for every id in `old.Properties.ExistingValues`,
not by which writes threw. Measured on 191 devices: no stored field was lost
(text, engraving, supplementary fields, user-defined properties). The only
differences were ids that depend on placement or wiring:

- Placement and page: 19002 to 19023, 20002, 20010, 1229, 46434/46435, 59968
- Connection-derived: connection points, target labels (45xxx, 46xxx, 48xxx),
  20038, 20219, 20342
- 20221 (width), 20470 (placed in circuit), and the main-function flags
  20122/20612

### Parts drive labels on the placed function

**Moving the parts off a placed function blanks every label it displays from
part data.** In the 191-device trial, 214 text runs disappeared from 14 pages.
They were breaker ratings and manufacturer part numbers. The data was still
correct, but the placed symbols no longer showed it. Move parts only where the
placed function displays no part-driven property. Otherwise keep the parts on
the placed function. The run that went to production was limited to
header-style black boxes: 48 moved, 0 text runs changed.

## 3. How "no visible change" was proven

1. Export the whole project to PDF before the write, with a fixed scheme and
   black-and-white output.
2. Run the write on a clone, then export again.
3. Extract the text runs per page and compare them as multisets. Count lost
   and gained runs per page.
4. Run a pixel diff per page. Expect differences only in the plot date/time
   stamp. Any other changed region means a visible change.

A clean text diff with a dirty pixel diff points to graphics. A dirty text
diff (as in the part-move trial above) shows exactly which labels changed.
