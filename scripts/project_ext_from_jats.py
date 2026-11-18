#!/usr/bin/env python3
"""Project publisher JATS into the links + in-text citations gold extension, checked against the PDF text layer.

    PY=~/dev/bibr-validation/.venv/bin/python
    $PY scripts/project_ext_from_jats.py --raw ~/dev/jats-eval-2026-10-15/data/raw --ids ids.txt \
        --v1 gold/jats_eval_v1/jats_bs_v1 --out gold/jats_eval_v1_ext/jats_bs_v1 --checks gold/jats_eval_v1_ext_checks

Adds two targets to gold/jats_eval_v1 without changing it. Rules are in gold/jats_eval_v1_ext/README.md.
Output per paper: <out>/<paper_id>.json with paras[], links[], links_optional[], citations[], provenance.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ext_common import URL_RE, host_class, is_furniture, norm_url, repo_key, url_like  # noqa: E402
from project_core_from_jats import Haystack, norm, parse, references, text  # noqa: E402

LABELER = "jats-ext-proj@1"
XLINK = "{http://www.w3.org/1999/xlink}href"
SKIP = {"ref-list", "sub-article"}
# front matter that is page furniture, not content: licence, author list, affiliations, dates
FRONT_FURNITURE = {"permissions", "contrib-group", "contrib", "aff", "history", "pub-date", "journal-meta",
                   "article-categories", "title-group", "kwd-group", "funding-group", "award-group"}
PARA_TAGS = ("p", "td", "th", "title", "caption", "attrib", "def", "term", "meta-value")
DASH_ONLY = re.compile(r"^\s*[-‐-―−]\s*$")


def ancestors(el):
    return [a.tag for a in el.iterancestors()]


def skipped(el) -> bool:
    return any(t in SKIP for t in ancestors(el))


def loc_of(el) -> str:
    anc = ancestors(el)
    if "front" in anc or "front-stub" in anc:
        return "front"
    if "table-wrap" in anc or el.tag in ("td", "th") or "td" in anc or "th" in anc:
        return "table"
    if "fig" in anc:
        return "fig"
    if "fn" in anc or "fn-group" in anc:
        return "fn"
    if "back" in anc:
        return "back"
    return "body"


def sec_title(el) -> str:
    for a in el.iterancestors("sec", "app", "ack", "fn-group", "boxed-text"):
        t = a.find("title")
        if t is not None:
            return text(t)
    return ""


def para_of(el):
    for a in el.iterancestors(*PARA_TAGS):
        return a
    return el.getparent()


def rid_to_bib_id(root) -> dict[str, int]:
    """Same walk as project_core_from_jats.references(): bib_id = ordinal of each <ref> in a <ref-list> with a citation."""
    out, n = {}, 0
    for ref in root.iter("ref"):
        if ref.getparent() is None or ref.getparent().tag != "ref-list":
            continue
        if next(ref.iter("mixed-citation", "element-citation", "citation"), None) is None:
            continue
        n += 1
        if ref.get("id"):
            out[ref.get("id")] = n
    return out


def marker_num(s: str) -> int | None:
    m = re.fullmatch(r"\s*[\[(]?\s*(\d{1,4})[a-z]?\s*[\])]?[,;]?\s*", s or "")
    return int(m.group(1)) if m else None


def project(pid: str, raw_dir: Path, v1_gold: dict) -> tuple[dict, dict]:
    root = parse((raw_dir / "jats.xml").read_bytes())
    hay = Haystack(raw_dir / "paper.pdf")
    am = root.find("front/article-meta")
    own = next((text(e) for e in am.findall("article-id") if e.get("pub-id-type") == "doi"), "") if am is not None else ""
    own_doi = norm_url("doi:" + own) if own else ""
    chk: dict = {"paper_id": pid, "links": Counter(), "citations": Counter(), "unprinted": []}

    paras: dict = {}  # keyed by the lxml element itself: id() of lxml proxies is reused after GC

    def para_id(el) -> int:
        p = para_of(el)
        key = p
        if key not in paras:
            t = text(p)
            paras[key] = {"para_id": len(paras) + 1, "loc": loc_of(p), "sec_title": sec_title(p), "text": t,
                          "printed": bool(hay.has_long(t)) if norm(t) else False}
        return paras[key]["para_id"]

    # ---------------- links ----------------
    links: dict[str, dict] = {}
    optional: set[str] = set()

    def printed(cands: list[str]) -> str | None:
        best = None
        for c in cands:
            if c and norm(c) and norm(c) in hay.n and (best is None or len(norm(c)) > len(norm(best))):
                best = c
        return best

    def add_link(raw: str, el, source: str, href_jats: str = ""):
        u = norm_url(raw)
        if not u:
            return
        if is_furniture(u, own_doi):
            optional.add(u)
            chk["links"]["furniture"] += 1
            return
        loc = loc_of(el)
        if loc == "front" and any(t in FRONT_FURNITURE for t in ancestors(el)):
            optional.add(u)
            chk["links"]["front_furniture"] += 1
            return
        if u in links:
            return
        pid_ = para_id(el)
        links[u] = {"link_id": len(links) + 1, "url": u, "url_raw": raw, "href_jats": href_jats,
                    "repo_key": repo_key(u), "host_class": host_class(u), "loc": loc,
                    "sec_title": sec_title(el), "source": source, "para_id": pid_}
        chk["links"][f"gold_{source}"] += 1

    tagged = []
    for el in root.iter("ext-link", "uri", "self-uri"):
        href = (el.get(XLINK) or "").strip()
        disp = text(el)
        in_skip = skipped(el)
        if in_skip or (el.get("ext-link-type") or "").startswith("pmc:") or el.tag == "self-uri":
            for c in (href, disp):
                if url_like(c):
                    optional.add(norm_url(c))
            chk["links"]["skipped_reflist_or_pmc"] += 1
            continue
        tagged.append(el)
        cands = [c for c in (href, disp) if url_like(c)]
        if href and not url_like(href) and re.match(r"^10\.\d{4,9}/", href):
            cands.append(href)
        best = printed(cands)
        if best is None:
            if href:
                optional.add(norm_url(href))
            kind = "not_printed" if url_like(disp) or not disp else "word_anchored"
            chk["links"][kind] += 1
            if not is_furniture(norm_url(href or disp), own_doi) and loc_of(el) != "front":
                chk["unprinted"].append({"kind": kind, "href": href, "text": disp[:120], "loc": loc_of(el)})
            continue
        add_link(best, el, "tagged", href)

    # every reference DOI / pub-id is optional (a citation, not a content link)
    for ref in root.iter("ref"):
        for pidel in ref.iter("pub-id"):
            if (pidel.get("pub-id-type") or "") == "doi" and text(pidel):
                optional.add(norm_url("doi:" + text(pidel)))
    for b in v1_gold.get("bib", []):
        if b.get("doi"):
            optional.add(norm_url("doi:" + b["doi"]))

    # untagged URLs in running text (tagged links, xrefs and labels removed)
    tagged_set = set(tagged)
    for p in root.iter(*PARA_TAGS):
        if skipped(p) or any(a.tag in PARA_TAGS for a in p.iterancestors()):
            continue
        buf = []
        for node in p.iter():
            if node is not p and (node in tagged_set or any(a in tagged_set for a in node.iterancestors())):
                pass
            elif node.text:
                buf.append(node.text)
            if node is not p and node.tail and not any(a in tagged_set for a in node.iterancestors()):
                buf.append(node.tail)
        s = " ".join(buf)
        for m in URL_RE.finditer(s):
            raw = m.group(0)
            if norm(raw) and norm(raw) in hay.n:
                add_link(raw, p, "regex")
            else:
                chk["links"]["regex_not_printed"] += 1

    optional -= set(links)
    optional.discard("")

    # ---------------- citations ----------------
    rid2bib = rid_to_bib_id(root)
    n_bib = len(v1_gold.get("bib", []))
    assert max(rid2bib.values(), default=0) <= n_bib, f"{pid}: rid ordinal {max(rid2bib.values())} > v1 bib {n_bib}"
    cites = []

    def add_cite(x, bib_id: int, marker: str, expanded: bool):
        pid_ = para_id(x)
        pr = next(p for p in paras.values() if p["para_id"] == pid_)
        scored = pr["loc"] not in ("table", "front") and pr["printed"]
        cites.append({"cite_id": len(cites) + 1, "para_id": pid_, "bib_id": bib_id, "marker": marker,
                      "expanded": expanded, "scored": scored})

    xs = [x for x in root.iter("xref") if x.get("ref-type") == "bibr" and not skipped(x)]
    for k, x in enumerate(xs):
        marker = text(x)
        rids = (x.get("rid") or "").split()
        bids = [rid2bib[r] for r in rids if r in rid2bib]
        if not bids:
            chk["citations"]["unresolved_rid"] += 1
            continue
        for b in bids:
            add_cite(x, b, marker, False)
        # "19–21" inside one xref with one rid
        m = re.fullmatch(r"\s*[\[(]?\s*(\d{1,4})\s*[-‐-―−]\s*(\d{1,4})\s*[\])]?\s*", marker)
        if m and len(bids) == 1:
            n1, n2 = int(m.group(1)), int(m.group(2))
            if 1 < n2 - n1 < 200 and bids[0] + (n2 - n1) <= n_bib:
                for j in range(1, n2 - n1 + 1):
                    add_cite(x, bids[0] + j, marker, True)
                chk["citations"]["expanded_single"] += n2 - n1
        # adjacent xrefs joined by a dash: [3]–[6] or 3–6 tagged as two xrefs
        nxt = x.getnext()
        if (len(bids) == 1 and nxt is not None and nxt.tag == "xref" and nxt.get("ref-type") == "bibr"
                and x.tail is not None and DASH_ONLY.match(x.tail)):
            n1, n2 = marker_num(marker), marker_num(text(nxt))
            b2 = [rid2bib[r] for r in (nxt.get("rid") or "").split() if r in rid2bib]
            if n1 is not None and n2 is not None and len(b2) == 1 and n2 - n1 > 1 and b2[0] - bids[0] == n2 - n1:
                for b in range(bids[0] + 1, b2[0]):
                    add_cite(x, b, f"{marker}–{text(nxt)}", True)
                chk["citations"]["expanded_range"] += b2[0] - bids[0] - 1
            elif n1 is not None and n2 is not None and n2 - n1 > 1:
                chk["citations"]["range_order_mismatch"] += 1

    chk["citations"]["gold"] = len(cites)
    chk["citations"]["scored"] = sum(c["scored"] for c in cites)
    used = {c["para_id"] for c in cites} | {l["para_id"] for l in links.values()}
    gold = {
        "paper_id": pid,
        "paras": [p for p in sorted(paras.values(), key=lambda p: p["para_id"]) if p["para_id"] in used],
        "links": list(links.values()),
        "links_optional": sorted(optional),
        "own_doi": own_doi,
        "citations": cites,
        "provenance": {"labeler": LABELER, "source": "PMC OpenData publisher JATS, checked against the PDF text layer",
                       "v1_bib_count": n_bib},
    }
    chk["links"] = dict(chk["links"])
    chk["citations"] = dict(chk["citations"])
    return gold, chk


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--ids", type=Path, required=True)
    ap.add_argument("--v1", type=Path, required=True, help="v1 gold dir for this set (bib ids)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--checks", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    a.checks.mkdir(parents=True, exist_ok=True)
    ids = [l.strip() for l in a.ids.read_text().splitlines() if l.strip() and not l.startswith("#")]
    fails = 0
    for pid in ids:
        try:
            v1 = json.loads((a.v1 / f"{pid}.json").read_text())
            gold, chk = project(pid, a.raw / pid, v1)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {pid}: {type(e).__name__}: {e}")
            fails += 1
            continue
        (a.out / f"{pid}.json").write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n")
        (a.checks / f"{pid}.json").write_text(json.dumps(chk, indent=1, ensure_ascii=False) + "\n")
        print(f"{pid}: links={len(gold['links'])} optional={len(gold['links_optional'])} "
              f"cites={chk['citations']['gold']} scored={chk['citations']['scored']} unprinted={len(chk['unprinted'])}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
