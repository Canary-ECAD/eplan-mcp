"""
EPLAN Data Portal web API (https://dataportal.eplan.com/api/doc), called directly.

These tools talk to the Data Portal over HTTPS and need no running EPLAN. They
complement dataportal.py, which drives the Data Portal add-in inside EPLAN:
that one queues parts in EPLAN's session; this one finds them first.

Two tiers, measured against the live API on 2026-11-19:

- Public, no token: /partscheck, /parts, /parts/{id}, /macros/{id},
  /macro_variants/{id}, /manufacturers, /eplan_catalog_entries,
  /eclass_catalog_entries, /data_types, /standards, /suggestions/*,
  /statistics. This is enough to turn a part number into the Data Portal id
  that eplan_dataportal_add_to_download_list needs, and to see whether a part
  has 3D, DXF, a function template and so on.
- Needs a Personal Access Token: every /download/* and /basketitems route
  (401 "Missing JWT token" without one). The token comes from the environment
  variable EPLAN_DATAPORTAL_PAT, set by a person; it is sent as
  "Authorization: Bearer PAT:<token>" and never returned in a result. A PAT is
  generated in the ePulse user profile, for the Data Portal specifically, and
  cannot belong to the ePulse Community organisation.

Token routes checked live on 2026-11-19 with a real PAT: e3d (5SLx3xx-x_3D.emav0r10.e3d,
171 KB), DXF per part and per download-list item (MAC_<macro>.zip with dxf/<macro>/
Panel layout/*.dxf, commercialdata.csv, readme.txt), commercial-data CSV for one and
several parts, and the download list: list, add, remove (by item id) and back.

Where the published spec is wrong (checked live):
- /parts filters by data type with filter[data_types]=a,b. The documented
  filter[features] is refused with 400 invalid-filter-type.
- filter[catalog_eplan] takes the 9-digit id the catalog endpoints return
  (200070000); the documented 10-digit form with a leading 0 also works.
- filter[manufacturer] takes the short name (SIE, RIT), not the numeric id.
- /partscheck POST takes the search values one per line (text/plain), and
  answers "partscheckmissingresult" for a value it doesn't know (still 200).
- A 3D macro's E3D file is downloaded per macro VARIANT id, which is in
  /macros/{graphic_macro id} -> relationships.macro_variants.
"""

import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("EPLAN_DATAPORTAL_URL", "https://dataportal.eplan.com/api").rstrip("/")
PAT_ENV = "EPLAN_DATAPORTAL_PAT"
TIMEOUT_S = 30.0
USER_AGENT = "eplan-mcp-dataportal/1"

DATA_TYPES = ("commercial_data", "function_template", "logic_macro", "2d_graphical_data",
              "connection_point_pattern", "drilling_pattern", "3d_graphical_data", "dxf_data")
SORT_FIELDS = ("part_number", "order_number", "type_number", "download_count",
               "manufacturer.short_name", "manufacturer.long_name")
_CATALOG_KINDS = {
    "manufacturers": "/manufacturers",
    "eplan_catalog": "/eplan_catalog_entries",
    "eclass_catalog": "/eclass_catalog_entries",
    "data_types": "/data_types",
    "standards": "/standards",
    "suggestions": "/suggestions/combined",
    "statistics": "/statistics",
}

__all__ = [
    "dataportal_api_find_parts",
    "dataportal_api_search_parts",
    "dataportal_api_get_part",
    "dataportal_api_catalog",
    "dataportal_api_download",
    "dataportal_api_download_list",
]


