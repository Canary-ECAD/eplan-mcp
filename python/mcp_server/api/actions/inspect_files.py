r"""
Host-side inspectors for files EPLAN has finished writing.

    pdf_inspect - page count, links/annotations, outline, page labels
    dwg_inspect - layouts, texts, entity counts (DXF natively, DWG via
                  AutoCAD's accoreconsole)

These reads cannot happen inside EPLAN: the artefact is a file EPLAN already
wrote, and eplan_execute_script cannot reference a PDF or DWG reader. Use them
to verify exports - that a "no links" PDF really carries zero GoTo links, that
the outline and page labels match the project's pages, that an exported sheet
carries the page's texts.

Dependencies:
  PDF: PyMuPDF (`pip install pymupdf`), optional. Without it pdf_inspect says
       so instead of returning an empty result.
  DXF: parsed natively (ASCII group-code/value line pairs).
  DWG: binary, no pure-Python reader. Driven through AutoCAD's accoreconsole
       with a generated LISP dumper; without AutoCAD the tool says so and
       names the DXF alternative.
"""

import json
import os
import re
import subprocess
import tempfile
import time

__all__ = ["pdf_inspect", "dwg_inspect"]

ACCORECONSOLE_CANDIDATES = [
    r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe",
    r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe",
]

_MAX_ROWS = 5000


def _scratch_dir(sub: str) -> str:
    root = os.environ.get("EPLAN_MCP_SCRATCH") or os.path.join(
        tempfile.gettempdir(), "eplan_mcp_scratch")
    d = os.path.join(root, sub)
    os.makedirs(d, exist_ok=True)
    return d


# =========================================================== pdf_inspect

