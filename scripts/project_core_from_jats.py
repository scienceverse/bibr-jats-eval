#!/usr/bin/env python3
"""Project publisher JATS into gold/core-format gold, checked against the PDF text layer.

    PY=.venv/bin/python
    $PY scripts/project_core_from_jats.py --raw ~/dev/jats-eval-2026-10-15/data/raw --ids ids.txt \
        --out gold/jats_eval_v1 --checks gold/jats_eval_v1_checks

Per paper the raw dir holds paper.pdf + jats.xml (same PMC OpenData version). Output:
  <out>/<paper_id>.json      gold in the bibr v10 shape evaluation.evaluate reads (info.title/doi/file_name/keywords/
                             abstract, author[] with given/family/affiliation/email/orcid/corresponding, bib[]).
  <checks>/<paper_id>.json   per-field JATS-vs-PDF agreement, and what was dropped.

JATS is publisher markup, not "as printed". Every gold value is looked up in the PDF text layer (pypdfium2) after
normalisation (NFKC, accents stripped, lowercase, every non-alphanumeric removed, so line breaks, hyphenation and
spacing do not matter); a value that is not found exactly is retried with rapidfuzz partial_ratio >= 90 (abstract:
>= 85% of its 40-char chunks found). Scope: title, authors, abstract, keywords and affiliations are looked up on
pages 1-2 (affiliations also anywhere, recorded separately); each reference's fields are looked up within +-500
normalised characters of that reference's own anchor (its title, else its DOI, else first surname + year), so short
values (years, volumes, pages, surnames) are not "found" elsewhere in the paper. Policy:
  - reference DOI not printed            -> dropped from gold (publishers add Crossref DOIs the PDF never shows)
  - reference last page abbreviated in JATS ("437-43") or not printed -> last page dropped, first page kept
  - reference page with an "Article"/"p." prefix -> prefix stripped; a DOI tagged as a page -> dropped
  - reference title/container/volume/pages/year not printed -> that field dropped from that reference
  - reference author surname not printed -> trimmed from that reference's author list (all missing: list dropped)
  - article DOI not printed              -> info.doi = "" (the scorer then excludes doi_match for the paper)
  - author ORCID not in the text layer   -> dropped (most PDFs print ORCIDs only as a linked icon)
  - keyword not printed in a "Keywords" block (anywhere in the PDF) -> dropped (e.g. Nature Communications and
    eLife subject terms, which the PDF never prints as keywords); none left -> no keywords field
  - title / author family / abstract / keyword (p1-2) / affiliation not printed on pages 1-2 -> kept, flagged
The checks feed the per-field disagreement rates in registry/jats_eval_v1/README.md.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import pypdfium2 as pdfium
from lxml import etree
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from refsets.jats import fields_from_jats  # noqa: E402

LABELER = "jats-core-proj@1"


def norm(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.lower().replace("ß", "ss")
    return re.sub(r"[^0-9a-z]", "", s)


def text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def text_wo(el, drop=("xref", "fn", "label", "tex-math")) -> str:
    """Element text without footnote markers / labels / LaTeX alternatives (cloned so the tree is untouched)."""
    if el is None:
        return ""
    el = etree.fromstring(etree.tostring(el))
    for d in list(el.iter(*drop)):
        if d is el:
            continue
        tail = d.tail
        parent = d.getparent()
        prev = d.getprevious()
        if tail:
            if prev is not None:
                prev.tail = (prev.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
        parent.remove(d)
    return text(el)


class Haystack:
    def __init__(self, pdf: Path):
        doc = pdfium.PdfDocument(str(pdf))
        pages = []
        for i in range(len(doc)):
            pages.append(doc[i].get_textpage().get_text_range())
        doc.close()
        self.page_n = [norm(re.sub(r"-\s*\n\s*", "-", p)) for p in pages]
        self.n = "".join(self.page_n)
        self.front = "".join(self.page_n[:2])  # front matter is checked on pages 1-2 only
        # keyword blocks: 800 normalised chars after each "Keywords" / "Key words" / "Index terms" label, wherever
        # it is printed (eLife and Nature Communications print none; their JATS subject terms are not keywords)
        self.kw_zone = "|".join(self.n[m.end():m.end() + 800] for m in re.finditer(r"keywords?|keyterms|indexterms",
                                                                                   self.n))
        self.pages = len(pages)

    def has(self, value: str | None, fuzzy: bool = True, cutoff: float = 90, scope: str | None = None) -> bool | None:
        hay = self.n if scope is None else scope
        v = norm(value)
        if not v:
            return None
        if v in hay:
            return True
        if not fuzzy or len(v) < 12:
            return False
        return fuzz.partial_ratio(v, hay, score_cutoff=cutoff) > 0

    def has_long(self, value: str, chunk: int = 40, need: float = 0.85, scope: str | None = None) -> bool | None:
        hay = self.n if scope is None else scope
        v = norm(value)
        if not v:
            return None
        if v in hay:
            return True
        chunks = [v[i:i + chunk] for i in range(0, len(v) - chunk + 1, chunk)] or [v]
        return sum(c in hay for c in chunks) / len(chunks) >= need

    def locate_refs(self, bib: list[dict]) -> list[tuple[int, str] | None]:
        """(position, anchor kind) of each reference in the normalised text, or None.

        Anchors, in order: the reference's title (first 60 normalised chars, last occurrence), its DOI (last
        occurrence), then its first surname followed by its year within 300 chars, searched only from 3000 chars
        before the earliest title/DOI-anchored reference.
        """
        out: list[tuple[int, str] | None] = []
        for b in bib:
            pos = None
            t = norm(b.get("title"))[:60]
            if len(t) >= 15 and (i := self.n.rfind(t)) >= 0:
                pos = (i, "title")
            elif (d := norm(b.get("doi"))) and (i := self.n.rfind(d)) >= 0:
                pos = (i, "doi")
            out.append(pos)
        anchored = [p[0] for p in out if p]
        start = max(0, min(anchored) - 3000) if anchored else 0
        for k, b in enumerate(bib):
            if out[k] or not b.get("authors") or not b.get("year"):
                continue
            fam, year = norm(b["authors"][0]["family"]), b["year"]
            if len(fam) < 2:
                continue
            i = self.n.find(fam, start)
            while i >= 0:
                if year in self.n[i:i + 300]:
                    out[k] = (i, "surname+year")
                    break
                i = self.n.find(fam, i + 1)
        return out


def parse(xml: bytes) -> etree._Element:
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    for el in root.iter():  # drop namespaces from tags (mml:, xlink: attributes stay)
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.rsplit("}", 1)[1]
    return root


def affiliations(am, root) -> dict[str, str]:
    affs = {}
    for aff in list(am.iter("aff")) + list(root.findall("front/article-meta/contrib-group/aff")):
        if aff.get("id") in affs:
            continue
        s = text_wo(aff, drop=("label", "sup", "institution-id"))
        affs[aff.get("id") or f"_{len(affs)}"] = s.strip(" ,;")
    return affs


def authors(am, root) -> list[dict]:
    affs = affiliations(am, root)
    corresp = {c.get("id"): c for c in am.iter("corresp")}
    out = []
    for cg in am.findall("contrib-group"):
        for c in cg.findall("contrib"):
            if c.get("contrib-type", "author") != "author":
                continue
            a: dict = {"author_id": len(out) + 1}
            name = c.find("name")
            collab = c.find("collab")
            if name is not None:
                a["given"] = text(name.find("given-names"))
                a["family"] = text(name.find("surname"))
            elif collab is not None:
                a["given"] = ""
                a["family"] = text_wo(collab, drop=("xref", "contrib-group", "fn"))
            else:
                continue
            rids = [x.get("rid", "") for x in c.findall("xref") if x.get("ref-type") == "aff"]
            aff_txt = [affs[r] for rid in rids for r in rid.split() if r in affs]
            aff_txt += [text_wo(x, drop=("label", "sup", "institution-id")) for x in c.findall("aff")]
            if not aff_txt and len(affs) == 1:
                aff_txt = list(affs.values())
            a["affiliation"] = "; ".join(t for t in aff_txt if t)
            email = c.findtext("email") or ""
            is_corr = c.get("corresp") == "yes" or any(x.get("ref-type") == "corresp" for x in c.findall("xref"))
            if not email and is_corr:
                for x in c.findall("xref"):
                    if x.get("ref-type") == "corresp" and x.get("rid") in corresp:
                        emails = [text(e) for e in corresp[x.get("rid")].iter("email")]
                        if len(emails) == 1:
                            email = emails[0]
            a["email"] = email.strip()
            orcid = next((text(i) for i in c.findall("contrib-id") if i.get("contrib-id-type") == "orcid"), "")
            a["orcid"] = re.sub(r"^https?://orcid\.org/", "", orcid)
            a["corresponding"] = bool(is_corr)
            out.append(a)
    return out


def abstract_text(am) -> tuple[str, str]:
    for ab in am.findall("abstract"):
        if ab.get("abstract-type") in ("graphical", "teaser", "summary", "author-summary", "editor-summary",
                                       "precis", "web-summary", "toc", "lay"):
            continue
        parts = []
        title = ab.find("title")
        header = text(title) if title is not None else "Abstract"
        for el in ab:
            if el.tag == "title":
                continue
            if el.tag == "sec":
                st = el.find("title")
                body = " ".join(text_wo(p) for p in el if p.tag == "p")
                parts.append(((text(st) + ": ") if st is not None and text(st) else "") + body)
            elif el.tag == "p":
                parts.append(text_wo(el))
        return header, " ".join(p for p in parts if p).strip()
    return "", ""


def keywords(am) -> list[str]:
    for kg in am.findall("kwd-group"):
        if (kg.get("kwd-group-type") or "").lower() in ("abbreviations", "abbr", "mesh", "jel", "classification"):
            continue
        if kg.get("{http://www.w3.org/XML/1998/namespace}lang", "en")[:2] not in ("en",):
            continue
        return [text(k) for k in kg.findall("kwd") if text(k)]
    return []


def references(root) -> list[dict]:
    out = []
    for ref in root.iter("ref"):
        if ref.getparent() is None or ref.getparent().tag != "ref-list":
            continue
        cit = None
        for el in ref.iter("mixed-citation", "element-citation", "citation"):
            cit = el
            break
        if cit is None:
            continue
        f = fields_from_jats(etree.tostring(cit, encoding="unicode"))
        b: dict = {"bib_id": len(out) + 1}
        names = []
        pg = [g for g in cit.iter("person-group") if (g.get("person-group-type") or "author") == "author"]
        holders = pg or [cit]
        for h in holders:
            for n in h:
                if n.tag in ("name", "string-name"):
                    fam = text(n.find("surname")) if n.find("surname") is not None else ""
                    giv = text(n.find("given-names")) if n.find("given-names") is not None else ""
                    if not fam and n.tag == "string-name":
                        fam = text(n)
                    if fam:
                        names.append({"family": fam, "given": giv})
                elif n.tag == "collab":
                    names.append({"family": text(n), "given": ""})
        if names:
            b["authors"] = names
        y = re.search(r"\d{4}", f.get("year", "") or "")
        if y:
            b["year"] = y.group(0)
        for k in ("title", "container", "volume", "first_page", "last_page", "doi"):
            if f.get(k):
                b[k] = f[k]
        for k in ("first_page", "last_page"):  # "Article 102121" -> "102121"; a DOI tagged as fpage is not a page
            if k in b:
                b[k] = re.sub(r"^(article|art\.|pp?\.)\s*", "", b[k].strip(), flags=re.I)
                if "/" in b[k] or not b[k]:
                    del b[k]
        if "last_page" in b and "first_page" not in b:
            del b["last_page"]
        b["_raw"] = text(cit)
        out.append(b)
    return out


def project(pid: str, raw_dir: Path) -> tuple[dict, dict]:
    xml = (raw_dir / "jats.xml").read_bytes()
    root = parse(xml)
    am = root.find("front/article-meta")
    hay = Haystack(raw_dir / "paper.pdf")
    chk: dict = {"paper_id": pid, "pages": hay.pages, "front": {}, "refs": {}}

    title = text_wo(am.find("title-group/article-title"))
    doi = next((text(e) for e in am.findall("article-id") if e.get("pub-id-type") == "doi"), "")
    auths = authors(am, root)
    header, abstract = abstract_text(am)
    kws = keywords(am)
    bib = references(root)

    f = chk["front"]
    fr = hay.front
    f["title"] = hay.has(title, scope=fr)
    f["doi"] = hay.has(doi, fuzzy=False)
    f["abstract"] = hay.has_long(abstract, scope=fr) if abstract else None
    f["author_family"] = [hay.has(a["family"], fuzzy=len(a["family"]) > 12, scope=fr) for a in auths]
    f["author_given_full"] = [hay.has(a["given"], fuzzy=False, scope=fr) if a["given"] else None for a in auths]
    f["affiliation"] = [hay.has_long(a["affiliation"], chunk=30, need=0.6, scope=fr) if a["affiliation"] else None
                        for a in auths]
    f["affiliation_anywhere"] = [hay.has_long(a["affiliation"], chunk=30, need=0.6) if a["affiliation"] else None
                                 for a in auths]
    f["keywords"] = [hay.has(k, fuzzy=False, scope=fr) for k in kws]
    f["keywords_anywhere"] = [hay.has(k, fuzzy=False, scope=hay.kw_zone) for k in kws]
    kws = [k for k, ok in zip(kws, f["keywords_anywhere"]) if ok]  # subject terms the PDF never prints
    f["email"] = [hay.has(a["email"], fuzzy=False) if a["email"] else None for a in auths]
    f["orcid"] = [hay.has(a["orcid"], fuzzy=False) if a["orcid"] else None for a in auths]

    for a, printed in zip(auths, f["orcid"]):  # ORCIDs printed only as a linked icon are not on the page
        if a["orcid"] and not printed:
            a["orcid"] = ""

    # References: each field is looked up in a +-500 normalised-char window around the reference's own anchor
    # (see Haystack.locate_refs); a reference that cannot be located is checked against the whole text and counted
    # in refs.unlocated. Fields not found are dropped from that gold reference; unprinted authors are trimmed.
    rc = chk["refs"]
    rc["n"] = len(bib)
    for k in ("title", "container", "volume", "pages", "year", "doi", "authors"):
        rc[k] = {"gold": 0, "printed": 0}
    locs = hay.locate_refs(bib)
    rc["anchors"] = {"title": 0, "doi": 0, "surname+year": 0}
    rc["unlocated"] = 0
    for b, loc in zip(bib, locs):
        if loc:
            rc["anchors"][loc[1]] += 1
            win = hay.n[max(0, loc[0] - 500): loc[0] + 500]
        else:
            rc["unlocated"] += 1
            win = hay.n
        for k in ("title", "container", "volume", "year", "doi"):
            if k not in b:
                continue
            rc[k]["gold"] += 1
            ok = (loc and loc[1] == "title" and k == "title") or hay.has(b[k], fuzzy=k in ("title", "container"), scope=win)
            if ok:
                rc[k]["printed"] += 1
            else:
                b.setdefault("_dropped", []).append(k)
                del b[k]
        if "first_page" in b:
            rc["pages"]["gold"] += 1
            if hay.has(b["first_page"], fuzzy=False, scope=win):
                rc["pages"]["printed"] += 1
                fp, lp = b["first_page"], b.get("last_page", "")
                if fp.isdigit() and lp.isdigit() and int(lp) < int(fp):
                    # abbreviated range ("437-43", as PLOS/BMC JATS store it): the full last page is not the printed
                    # string and an extractor may legitimately print or expand it, so score the first page only
                    rc["last_page_abbrev"] = rc.get("last_page_abbrev", 0) + 1
                    b.pop("last_page")
                elif b.get("last_page") and not hay.has(norm(b["first_page"]) + norm(b["last_page"]), fuzzy=False, scope=win):
                    # printed abbreviated ("679-85") or not at all: the scorer requires an exact last page, so keep
                    # only the first page
                    rc.setdefault("last_page_dropped", 0)
                    rc["last_page_dropped"] += 1
                    b.pop("last_page")
            else:
                b.setdefault("_dropped", []).append("pages")
                b.pop("first_page", None)
                b.pop("last_page", None)
        if "authors" in b:
            rc["authors"]["gold"] += 1
            found = [hay.has(n["family"], fuzzy=len(norm(n["family"])) > 12, scope=win) for n in b["authors"]]
            if all(found):
                rc["authors"]["printed"] += 1
            else:
                b["_dropped_authors"] = [n["family"] for n, ok in zip(b["authors"], found) if not ok]
                b["authors"] = [n for n, ok in zip(b["authors"], found) if ok]
                if not b["authors"]:
                    b.setdefault("_dropped", []).append("authors")
                    del b["authors"]
    chk["refs"]["dropped"] = [{"bib_id": b["bib_id"], "fields": b.get("_dropped", []),
                               "authors_not_found": b.get("_dropped_authors", [])}
                              for b in bib if b.get("_dropped") or b.get("_dropped_authors")]

    gold = {
        "paper_id": pid,
        "info": {
            "title": title,
            "doi": doi if f["doi"] else "",
            "file_name": f"{pid}.pdf",
            "keywords": kws,
            "abstract": abstract,
        },
        "author": [{k: v for k, v in a.items()} for a in auths],
        "section": [{"section_id": 1, "section_type": "abstract", "header": header or "Abstract", "level": 1,
                     "parent_section_id": None, "classification_score": 1.0}] if abstract else [],
        "text": [{"text_id": 1, "section_id": 1, "paragraph_id": 1, "text": abstract, "page_number": 1}] if abstract else [],
        "bib": [{k: v for k, v in b.items() if not k.startswith("_")} for b in bib],
        "provenance": {"labeler": LABELER, "source": "PMC OpenData publisher JATS, checked against the PDF text layer",
                       "jats_doi": doi},
    }
    if not kws:
        del gold["info"]["keywords"]
    return gold, chk


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--ids", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--checks", type=Path, required=True)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    a.checks.mkdir(parents=True, exist_ok=True)
    ids = [l.strip() for l in a.ids.read_text().splitlines() if l.strip() and not l.startswith("#")]
    for pid in ids:
        try:
            gold, chk = project(pid, a.raw / pid)
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {pid}: {type(e).__name__}: {e}")
            continue
        (a.out / f"{pid}.json").write_text(json.dumps(gold, indent=1, ensure_ascii=False) + "\n")
        (a.checks / f"{pid}.json").write_text(json.dumps(chk, indent=1, ensure_ascii=False) + "\n")
        f = chk["front"]
        print(f"{pid}: authors={len(gold['author'])} refs={len(gold['bib'])} title={f['title']} doi={f['doi']} "
              f"abs={f['abstract']} kw={sum(bool(x) for x in f['keywords'])}/{len(f['keywords'])} "
              f"ref_doi={chk['refs']['doi']['printed']}/{chk['refs']['doi']['gold']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