class DataPortalError(Exception):
    def __init__(self, status, message, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


# ------------------------------------------------------------------ transport

def _pat():
    return (os.environ.get(PAT_ENV) or "").strip()


def _no_pat_result(what):
    return {
        "success": False, "errorType": "DataPortalTokenMissing",
        "error": (f"{what} needs a Data Portal Personal Access Token, and {PAT_ENV} is not set "
                  "for the MCP server."),
        "userAction": (
            "A person has to set it: generate a PAT for the Data Portal in the ePulse user profile "
            f"(not for the ePulse Community organisation), put it in the {PAT_ENV} environment "
            "variable of the MCP server (e.g. `claude mcp add ... -e " + PAT_ENV + "=...`) and restart "
            "the server. Never paste the token into the chat."),
    }


def _request(method, path, params=None, body=None, content_type=None, auth=False, raw=False):
    """One HTTP call. Returns parsed JSON, or (bytes, headers) when raw.

    Raises DataPortalError on HTTP errors with the API's own error title."""
    url = BASE_URL + path
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")},
                                       safe="[],")
        if query:
            url += "?" + query
    headers = {"Accept": "application/vnd.api+json, application/json, */*", "User-Agent": USER_AGENT}
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type or "application/vnd.api+json"
        else:
            data = body.encode("utf-8") if isinstance(body, str) else body
            headers["Content-Type"] = content_type or "text/plain"
    if auth:
        headers["Authorization"] = "Bearer PAT:" + _pat()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            payload = resp.read()
            if raw:
                return payload, dict(resp.headers)
            if not payload:
                return {}
            return json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        message = f"HTTP {e.code}"
        try:
            errs = json.loads(text).get("errors") or []
            if errs:
                message += ": " + "; ".join(
                    " - ".join(x for x in (err.get("title"), err.get("detail")) if x) for err in errs)
        except (ValueError, AttributeError):
            if text.strip():
                message += ": " + text.strip()[:300]
        raise DataPortalError(e.code, message, text[:2000])
    except urllib.error.URLError as e:
        raise DataPortalError(None, f"Data Portal not reachable: {e.reason}")


def _fail(e):
    res = {"success": False, "error": str(e)}
    if isinstance(e, DataPortalError) and e.status:
        res["httpStatus"] = e.status
        if e.status == 401:
            res["errorType"] = "DataPortalUnauthorized"
            res["note"] = (f"The token in {PAT_ENV} was refused: it may have expired or not be a "
                           "Data Portal PAT. A person has to renew it.")
    return res


# ------------------------------------------------------------------ shaping

def _lang(value, language):
    """A {"en_US": ..., "de_DE": ...} field in one language (falls back to en_US, then any)."""
    if not isinstance(value, dict):
        return value
    return value.get(language) or value.get("en_US") or next(iter(value.values()), None)


def _ml(text, language):
    """EPLAN's multilanguage string "de_DE@a;en_US@b;" in one language (plain text unchanged)."""
    if not isinstance(text, str) or "@" not in text:
        return text or None
    parts = dict(m.groups() for m in re.finditer(r"([a-z]{2}_[A-Z]{2})@(.*?)(?:;(?=[a-z]{2}_[A-Z]{2}@)|;?$)", text, re.S))
    if not parts:
        return text
    value = parts.get(language) or parts.get("en_US") or next(iter(parts.values()))
    return value.strip() or None


def _rel_id(rels, name):
    data = ((rels or {}).get(name) or {}).get("data")
    if isinstance(data, dict):
        return data.get("id")
    if isinstance(data, list):
        return [d.get("id") for d in data]
    return None


def _web_url(manufacturer, part_number, part_id):
    if not (manufacturer and part_number and part_id):
        return None
    return (f"https://dataportal.eplan.com/part-details/{urllib.parse.quote(manufacturer)}/"
            f"{urllib.parse.quote(part_number)}/id-{part_id}")


def _short_part(item, language):
    a = item.get("attributes") or {}
    rels = item.get("relationships") or {}
    pn = a.get("part_number")
    mfr = a.get("data_supplier") or (pn.split(".", 1)[0] if pn and "." in pn else None)
    return {
        "dataportal_id": item.get("id"),
        "part_number": pn,
        "order_number": a.get("order_number"),
        "type_number": a.get("type_number"),
        "manufacturer": mfr,
        "designation": _lang(a.get("designation"), language),
        "description": _lang(a.get("description"), language),
        "data_types": _rel_id(rels, "data_types") or [],
        "lifecycle": (a.get("lifecycle") or {}).get("name"),
        "eds_compliant": a.get("eds_compliant"),
        "download_count": a.get("download_count"),
        "update_date": a.get("update_date"),
        "url": _web_url(mfr, pn, item.get("id")),
    }


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,\n]", value) if v.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


# ------------------------------------------------------------------ tools

