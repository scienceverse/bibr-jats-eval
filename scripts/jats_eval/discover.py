#!/usr/bin/env python3
"""Discover candidate PMCIDs per journal from Europe PMC (and the PLOS search API for PLOS ONE subject scoping).

    python discover.py --from 2026-07-01 --to 2026-10-14 --out data/pool.jsonl

One row per (set, journal, pmcid): the raw candidate pool before eligibility checks. Europe PMC is queried with
IN_PMC, OPEN_ACCESS and a CC BY / CC0 licence filter; the licence is re-checked from the PMC OpenData sidecar later.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PLOS = "https://api.plos.org/search"

# (set, journal label, Europe PMC journal abbreviation, publisher, field, PLOS subject scope or None)
JOURNALS = [
    ("jats_bs_v1", "Frontiers in Psychology", "Front Psychol", "Frontiers", "psychology", None),
    ("jats_bs_v1", "PLOS ONE (Psychology)", "PLoS One", "PLOS", "psychology", "Psychology"),
    ("jats_bs_v1", "Royal Society Open Science", "R Soc Open Sci", "The Royal Society", "psychology", None),
    ("jats_bs_v1", "BMC Psychology", "BMC Psychol", "Springer Nature (BMC)", "psychology", None),
    ("jats_bs_v1", "JMIR Mental Health", "JMIR Ment Health", "JMIR Publications", "psychology", None),
    ("jats_bs_v1", "Cognitive Research: Principles and Implications", "Cogn Res Princ Implic", "Springer Nature", "psychology", None),
    ("jats_bs_v1", "Journal of Cognition", "J Cogn", "Ubiquity Press", "psychology", None),
    ("jats_bs_v1", "Open Mind", "Open Mind (Camb)", "MIT Press", "psychology", None),
    ("jats_bs_v1", "Psychonomic Bulletin & Review", "Psychon Bull Rev", "Springer Nature", "psychology", None),
    ("jats_bs_v1", "Behavior Research Methods", "Behav Res Methods", "Springer Nature", "psychology", None),
    ("jats_bs_v1", "Developmental Science", "Dev Sci", "Wiley", "psychology", None),
    ("jats_bs_v1", "Psychological Medicine", "Psychol Med", "Cambridge University Press", "psychology", None),
    ("jats_other_v1", "Ecology and Evolution", "Ecol Evol", "Wiley", "ecology/evolution", None),
    ("jats_other_v1", "PLOS Computational Biology", "PLoS Comput Biol", "PLOS", "computational biology/bioinformatics", None),
    ("jats_other_v1", "eLife", "Elife", "eLife Sciences Publications", "biomedicine/life sciences", None),
    ("jats_other_v1", "BMC Public Health", "BMC Public Health", "Springer Nature (BMC)", "public health", None),
    ("jats_other_v1", "Global Health Action", "Glob Health Action", "Taylor & Francis", "public health", None),
    ("jats_other_v1", "PeerJ", "PeerJ", "PeerJ", "life/environmental sciences", None),
    ("jats_other_v1", "Nature Communications", "Nat Commun", "Springer Nature", "multidisciplinary natural sciences", None),
    ("jats_other_v1", "PLOS ONE (Economics)", "PLoS One", "PLOS", "economics/social science", "Economics"),
]


def get_json(url: str, tries: int = 5) -> dict:
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - retry any network error
            if i == tries - 1:
                raise
            print(f"retry {i+1}: {e}")
            time.sleep(2 ** (i + 1))
    raise AssertionError


def epmc_all(query: str) -> list[dict]:
    out, cursor = [], "*"
    while True:
        params = {"query": query, "format": "json", "pageSize": "1000", "cursorMark": cursor, "resultType": "lite"}
        d = get_json(EPMC + "?" + urllib.parse.urlencode(params))
        out.extend(d["resultList"]["result"])
        nxt = d.get("nextCursorMark")
        if not nxt or nxt == cursor or not d["resultList"]["result"]:
            return out
        cursor = nxt


def plos_dois(subject: str, date_from: str, date_to: str) -> set[str]:
    q = (f'subject:"{subject}" AND journal_key:PLoSONE AND doc_type:full AND article_type:"Research Article" '
         f"AND publication_date:[{date_from}T00:00:00Z TO {date_to}T23:59:59Z]")
    dois, start = set(), 0
    while True:
        params = {"q": q, "fl": "id", "rows": "1000", "start": str(start), "wt": "json"}
        d = get_json(PLOS + "?" + urllib.parse.urlencode(params))
        docs = d["response"]["docs"]
        dois |= {x["id"].lower() for x in docs}
        start += len(docs)
        if not docs or start >= d["response"]["numFound"]:
            return dois
        time.sleep(6)  # PLOS API: max 10 requests/minute


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = []
    psych_plos = None
    for set_id, label, abbr, publisher, field, plos_subject in JOURNALS:
        q = (f'JOURNAL:"{abbr}" AND FIRST_PDATE:[{a.date_from} TO {a.date_to}] AND IN_PMC:y AND OPEN_ACCESS:y '
             f'AND (LICENSE:"cc by" OR LICENSE:"cc0")')
        res = epmc_all(q)
        if plos_subject:
            if psych_plos is None:
                psych_plos = plos_dois("Psychology", a.date_from, a.date_to)
            scope = plos_dois(plos_subject, a.date_from, a.date_to)
            if plos_subject != "Psychology":
                scope -= psych_plos  # the other-fields set never takes a psychology-tagged PLOS ONE paper
            res = [r for r in res if (r.get("doi") or "").lower() in scope]
        n = 0
        for r in res:
            if not r.get("pmcid"):
                continue
            rows.append({"set": set_id, "journal": label, "epmc_journal": abbr, "publisher": publisher, "field": field,
                         "pmcid": r["pmcid"], "epmc_doi": (r.get("doi") or "").lower() or None,
                         "first_pdate": r.get("firstPublicationDate"), "epmc_pubtype": r.get("pubType")})
            n += 1
        print(f"{set_id:14s} {label:50s} {n}")
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(len(rows), "rows ->", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