def pdf_inspect(path: str, include: list = None, max_pages: int = 500) -> dict:
    r"""
    Read a PDF's structure: page count, per-page link/annotation targets,
    outline (bookmarks), and page labels.

    Args:
        path: PDF file to read.
        include: Any of "pages", "annotations", "outline", "labels", "bytes".
            Default: all of them. Use ["outline"] on a large export to keep the
            response small - a 500-page combined print with annotations is a
            lot of rows.
        max_pages: Cap on per-page rows returned (default 500). page_count is
            always the real count.

    Returns:
        {"success", "path", "byte_length", "page_count", "encrypted",
         "goto_link_count",            # the print-domain assertion, precomputed
                                       # over EVERY page; None if not measured
         "pages": [{"index", "label", "annotations": [{subtype, has_dest,
                    action_s, target_page_index, uri}], "link_count"}],
         "outline": [{title, depth, target_page_index, dest_type}],
         "outline_depth_max", "page_labels": [{page_index, label}]}

    A "no links" export is proven by goto_link_count == 0, which is counted over
    every page regardless of max_pages. Do not read that off the pages array
    instead - a page whose rows were capped would look clean. goto_link_count is
    None when include excluded both "pages" and "annotations", or when any page's
    links could not be read (those pages are in "unmeasured_pages"), i.e. it was
    not fully measured; treating that as 0 would assert something never checked.
    """
    want = set(include or ["pages", "annotations", "outline", "labels", "bytes"])
    # None, not 0: "not measured" must never be mistaken for "none found",
    # which is exactly the assertion this field exists to make.
    out = {"success": False, "path": path, "byte_length": None,
           "page_count": None, "encrypted": None, "goto_link_count": None,
           "unmeasured_pages": [],
           "pages": [], "outline": [], "outline_depth_max": 0,
           "page_labels": [], "truncated": False, "error": None}

    if not os.path.isfile(path):
        out["error"] = "not a file: %s" % path
        return out
    try:
        out["byte_length"] = os.path.getsize(path)
    except Exception as ex:
        out["error"] = "could not stat: %r" % (ex,)
        return out
    if "bytes" not in want:
        out["byte_length"] = None

    try:
        import fitz  # PyMuPDF
    except Exception as ex:
        out["error"] = ("PyMuPDF (fitz) is not importable in the MCP server's "
                        "interpreter: %r. Install it (pip install pymupdf) - "
                        "there is no PDF structure read without it." % (ex,))
        return out

    try:
        doc = fitz.open(path)
    except Exception as ex:
        out["error"] = "could not open as PDF: %r" % (ex,)
        return out

    try:
        out["encrypted"] = bool(doc.is_encrypted)
        out["page_count"] = doc.page_count

        labels = {}
        if "labels" in want:
            for i in range(doc.page_count):
                try:
                    lab = doc[i].get_label()
                except Exception:
                    lab = None
                if lab:
                    labels[i] = lab
            out["page_labels"] = [{"page_index": i, "label": l}
                                  for i, l in sorted(labels.items())]

        # Count GoTo links across EVERY page regardless of max_pages, because
        # "there are no links" is the assertion and a capped scan cannot make it.
        if "annotations" in want or "pages" in want:
            count, unmeasured = 0, []
            for i in range(doc.page_count):
                try:
                    for l in doc[i].get_links():
                        if l.get("kind") in (getattr(fitz, "LINK_GOTO", 1),
                                             getattr(fitz, "LINK_NAMED", 4)):
                            count += 1
                except Exception:
                    unmeasured.append(i)
            # A page that could not be read proves nothing: report the count as
            # not measured rather than letting it read as "no links there".
            out["goto_link_count"] = None if unmeasured else count
            out["unmeasured_pages"] = unmeasured

        if "pages" in want:
            limit = min(doc.page_count, max(0, int(max_pages)))
            out["truncated"] = limit < doc.page_count
            for i in range(limit):
                page = doc[i]
                row = {"index": i, "label": labels.get(i),
                       "annotations": [], "link_count": 0}
                if "annotations" in want:
                    try:
                        links = page.get_links()
                    except Exception as ex:
                        links = []
                        row["error"] = "links unreadable: %r" % (ex,)
                    row["link_count"] = len(links)
                    for l in links:
                        kind = l.get("kind")
                        row["annotations"].append({
                            "subtype": "Link",
                            "kind": int(kind) if kind is not None else None,
                            "has_dest": bool(l.get("page") is not None
                                             and int(l.get("page", -1)) >= 0),
                            "action_s": ("GoTo" if kind == getattr(fitz, "LINK_GOTO", 1)
                                         else "URI" if kind == getattr(fitz, "LINK_URI", 2)
                                         else "Named" if kind == getattr(fitz, "LINK_NAMED", 4)
                                         else "Other"),
                            "target_page_index": l.get("page"),
                            "uri": l.get("uri"),
                        })
                    try:
                        for a in page.annots() or []:
                            row["annotations"].append(
                                {"subtype": a.type[1] if a.type else None,
                                 "kind": None, "has_dest": None,
                                 "action_s": None, "target_page_index": None,
                                 "uri": None})
                    except Exception:
                        pass
                out["pages"].append(row)

        if "outline" in want:
            try:
                toc = doc.get_toc(simple=False) or []
            except Exception:
                toc = []
            for entry in toc[:_MAX_ROWS]:
                depth = entry[0] if entry else None
                title = entry[1] if len(entry) > 1 else None
                target = entry[2] if len(entry) > 2 else None
                dest = entry[3] if len(entry) > 3 else None
                out["outline"].append({
                    "title": title, "depth": depth,
                    # get_toc pages are 1-based; -1 means no destination.
                    "target_page_index": (target - 1) if isinstance(target, int)
                                         and target > 0 else target,
                    "dest_type": (dest or {}).get("kind") if isinstance(dest, dict) else None,
                })
            out["outline_depth_max"] = max(
                [e["depth"] for e in out["outline"] if e["depth"]] or [0])

        out["success"] = True
        return out
    finally:
        try:
            doc.close()
        except Exception:
            pass


# =========================================================== dwg_inspect

# DXF is a stream of (group code, value) LINE PAIRS. Everything below is that
# and nothing more: code 0 starts an entity, 8 is the layer, 1 the text value,
# 10/20 the insertion point, 7 the text style, 410 the layout name.
_DXF_ENTITY = "0"
_DXF_LAYER = "8"
_DXF_TEXT = "1"
_DXF_TEXT_MORE = "3"       # MTEXT continuation chunks precede code 1
_DXF_X = "10"
_DXF_Y = "20"
_DXF_STYLE = "7"
_DXF_LAYOUT = "410"