def resolve_ids(values, exact=False):
    """{search value: partscheck hit or None}. Used by dataportal_add_to_download_list."""
    values = _as_list(values)
    params = {"exact": 1 if exact else 0}
    res = _request("POST", "/partscheck", params=params, body="\n".join(values))
    found = {v: None for v in values}
    for item in res.get("data") or []:
        a = item.get("attributes") or {}
        if item.get("type") == "partscheckresult" and a.get("search") in found and found[a["search"]] is None:
            found[a["search"]] = a
    return found


def dataportal_api_find_parts(search, exact: bool = False, allow_multiple_results: bool = False) -> dict:
    """
    Look parts up on EPLAN Data Portal by part number, type number or order number. No EPLAN, no token.

    Read-only, over the Data Portal web API. Use it to check that parts exist
    and to get their Data Portal id (needed by eplan_dataportal_add_to_download_list)
    and web address. One call takes many values; each comes back as found or missing.

    Args:
        search: one value or a list, e.g. ["SIE.5SL6316-7", "9343210"]. A full EPLAN part
            number (MFR.TYPE), a bare type number or an order number all work.
        exact: True = case sensitive and no trimming (default off).
        allow_multiple_results: True = return every part matching a value (a bare
            order number is often shared by several manufacturers); default the best one.

    Returns:
        {"success", "found": [{"search", "dataportal_id", "part_number", "type_number",
        "order_number", "manufacturer", "upload_date", "url"}], "missing": [values]}
    """
    values = _as_list(search)
    if not values:
        return {"success": False, "error": "No search value given."}
    params = {"exact": 1 if exact else 0,
              "allow_multiple_results": "true" if allow_multiple_results else None}
    try:
        res = _request("POST", "/partscheck", params=params, body="\n".join(values))
    except DataPortalError as e:
        return _fail(e)
    found, missing, seen = [], [], set()
    for item in res.get("data") or []:
        a = item.get("attributes") or {}
        if item.get("type") == "partscheckresult":
            key = (a.get("search"), a.get("partid"))
            if key in seen:
                continue    # the API repeats a hit that matches on several numbers
            seen.add(key)
            found.append({
                "search": a.get("search"), "dataportal_id": str(a.get("partid")),
                "part_number": a.get("partnr"), "type_number": a.get("typenr"),
                "order_number": a.get("ordernr"), "manufacturer": a.get("data_supplier"),
                "upload_date": a.get("upload_date"), "url": a.get("url"),
            })
        else:
            missing.append(a.get("search"))
    return {"success": True, "found": found, "missing": missing}


def dataportal_api_search_parts(search: str = "", manufacturer: str = "", data_types=None,
                                catalog_eplan: str = "", catalog_eclass: str = "",
                                eds_min_version: int = None, sort: str = "",
                                offset: int = 0, limit: int = 10, language: str = "en_US") -> dict:
    """
    Full-text search of EPLAN Data Portal parts, with filters. No EPLAN, no token.

    Read-only, over the Data Portal web API. For a known part number prefer
    dataportal_api_find_parts (exact, many at once).

    Args:
        search: free text, max 100 characters (e.g. "5SL6316", "contactor 24V").
        manufacturer: manufacturer SHORT name, e.g. "SIE", "RIT", "PXC". Get it from
            dataportal_api_catalog(kind="suggestions", search="siemens").
        data_types: only parts that have all of these, from: commercial_data,
            function_template, logic_macro, 2d_graphical_data, connection_point_pattern,
            drilling_pattern, 3d_graphical_data, dxf_data. E.g. ["3d_graphical_data"].
        catalog_eplan: EPLAN product group id from dataportal_api_catalog(kind="eplan_catalog").
        catalog_eclass: ECLASS id.
        eds_min_version: only parts at or above this EPLAN Data Standard level.
        sort: one of part_number, order_number, type_number, download_count,
            manufacturer.short_name, manufacturer.long_name; prefix "-" for descending.
        offset, limit: paging (limit max 100).
        language: en_US, de_DE, fr_FR, es_ES... for designation/description.

    Returns:
        {"success", "total", "offset", "limit", "parts": [{"dataportal_id", "part_number",
        "manufacturer", "designation", "description", "data_types", "url", ...}]}
    """
    if sort and sort.lstrip("-") not in SORT_FIELDS:
        return {"success": False, "error": f"sort must be one of {', '.join(SORT_FIELDS)} (optionally with '-')."}
    types = _as_list(data_types)
    bad = [t for t in types if t not in DATA_TYPES]
    if bad:
        return {"success": False, "error": f"Unknown data_types {bad}; valid: {', '.join(DATA_TYPES)}."}
    if search and len(search) > 100:
        return {"success": False, "error": "search is limited to 100 characters by the Data Portal."}
    if not (search or manufacturer or types or catalog_eplan or catalog_eclass):
        return {"success": False, "error": "Give at least a search text or one filter."}
    params = {
        "search": search or None,
        "sort": sort or None,
        "page[offset]": max(0, int(offset or 0)),
        "page[limit]": min(100, max(1, int(limit or 10))),
        "filter[manufacturer]": manufacturer or None,
        "filter[data_types]": ",".join(types) or None,
        "filter[catalog_eplan]": catalog_eplan or None,
        "filter[catalog_eclass]": catalog_eclass or None,
    }
    if eds_min_version is not None:
        params["filter[eplan_data_standard][ge]"] = int(eds_min_version)
    try:
        res = _request("GET", "/parts", params=params)
    except DataPortalError as e:
        return _fail(e)
    page = (res.get("meta") or {}).get("page") or {}
    return {"success": True, "total": page.get("total"), "offset": page.get("offset"),
            "limit": page.get("limit"),
            "parts": [_short_part(item, language) for item in res.get("data") or []]}


