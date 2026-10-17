#!/usr/bin/env python3
"""Fixed-seed walk over the discovered PMC OA pool: eligibility, pilot draw, frozen main sample, file fetch.

    PY=~/dev/bibr-validation/.venv/bin/python
    $PY select_sets.py --pool data/pool_raw.jsonl --cutoff 2026-07-01 --exclusions data/exclusion --seed 20261015 \
        --stage pilot|main

Walk: per set, each journal's candidates are sorted by PMCID and shuffled with random.Random(f"{seed}:{set}:{journal}").
Journals are then visited round-robin (fixed order, the order of discover.JOURNALS); at each visit the journal advances
along its own shuffled list to its next eligible paper. The first --pilot-n eligible papers so drawn are the pilot; the
walk then continues, skipping pilot papers, and the next --n eligible papers are the main set. A journal stops taking
papers at --journal-cap, a publisher at --publisher-cap; an exhausted journal drops out of the rotation.

Eligibility (in order; the first failing rule is the recorded reason):
  no_opendata_version, retracted, historical_ocr, author_manuscript, licence (CC BY / CC0 only, from the OpenData
  sidecar), no_pdf (no canonical .pdf in the same version), article_type (JATS research-article / brief-report),
  subject (Royal Society Open Science: a psychology / cognitive-neuroscience heading), published_before_cutoff (earliest
  JATS electronic/print pub date), no_doi, pdf_unreadable / pdf_no_text (pypdfium2 cannot open it or the first page has <200 text chars), then
  heading (JATS heading subject matches a review/protocol/viewpoint/tutorial/primer/education/... denylist), then
  excluded_doi / excluded_pmcid (exclusion lists), then (main draw only) never_main (--never-main ids: papers already
  scored during plumbing tests, which may only ever be pilot papers). The last three are applied at walk time.
Checks are cached in data/walk_cache.jsonl so re-runs are deterministic and cheap.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import random
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import pypdfium2 as pdfium
from lxml import etree

S3 = "https://pmc-oa-opendata.s3.amazonaws.com"
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
CACHE = ROOT / "data" / "walk_cache.jsonl"
OK_TYPES = {"research-article", "brief-report"}
OK_LIC = {"CC BY", "CC0"}
JOURNAL_ORDER = [
    "Frontiers in Psychology", "PLOS ONE (Psychology)", "Royal Society Open Science", "BMC Psychology",
    "JMIR Mental Health", "Cognitive Research: Principles and Implications", "Journal of Cognition", "Open Mind",
    "Psychonomic Bulletin & Review", "Behavior Research Methods", "Developmental Science", "Psychological Medicine",
    "Ecology and Evolution", "PLOS Computational Biology", "eLife", "BMC Public Health", "Global Health Action",
    "PeerJ", "Nature Communications", "PLOS ONE (Economics)",
]

_lock = threading.Lock()
_pdfium_lock = threading.Lock()
_client = httpx.Client(timeout=120, follow_redirects=True, limits=httpx.Limits(max_connections=16))


def norm_doi(d: str | None) -> str | None:
    if not d:
        return None
    d = d.strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    d = d.removeprefix("doi:").strip()
    return d or None


def paper_id(doi: str) -> str:
    return doi.replace("/", "_")


def get(url: str, **kw) -> httpx.Response:
    for i in range(6):
        try:
            r = _client.get(url, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPError(f"status {r.status_code}")
            return r
        except httpx.HTTPError:
            if i == 5:
                raise
            time.sleep(2 ** (i + 1))
    raise AssertionError


def jats_facts(xml: bytes) -> dict:
    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    am = root.find("front/article-meta")
    doi = None
    for e in am.findall("article-id") if am is not None else []:
        if e.get("pub-id-type") == "doi":
            doi = (e.text or "").strip()
    dates = []
    for pd in am.findall("pub-date") if am is not None else []:
        kind = pd.get("date-type") or pd.get("pub-type") or ""
        if kind in ("collection", "ppub-collection") or kind.startswith("nihms"):
            continue
        iso = pd.get("iso-8601-date")
        if not iso:
            y, m, d = (pd.findtext(t) for t in ("year", "month", "day"))
            if not y:
                continue
            iso = f"{int(y):04d}-{int(m or 1):02d}-{int(d or 1):02d}"
        dates.append(iso[:10])
    headings = [s.text or "" for g in (am.iter("subj-group") if am is not None else []) for s in g.findall("subject")]
    return {
        "article_type": root.get("article-type"),
        "doi": doi,
        "pub_date": min(dates) if dates else None,
        "subjects": headings,
        "journal_title": root.findtext("front/journal-meta/journal-title-group/journal-title"),
        "publisher_name": root.findtext("front/journal-meta/publisher/publisher-name"),
        "title": "".join(am.find("title-group/article-title").itertext()).strip() if am is not None and am.find("title-group/article-title") is not None else None,
    }


def check(row: dict, cutoff: str) -> dict:
    """Eligibility of one pool row; downloads the XML (always) and PDF (when every metadata rule passes)."""
    pmcid = row["pmcid"]
    out = {"pmcid": pmcid, "journal": row["journal"], "set": row["set"]}
    lst = get(S3, params={"list-type": "2", "prefix": f"{pmcid}.", "delimiter": "/"})
    vers = [e.findtext(NS + "Prefix").rstrip("/") for e in etree.fromstring(lst.content).findall(NS + "CommonPrefixes")]
    if not vers:
        return {**out, "eligible": False, "reason": "no_opendata_version"}
    ver = max(vers, key=lambda v: int(v.rsplit(".", 1)[1]))
    out["version"] = ver
    meta = get(f"{S3}/{ver}/{ver}.json").json()
    out["licence"] = meta.get("license_code")
    out["sidecar_doi"] = norm_doi(meta.get("doi"))
    for flag, reason in (("is_retracted", "retracted"), ("is_historical_ocr", "historical_ocr"), ("is_manuscript", "author_manuscript")):
        if meta.get(flag):
            return {**out, "eligible": False, "reason": reason}
    if meta.get("license_code") not in OK_LIC:
        return {**out, "eligible": False, "reason": "licence"}
    if not meta.get("pdf_url") or f"{ver}/{ver}.pdf" not in (meta.get("pdf_url") or ""):
        return {**out, "eligible": False, "reason": "no_pdf"}
    xml = get(f"{S3}/{ver}/{ver}.xml").content
    f = jats_facts(xml)
    doi = norm_doi(f["doi"]) or out["sidecar_doi"]
    out.update(article_type=f["article_type"], doi=doi, pub_date=f["pub_date"], jats_journal=f["journal_title"],
               jats_publisher=f["publisher_name"], title=f["title"])
    if f["article_type"] not in OK_TYPES:
        return {**out, "eligible": False, "reason": "article_type"}
    if row["journal"] == "Royal Society Open Science" and not any(
        re.search(r"psycholog|cognitive neuroscience", s, re.I) for s in f["subjects"]
    ):
        return {**out, "eligible": False, "reason": "subject"}
    if not f["pub_date"] or f["pub_date"] < cutoff:
        return {**out, "eligible": False, "reason": "published_before_cutoff"}
    if not doi:
        return {**out, "eligible": False, "reason": "no_doi"}
    pdf = get(f"{S3}/{ver}/{ver}.pdf").content
    if not pdf.startswith(b"%PDF"):
        return {**out, "eligible": False, "reason": "no_pdf"}
    try:
        with _pdfium_lock:  # pdfium is not thread-safe
            doc = pdfium.PdfDocument(pdf)
            pages = len(doc)
            first_text = doc[0].get_textpage().get_text_range()
            doc.close()
    except Exception:  # noqa: BLE001
        return {**out, "eligible": False, "reason": "pdf_unreadable"}
    if len(first_text.strip()) < 200:
        return {**out, "eligible": False, "reason": "pdf_no_text"}
    d = RAW / paper_id(doi)
    d.mkdir(parents=True, exist_ok=True)
    (d / "paper.pdf").write_bytes(pdf)
    (d / "jats.xml").write_bytes(xml)
    (d / "opendata.json").write_text(json.dumps(meta, indent=1))
    out.update(eligible=True, reason=None, pages=pages, pdf_sha256=hashlib.sha256(pdf).hexdigest(),
               xml_sha256=hashlib.sha256(xml).hexdigest(), paper_id=paper_id(doi))
    return out


HEADING_DENY = re.compile(r"review|protocol|perspective|opinion|editorial|correction|corrigendum|erratum|retraction|"
                          r"commentary|comment|viewpoint|tutorial|primer|education|letter|reply|news|obituary|"
                          r"case report|hypothesis", re.I)


def heading_denied(pid: str) -> bool:
    """Article-type headings that JATS marks research-article but are not original research (applied at walk time)."""
    root = etree.parse(str(RAW / pid / "jats.xml"), etree.XMLParser(recover=True, huge_tree=True))
    heads = [s.text or "" for s in root.iterfind(".//article-meta/article-categories/subj-group[@subj-group-type='heading']/subject")]
    return any(HEADING_DENY.search(h) for h in heads)


def load_cache() -> dict:
    c = {}
    if CACHE.exists():
        for line in CACHE.read_text().splitlines():
            r = json.loads(line)
            c[(r["set"], r["journal"], r["pmcid"])] = r
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--cutoff", required=True)
    ap.add_argument("--exclusions", required=True, help="dir with doi_keys.txt and pmcid.txt (build_exclusions.py)")
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--stage", choices=["pilot", "main"], required=True)
    ap.add_argument("--set", dest="sets", nargs="+", default=["jats_bs_v1", "jats_other_v1"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--never-main", help="file of paper ids that must not enter the main draw")
    ap.add_argument("--out", default=str(ROOT / "data" / "selection"))
    a = ap.parse_args()
    excl_doi = set(Path(a.exclusions, "doi_keys.txt").read_text().split())  # paper-id form: lowercase, "/" -> "_"
    excl_pmcid = {x.strip().lower() for x in Path(a.exclusions, "pmcid.txt").read_text().split()}
    params = {
        "jats_bs_v1": {"pilot": 20, "n": 200, "journal_cap": 35, "publisher_cap": 60},
        "jats_other_v1": {"pilot": 5, "n": 100, "journal_cap": 20, "publisher_cap": 30},
    }
    never_main = set(Path(a.never_main).read_text().split()) if a.never_main else set()
    pool = [json.loads(l) for l in open(a.pool)]
    cache = load_cache()
    cache_f = open(CACHE, "a")
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    ex = cf.ThreadPoolExecutor(a.workers)

    for set_id in a.sets:
        p = params[set_id]
        by_j: dict[str, list[dict]] = defaultdict(list)
        seen = set()
        for r in pool:
            if r["set"] == set_id and (r["journal"], r["pmcid"]) not in seen:
                seen.add((r["journal"], r["pmcid"]))
                by_j[r["journal"]].append(r)
        order = [j for j in JOURNAL_ORDER if j in by_j]
        walks = {}
        for j in order:
            lst = sorted(by_j[j], key=lambda r: int(r["pmcid"][3:]))
            random.Random(f"{a.seed}:{set_id}:{j}").shuffle(lst)
            walks[j] = lst
        pos = {j: 0 for j in order}

        def result(j: str, i: int) -> dict:
            key = (set_id, j, walks[j][i]["pmcid"])
            if key not in cache:
                # prefetch this and the next few candidates of the journal in parallel
                todo = [k for k in range(i, min(i + a.workers, len(walks[j])))
                        if (set_id, j, walks[j][k]["pmcid"]) not in cache]
                futs = {k: ex.submit(check, walks[j][k], a.cutoff) for k in todo}
                for k, fu in futs.items():
                    try:
                        res = fu.result()
                    except Exception as e:  # noqa: BLE001
                        res = {"pmcid": walks[j][k]["pmcid"], "journal": j, "set": set_id, "eligible": False,
                               "reason": f"fetch_error:{type(e).__name__}", "transient": True}
                        print("ERROR", walks[j][k]["pmcid"], e, file=sys.stderr)
                    res["walk_index"] = k
                    if not res.get("transient"):
                        cache[(set_id, j, walks[j][k]["pmcid"])] = res
                        with _lock:
                            cache_f.write(json.dumps(res) + "\n")
                            cache_f.flush()
                    elif k == i:
                        raise SystemExit(f"transient failure at {walks[j][k]['pmcid']}; re-run")
            r = dict(cache[key])
            if r["eligible"] and (r.get("pub_date") or "") < a.cutoff:  # cache built at an earlier cutoff
                r.update(eligible=False, reason="published_before_cutoff")
            if r["eligible"] and heading_denied(r["paper_id"]):
                r.update(eligible=False, reason="heading")
            if r["eligible"]:  # exclusions are applied at walk time so the cache stays exclusion-independent
                if paper_id(r["doi"]) in excl_doi or (r.get("sidecar_doi") and paper_id(r["sidecar_doi"]) in excl_doi):
                    r.update(eligible=False, reason="excluded_doi")
                elif r["pmcid"].lower() in excl_pmcid:
                    r.update(eligible=False, reason="excluded_pmcid")
            return r

        picked: list[dict] = []
        walk_log: list[dict] = []
        n_j: Counter = Counter()
        n_pub: Counter = Counter()
        pilot_ids = set()
        target = p["pilot"] if a.stage == "pilot" else p["pilot"] + p["n"]
        active = list(order)
        publisher_of = {j: by_j[j][0]["publisher"] for j in order}
        pub_group = {j: publisher_of[j].split(" (")[0] for j in order}
        while len(picked) < target and active:
            for j in list(active):
                if len(picked) >= target:
                    break
                in_pilot = len(picked) < p["pilot"]
                if not in_pilot and (n_j[j] >= p["journal_cap"] or n_pub[pub_group[j]] >= p["publisher_cap"]):
                    active.remove(j)
                    continue
                took = False
                while pos[j] < len(walks[j]):
                    r = result(j, pos[j])
                    pos[j] += 1
                    if r["eligible"] and not in_pilot and r["paper_id"] in never_main:
                        r = {**r, "eligible": False, "reason": "never_main"}
                    walk_log.append({k: r.get(k) for k in ("pmcid", "journal", "walk_index", "eligible", "reason", "doi")})
                    if r["eligible"]:
                        row = {**walks[j][pos[j] - 1], **r, "role": "pilot" if in_pilot else "main"}
                        picked.append(row)
                        if not in_pilot:
                            n_j[j] += 1
                            n_pub[pub_group[j]] += 1
                        took = True
                        break
                if not took:
                    active.remove(j)
        pilot = [r for r in picked if r["role"] == "pilot"]
        main_ = [r for r in picked if r["role"] == "main"]
        (outdir / f"{set_id}.pilot.jsonl").write_text("".join(json.dumps(r) + "\n" for r in pilot))
        if a.stage == "main":
            (outdir / f"{set_id}.main.jsonl").write_text("".join(json.dumps(r) + "\n" for r in main_))
            (outdir / f"{set_id}.walk.jsonl").write_text("".join(json.dumps(r) + "\n" for r in walk_log))
        reasons = Counter(r["reason"] for r in walk_log if not r["eligible"])
        print(f"== {set_id} stage={a.stage}: pilot {len(pilot)}, main {len(main_)}, walked {len(walk_log)}")
        print("   per journal (main):", dict(n_j))
        print("   per publisher (main):", dict(n_pub))
        print("   pilot journals:", dict(Counter(r["journal"] for r in pilot)))
        print("   ineligible reasons:", dict(reasons))
        print("   exhausted:", [j for j in order if pos[j] >= len(walks[j])])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
