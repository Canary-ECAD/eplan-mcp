<#
.SYNOPSIS
    Out-of-process UI Automation driver for EPLAN and add-in WinForms dialogs.

.DESCRIPTION
    One PowerShell entry point, dispatched by -Op, taking JSON on -ArgsJson and
    emitting exactly ONE JSON object on stdout. Designed to be shelled out to
    from Python (api/actions/ui_automation.py).

    Ops:
      list_windows   all top-level windows (title, class, pid, rect, enabled)
      wait_window    poll for a window whose title matches a regex
      dump           full control tree of a window (the debugging workhorse)
      set            ValuePattern.SetValue on a control
      type           REAL KEYSTROKES into a control (SendKeys)
      click          InvokePattern -> TogglePattern -> synthesized mouse click
      read            text/value of a control (labels, status text)
      grid           DataGridView rows as arrays
      dismiss_watch  background watcher clicking named buttons on matching windows
      main_window    IsWindowEnabled(EPLAN main hwnd) + optional force re-enable

    SELECTOR SHAPE (JSON object):
      { "by": "automationId"|"name"|"class"|"index", "value": "...",
        "type": "Button"|"Edit"|"Text"|"CheckBox"|"ComboBox"|"DataGrid"|... }
      - "by":"index" indexes into the flattened descendant list (optionally
        filtered by "type"), so it works on controls with neither id nor name.
      - "value" is treated as a REGEX for name/class/automationId; anchor it
        (^...$) when you need an exact match. Buttons whose labels collide
        ("Close" vs "Close All") are the usual reason to anchor.

    HAZARDS THIS DRIVER HANDLES EXPLICITLY
      1. OWNER-LESS TopMost DIALOGS. Add-in dialogs created with no owner
         can end up BEHIND EPLAN's main window.
         Every window lookup therefore starts at AutomationElement::RootElement
         (the DESKTOP), never at EPLAN's window element. A window found this way
         is raised via SetForegroundWindow before any interaction.
      2. MODAL ACTIONS. eplan_execute_raw_action does not return until a modal
         dialog closes, so the thing that drives the dialog CANNOT be the thing
         awaiting the action. This script is a separate PROCESS by construction;
         that is the whole point of shelling out. The pattern is:
             arm dismiss_watch (background, returns immediately)
             fire the action (blocks)
             stop dismiss_watch, read its log
         Never fire the action first and then try to drive it from the same
         caller - it will never get the chance.
      3. MFC RIBBON IS INVISIBLE TO UIA. Enumerating descendants of EPLAN's
         AfxMDIFrame140u frame returns 0 buttons. Do not try to click the
         ribbon; dispatch the action instead and drive the dialog it opens.
      4. NO UNBOUNDED WAITS. Every poll loop has a timeout and every failure
         path still emits {"success":false,"error":"..."}.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File UiDrive.ps1 `
        -Op dump -ArgsJson '{"window":{"title_regex":"^My Dialog$"}}'
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('list_windows', 'wait_window', 'dump', 'set', 'type', 'click',
                 'read', 'grid', 'dismiss_watch', 'main_window', 'keys', 'right_click')]
    [string]$Op,

    # JSON object of op arguments. Default {} so argument-less ops need nothing.
    [string]$ArgsJson = '{}',

    # Path to a UTF-8 file holding the same JSON. Wins over -ArgsJson.
    # Preferred from a shell: powershell.exe's own command-line splitting
    # mangles inline JSON containing spaces. Python's subprocess quotes
    # correctly, so the Python wrapper may use either; it uses a file.
    [string]$ArgsFile = ''
)

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------- JSON output

# Emit exactly one JSON object and exit. Nothing else may write to stdout.
function Write-Result {
    param([hashtable]$Obj, [int]$ExitCode = 0)
    # Dialog text is arbitrary Unicode (EPLAN ships German/CJK strings and
    # captions can contain '&'). The console default is the OEM codepage,
    # which mangles them into bytes Python's cp1252 reader then dies on.
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
    try {
        $json = $Obj | ConvertTo-Json -Depth 12 -Compress
    } catch {
        $json = '{"success":false,"error":"result not serializable: ' +
                ($_.Exception.Message -replace '"', "'") + '"}'
    }
    [Console]::Out.Write($json)
    [Console]::Out.Flush()
    exit $ExitCode
}

function Fail { param([string]$Message, [hashtable]$Extra)
    $o = @{ success = $false; op = $Op; error = $Message }
    if ($Extra) { foreach ($k in $Extra.Keys) { $o[$k] = $Extra[$k] } }
    Write-Result $o 1
}

# ------------------------------------------------------------------- P/Invoke

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms | Out-Null

<#
  *** THE SINGLE MOST IMPORTANT LINE IN THIS FILE ***

  The managed UIA client (UIAutomationClient.dll) ships with NO client-side
  providers registered. Without them it sees only the raw HWND provider, so an
  entire WinForms dialog comes back as a handful of anonymous `Pane` nodes with
  numeric AutomationIds, no Button/Edit/CheckBox control types, no real
  AutomationIds, no ValuePattern, no TogglePattern and no grid at all.

  On a plain WinForms test dialog:
      without RegisterClientSideProviders :  6 descendants, all ControlType.Pane
      with    RegisterClientSideProviders : 32 descendants, Edit/Button/CheckBox/
                                            Text/Table with real AutomationIds

  An unregistered client under-reports EVERY Win32/WinForms surface (EPLAN's
  ribbon then seems to expose no buttons at all). Never remove this, and never trust a UIA dump taken without it.

  ORDERING TRAP: RegisterClientSideProviders throws
      NullReferenceException at MS.Internal.Automation.ProxyManager.LoadDefaultProxies()
  if it is the FIRST UIA call in a fresh process. ProxyManager's statics are
  initialised lazily by ordinary UIA use, so the RootElement touch below is
  load-bearing, not decoration. It reproduces 100% of the time without it -
  and it fails SILENTLY into the 6-anonymous-Pane view, which looks exactly
  like "this app has no automation tree". Do not reorder these lines.
#>
$script:ClientProviders = $false
$script:ClientProvidersError = $null
try {
    Add-Type -AssemblyName UIAutomationClientsideProviders | Out-Null
    $warm = [System.Windows.Automation.AutomationElement]::RootElement
    $null = $warm.Current.Name
    $null = $warm.FindFirst([System.Windows.Automation.TreeScope]::Children,
                            [System.Windows.Automation.Condition]::TrueCondition)
    [System.Windows.Automation.ClientSettings]::RegisterClientSideProviders(
        [UIAutomationClientsideProviders.UIAutomationClientSideProviders]::ClientSideProviderDescriptionTable)
    $script:ClientProviders = $true
} catch {
    $script:ClientProvidersError = $_.Exception.Message
}

if (-not ('UiNative' -as [type])) {
@'
using System;
using System.Text;
using System.Runtime.InteropServices;

public static class UiNative
{
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr h);
    [DllImport("user32.dll")] public static extern bool EnableWindow(IntPtr h, bool enable);
    [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int idx);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int max);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassNameW(IntPtr h, StringBuilder s, int max);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);

    public const int GWL_EXSTYLE = -20;
    public const int WS_EX_TOPMOST = 0x00000008;
    public const uint GW_OWNER = 4;

    public static string Title(IntPtr h)
    { var sb = new StringBuilder(1024); GetWindowTextW(h, sb, sb.Capacity); return sb.ToString(); }

    public static string ClassOf(IntPtr h)
    { var sb = new StringBuilder(512); GetClassNameW(h, sb, sb.Capacity); return sb.ToString(); }

    public static void ClickAt(int x, int y)
    {
        SetCursorPos(x, y);
        mouse_event(0x0002, 0, 0, 0, UIntPtr.Zero);  // LEFTDOWN
        mouse_event(0x0004, 0, 0, 0, UIntPtr.Zero);  // LEFTUP
    }

    public static void RightClickAt(int x, int y)
    {
        SetCursorPos(x, y);
        mouse_event(0x0008, 0, 0, 0, UIntPtr.Zero);  // RIGHTDOWN
        mouse_event(0x0010, 0, 0, 0, UIntPtr.Zero);  // RIGHTUP
    }
}
'@ | ForEach-Object { Add-Type -TypeDefinition $_ -Language CSharp } | Out-Null
}

$UIA  = [System.Windows.Automation.AutomationElement]
$TREE = [System.Windows.Automation.TreeScope]
$COND = [System.Windows.Automation.Condition]::TrueCondition

# ------------------------------------------------------------------ arguments

if ($ArgsFile) {
    if (-not (Test-Path $ArgsFile)) { Fail "ArgsFile not found: $ArgsFile" }
    try { $ArgsJson = Get-Content -Raw -Encoding UTF8 $ArgsFile }
    catch { Fail "could not read ArgsFile: $($_.Exception.Message)" }
}
try { $A = if ([string]::IsNullOrWhiteSpace($ArgsJson)) { @{} }
           else { ConvertFrom-Json $ArgsJson } }
catch { Fail "ArgsJson is not valid JSON: $($_.Exception.Message)" }

function Get-Arg { param($Name, $Default = $null)
    if ($null -eq $A) { return $Default }
    $p = $A.PSObject.Properties[$Name]
    if ($null -eq $p -or $null -eq $p.Value) { return $Default }
    return $p.Value
}

# ------------------------------------------------------------ window handling

function Get-TopLevelWindows {
    param([switch]$IncludeInvisible)
    $out = New-Object System.Collections.ArrayList
    $cb = [UiNative+EnumWindowsProc]{
        param($h, $l)
        if ($IncludeInvisible -or [UiNative]::IsWindowVisible($h)) {
            $t = [UiNative]::Title($h)
            $c = [UiNative]::ClassOf($h)
            if ($t -or $c) {
                # NB: not $pid - that is a read-only PowerShell automatic variable.
                $ownerPid = [uint32]0
                [void][UiNative]::GetWindowThreadProcessId($h, [ref]$ownerPid)
                $pname = $null
                try { $pname = (Get-Process -Id $ownerPid -ErrorAction Stop).ProcessName } catch { }
                $ex = [UiNative]::GetWindowLong($h, [UiNative]::GWL_EXSTYLE)
                [void]$out.Add([pscustomobject]@{
                    hwnd     = [int64]$h
                    title    = $t
                    class    = $c
                    pid      = [int]$ownerPid
                    process  = $pname
                    enabled  = [UiNative]::IsWindowEnabled($h)
                    visible  = [UiNative]::IsWindowVisible($h)
                    topmost  = (($ex -band [UiNative]::WS_EX_TOPMOST) -ne 0)
                    owned    = ([UiNative]::GetWindow($h, [UiNative]::GW_OWNER) -ne [IntPtr]::Zero)
                })
            }
        }
        return $true
    }
    [void][UiNative]::EnumWindows($cb, [IntPtr]::Zero)
    return $out
}

<#
  Resolve the window spec to a live AutomationElement.

  ALWAYS searches from the DESKTOP ROOT. Owner-less TopMost add-in dialogs
  are NOT descendants of EPLAN's element, so searching from EPLAN's window
  would silently miss them.

  Spec: { "hwnd": 123456 }                      exact handle (fastest, stable)
        { "title_regex": "^My Dialog$" }     regex over the caption
        { "class_regex": "...", "pid": 1234, "process": "EPLAN" }  extra filters
#>
function Resolve-WindowSpec {
    param($Spec, [switch]$Quiet)
    if ($null -eq $Spec) { return $null }

    # A caller may pass `window` as a plain STRING (a title regex, or an hwnd as digits) or as a
    # number, not only as the {hwnd/title_regex/...} object this used to assume. It did not, and a
    # string has none of those properties, so EVERY filter below was skipped and the function
    # returned the first top-level window on the desktop -- an unrelated ThumbnailDeviceHelperWnd,
    # whatever you asked for: `dump` was unusable that way, while `wait_window` worked because
    # title_regex is its own parameter. Normalise first.
    if ($Spec -is [string] -or $Spec -is [int] -or $Spec -is [int64] -or $Spec -is [double]) {
        $text = [string]$Spec
        if ($text -match '^\s*\d+\s*$') {
            $Spec = [pscustomobject]@{ hwnd = [int64]$text.Trim() }
        }
        elseif ($text -match '^\s*\d+\.(\d+)\s*$') {
            # a runtime_id like "42.1841024" -- its second part is the hwnd
            $Spec = [pscustomobject]@{ hwnd = [int64]$Matches[1] }
        }
        else {
            $Spec = [pscustomobject]@{ title_regex = [regex]::Escape($text) }
        }
    }

    $hwnd = $null
    if ($Spec.PSObject.Properties['hwnd'] -and $Spec.hwnd) { $hwnd = [int64]$Spec.hwnd }

    if (-not $hwnd) {
        # Refuse to guess. Without at least one filter this used to hand back an arbitrary window
        # and every later op silently acted on it.
        $hasFilter = @('title_regex','class_regex','pid','process') |
            Where-Object { $Spec.PSObject.Properties[$_] -and $Spec.$_ }
        if (-not $hasFilter) { return $null }

        $cands = Get-TopLevelWindows
        if ($Spec.PSObject.Properties['title_regex'] -and $Spec.title_regex) {
            $cands = $cands | Where-Object { $_.title -match $Spec.title_regex }
        }
        if ($Spec.PSObject.Properties['class_regex'] -and $Spec.class_regex) {
            $cands = $cands | Where-Object { $_.class -match $Spec.class_regex }
        }
        if ($Spec.PSObject.Properties['pid'] -and $Spec.pid) {
            $cands = $cands | Where-Object { $_.pid -eq [int]$Spec.pid }
        }
        if ($Spec.PSObject.Properties['process'] -and $Spec.process) {
            $cands = $cands | Where-Object { $_.process -eq $Spec.process }
        }
        $first = @($cands)[0]
        if (-not $first) { return $null }
        $hwnd = $first.hwnd
    }

    try { $el = $UIA::FromHandle([IntPtr]$hwnd) } catch { $el = $null }
    if (-not $el -and -not $Quiet) { return $null }
    return $el
}

function Get-WindowInfo {
    param($El)
    $h = [int64]$El.Current.NativeWindowHandle
    $ex = [UiNative]::GetWindowLong([IntPtr]$h, [UiNative]::GWL_EXSTYLE)
    $r = $El.Current.BoundingRectangle
    return @{
        hwnd       = $h
        runtime_id = ($El.GetRuntimeId() -join '.')
        title      = $El.Current.Name
        class      = $El.Current.ClassName
        pid        = $El.Current.ProcessId
        enabled    = [bool]$El.Current.IsEnabled
        topmost    = (($ex -band [UiNative]::WS_EX_TOPMOST) -ne 0)
        owned      = ([UiNative]::GetWindow([IntPtr]$h, [UiNative]::GW_OWNER) -ne [IntPtr]::Zero)
        rect       = @{ x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height }
    }
}

# Bring an owner-less dialog that may be sitting behind EPLAN to the front.
# Best-effort: foreground stealing is restricted by Windows, and a failure to
# raise is never fatal - UIA patterns work on background windows anyway. Only
# real keystrokes (Op=type) actually require focus.
function Set-WindowForeground {
    param($El)
    try {
        $h = [IntPtr]$El.Current.NativeWindowHandle
        if ($h -eq [IntPtr]::Zero) { return $false }
        [void][UiNative]::ShowWindow($h, 9)          # SW_RESTORE
        [void][UiNative]::BringWindowToTop($h)
        return [UiNative]::SetForegroundWindow($h)
    } catch { return $false }
}

# ----------------------------------------------------------- control lookup

function Get-Descendants {
    param($Root)
    try { return @($Root.FindAll($TREE::Descendants, $COND)) } catch { return @() }
}

function Get-ElementValue {
    param($El)
    try {
        $vp = $El.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        if ($vp) { return $vp.Current.Value }
    } catch { }
    try {
        $tp = $El.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        if ($tp) { return $tp.DocumentRange.GetText(4096) }
    } catch { }
    try {
        $tg = $El.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        if ($tg) { return $tg.Current.ToggleState.ToString() }
    } catch { }
    try {
        $sel = $El.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        if ($sel) { return $sel.Current.IsSelected.ToString() }
    } catch { }
    return $null
}

<#
  NOTE ON LABEL TEXT

  A WinForms Label exposes its caption as the UIA *Name*, not through any
  value pattern - and only while the control has no AccessibleName overriding
  it. Status strings a test asserts on (e.g. "3 matches
  found") therefore arrive as Name, while a TextBox's content
  arrives as ValuePattern.Value. The 'read' op returns BOTH plus a coalesced
  'text' so a caller never has to know which kind of control it hit.

  LegacyIAccessiblePattern is deliberately NOT used: the managed
  System.Windows.Automation client does not surface it (on a plain WinForms
  dialog it returns null every time), so anything relying on it would be
  a field that is always empty.
#>

function Get-PatternNames {
    param($El)
    $names = @()
    try {
        foreach ($p in $El.GetSupportedPatterns()) {
            $n = $p.ProgrammaticName -replace 'Identifiers\.Pattern$', ''
            $names += $n
        }
    } catch { }
    return $names
}

function ConvertTo-Node {
    param($El, [int]$Depth)
    $r = $El.Current.BoundingRectangle
    $rect = $null
    if (-not [double]::IsInfinity($r.X)) {
        $rect = @{ x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height }
    }
    return @{
        depth        = $Depth
        control_type = ($El.Current.ControlType.ProgrammaticName -replace '^ControlType\.', '')
        name         = $El.Current.Name
        automation_id= $El.Current.AutomationId
        class        = $El.Current.ClassName
        value        = (Get-ElementValue $El)
        enabled      = [bool]$El.Current.IsEnabled
        is_offscreen = [bool]$El.Current.IsOffscreen
        keyboard_focusable = [bool]$El.Current.IsKeyboardFocusable
        rect         = $rect
        patterns     = (Get-PatternNames $El)
        runtime_id   = ($El.GetRuntimeId() -join '.')
    }
}

<#
  Selector matching. `value` is a regex for automationId / name / class.
  `type` (optional) filters on the control type name, e.g. "Button", "Edit",
  "Text", "CheckBox", "ComboBox", "DataGrid", "List".
#>
function Test-TypeMatch {
    param($El, $Type)
    if (-not $Type) { return $true }
    $ct = ($El.Current.ControlType.ProgrammaticName -replace '^ControlType\.', '')
    return ($ct -eq $Type) -or ($ct -match "^$([regex]::Escape($Type))$")
}

function Find-Control {
    param($Window, $Selector)
    if ($null -eq $Selector) { throw "selector is required" }
    $by = $Selector.by
    $val = [string]$Selector.value
    $type = $null
    if ($Selector.PSObject.Properties['type']) { $type = $Selector.type }

    $all = Get-Descendants $Window
    $pool = @($all | Where-Object { Test-TypeMatch $_ $type })

    switch ($by) {
        'automationId' { $m = @($pool | Where-Object { $_.Current.AutomationId -match $val }) }
        'name'         { $m = @($pool | Where-Object { $_.Current.Name -match $val }) }
        'class'        { $m = @($pool | Where-Object { $_.Current.ClassName -match $val }) }
        'index'        {
            $i = [int]$val
            if ($i -lt 0 -or $i -ge $pool.Count) {
                throw "selector index $i out of range (0..$($pool.Count - 1) for type '$type')"
            }
            $m = @($pool[$i])
        }
        default { throw "unknown selector.by '$by' (automationId|name|class|index)" }
    }

    if ($m.Count -eq 0) {
        throw ("no control matched {by=$by, value='$val', type='$type'}. " +
               "Run Op=dump to see the tree.")
    }
    # Prefer an exact name/id hit when a regex matched several - the corpus has
    # colliding button labels ("Close" vs "Close All").
    if ($m.Count -gt 1) {
        $exact = @($m | Where-Object {
            $_.Current.Name -eq $val -or $_.Current.AutomationId -eq $val })
        if ($exact.Count -ge 1) { return @{ element = $exact[0]; ambiguous = $m.Count } }
    }
    return @{ element = $m[0]; ambiguous = $m.Count }
}

# ------------------------------------------------------------------ grid read

function Read-Grid {
    param($El)
    $rows = New-Object System.Collections.ArrayList
    $headers = @()

    $gp = $null
    try { $gp = $El.GetCurrentPattern([System.Windows.Automation.GridPattern]::Pattern) } catch { }

    if ($gp) {
        $rc = $gp.Current.RowCount; $cc = $gp.Current.ColumnCount
        try {
            $tp = $El.GetCurrentPattern([System.Windows.Automation.TablePattern]::Pattern)
            if ($tp) { $headers = @($tp.Current.GetColumnHeaders() | ForEach-Object { $_.Current.Name }) }
        } catch { }
        for ($r = 0; $r -lt $rc; $r++) {
            $cells = @()
            for ($c = 0; $c -lt $cc; $c++) {
                $txt = $null
                try {
                    $cell = $gp.GetItem($r, $c)
                    $txt = Get-ElementValue $cell
                    if ($null -eq $txt -or $txt -eq '') { $txt = $cell.Current.Name }
                } catch { $txt = $null }
                $cells += $txt
            }
            [void]$rows.Add($cells)
        }
        return @{ kind = 'grid'; row_count = $rc; column_count = $cc;
                  headers = $headers; rows = $rows }
    }

    # No GridPattern (a WinForms DataGridView surfaces as ControlType.Table
    # through the MSAA bridge and does NOT support GridPattern). Walk the row
    # elements instead: the first child is the header row - all of whose cells
    # are ControlType.Header - and every data row starts with a Header cell
    # that is the row selector, not data. Both are dropped so `rows` contains
    # only real cell values, which is what an assertion wants.
    $items = @($El.FindAll($TREE::Children, $COND))
    foreach ($it in $items) {
        $kids = @($it.FindAll($TREE::Children, $COND))
        if ($kids.Count -eq 0) { [void]$rows.Add(@($it.Current.Name)); continue }

        $kindOf = { param($e) ($e.Current.ControlType.ProgrammaticName -replace '^ControlType\.', '') }
        $types = @($kids | ForEach-Object { & $kindOf $_ })
        $isHeaderRow = ($types.Count -gt 0) -and (@($types | Where-Object { $_ -ne 'Header' }).Count -eq 0)

        $cells = @()
        for ($i = 0; $i -lt $kids.Count; $i++) {
            if (-not $isHeaderRow -and $types[$i] -eq 'Header') { continue }  # row selector
            $k = $kids[$i]
            $v = Get-ElementValue $k
            if ($null -eq $v -or $v -eq '') { $v = $k.Current.Name }
            $cells += $v
        }
        if ($isHeaderRow) {
            # Drop the empty top-left corner cell if present.
            if ($cells.Count -gt 0 -and ($cells[0] -match 'Header Cell$')) {
                $cells = @($cells[1..($cells.Count - 1)])
            }
            $headers = $cells
        } else {
            [void]$rows.Add($cells)
        }
    }
    $cc = $null
    if ($headers.Count -gt 0) { $cc = $headers.Count }
    elseif ($rows.Count -gt 0) { $cc = @($rows[0]).Count }
    return @{ kind = 'items'; row_count = $rows.Count; column_count = $cc;
              headers = $headers; rows = $rows }
}

# --------------------------------------------------------------------- clicks

function Invoke-ControlClick {
    param($El)
    $tried = @()
    try {
        $ip = $El.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        if ($ip) { $ip.Invoke(); return @{ method = 'InvokePattern'; tried = $tried } }
    } catch { $tried += "InvokePattern: $($_.Exception.Message)" }

    try {
        $tg = $El.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        if ($tg) {
            $before = $tg.Current.ToggleState.ToString()
            $tg.Toggle()
            Start-Sleep -Milliseconds 60
            $after = $tg.Current.ToggleState.ToString()
            return @{ method = 'TogglePattern'; toggle_before = $before;
                      toggle_after = $after; tried = $tried }
        }
    } catch { $tried += "TogglePattern: $($_.Exception.Message)" }

    try {
        $sel = $El.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        if ($sel) { $sel.Select(); return @{ method = 'SelectionItemPattern'; tried = $tried } }
    } catch { $tried += "SelectionItemPattern: $($_.Exception.Message)" }

    # Last resort: synthesized mouse click at the control's centre. Needs the
    # window raised, hence the caller's Set-WindowForeground.
    try {
        $r = $El.Current.BoundingRectangle
        if ([double]::IsInfinity($r.X) -or $r.Width -le 0) { throw "no bounding rectangle" }
        $x = [int]($r.X + $r.Width / 2); $y = [int]($r.Y + $r.Height / 2)
        [UiNative]::ClickAt($x, $y)
        return @{ method = 'synthesized_click'; at = @{ x = $x; y = $y }; tried = $tried }
    } catch { $tried += "synthesized_click: $($_.Exception.Message)" }

    throw ("no click method worked: " + ($tried -join ' | '))
}

# ------------------------------------------------------------------- SendKeys

# Escape literal text for System.Windows.Forms.SendKeys.
# Callers who WANT key syntax ({ENTER}, ^a, %{F4}) pass raw=true.
function ConvertTo-SendKeysLiteral {
    param([string]$Text)
    $sb = New-Object System.Text.StringBuilder
    # NB: -contains on a string tests whole-string equality, not substring -
    # using it here silently let '{' and '}' through and SendKeys then parsed
    # "{ok}" as a keyword. IndexOf is the correct test.
    $special = '+^%~(){}[]'
    foreach ($ch in $Text.ToCharArray()) {
        if ($special.IndexOf($ch) -ge 0) { [void]$sb.Append('{').Append($ch).Append('}') }
        else { [void]$sb.Append($ch) }
    }
    return $sb.ToString()
}

# =============================================================== OP DISPATCH ==

$started = Get-Date
try {
    switch ($Op) {

    # ------------------------------------------------------------------------
    'list_windows' {
        $filter  = Get-Arg 'title_regex'
        $proc    = Get-Arg 'process'
        $all     = Get-Arg 'include_invisible' $false
        $wins = if ($all) { Get-TopLevelWindows -IncludeInvisible } else { Get-TopLevelWindows }
        if ($filter) { $wins = $wins | Where-Object { $_.title -match $filter } }
        if ($proc)   { $wins = $wins | Where-Object { $_.process -eq $proc } }
        $list = @($wins | ForEach-Object {
            @{ hwnd = $_.hwnd; title = $_.title; class = $_.class; pid = $_.pid
               process = $_.process; enabled = $_.enabled; topmost = $_.topmost
               owned = $_.owned }
        })
        Write-Result @{ success = $true; op = $Op; count = $list.Count; windows = $list }
    }

    # ------------------------------------------------------------------------
    # Poll the DESKTOP for a matching window. Dialogs appear asynchronously
    # after an action dispatch, so this is always a poll, never a single shot.
    'wait_window' {
        $rx = Get-Arg 'title_regex'
        if (-not $rx) { Fail "wait_window requires 'title_regex'" }
        $timeout = [double](Get-Arg 'timeout_s' 20)
        $poll    = [int](Get-Arg 'poll_ms' 200)
        $proc    = Get-Arg 'process'
        $cls     = Get-Arg 'class_regex'
        $raise   = [bool](Get-Arg 'raise' $true)
        $deadline = (Get-Date).AddSeconds($timeout)

        do {
            $wins = Get-TopLevelWindows | Where-Object { $_.title -match $rx }
            if ($proc) { $wins = $wins | Where-Object { $_.process -eq $proc } }
            if ($cls)  { $wins = $wins | Where-Object { $_.class -match $cls } }
            $hit = @($wins)[0]
            if ($hit) {
                $el = $UIA::FromHandle([IntPtr]$hit.hwnd)
                if ($raise) { [void](Set-WindowForeground $el) }
                $info = Get-WindowInfo $el
                $info['success'] = $true; $info['op'] = $Op
                $info['waited_s'] = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
                Write-Result $info
            }
            Start-Sleep -Milliseconds $poll
        } while ((Get-Date) -lt $deadline)

        Fail "timed out after ${timeout}s waiting for a window matching /$rx/" `
             @{ timed_out = $true
                visible_titles = @(Get-TopLevelWindows |
                    Where-Object { $_.title } | ForEach-Object { $_.title } |
                    Select-Object -Unique) }
    }

    # ------------------------------------------------------------------------
    # THE DEBUGGING WORKHORSE. Everything else is diagnosed from this output.
    'dump' {
        $spec = Get-Arg 'window'
        $win = Resolve-WindowSpec $spec
        if (-not $win) { Fail "window not found: $($spec | ConvertTo-Json -Compress)" }
        $maxNodes = [int](Get-Arg 'max_nodes' 800)

        $info = Get-WindowInfo $win
        $nodes = New-Object System.Collections.ArrayList
        $truncated = $false

        # Iterative walk (an MFC/WinForms mixed tree can be deep and a
        # recursive PS walk blows the pipeline on big grids).
        $stack = New-Object System.Collections.Stack
        foreach ($c in @($win.FindAll($TREE::Children, $COND))) { $stack.Push(@($c, 1)) }
        while ($stack.Count -gt 0) {
            if ($nodes.Count -ge $maxNodes) { $truncated = $true; break }
            $pair = $stack.Pop()
            $el = $pair[0]; $d = [int]$pair[1]
            try { [void]$nodes.Add((ConvertTo-Node $el $d)) } catch { continue }
            try {
                $kids = @($el.FindAll($TREE::Children, $COND))
                for ($i = $kids.Count - 1; $i -ge 0; $i--) { $stack.Push(@($kids[$i], $d + 1)) }
            } catch { }
        }

        Write-Result @{ success = $true; op = $Op; window = $info
                        node_count = $nodes.Count; truncated = $truncated
                        client_side_providers = $script:ClientProviders
                        controls = $nodes }
    }

    # ------------------------------------------------------------------------
    # ValuePattern.SetValue. FAST but it BYPASSES keyboard hooks - see 'type'.
    'set' {
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $hit = Find-Control $win (Get-Arg 'selector')
        $el = $hit.element
        $value = [string](Get-Arg 'value' '')
        $vp = $null
        try { $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern) } catch { }
        if (-not $vp) {
            Fail ("control does not support ValuePattern (patterns: " +
                  ((Get-PatternNames $el) -join ',') + "). Use Op=type instead.")
        }
        if ($vp.Current.IsReadOnly) { Fail "control is read-only" }
        $vp.SetValue($value)
        Start-Sleep -Milliseconds 60
        Write-Result @{ success = $true; op = $Op; ambiguous_matches = $hit.ambiguous
                        set_to = $value; read_back = (Get-ElementValue $el) }
    }

    # ------------------------------------------------------------------------
    # REAL KEYSTROKES, deliberately not SetValue.
    #
    # An add-in dialog may install a WH_GETMESSAGE keyboard hook so EPLAN's
    # TranslateAccelerator cannot eat its keys. ValuePattern.SetValue never
    # generates WM_KEY* messages, so it slips past such a hook entirely and
    # would NOT exercise keyboard behaviour under test. This op focuses the control and
    # sends genuine key input.
    'type' {
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $hit = Find-Control $win (Get-Arg 'selector')
        $el = $hit.element
        $text = [string](Get-Arg 'text' '')
        $raw  = [bool](Get-Arg 'raw' $false)          # true => SendKeys syntax
        $clear = [bool](Get-Arg 'clear_first' $true)
        $perKeyMs = [int](Get-Arg 'per_key_ms' 0)

        [void](Set-WindowForeground $win)
        Start-Sleep -Milliseconds 120
        try { $el.SetFocus() } catch {
            Fail "could not focus the control for real keystrokes: $($_.Exception.Message)"
        }
        Start-Sleep -Milliseconds 120

        if ($clear) {
            # '^a' is NOT safe here. A dialog's WH_GETMESSAGE hook can swallow the CTRL
            # modifier, so SendKeys '^a' arrives as a literal 'a' and the field ends up with a
            # stray leading character (observed live 2026-08-20: typed 'ZZTEST', read back
            # 'aZZTEST'). Select the existing text with navigation keys instead, which carry no
            # modifier that can be lost, then delete the selection.
            [System.Windows.Forms.SendKeys]::SendWait('{HOME}')
            Start-Sleep -Milliseconds 40
            [System.Windows.Forms.SendKeys]::SendWait('+{END}')
            Start-Sleep -Milliseconds 40
            [System.Windows.Forms.SendKeys]::SendWait('{DEL}')
            Start-Sleep -Milliseconds 40

            # Multi-line controls keep text below the first line; fall back to ValuePattern.
            $residue = Get-ElementValue $el
            if ($residue) {
                try {
                    $vp = $el.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                    if ($vp) { $vp.SetValue('') ; Start-Sleep -Milliseconds 40 }
                } catch { }
            }
        }

        $payload = if ($raw) { $text } else { ConvertTo-SendKeysLiteral $text }
        if ($perKeyMs -gt 0 -and -not $raw) {
            foreach ($ch in $text.ToCharArray()) {
                [System.Windows.Forms.SendKeys]::SendWait((ConvertTo-SendKeysLiteral ([string]$ch)))
                Start-Sleep -Milliseconds $perKeyMs
            }
        } else {
            [System.Windows.Forms.SendKeys]::SendWait($payload)
        }
        Start-Sleep -Milliseconds 120

        Write-Result @{ success = $true; op = $Op; ambiguous_matches = $hit.ambiguous
                        sent = $payload; raw = $raw
                        read_back = (Get-ElementValue $el)
                        note = 'real keystrokes via SendKeys - exercises WH_GETMESSAGE hooks' }
    }

    # ------------------------------------------------------------------------
    'click' {
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $hit = Find-Control $win (Get-Arg 'selector')
        $el = $hit.element
        if (-not $el.Current.IsEnabled -and -not (Get-Arg 'allow_disabled' $false)) {
            Fail "control '$($el.Current.Name)' is disabled"
        }
        [void](Set-WindowForeground $win)
        $res = Invoke-ControlClick $el
        Start-Sleep -Milliseconds ([int](Get-Arg 'settle_ms' 200))
        Write-Result @{ success = $true; op = $Op; ambiguous_matches = $hit.ambiguous
                        control = $el.Current.Name; click = $res }
    }

    # ------------------------------------------------------------------------
    'read' {
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $hit = Find-Control $win (Get-Arg 'selector')
        $el = $hit.element
        # WinForms Labels put their caption in Name; TextBoxes put it in Value.
        # Return both plus the legacy IAccessible view so callers asserting on
        # status text never have to guess which one a control uses.
        $v = Get-ElementValue $el
        $n = $el.Current.Name
        Write-Result @{ success = $true; op = $Op; ambiguous_matches = $hit.ambiguous
                        control = (ConvertTo-Node $el 0)
                        name = $n
                        text = $(if ($v) { $v } else { $n })
                        value = $v }
    }

    # ------------------------------------------------------------------------
    'grid' {
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $sel = Get-Arg 'selector'
        if ($null -eq $sel) {
            # Default to the first DataGrid/Table/List in the window.
            $all = Get-Descendants $win
            $g = @($all | Where-Object {
                ($_.Current.ControlType.ProgrammaticName -replace '^ControlType\.', '') -in
                    @('DataGrid', 'Table', 'List') })[0]
            if (-not $g) { Fail "no DataGrid/Table/List in the window; pass an explicit selector" }
            $el = $g; $amb = 1
        } else {
            $hit = Find-Control $win $sel; $el = $hit.element; $amb = $hit.ambiguous
        }
        $data = Read-Grid $el
        $data['success'] = $true; $data['op'] = $Op
        $data['ambiguous_matches'] = $amb
        $data['control'] = $el.Current.Name
        Write-Result $data
    }

    # ------------------------------------------------------------------------
    # Background watcher: clicks a named button when a matching window shows up.
    #
    # THIS IS THE ANSWER TO THE MODAL HAZARD. A modal add-in dialog blocks
    # eplan_execute_raw_action, so the caller awaiting the action cannot also
    # drive the dialog. Arm this FIRST (start), then fire the action, then stop.
    #
    #   start  -> {"success":true,"watch_id":"...","log":"...","pid":N}
    #   stop   -> {"success":true,"events":[...],"still_running":false}
    #   status -> same as stop but leaves the watcher running
    #
    # 'start' spawns a DETACHED powershell that polls the desktop root, so it
    # keeps running after this process exits and across the blocking action.
    'dismiss_watch' {
        $mode = [string](Get-Arg 'mode' 'start')
        $stateDir = Join-Path $env:TEMP 'eplan_ui_watch'
        [void](New-Item -ItemType Directory -Force -Path $stateDir)

        if ($mode -eq 'start') {
            $rules = Get-Arg 'rules'
            if (-not $rules) { Fail "dismiss_watch start requires 'rules':[{title_regex,button_name}]" }
            $timeout = [double](Get-Arg 'timeout_s' 300)
            $poll = [int](Get-Arg 'poll_ms' 300)
            $id = [guid]::NewGuid().ToString('N').Substring(0, 12)
            $log  = Join-Path $stateDir "$id.jsonl"
            $stop = Join-Path $stateDir "$id.stop"
            $rulesFile = Join-Path $stateDir "$id.rules.json"
            ($rules | ConvertTo-Json -Depth 6 -Compress) |
                Set-Content -Path $rulesFile -Encoding UTF8
            '' | Set-Content -Path $log -Encoding UTF8

            $self = $PSCommandPath
            $child = @"
`$ErrorActionPreference='SilentlyContinue'
. { } # keep the profile out
`$rules = Get-Content -Raw '$rulesFile' | ConvertFrom-Json
`$deadline = (Get-Date).AddSeconds($timeout)
`$seen = @{}
`$claimed = @{}
`$tmpArgs = '$stateDir\$id.args.json'
function Invoke-Drive(`$op, `$obj) {
    (`$obj | ConvertTo-Json -Depth 6 -Compress) | Set-Content -Path `$tmpArgs -Encoding UTF8
    return (& powershell -NoProfile -ExecutionPolicy Bypass -File '$self' ``
              -Op `$op -ArgsFile `$tmpArgs 2>`$null)
}
while ((Get-Date) -lt `$deadline -and -not (Test-Path '$stop')) {
    # ONE window snapshot per cycle, rules applied to it in order. A per-rule list_windows let
    # a window that appeared between two rules' calls skip the earlier (claim) rule and be
    # clicked by a later one.
    `$snap = @{}
    foreach (`$r in @(`$rules)) {
        `$rproc = if (`$r.PSObject.Properties['process'] -and `$r.process) { `$r.process } else { 'EPLAN' }
        if (-not `$snap.ContainsKey(`$rproc)) {
            `$probe = Invoke-Drive 'list_windows' @{ title_regex = '.'; process = `$rproc }
            try { `$p = `$probe | ConvertFrom-Json } catch { `$p = `$null }
            `$snap[`$rproc] = if (`$p -and `$p.success) { @(`$p.windows) } else { @() }
        }
        `$matching = @(`$snap[`$rproc] | Where-Object { `$_.title -match `$r.title_regex })
        if (`$matching.Count -lt 1) { continue }
        foreach (`$w in `$matching) {
            `$key = "`$(`$w.hwnd)"
            if (`$seen.ContainsKey(`$key)) { continue }
            # Never click on an application main frame - only dialogs. A rule as broad as
            # {title_regex:'^EPLAN'} once matched EPLAN's own MDI frame AND an unrelated
            # File Explorer window, and the watcher clicked Close on the Explorer window
            # (observed live 2026-08-20).
            if (-not (`$r.PSObject.Properties['allow_main_frame'] -and `$r.allow_main_frame)) {
                if (`$w.class -match '^Afx' -or `$w.class -eq 'CabinetWClass') { continue }
            }
            `$seen[`$key] = `$true
            # A 'claim' rule hands matching windows to a dialog driver: each is marked handled
            # (so no later rule or preset clicks it) and never clicked. With claim_until, the
            # claim lapses once that file exists (the driver is done); windows that appear
            # after it fall through to the normal rules.
            if (`$r.PSObject.Properties['claim'] -and `$r.claim) {
                `$until = if (`$r.PSObject.Properties['claim_until']) { [string]`$r.claim_until } else { '' }
                if (`$until -and (Test-Path `$until)) { `$seen.Remove(`$key); continue }
                if (-not `$until) {
                    `$ck = [string][array]::IndexOf(@(`$rules), `$r)
                    if (`$claimed.ContainsKey(`$ck)) { `$seen.Remove(`$key); continue }
                    `$claimed[`$ck] = `$true
                }
                `$ev = @{ at = (Get-Date).ToString('o'); hwnd = `$w.hwnd; title = `$w.title
                          class = `$w.class; rule = `$r.title_regex; event = 'claimed' } | ConvertTo-Json -Compress
                Add-Content -Path '$log' -Value `$ev
                continue
            }
            `$out = Invoke-Drive 'click' @{ window = @{ hwnd = `$w.hwnd } ;
                    selector = @{ by='name'; value=`$r.button_name; type='Button' } }
            `$ev = @{ at = (Get-Date).ToString('o'); hwnd = `$w.hwnd; title = `$w.title
                      class = `$w.class; rule = `$r.title_regex; button = `$r.button_name
                      result = "`$out" } | ConvertTo-Json -Depth 6 -Compress
            Add-Content -Path '$log' -Value `$ev
        }
    }
    Start-Sleep -Milliseconds $poll
}
Add-Content -Path '$log' -Value (@{ at=(Get-Date).ToString('o'); event='watcher_exit' } | ConvertTo-Json -Compress)
"@
            $childFile = Join-Path $stateDir "$id.child.ps1"
            $child | Set-Content -Path $childFile -Encoding UTF8
            $p = Start-Process -FilePath 'powershell' -WindowStyle Hidden -PassThru `
                 -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $childFile)
            Write-Result @{ success = $true; op = $Op; mode = 'start'; watch_id = $id
                            pid = $p.Id; log = $log; stop_file = $stop
                            timeout_s = $timeout
                            note = 'armed BEFORE the blocking action, as the modal hazard requires' }
        }

        if ($mode -eq 'stop' -or $mode -eq 'status') {
            $id = [string](Get-Arg 'watch_id')
            if (-not $id) { Fail "dismiss_watch $mode requires 'watch_id'" }
            $log  = Join-Path $stateDir "$id.jsonl"
            $stop = Join-Path $stateDir "$id.stop"
            if ($mode -eq 'stop') {
                '' | Set-Content -Path $stop -Encoding UTF8
                # The watcher only notices the stop file at its next poll, so
                # give it a bounded moment to write its watcher_exit record -
                # otherwise every stop reports still_running:true.
                $waitUntil = (Get-Date).AddSeconds([double](Get-Arg 'stop_wait_s' 3))
                while ((Get-Date) -lt $waitUntil) {
                    if ((Test-Path $log) -and
                        (Select-String -Path $log -Pattern 'watcher_exit' -Quiet)) { break }
                    Start-Sleep -Milliseconds 200
                }
            }
            $events = @()
            if (Test-Path $log) {
                foreach ($line in (Get-Content $log)) {
                    if ([string]::IsNullOrWhiteSpace($line)) { continue }
                    try { $events += (ConvertFrom-Json $line) } catch { }
                }
            }
            $exited = @($events | Where-Object { $_.event -eq 'watcher_exit' }).Count -gt 0
            Write-Result @{ success = $true; op = $Op; mode = $mode; watch_id = $id
                            dismissed = @($events | Where-Object { $_.event -ne 'watcher_exit' })
                            count = @($events | Where-Object { $_.event -ne 'watcher_exit' }).Count
                            still_running = (-not $exited); log = $log }
        }

        if ($mode -eq 'list') {
            $ids = @()
            if (Test-Path $stateDir) {
                $ids = @(Get-ChildItem $stateDir -Filter '*.jsonl' |
                         ForEach-Object { $_.BaseName })
            }
            Write-Result @{ success = $true; op = $Op; mode = 'list'; watch_ids = $ids
                            state_dir = $stateDir }
        }

        Fail "unknown dismiss_watch mode '$mode' (start|stop|status|list)"
    }

    # ------------------------------------------------------------------------
    # Recovery: a crash between EplanInteractionGate construct and Dispose
    # leaves EPLAN's main window DISABLED and apparently hung. Report it and
    # optionally force it back on.
    # ------------------------------------------------------------------------
    # Send raw keystrokes to a WINDOW, with no control selector and no
    # AutomationElement.SetFocus.
    #
    # Why this exists: EPLAN's GED page view (class AfxFrameOrView140u) reports
    # keyboard_focusable=false and its children throw "Target element cannot
    # receive focus" on SetFocus, so the 'type' op cannot reach it. But the GED
    # is exactly where a test has to send Ctrl+A - object-level GED selection is
    # the only input channel for actions that work on the GED selection,
    # and Edit.SelectObjects does not make the GED the ACTIVE window, so
    # SelectionSet.Selection keeps reporting the page navigator's page instead
    # (verified live 2026-08-20).
    #
    # args: { window, keys, raw?=true, settle_ms?=300 }
    'keys' {
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $keys = [string](Get-Arg 'keys' '')
        if (-not $keys) { Fail "keys op requires 'keys'" }
        $raw = [bool](Get-Arg 'raw' $true)
        $settle = [int](Get-Arg 'settle_ms' 300)

        $ok = Set-WindowForeground $win
        Start-Sleep -Milliseconds 200
        $payload = if ($raw) { $keys } else { ConvertTo-SendKeysLiteral $keys }
        [System.Windows.Forms.SendKeys]::SendWait($payload)
        Start-Sleep -Milliseconds $settle

        Write-Result @{ success = $true; op = $Op; sent = $payload; raw = $raw
                        foregrounded = $ok
                        note = 'window-level keystrokes - no control focus required' }
    }

    # ------------------------------------------------------------------------
    'right_click' {
        # A real mouse right-click inside a window, at a fraction of its rectangle. EPLAN's GED
        # opens its context menu only for a real click; Shift+F10 into the page frame opens none.
        $win = Resolve-WindowSpec (Get-Arg 'window')
        if (-not $win) { Fail "window not found" }
        $fx = [double](Get-Arg 'fx' 0.5)
        $fy = [double](Get-Arg 'fy' 0.5)
        $r = $win.Current.BoundingRectangle
        if ($r.IsEmpty -or $r.Width -le 0) { Fail "window has no on-screen rectangle" }
        $x = [int]($r.Left + $r.Width * $fx)
        $y = [int]($r.Top + $r.Height * $fy)
        $ok = Set-WindowForeground $win
        Start-Sleep -Milliseconds 200
        [UiNative]::RightClickAt($x, $y)
        Start-Sleep -Milliseconds ([int](Get-Arg 'settle_ms' 500))
        Write-Result @{ success = $true; op = $Op; x = $x; y = $y; foregrounded = $ok }
    }

    # ------------------------------------------------------------------------
    'main_window' {
        $rx = [string](Get-Arg 'class_regex' '^Afx')
        $procName = [string](Get-Arg 'process' 'EPLAN')
        $wins = @(Get-TopLevelWindows | Where-Object {
            $_.process -eq $procName -and $_.class -match $rx })
        if ($wins.Count -eq 0) { Fail "no top-level window for process '$procName' matching /$rx/" }
        $w = $wins[0]
        $forced = $false
        if ([bool](Get-Arg 'force_enable' $false) -and -not $w.enabled) {
            [void][UiNative]::EnableWindow([IntPtr]$w.hwnd, $true)
            $forced = $true
            $w.enabled = [UiNative]::IsWindowEnabled([IntPtr]$w.hwnd)
        }
        Write-Result @{ success = $true; op = $Op; hwnd = $w.hwnd; title = $w.title
                        class = $w.class; pid = $w.pid; enabled = $w.enabled
                        force_enabled = $forced }
    }

    }
} catch {
    Fail ("$($_.Exception.GetType().Name): $($_.Exception.Message)") `
         @{ script_line = $_.InvocationInfo.ScriptLineNumber }
}

Fail "op '$Op' produced no result"