_UNDERLINE_HINTS = (r"\L", r"%%u", r"\l")

# Code-0 records that structure the file rather than draw anything. Counting
# them as entities makes entity_counts useless for "did the sheet get content".
_DXF_NON_ENTITY = frozenset((
    "SECTION", "ENDSEC", "EOF", "TABLE", "ENDTAB", "BLOCK", "ENDBLK",
    "CLASS", "SEQEND",
))


def _dxf_pairs(path: str):
    # utf-8-sig: a BOM would otherwise glue onto the first group code and drop it.
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        while True:
            code = f.readline()
            if not code:
                return
            value = f.readline()
            if not value:
                return
            yield code.strip(), value.rstrip("\r\n")


def _inspect_dxf(path: str, include: set, layer_filter) -> dict:
    out = {"format": "dxf", "layouts": [], "texts": [], "entity_counts": {},
           "text_total": 0, "truncated": False}
    layouts, counts, texts = [], {}, []
    cur = None
    mtext_chunks = []
    # Only ENTITIES and BLOCKS hold drawn objects; TABLES/OBJECTS records
    # (LAYER, STYLE, DICTIONARY, ...) also start with code 0 and must not count.
    section, want_section_name = None, False

    for code, value in _dxf_pairs(path):
        if want_section_name and code == "2":
            section, want_section_name = value.upper(), False
            continue
        if code == _DXF_ENTITY:
            if cur and cur["kind"] in ("TEXT", "MTEXT"):
                if mtext_chunks:
                    cur["value"] = "".join(mtext_chunks) + (cur.get("value") or "")
                _emit_text(cur, texts, layer_filter, out)
            mtext_chunks = []
            kind = value.upper()
            want_section_name = kind == "SECTION"
            if kind not in _DXF_NON_ENTITY and section in ("ENTITIES", "BLOCKS"):
                counts[kind] = counts.get(kind, 0) + 1
            cur = {"kind": kind, "layout": None, "value": None, "x": None,
                   "y": None, "layer": None, "style": None} \
                if kind in ("TEXT", "MTEXT") else None
            continue
        if cur is None:
            continue
        if code == _DXF_LAYER:
            cur["layer"] = value
        elif code == _DXF_TEXT:
            cur["value"] = value
        elif code == _DXF_TEXT_MORE:
            mtext_chunks.append(value)
        elif code == _DXF_X and cur["x"] is None:
            try:
                cur["x"] = float(value)
            except ValueError:
                pass
        elif code == _DXF_Y and cur["y"] is None:
            try:
                cur["y"] = float(value)
            except ValueError:
                pass
        elif code == _DXF_STYLE:
            cur["style"] = value
        elif code == _DXF_LAYOUT:
            cur["layout"] = value
            if value not in layouts:
                layouts.append(value)

    if cur and cur["kind"] in ("TEXT", "MTEXT"):
        if mtext_chunks:
            cur["value"] = "".join(mtext_chunks) + (cur.get("value") or "")
        _emit_text(cur, texts, layer_filter, out)

    out["layouts"] = layouts
    out["entity_counts"] = dict(sorted(counts.items()))
    if "texts" in include:
        out["texts"] = texts
    return out


def _emit_text(cur, texts, layer_filter, out) -> None:
    out["text_total"] += 1
    if layer_filter and cur.get("layer") and not re.search(
            layer_filter, cur["layer"]):
        return
    if len(texts) >= _MAX_ROWS:
        out["truncated"] = True
        return
    v = cur.get("value") or ""
    texts.append({"layout": cur.get("layout"), "kind": cur["kind"],
                  "value": v, "x": cur.get("x"), "y": cur.get("y"),
                  "layer": cur.get("layer"), "style": cur.get("style"),
                  "underline_hint": any(h in v for h in _UNDERLINE_HINTS)})