def _macro(macro_id, language="en_US"):
    if not macro_id:
        return None
    data = _request("GET", f"/macros/{urllib.parse.quote(str(macro_id))}").get("data") or {}
    rels = data.get("relationships") or {}
    variants = []
    for vid in _rel_id(rels, "macro_variants") or []:
        try:
            vres = _request("GET", f"/macro_variants/{urllib.parse.quote(str(vid))}").get("data")
            v = (vres[0] if isinstance(vres, list) and vres else vres) or {}
            va = v.get("attributes") or {}
            variants.append({"macro_variant_id": vid, "representation_type": va.get("representation_type"),
                             "variant": va.get("variant"), "name": _ml(va.get("name"), language),
                             "description": _ml(va.get("description"), language)})
        except DataPortalError:
            variants.append({"macro_variant_id": vid})
    return {"macro_id": str(macro_id), "name": (data.get("attributes") or {}).get("name"),
            "file": _rel_id(rels, "preview"), "variants": variants}


def dataportal_api_get_part(part_id: str = "", part_number: str = "", include_macros: bool = True,
                            language: str = "en_US") -> dict:
    """
    Details of one EPLAN Data Portal part: texts, groups, data types, macros. No EPLAN, no token.

    Read-only. Give the Data Portal id, or a part number (resolved with
    /partscheck first). With include_macros the graphic macro (3D) and group
    symbol macro (2D) are expanded with their macro variants: a variant id with
    representation_type 10 (3D) is what dataportal_api_download(kind="e3d") takes.

    Args:
        part_id: Data Portal id, e.g. "454767".
        part_number: alternative to part_id, e.g. "SIE.5SL6316-7".
        include_macros: also fetch macro names and variant ids (2-4 extra requests).
        language: en_US, de_DE, fr_FR, es_ES... for the texts.

    Returns:
        {"success", "part": {..., "product_top_group", "product_group", "product_sub_group",
        "graphic_macro_path", "group_symbol_macro_path", "accessories", "eds_version", ...},
        "manufacturer": {...}, "graphic_macro": {...}, "group_symbol_macro": {...}}
    """
    pid = str(part_id or "").strip()
    try:
        if not pid:
            if not part_number:
                return {"success": False, "error": "Give part_id or part_number."}
            hit = resolve_ids([part_number]).get(part_number.strip())
            if not hit:
                return {"success": False, "errorType": "PartNotFound",
                        "error": f"{part_number!r} is not on Data Portal."}
            pid = str(hit["partid"])
        if not pid.isdigit():
            return {"success": False, "error": f"part_id must be the numeric Data Portal id, got {pid!r}."}
        res = _request("GET", f"/parts/{pid}", params={"include": "manufacturer"})
        item = res.get("data") or {}
        a = item.get("attributes") or {}
        rels = item.get("relationships") or {}
        part = _short_part(item, language)
        part.update({
            "languages": a.get("languages"),
            "part_type": a.get("part_type"),
            "version": a.get("version"),
            "identcode": a.get("identcode"),
            "basketable": a.get("basketable"),
            "deviceplaceable": a.get("deviceplaceable"),
            "eds_version": a.get("eds_version"),
            "graphic_macro_path": a.get("graphic_macro_path") or None,
            "group_symbol_macro_path": a.get("group_symbol_macro_path") or None,
            "product_top_group": _rel_id(rels, "product_top_group"),
            "product_group": _rel_id(rels, "product_group"),
            "product_sub_group": _rel_id(rels, "product_sub_group"),
            "eclass": [x for x in (_rel_id(rels, f"eclass_level{i}") for i in range(1, 5)) if x],
            "accessories": _rel_id(rels, "accessories") or [],
            "dependent_parts": _rel_id(rels, "dependent_parts") or [],
            "variants": _rel_id(rels, "variants") or [],
        })
        out = {"success": True, "part": part}
        for inc in res.get("included") or []:
            if inc.get("type") == "manufacturers":
                out["manufacturer"] = dict(inc.get("attributes") or {}, id=inc.get("id"))
        if include_macros:
            out["graphic_macro"] = _macro(_rel_id(rels, "graphic_macro"), language)
            out["group_symbol_macro"] = _macro(_rel_id(rels, "group_symbol_macro"), language)
        return out
    except DataPortalError as e:
        return _fail(e)


