#!/usr/bin/env python3
"""Per-field JATS-vs-PDF agreement from the checks written by scripts/project_core_from_jats.py.

    python scripts/jats_eval/agreement.py gold/jats_eval_v1_checks/jats_bs_v1 [more dirs] [--md out.md]

Front-matter rates are per value (one per author, keyword, ...), reference rates per gold reference carrying the
field. "Disagreement" = the JATS value was not found in the PDF text layer (in scope); see the projector docstring.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

FRONT = [("title", "title (p1-2)"), ("doi", "article DOI (anywhere)"), ("abstract", "abstract (p1-2, 85% of chunks)"),
         ("author_family", "author family name (p1-2)"), ("author_given_full", "author given name, full form (p1-2)"),
         ("affiliation", "affiliation (p1-2)"), ("affiliation_anywhere", "affiliation (anywhere)"),
         ("keywords", "keyword (p1-2)"), ("keywords_anywhere", "keyword in a Keywords block (else dropped)"), ("email", "author email"), ("orcid", "author ORCID (text layer)")]
REFS = ["authors", "year", "title", "container", "volume", "pages", "doi"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    lines = []
    for d in a.dirs:
        fr = defaultdict(lambda: [0, 0])
        rf = defaultdict(lambda: [0, 0])
        anchors = defaultdict(int)
        n_refs = unloc = papers = trimmed = lastp = abbrev = 0
        for p in sorted(Path(d).glob("*.json")):
            c = json.loads(p.read_text())
            papers += 1
            for k, _ in FRONT:
                v = c["front"].get(k)
                for x in (v if isinstance(v, list) else [v]):
                    if x is None:
                        continue
                    fr[k][0] += 1
                    fr[k][1] += not x
            r = c["refs"]
            n_refs += r["n"]
            unloc += r.get("unlocated", 0)
            lastp += r.get("last_page_dropped", 0)
            abbrev += r.get("last_page_abbrev", 0)
            for k, v in r.get("anchors", {}).items():
                anchors[k] += v
            for k in REFS:
                rf[k][0] += r[k]["gold"]
                rf[k][1] += r[k]["gold"] - r[k]["printed"]
            trimmed += sum(1 for x in r.get("dropped", []) if x.get("authors_not_found") and "authors" not in x["fields"])
        lines += [f"**{Path(d).name}** ({papers} papers, {n_refs} references)", "",
                  "| field | JATS values | not found in PDF | rate |", "|---|---|---|---|"]
        for k, label in FRONT:
            n, m = fr[k]
            lines.append(f"| {label} | {n} | {m} | {m / n:.1%} |" if n else f"| {label} | 0 | – | – |")
        for k in REFS:
            n, m = rf[k]
            lines.append(f"| reference {k} | {n} | {m} | {m / n:.1%} |" if n else f"| reference {k} | 0 | – | – |")
        lines += ["", f"References located by title {anchors['title']}, by DOI {anchors['doi']}, by surname+year "
                  f"{anchors['surname+year']}, unlocated {unloc} ({unloc / max(n_refs, 1):.1%}; checked against the whole "
                  f"text). References with some but not all author surnames printed (list trimmed): {trimmed}. "
                  f"Last pages abbreviated in JATS (dropped, first page kept): {abbrev}; other last pages not printed in "
                  f"full (dropped): {lastp}.", ""]
    md = "\n".join(lines)
    print(md)
    if a.md:
        Path(a.md).write_text(md + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