_LISP_DUMP = r"""(defun mcp-esc (s / i c out)
  (setq out "" i 1)
  (while (<= i (strlen s))
    (setq c (substr s i 1))
    ; Control characters (tab, CR, LF in drawing text) would break the JSON: blank them.
    (setq out (strcat out (cond ((= c "\"") "\\\"") ((= c "\\") "\\\\")
                                ((< (ascii c) 32) " ") (t c))))
    (setq i (1+ i)))
  out)
(defun mcp-num (e k / p)
  (setq p (cdr (assoc 10 e)))
  (if p (rtos (if (= k 0) (car p) (cadr p)) 2 6) "null"))
(defun c:MCPDUMP ( / f ss n i e out lay kinds k)
  (setq f (open "%OUT%" "w"))
  (write-line "{\"layouts\":[" f)
  ; LAYOUTLIST is not defined in accoreconsole: read the layout dictionary.
  (setq lay '() i 0)
  (foreach x (dictsearch (namedobjdict) "ACAD_LAYOUT")
    (if (= (car x) 3) (setq lay (cons (cdr x) lay))))
  (setq lay (reverse lay))
  (foreach l lay
    (write-line (strcat (if (> i 0) "," "") "\"" (mcp-esc l) "\"") f)
    (setq i (1+ i)))
  (write-line "],\"texts\":[" f)
  (setq ss (ssget "_X" '((0 . "TEXT,MTEXT"))) i 0)
  (if ss
    (repeat (setq n (sslength ss))
      (setq e (entget (ssname ss (setq n (1- n)))))
      (write-line
        (strcat (if (> i 0) "," "")
          "{\"kind\":\"" (cdr (assoc 0 e)) "\""
          ",\"value\":\"" (mcp-esc (cond ((cdr (assoc 1 e))) (""))) "\""
          ",\"layer\":\"" (mcp-esc (cond ((cdr (assoc 8 e))) (""))) "\""
          ",\"style\":\"" (mcp-esc (cond ((cdr (assoc 7 e))) (""))) "\""
          ",\"x\":" (mcp-num e 0)
          ",\"y\":" (mcp-num e 1)
          "}") f)
      (setq i (1+ i))))
  ; Every entity in the drawing, counted by type (not only the texts above).
  (write-line "],\"counts\":{" f)
  (setq ss (ssget "_X") kinds '() i 0)
  (if ss
    (repeat (setq n (sslength ss))
      (setq k (cdr (assoc 0 (entget (ssname ss (setq n (1- n)))))))
      (if (assoc k kinds)
        (setq kinds (subst (cons k (1+ (cdr (assoc k kinds)))) (assoc k kinds) kinds))
        (setq kinds (cons (cons k 1) kinds)))))
  (foreach x kinds
    (write-line (strcat (if (> i 0) "," "") "\"" (mcp-esc (car x)) "\":" (itoa (cdr x))) f)
    (setq i (1+ i)))
  (write-line "}}" f)
  (close f)
  (princ))
(c:MCPDUMP)
"""