def dataportal_api_catalog(kind: str, search: str = "", parent: str = "", limit: int = 50,
                           language: str = "en_US") -> dict:
    """
    EPLAN Data Portal reference lists: manufacturers, product groups, data types... No EPLAN, no token.

    Read-only. Use it to find the codes dataportal_api_search_parts filters on.

    Args:
        kind: "suggestions" (search text -> manufacturer short names and words, e.g.
            search="siemens" -> SIE), "manufacturers", "eplan_catalog" (EPLAN product
            groups; pass parent=<id> for the children of a group), "eclass_catalog",
            "data_types", "standards", or "statistics" (portal totals).
        search: text for suggestions (required there) and for filtering manufacturers.
        parent: catalog id whose children to list (eplan_catalog / eclass_catalog).
        limit: max entries returned (counts still cover all).

    Returns:
        {"success", "kind", "entries": [{"id", "name"/..., "count"}]} or, for
        suggestions/statistics, the API's attributes as they are.
    """
    path = _CATALOG_KINDS.get(kind)
    if not path:
        return {"success": False, "error": f"kind must be one of {', '.join(_CATALOG_KINDS)}."}
    if kind == "suggestions" and not search:
        return {"success": False, "error": "suggestions needs a search text."}
    params = {"search": search or None}
    if parent and kind in ("eplan_catalog", "eclass_catalog"):
        params["filter[catalog_eplan]" if kind == "eplan_catalog" else "filter[catalog_eclass]"] = parent
    try:
        res = _request("GET", path, params=params)
    except DataPortalError as e:
        return _fail(e)
    data = res.get("data")
    if kind in ("suggestions", "statistics"):
        attrs = dict((data or {}).get("attributes") or {})
        if kind == "statistics":
            # The per-manufacturer table is 600+ lines; keep the totals.
            attrs.pop("eds_count_per_manufacturer", None)
            attrs.pop("manufacturers_sprites_url", None)
        return {"success": True, "kind": kind, "result": attrs}
    counts = {}
    for facet in ((res.get("meta") or {}).get("facets_counts") or {}).values():
        for c in (facet or {}).get("data") or []:
            counts[str(c.get("id"))] = c.get("count")
    entries = []
    for item in data or []:
        attrs = item.get("attributes") or {}
        entry = {"id": item.get("id")}
        for k, v in attrs.items():
            if k in ("logo_url",):
                continue
            entry[k] = _lang(v, language)
        if str(item.get("id")) in counts:
            entry["count"] = counts[str(item.get("id"))]
        entries.append(entry)
    total = len(entries)
    return {"success": True, "kind": kind, "total": total, "entries": entries[:max(1, int(limit or 50))],
            "truncated": total > int(limit or 50)}


