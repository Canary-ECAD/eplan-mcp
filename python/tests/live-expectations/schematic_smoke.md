# Live expectations: schematic primitives

What the six schematic tools actually did on a real EPLAN, so a future change
that breaks one of them has something to be compared against. The offline suite
pins the generated C#; this pins the OBSERVED BEHAVIOUR, which no offline test
can reach.

**Measured:** 2026-09-03, EPLAN Electric P8 2027.0.1, remoting port 49152.
**Against:** a disposable clone in `%TEMP%\eplan_mcp_scratch`. No project or
master data outside that directory was written. Production master data on that
machine resolves to `P:\04\EPLAN\...`; the clone carries project-local copies of
all seven symbol libraries inside its own `.edb`, which is what makes the
scratch guard meaningful rather than decorative.

**Reproduce:** with a scratch project open in EPLAN, run the end-to-end script
described under "The sequence" below against the working tree (import
`api.actions.schematic` directly - a connected MCP server is running the
*installed* code, not your edit).

## The sequence, and what each step returned

| # | Call | Result |
|---|---|---|
| 1 | `live_symbol_catalog()` | 7 libraries: 4 stock (`SPECIAL_en_US`, `GRAPHICS_en_US`, `NFPA_symbol_en_US`, `Symbol Library - Special`) plus 3 site-specific ones, names redacted - a client's library names are not ours to publish, and only the COUNT matters here |
| 2 | `live_symbol_catalog(library="NFPA_symbol_en_US")` | 12 symbols; `SL`, `S`, `O`, `SSV`, `SWR`, `ONE` have 2 connection points, `Q1` has 6 |
| 3 | `live_symbol_catalog(library=..., symbol="SL")` | 9 variants, each with its pin list |
| 4 | `live_create_page(location="MCPTEST", counter=777)` | page **`+MCPTEST/777`**, `pageType=Circuit`, `gridSize=3.175` |
| 5 | `live_place_symbol(page, lib, "SL", 60.0, 200.0)` | handle `207/17/40965/0`, snapped to **(60.325, 200.025)** |
| 6 | `live_place_symbol(page, lib, "SL", 140.0, 200.0)` | handle `207/17/40966/0`, snapped to **(139.7, 200.025)** |
| 7 | `live_read_page(page)` | `placementCount=2`, both `Function` |
| 8 | `live_connect_pins(page, hA, 0, hB, 0)` | `lineDrawn=true`, from (60.325, 206.375) to (139.7, 206.375) |
| 9 | `live_read_page(page)` | `placementCount=3`: DynamicConnectionLine + 2 Function |
| 10 | `live_remove_placement(page, handle=hB, expect_type="Function")` | removed; count back to 2 |
| 11 | `live_remove_placement(page, handle=hA, expect_type="DynamicConnectionLine")` | **refused** - "handle resolves to a Function" |
| 12 | `live_remove_placement(page, remove_page=True)` | `pageRemoved=true`; a later read fails with the page list |

## Numbers a future change must not silently alter