def _inspect_dwg(path: str, include: set, layer_filter, timeout_s: int) -> dict:
    out = {"format": "dwg", "layouts": [], "texts": [], "entity_counts": {},
           "text_total": 0, "truncated": False, "error": None,
           "converter": None}

    exe = next((c for c in ACCORECONSOLE_CANDIDATES if os.path.isfile(c)), None)
    if not exe:
        out["error"] = (
            "DWG is a binary format and no reader is available: none of %s "
            "exists, and there is no pure-Python DWG parser. Either install "
            "AutoCAD / ODA File Converter, or export the page as DXF and "
            "inspect that (this tool parses DXF natively)."
            % ", ".join(ACCORECONSOLE_CANDIDATES))
        return out
    out["converter"] = exe

    work = _scratch_dir("dwg_inspect")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dump_path = os.path.join(work, "dump_%s.json" % stamp)
    scr_path = os.path.join(work, "dump_%s.scr" % stamp)
    lsp_path = os.path.join(work, "dump_%s.lsp" % stamp)

    with open(lsp_path, "w", encoding="ascii", errors="replace") as f:
        f.write(_LISP_DUMP.replace("%OUT%", dump_path.replace("\\", "\\\\")))
    with open(scr_path, "w", encoding="ascii", errors="replace") as f:
        f.write('(load "%s")\n' % lsp_path.replace("\\", "/"))

    try:
        proc = subprocess.run([exe, "/i", path, "/s", scr_path],
                              capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        out["error"] = "accoreconsole timed out after %ss" % timeout_s
        return out
    except Exception as ex:
        out["error"] = "accoreconsole failed to start: %r" % (ex,)
        return out

    if not os.path.isfile(dump_path):
        out["error"] = ("accoreconsole ran but wrote no dump. stdout tail: %s"
                        % (proc.stdout or "")[-800:])
        return out

    try:
        with open(dump_path, "r", encoding="utf-8", errors="replace") as f:
            dumped = json.load(f)
    except Exception as ex:
        out["error"] = "dump was not valid JSON: %r" % (ex,)
        return out

    out["layouts"] = dumped.get("layouts") or []
    rows = dumped.get("texts") or []
    out["text_total"] = len(rows)
    counts = dumped.get("counts") or {}
    kept = []
    for r in rows:
        kind = (r.get("kind") or "").upper()
        if layer_filter and r.get("layer") and not re.search(
                layer_filter, r["layer"]):
            continue
        if len(kept) >= _MAX_ROWS:
            out["truncated"] = True
            continue
        v = r.get("value") or ""
        kept.append({"layout": None, "kind": kind, "value": v,
                     "x": r.get("x"), "y": r.get("y"), "layer": r.get("layer"),
                     "style": r.get("style"),
                     "underline_hint": any(h in v for h in _UNDERLINE_HINTS)})
    out["entity_counts"] = dict(sorted(counts.items()))
    if "texts" in include:
        out["texts"] = kept
    return out


def dwg_inspect(path: str, include: list = None, layer_filter: str = None,
                timeout_s: int = 180) -> dict:
    r"""
    Read a DWG or DXF drawing: layout names, TEXT/MTEXT contents with position,
    layer and style, and entity counts by type.

    DXF is parsed natively here. DWG is binary, so it is read by driving
    AutoCAD's accoreconsole with a generated LISP dumper - if AutoCAD is not
    installed the result says so explicitly rather than returning an empty
    drawing, which would read as "the export carried no texts".

    Args:
        path: .dwg or .dxf file.
        include: Any of "texts", "layouts", "entities". Default all. Drop
            "texts" on a dense sheet to keep the response small - text_total is
            reported either way.
        layer_filter: Regex; only texts whose layer matches are returned.
            text_total still counts every text found.
        timeout_s: accoreconsole budget (default 180). DWG only.

    Returns:
        {"success", "path", "format": "dwg"|"dxf", "byte_length",
         "layouts": [name], "text_total",
         "texts": [{layout, kind, value, x, y, layer, style, underline_hint}],
         "entity_counts": {type: n}, "truncated", "error"}

    Limits: entity_counts covers every entity type in both formats. Text
    rows carry "layout" for DXF only (it is None for DWG). DXF layouts are
    the ones that hold entities; an empty paper-space layout is not listed.
    The file is opened by AutoCAD (DWG) or parsed here (DXF), so only pass
    drawings you trust, such as EPLAN's own exports.

    underline_hint flags a text carrying DXF/MTEXT underline markup (\L, %%u).
    EPLAN's own DXF/DWG export drops underline formatting, so this is how a
    post-processing step that re-applies it can be checked.
    """
    want = set(include or ["texts", "layouts", "entities"])
    out = {"success": False, "path": path, "format": None,
           "byte_length": None, "error": None}
    if not os.path.isfile(path):
        out["error"] = "not a file: %s" % path
        return out
    out["byte_length"] = os.path.getsize(path)

    ext = os.path.splitext(path)[1].lower()
    if ext == ".dxf":
        try:
            res = _inspect_dxf(path, want, layer_filter)
        except Exception as ex:
            out["error"] = "DXF parse failed: %r" % (ex,)
            return out
    elif ext == ".dwg":
        res = _inspect_dwg(path, want, layer_filter, timeout_s)
    else:
        out["error"] = "unsupported extension %r - expected .dwg or .dxf" % ext
        return out

    out.update(res)
    if "layouts" not in want:
        out.pop("layouts", None)
    if "entities" not in want:
        out.pop("entity_counts", None)
    out["success"] = not res.get("error")
    return out