def _filename(headers, fallback):
    cd = ""
    for k, v in (headers or {}).items():
        if k.lower() == "content-disposition":
            cd = v
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd or "")
    name = urllib.parse.unquote(m.group(1)) if m else fallback
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", os.path.basename(name)) or fallback


def _default_out_dir():
    root = os.environ.get("EPLAN_MCP_SCRATCH") or os.path.join(tempfile.gettempdir(), "eplan_mcp_scratch")
    return os.path.join(root, "dataportal")


def dataportal_api_download(kind: str, part_ids=None, macro_variant_id: str = "",
                            basket_item_ids=None, from_download_list: bool = False,
                            out_dir: str = "") -> dict:
    """
    Download a file from EPLAN Data Portal: 3D (E3D), DXF or commercial data CSV. Needs EPLAN_DATAPORTAL_PAT.

    Saves the file locally and returns its path; it does NOT import anything
    into EPLAN (eplan_import_3d takes an .e3d, eplan_import_dxf_page a .dxf). To
    get a part with its macros into the parts database use
    eplan_dataportal_add_to_download_list, which goes through EPLAN.

    Args:
        kind: "e3d" (needs macro_variant_id), "dxf" or "commercial_data".
        part_ids: Data Portal part ids (dxf / commercial_data), one or many.
        macro_variant_id: for e3d, a 3D macro variant id from dataportal_api_get_part
            (graphic_macro.variants[].macro_variant_id).
        basket_item_ids: dxf / commercial_data for these download-list item ids.
        from_download_list: dxf / commercial_data for the user's whole download list.
        out_dir: folder to save into (default: <EPLAN_MCP_SCRATCH or %TEMP%\\eplan_mcp_scratch>\\dataportal).

    Returns:
        {"success", "path", "bytes", "content_type"}. Several DXFs come as one zip.
    """
    if kind not in ("e3d", "dxf", "commercial_data"):
        return {"success": False, "error": "kind must be e3d, dxf or commercial_data."}
    if not _pat():
        return _no_pat_result("Downloading from the Data Portal")
    ids = _as_list(part_ids)
    items = _as_list(basket_item_ids)
    if kind == "e3d":
        vid = str(macro_variant_id or "").strip()
        if not vid.isdigit():
            return {"success": False, "error": "e3d needs a numeric macro_variant_id (see dataportal_api_get_part)."}
        call, fallback = ("GET", f"/download/e3d_data/{vid}", None), f"{vid}.e3d"
    else:
        route = "dxf_data" if kind == "dxf" else "commercial_data"
        ext = ".zip" if kind == "dxf" else ".csv"
        chosen = sum(bool(x) for x in (ids, items, from_download_list))
        if chosen != 1:
            return {"success": False,
                    "error": "Give exactly one of part_ids, basket_item_ids or from_download_list=True."}
        if any(not x.isdigit() for x in ids + items):
            return {"success": False, "error": "Ids must be numeric Data Portal ids."}
        if from_download_list:
            call = ("GET", f"/download/{route}/basket", None)
        elif items:
            call = ("POST", f"/download/{route}/basket", ",".join(items))
        elif len(ids) == 1:
            call = ("GET", f"/download/{route}/part/{ids[0]}", None)
        else:
            call = ("POST", f"/download/{route}/part", ",".join(ids))
        fallback = f"{route}{ext}"
    try:
        payload, headers = _request(call[0], call[1], body=call[2], auth=True, raw=True)
    except DataPortalError as e:
        return _fail(e)
    folder = out_dir or _default_out_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, _filename(headers, fallback))
    # The portal names every commercial-data CSV "commercial_data.csv": never overwrite.
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        n += 1
        path = f"{stem}_{n}{ext}"
    with open(path, "wb") as f:
        f.write(payload)
    ctype = next((v for k, v in headers.items() if k.lower() == "content-type"), None)
    return {"success": True, "path": path, "bytes": len(payload), "content_type": ctype}