- **Grid is 3.175 mm** (1/8"). `Page.GridSize` on this installation. Snapping
  60.0 -> 60.325 and 140.0 -> 139.7 follows from it; if those two numbers move,
  either the grid or the snap formula changed.
- **`SL` pin 0 reports raw `(0.0, 6.35)`** with the placement at
  `(60.325, 200.025)`, resolving to absolute `(60.325, 206.375)` with
  `frame="relative"`. This is the single most important observation in the file:
  the raw value is an OFFSET, and publishing it as a page coordinate would draw
  wires near the page origin that touch nothing while reporting success.
- **A newly placed Function's `Name` is `"+"`.** It has no device tag until one
  is assigned. Not a failure.
- **Page naming ignored the plant designation.** An earlier run set
  `DESIGNATION_PLANT` alongside location and counter and got `+SPIKE5/950` - the
  plant part did not appear. Hence `live_create_page` reads the name back rather
  than predicting it.

## The scratch guard, verified in both directions

With `SCRATCH_ROOT` pointed away from the open project (the same condition as
"a real project is focused"):

- `live_create_page(...)` with the default `allow_real_project=False` was
  **refused**: `REFUSING TO WRITE: the open project is '...SCHEM_SPIKE_01.edb',
  which is outside the scratch root '...'`.
- The same call with `allow_real_project=True` **succeeded** and created
  `+OVERRIDE/998`, which was then removed.

Both halves matter: a guard that never fires is not protecting anything, and one
that cannot be overridden makes the tool unusable for its real purpose.

## Failures found by running this, not by reading it

Recorded because each one cost real debugging time and none was visible from
Python:

1. `SetLiveProp` was called before it was defined. EPLAN reported
   `CS0103 (Row:712)`; the tool returned only "Timeout waiting for script
   results". **A compile error is indistinguishable from a timeout** unless you
   read `eplan_get_system_messages` - which is why every timeout from these
   tools now carries a hint saying so.
2. `Page.Properties` (a `PagePropertyList`) has **no page-description member**.
   The `description` argument was removed rather than shipped as a parameter
   that silently does nothing. Setting one needs the generic
   `Property[AnyPropertyId]` indexer and a decision about which property id
   represents "page description" - see the roadmap issue.

## Scope limit

Step 8 draws a graphical connection line between two pin coordinates. Whether
EPLAN has also created a LOGICAL `Connection` between the two functions is NOT
asserted here - that needs `generate_connections` + `export_connections` to
settle. The tool's own result says the same thing in its `scopeNote`, so a
caller cannot mistake "a line was drawn" for "the devices are wired".

---

# Connections: graphical vs logical

**Measured** 2026-09-03, EPLAN 2027.0.1, against a clone of a production project.

## `live_read_connections` reads real wiring

The production go-by reports **3085** logical connections, e.g.

```
+P03-CA[2] -> +P03-E-A[1]    kindOfWire=IndividualConnection
```

so the reader works against real data, not just synthetic pages.

## The connection-line geometry bug this exposed

`SetGraphics(p1, p2)` takes coordinates **RELATIVE to the line's `Location`**, not
absolute page coordinates. Confirmed by reading real, human-drawn lines:

| | Value |
|---|---|
| `Location` | (326.39, 346.71) — the absolute anchor |
| `GetGraphics()` | a `Line` from (0,0) to (-1.27, 2.54) — relative |
| `GraphicalConnectionPoints` | also relative |

The first version of `live_connect_pins` passed **absolute** coordinates with
`Location` left at its default, which put one end of every wire at the **page
origin**:

```
DynamicConnectionLine  loc=(0,0)  pins=[(0,0), (139.7, 206.375)]
```

A line that visibly exists, reports success, and connects nothing — exactly the
failure the pin-frame handling was written to prevent, arriving by another route.

**Fixed**: anchor `Location` at the first pin, then draw the segment relative.
After the fix:

```
DynamicConnectionLine  loc=(60.325, 206.375)
                       pins=[(60.325, 206.375), (139.7, 206.375)]
Function +-WA1         pin 0 = (60.325, 206.375)     <- exact match
Function +-WA2         pin 0 = (139.7, 206.375)      <- exact match
```

## UNRESOLVED: a drawn line did not become a logical Connection

With the geometry correct, both devices tagged (`+-WA1`, `+-WA2`) and
`eplan_generate_connections` run successfully, the page still reported **0**
logical connections.

What was ruled out:
- **Untagged devices** — tagging both made no difference.
- **Wrong geometry** — the line's connection points now coincide exactly with
  the device pins.
- **Generation not running** — `generate_connections` returned success, and the
  project's 3085 existing connections were unaffected.

Still open: whether the `SL` symbol from `NFPA_symbol_en_US` carries real
electrical connection points, whether generation is scheme- or scope-driven, or
whether programmatically created lines need something further.

**This is why `live_connect_pins` reports `lineDrawn`, never `wired`** — and why
`live_read_connections` exists. The gap is real, and it is now measurable rather
than assumed.

## RESOLVED (2026-09-03): generation works, but it ignores the drawn line

Two findings, and the second is the important one.

**1. Connections must be generated, and `generate /TYPE:CONNECTIONS` does it.**
The earlier "0 connections" reading was taken before generation had produced
anything for that page. On a page with four devices, generation moved the
project from 3085 to 3087 connections.

**2. EPLAN connected the devices it thought were adjacent, NOT the ones the
drawn lines joined.**

Placed and tagged:

| Device | Position | Pins |
|---|---|---|
| `-K1` | (60.3, 241.3) | 0 above at y=247.65, 1 below at y=234.95 |
| `-K2` | (139.7, 241.3) | same shape |
| `-K3` | (60.3, 181.0) | pin 0 at y=187.325 |
| `-K4` | (139.7, 139.7) | pin 0 at y=146.05 |

Lines drawn: `-K1 → -K2` (horizontal, same Y) and `-K3 → -K4` (routed, via a
corner). **Three** DynamicConnectionLines on the page.

What generation produced:

```
+-K1[2] (60.325, 241.3)  ->  +-K3[1] (60.325, 180.975)
+-K2[2] (139.7, 241.3)   ->  +-K4[1] (139.7, 139.7)
```

Those are the **vertically aligned** pairs — same X, bottom pin facing top pin.
Not one of the three drawn lines produced a connection.

### What this means for the wiring primitives

EPLAN's auto-connect works on **device alignment**, not on graphical lines added
through the API. The EPLAN-native way to wire two devices is to POSITION them so
their connection points face each other and let generation create the
connection; a `DynamicConnectionLine` placed programmatically is decoration
unless it participates in that logic.

So `live_connect_pins` and `live_connect_pins_routed` draw something visible and
geometrically correct that does **not** wire anything. Their geometry fixes
(anchoring, corners) remain valid and worth keeping, but the primitive a caller
actually needs is placement-driven: put the devices where their pins meet.

Recorded rather than patched, because the fix is a design change to the wiring
layer and not a bug in these two tools.


---

# How EPLAN actually wires a schematic

**Measured** 2026-09-03 across 30 pages of a production project. This supersedes
every earlier guess in this file about connections, including two of mine.

## Nothing draws a wire. Everything is a placed symbol.

| Need | Mechanism | Object | Seen in 30 pages |
|---|---|---|---|
| Straight run between aligned pins | autoconnecting line - implicit | **none** | - |
| Corner / turn | place a `CO` symbol (v0-v3 = 4 orientations) | SymbolReference | 2241 total |
| T-node / branch | place `TLRO` / `TLRU` | SymbolReference | (included above) |
| Wire number, colour, cross-section | `CDPNG` / `CDPNG2` on the connection | ConnectionDefinitionPoint | 1033 |
| Cross-page jump | `BP`, paired by name (A, B, C...) | InterruptionPoint | 156 |
| Diagonal / free routing | `DynamicConnectionLine` | rare | **18, all on ONE page** |

All from `SPECIAL_en_US` / `Symbol Library - Special`.

## The autoconnecting line is not an object

A page built with four devices and no lines at all:

```
placements: 4 (all Function)   line objects: 0
rendered:   two vertical lines between the vertically-aligned pairs
connections after generation:
    +-K1[2] (60.325, 241.3) -> +-K3[1] (60.325, 180.975)
    +-K2[2] (139.7, 241.3)  -> +-K4[1] (139.7, 139.7)
```

EPLAN renders the line between connection points that FACE EACH OTHER on a
shared axis, and generation turns it into an `IndividualConnection`. There is
nothing on the page to create, address or delete.

## A corner is a symbol, not a drawn elbow

`CO` has connection points on two perpendicular sides, so it autoconnects to
whatever is aligned above/below and left/right of it. Turning a corner means
PLACING `CO` at the turn - not drawing two segments. Its four variants are the
four orientations.

## Why the first attempt failed

`live_connect_pins` drew a `DynamicConnectionLine` between two pins for an
ordinary straight run. That primitive is real but rare - 18 instances in 30
pages, all on one detail page, used for genuine diagonals. Using it for a
straight run produced a line that was geometrically exact, visible on the page,
and connected to nothing, because the connection comes from ALIGNMENT and not
from the line.

The correct primitive set is placement-driven:

  place a device so its pin faces an existing pin  -> straight run
  place `CO` at a turn                             -> corner
  place `TLRO`/`TLRU`                              -> branch
  place `CDPNG` on a connection                    -> wire properties
  place `BP` pairs                                 -> cross-page
  `DynamicConnectionLine`                          -> diagonals only

## Note for the convention profile

Learning from a go-by ranked `Symbol Library - Special / CO` top with 175
observations. That is not a device - it is the corner symbol, and it is the most
common thing on a schematic page. A profile that treats it as device vocabulary
is mis-reading the page; connection symbols should be classified separately.


---

# The connection vocabulary, read from the symbol library

**Measured** 2026-09-03 on EPLAN 2027.0.1 by reflecting over `SPECIAL_en_US`.
This is authoritative - it comes from the master data, not from inference.

## PinBase.Direction is the missing piece

`Eplan.EplApi.DataModel.PinBase+Directions` = `Undefined | Up | Right | Down | Left`

Every connection point knows which way it FACES. That is what makes
placement-based wiring computable: two pins connect when they are aligned on an
axis AND face each other (one `Down` above one `Up`, or one `Right` left of one
`Left`). Before finding this I was inferring "facing" from coordinates, which is
guesswork.

## Symbol.Type is the category

`Symbol.Type` is an enum of 54 values. The connection-relevant ones, with how
many symbols of each `SPECIAL_en_US` holds:

| Symbol.Type | Count | Purpose |
|---|---:|---|
| `Function` | 29 | devices |
| `Routing` | 1 | **`CO`** - the corner |
| `DynamicRouting` | 1 | the free/diagonal line |
| `TNodeUp` / `TNodeDown` / `TNodeLeft` / `TNodeRight` | 2/1/1/1 | branches |
| `RoutingCross` | 1 | four-way cross |
| `RoutingBridge` | 1 | hop over |
| `InterruptionPoint` | 6 | cross-page jump |
| `ConnectionDefinition` | - | `CDPNG`, `CDPNG2` - wire properties |
| `PotentialTerminal` | 5 | potentials |
| `Shielding` | 2 | shields |
| `CableDefinitionLine` | 1 | cables |

**T-nodes are separate symbol TYPES, not variants of one symbol.** Branching
up/down/left/right means choosing a different symbol type, unlike corners.

## CO variant -> orientation: the four quadrants

| Variant | Pin directions | Turns |
|---|---|---|
| v0 | `Right` + `Down` | east and south |
| v1 | `Right` + `Up` | east and north |
| v2 | `Left` + `Up` | west and north |
| v3 | `Left` + `Down` | west and south |

To turn a corner, place `CO` at the turn and pick the variant whose two
directions match the two legs. Both its connection points sit AT the corner
location (relative 0,0), so the corner is a point, not a segment.

## CDPNG vs CDPNG2

Both are `Symbol.Type = ConnectionDefinition`, both have a single variant v0
with **no connection points at all**. So they are structurally identical, and
the difference between them is presentational - which properties the symbol
displays - not functional. Either can carry a connection's wire number, colour
and cross-section. (125 CDPNG2 vs 67 CDPNG on one page suggests house
convention, not a technical distinction.)

## What this makes buildable

Everything needed for placement-driven wiring is now readable:

    Symbol.Type          -> is this a device, a corner, a T-node, a break?
    PinBase.Direction    -> which way does this connection point face?
    SymbolVariant        -> which orientation of that symbol?

so "place B so its pin faces A's pin" is a calculation, not a guess.

## `live_routing_catalog`, measured

Run against a clone of a production project on 2027.0.1, 7 symbol libraries.
**24 connection symbols, every one of them in `SPECIAL_en_US`** — the six device
libraries hold none:

| `Symbol.Type` | symbols |
| --- | --- |
| `Routing` | `CO` |
| `TNodeUp` | `TLRO`, `TLRO_1` |
| `TNodeDown` | `TLRU` |
| `TNodeLeft` | `TOUL` |
| `TNodeRight` | `TOUR` |
| `RoutingCross` | `CR` |
| `RoutingBridge` | `BR` |
| `DynamicRouting` | `CRL` |
| `InterruptionPoint` | `BP`, `BP2`, `BPOL`, `BPNFPA`, `BPIN`, `BPOUT` |
| `ConnectionDefinition` | `CDPNG2` |
| `PotentialTerminal` | `PCP`, `PCP5`, `PCPOL`, `PDCP2`, `PDCP2OL` |
| `Shielding` | `SH`, `SH2` |
| `CableDefinitionLine` | `CABDL` |

`CO` carries all four corners as variants:

    v0 Right+Down    v1 Right+Up    v2 Left+Up    v3 Left+Down

A branch does NOT work that way. It is a separate `Symbol.Type` per direction —
`TNodeUp` is a different type from `TNodeDown`, not a variant of one type. So
corners are picked by variant and T-nodes by type. That asymmetry is why
selection has to be driven off `Symbol.Type` plus pin directions rather than off
a symbol name.

### Two symbols of the same type, differing only in pin ORDER

The reason the catalog reports ordered directions instead of a sorted set:

    TLRO    v2: Right+Left+Up      TLRO_1  v2: Right+Up+Left
    TLRO    v3: Left+Right+Up      TLRO_1  v3: Left+Up+Right

Both are `TNodeUp`; both face the same three directions. Sorting the directions
would make them look interchangeable. So the catalog matches on the direction
SET, but reports the ORDER, and when more than one symbol matches it returns
them ALL with `ambiguous: true` rather than choosing — which of the two is
correct is a house convention, not something the tool can derive.

Queried live: `directions=["Right","Down"]` → exactly `SPECIAL_en_US/CO` v0.
`directions=["Up","Left","Right"]` → both `TLRO` and `TLRO_1`, flagged ambiguous.

## Placing a corner, measured end to end

### A routing symbol is not a Function

    Function.Create(page, CO v0, ...)  ->  ObjectCreationException:
                                           "S511085Cannot create function."

That message names no cause, and it is the same for every reason a function
cannot be created. The path that works is the generic one:

    SymbolVariant.Create(Page)  ->  Eplan.EplApi.DataModel.SymbolReference
                                    (base: Eplan.EplApi.DataModel.Placement)

`SymbolVariant` offers exactly two Create overloads - `SymbolReference
Create(Page)` and `Void Create(Placement[])`. Neither takes a coordinate, so a
connection symbol is BORN AT (0, 0) and has to be moved:

    locationAfterCreate  {"x": 0.0, "y": 0.0}
    locationWritable     true
    locationAfterMove    {"x": 120.0, "y": 200.0}

Hence two tools rather than one, each refusing the other's input by name:
`live_place_symbol` for devices, `live_place_connection_symbol` for wiring.
Placing a device through `SymbolVariant.Create` would not error - it would
return a bare `SymbolReference` that can carry no device tag and no article,
which is worse than a refusal.

### A corner's two pins coincide

    CO v0 at (120, 200):  pin0 Right offset (0, 0)
                          pin1 Down  offset (0, 0)

Both connection points sit exactly at the placement location, because a corner
IS the turn. That is why one coordinate places it. The direction pair is what
distinguishes the four variants, not the geometry.

### Direction is absolute, and +y is Up

    SL v0 at (120.7, 200):  pin0 Up   offset (0, +6.3)
                            pin1 Down offset (0, -6.3)

`PinBase.Direction` names the page direction the pin faces, and it agrees with
the geometry. It is NOT derivable from the offset - a pin at the top of a
symbol need not face up - so `DumpPlacement` now reports it.

### Variant IS rotation

Measured across `NFPA_symbol_en_US/SL`:

    v0  Up / Down          v4  Up / Down        (mirrored)
    v1  Left / Right       v5  Left / Right
    v2  Down / Up          v6  Down / Up
    v3  Right / Left       v7  Right / Left

So there is no separate rotation parameter to add: 0-3 are the four rotations
and 4-7 their mirrors. v2 is not v0 - the pin ORDER is swapped, which decides
which physical terminal is designation 1.

### Same-direction variants are NOT interchangeable

The important correction. All five `TLRU` variants face Down+Left+Right, but
they put the pins in DIFFERENT PLACES:

    v0  Down (0,0)   Left (0,0)      Right (+3.17, 0)
    v1  Down (0,0)   Right (0,0)     Left  (-3.17, 0)
    v2  Left (0,0)   Right (0,0)     Down  (0, -3.17)
    v3  Right (0,0)  Left (0,0)      Down  (0, -3.17)
    v8  Right (0,0)  Left (0,0)      Down  (0, 0)       <- all three at the vertex

An earlier version of the ambiguity message said these "differ in pin ORDER".
That was wrong, and it mattered: a caller told only that would have assumed any
variant would do. `live_routing_catalog` therefore reports each variant's pin
OFFSETS as well as its directions, and the refusal prints them.

### The proof: a corner is a pass-through, not an endpoint

Built on a scratch page, then `generate_connections`:

    -K1  (SL v0, vertical)    pin1 Down  at (120.65, 228.60)
    CO   v1  Up+Right         pin0 Right at (120.65, 190.50)
                              pin1 Up    at (120.65, 190.50)
    -K2  (SL v1, horizontal)  pin0 Left  at (158.75, 190.50)

    connections on the page: 1
        +-K1[2] -> +-K2[1]   isPlaced=True

ONE connection, and the corner is not either end of it. EPLAN routes the wire
from -K1 down, through the corner, and right into -K2, reporting a single
logical connection between the two devices. So a corner is not a connection
endpoint - it is a hint about the path.

The first attempt at this test produced ZERO connections, because -K2 was
placed with its default vertical variant: its pins faced Up and Down, so
nothing faced the corner's Right pin and the run dead-ended. A connection
symbol only does anything if something faces each of its pins.

### The branch

    TLRU v8 at (120.65, 133.35), all three pins at the vertex
    -K3 (SL v1) to the left, -K4 (SL v1) to the right, -K5 (SL v0) below

    connections on the page: 3
        +-K1[2] -> +-K2[1]     (the corner, from above)
        +-K3[2] -> +-K4[1]     (straight through the T)
        +-K4[1] -> +-K5[1]     (the branch)

All three legs wired, and the PDF export shows the solid junction dot EPLAN
draws at a real T. Note the branch is reported against -K4, not against the
T-node: same rule as the corner - the connection symbol is not an endpoint.
