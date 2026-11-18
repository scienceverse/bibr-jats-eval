#!/usr/bin/env python3
"""Turn one system's output into the neutral view score_ext.py reads.

    view = {"urls": [{"href", "text", "in_ref_list"}],
            "citations": [{"ctx_left", "ctx_right", "marker", "bib_idx"}],   # bib_idx: 0-based index into the
            "bib_json": <path or None>}                                       # system's own bib list, or None

Adapters: bibr JSON (schema 1.x: text/url/xref/bib) and GROBID TEI (<ref type="bibr">, <ptr>, <ref type="url">).
The GROBID view also regex-scans its TEI text for URLs (outside listBibl), the way a GROBID user would.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ext_common import URL_RE  # noqa: E402

CTX = 80
TEI = "{http://www.tei-c.org/ns/1.0}"
XMLID = "{http://www.w3.org/XML/1998/namespace}id"


def bibr_view(data: dict) -> dict:
    texts = data.get("text") or []
    # stitch text items of one paragraph so citation context crosses item boundaries
    para_of, buf, off = {}, {}, {}
    for t in texts:
        key = t.get("paragraph_id") if t.get("paragraph_id") is not None else ("t", t["text_id"])
        s = buf.get(key, "")
        if s:
            s += " "
        off[t["text_id"]] = len(s)
        buf[key] = s + (t.get("text") or "")
        para_of[t["text_id"]] = key
    bib_text_ids = {b.get("text_id") for b in data.get("bib") or [] if b.get("text_id") is not None}
    bib_pos = {b.get("bib_id"): i for i, b in enumerate(data.get("bib") or [])}
    urls = [{"href": u.get("href") or "", "text": u.get("link_text") or "",
             "in_ref_list": u.get("text_id") in bib_text_ids} for u in data.get("url") or []]
    cites, seen = [], set()
    for x in data.get("xref") or []:
        if x.get("xref_type") != "bib":
            continue
        tid = x.get("text_id")
        if tid not in para_of or tid in bib_text_ids:
            continue
        s = buf[para_of[tid]]
        a, b = off[tid] + (x.get("start") or 0), off[tid] + (x.get("end") or 0)
        cites.append({"ctx_left": s[max(0, a - CTX):a], "ctx_right": s[b:b + CTX], "marker": x.get("contents") or s[a:b],
                      "bib_idx": bib_pos.get(x.get("target_id"))})
    return {"urls": urls, "citations": cites}


def _flatten(el, out: list, refs: list):
    """Depth-first text of a TEI element; records (start, end, ref element) for every <ref>."""
    if el.text:
        out.append(el.text)
    for ch in el:
        tag = ch.tag.replace(TEI, "") if isinstance(ch.tag, str) else ""
        start = sum(map(len, out))
        _flatten(ch, out, refs)
        if tag == "ref":
            refs.append((start, sum(map(len, out)), ch))
        if ch.tail:
            out.append(ch.tail)


def grobid_view(tei_path: Path) -> dict:
    from lxml import etree
    root = etree.parse(str(tei_path)).getroot()
    lb = root.find(f".//{TEI}listBibl")
    pos = {}
    if lb is not None:
        for i, bs in enumerate(lb.iter(f"{TEI}biblStruct")):
            if bs.get(XMLID):
                pos[bs.get(XMLID)] = i
    in_lb = set(lb.iter()) if lb is not None else set()  # elements, not id(): lxml proxy ids are reused
    urls, cites = [], []
    for e in root.iter(f"{TEI}ptr", f"{TEI}ref"):
        if e.tag == f"{TEI}ref" and e.get("type") != "url":
            continue
        if e.get("target"):
            urls.append({"href": e.get("target"), "text": "".join(e.itertext()), "in_ref_list": e in in_lb})
    blocks = [b for b in root.iter(f"{TEI}p", f"{TEI}head", f"{TEI}cell", f"{TEI}note", f"{TEI}figDesc", f"{TEI}item")
              if b not in in_lb and not any(a.tag in (f"{TEI}p", f"{TEI}cell", f"{TEI}note", f"{TEI}figDesc")
                                                for a in b.iterancestors())]
    tagged = {u["href"] for u in urls}
    for b in blocks:
        out, refs = [], []
        _flatten(b, out, refs)
        s = "".join(out)
        for a, z, r in refs:
            if r.get("type") != "bibr":
                continue
            tgt = (r.get("target") or "").lstrip("#")
            cites.append({"ctx_left": s[max(0, a - CTX):a], "ctx_right": s[z:z + CTX], "marker": s[a:z],
                          "bib_idx": pos.get(tgt) if tgt else None})
        # mask tagged url refs so the untagged scan does not re-find their (line-broken) text as fragments
        masked = list(s)
        for a, z, r in refs:
            if r.get("type") == "url":
                masked[a:z] = " " * (z - a)
        for m in URL_RE.finditer("".join(masked)):
            if m.group(0) not in tagged:
                urls.append({"href": m.group(0), "text": "", "in_ref_list": False})
    return {"urls": urls, "citations": cites}


def load_view(path: Path, kind: str) -> dict:
    if kind == "bibr":
        return bibr_view(json.loads(path.read_text()))
    if kind == "grobid":
        return grobid_view(path)
    raise ValueError(kind)