def dataportal_api_download_list(action: str = "list", parts=None, item_ids=None) -> dict:
    """
    Read or change the user's EPLAN Data Portal download list over the web API. Needs EPLAN_DATAPORTAL_PAT.

    This is the account's download list (basket), the one EPLAN's Data Portal
    window shows when signed in to the same account. Adding here does not
    import anything: the user still downloads the list in EPLAN. Without a PAT
    use eplan_dataportal_add_to_download_list (through EPLAN's own sign-in).

    Args:
        action: "list", "add" or "remove".
        parts: for add: [{"dataportal_id": "454767", "count": 1, "description": "..."}]
            or plain part numbers / ids, which are resolved with /partscheck.
        item_ids: for remove: download-list item ids (from action="list"), not part ids.

    Returns:
        list: {"success", "items": [{"item_id", "count", "description", "dataportal_id",
        "part_number"}], "inactive_parts"}; add/remove: {"success", ...}.
    """
    if action not in ("list", "add", "remove"):
        return {"success": False, "error": "action must be list, add or remove."}
    if not _pat():
        return _no_pat_result("The Data Portal download list over the web API")
    try:
        if action == "list":
            res = _request("GET", "/basketitems", params={"include": "part"}, auth=True)
            parts_by_id = {i.get("id"): i.get("attributes") or {} for i in res.get("included") or []
                           if i.get("type") == "parts"}
            items = []
            for item in res.get("data") or []:
                a = item.get("attributes") or {}
                pid = _rel_id(item.get("relationships"), "part")
                items.append({"item_id": item.get("id"), "count": a.get("count"),
                              "description": a.get("description"), "dataportal_id": pid,
                              "part_number": (parts_by_id.get(pid) or {}).get("part_number")})
            return {"success": True, "items": items,
                    "inactive_parts": (res.get("meta") or {}).get("inactive_parts") or {}}
        if action == "remove":
            ids = _as_list(item_ids)
            if not ids:
                return {"success": False, "error": "remove needs item_ids (from action='list')."}
            _request("DELETE", "/basketitems", body={"data": [{"type": "basketitems", "id": i} for i in ids]},
                     auth=True)
            return {"success": True, "removed": ids}
        # add
        wanted, lookups = [], []
        for p in parts or []:
            if isinstance(p, dict):
                pid = str(p.get("dataportal_id") or "").strip()
                entry = {"count": int(p.get("count") or 1), "description": p.get("description") or ""}
                if pid.isdigit():
                    wanted.append(dict(entry, id=pid))
                elif p.get("part_number"):
                    lookups.append((str(p["part_number"]).strip(), entry))
                else:
                    return {"success": False, "error": f"Part needs dataportal_id or part_number: {p!r}"}
            else:
                s = str(p).strip()
                if s.isdigit():
                    wanted.append({"id": s, "count": 1, "description": ""})
                elif s:
                    lookups.append((s, {"count": 1, "description": ""}))
        missing = []
        if lookups:
            hits = resolve_ids([pn for pn, _ in lookups])
            for pn, entry in lookups:
                hit = hits.get(pn)
                if hit:
                    wanted.append(dict(entry, id=str(hit["partid"])))
                else:
                    missing.append(pn)
        if missing:
            return {"success": False, "errorType": "PartNotFound", "missing": missing,
                    "error": "Not on Data Portal, nothing was added: " + ", ".join(missing)}
        if not wanted:
            return {"success": False, "error": "add needs parts."}
        body = {"data": [{"type": "basketitems",
                          "attributes": {"count": w["count"], "description": w["description"]},
                          "relationships": {"part": {"data": {"id": w["id"], "type": "parts"}}}}
                         for w in wanted]}
        res = _request("POST", "/basketitems", body=body, auth=True)
        return {"success": True, "added": [w["id"] for w in wanted],
                "item_ids": [d.get("id") for d in (res.get("data") or []) if isinstance(d, dict)],
                "userAction": ("Parts are in the Data Portal download list of the account. To import "
                               "them, the user opens Data Portal in EPLAN (same account), goes to the "
                               "download list and downloads it.")}
    except DataPortalError as e:
        res = _fail(e)
        if isinstance(e, DataPortalError) and e.status == 409:
            res["note"] = "The download list is full (Data Portal's maximum size)."
        return res
