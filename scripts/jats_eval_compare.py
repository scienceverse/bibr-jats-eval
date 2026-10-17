#!/usr/bin/env python3
"""Per-field means and paper_pass with 95% bootstrap CIs, and paired A-vs-B differences, from evaluation.evaluate JSON.

    python scripts/jats_eval_compare.py --a bibr=eval_bibr.json --b grobid=eval_grobid.json --ids ids.txt \
        [--out table.json] [--md table.md] [--title "jats_bs_v1, born-digital"]

A run whose eval file does not exist (evaluate.py writes none when nothing was predicted) counts as all missing.
Both files must score the same cohort (--ids; a paper missing from a run counts as failed on paper_pass and is left
out of field means, as evaluate.py does). paper_pass = not abstained and every floor met where gold has the field:
title_soft >= 0.9, doi_match >= 1.0, authors_fullname_f1 >= 0.9, ref_matching_f1 >= 0.8 (evaluate.FLOORS).
CIs: percentile bootstrap over papers, 10000 resamples, seed 20260925 (the seed tools/compare_arms.py uses); the
difference CI resamples papers jointly (paired), over papers both runs scored for that field.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

FLOORS = {"title_soft": 0.9, "doi_match": 1.0, "authors_fullname_f1": 0.9, "ref_matching_f1": 0.8}
FIELDS = ["title_soft", "doi_match", "authors_fullname_f1", "abstract_rouge_l", "keywords_f1", "affiliation_sim",
          "ref_matching_f1", "ref_count_ratio", "ref_author_acc", "ref_year_acc", "ref_title_acc", "ref_journal_acc",
          "ref_volume_acc", "ref_pages_acc", "ref_doi_recall"]
B = 10000
SEED = 20260925


def load(path: str, ids: list[str]) -> dict[str, dict]:
    # evaluate.py writes no file when a run has no predictions at all (GROBID on image-only scans): all missing
    p = Path(path)
    d = json.loads(p.read_text()) if p.is_file() and p.stat().st_size else {"per_paper": []}
    rows = {}
    for r in d["per_paper"]:
        pid = Path(r.get("file_name") or "").stem or (r.get("doi") or "").replace("/", "_")
        rows[pid] = r
    out = {}
    for pid in ids:
        r = rows.get(pid)
        out[pid] = r if r is not None else {"missing": True}
    return out


def passes(r: dict) -> float:
    if r.get("missing") or r.get("abstained"):
        return 0.0
    return float(all(r.get(f) is None or r[f] >= t for f, t in FLOORS.items()))


def val(r: dict, f: str):
    if f == "paper_pass":
        return passes(r)
    if r.get("missing"):
        return None
    return r.get(f)


def ci(xs: list[float], rng: random.Random) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return (float("nan"), float("nan"))
    g = np.random.default_rng(rng.getrandbits(64))
    ms = np.asarray(xs, dtype=float)[g.integers(0, n, size=(B, n))].mean(axis=1)
    return float(np.quantile(ms, 0.025)), float(np.quantile(ms, 0.975))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--ids", required=True)
    ap.add_argument("--out")
    ap.add_argument("--md")
    ap.add_argument("--title", default="")
    a = ap.parse_args(argv)
    ids = [l.strip() for l in Path(a.ids).read_text().splitlines() if l.strip() and not l.startswith("#")]
    (na, pa), (nb, pb) = (x.split("=", 1) for x in (a.a, a.b))
    A, Bm = load(pa, ids), load(pb, ids)
    res = {"title": a.title, "n": len(ids), "a": na, "b": nb, "missing": {na: sum(1 for r in A.values() if r.get("missing")),
                                                                      nb: sum(1 for r in Bm.values() if r.get("missing"))},
           "fields": {}}
    lines = [f"**{a.title}** (n={len(ids)})", "", f"| field | {na} | {nb} | {na} − {nb} (paired) | n |",
             "|---|---|---|---|---|"]
    for f in ["paper_pass"] + FIELDS:
        rng = random.Random(f"{SEED}:{f}")
        xa = [v for v in (val(A[p], f) for p in ids) if v is not None]
        xb = [v for v in (val(Bm[p], f) for p in ids) if v is not None]
        pairs = [(val(A[p], f), val(Bm[p], f)) for p in ids]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        d = [x - y for x, y in pairs]
        row = {
            na: {"mean": sum(xa) / len(xa) if xa else None, "ci95": ci(xa, rng), "n": len(xa)},
            nb: {"mean": sum(xb) / len(xb) if xb else None, "ci95": ci(xb, rng), "n": len(xb)},
            "diff": {"mean": sum(d) / len(d) if d else None, "ci95": ci(d, rng), "n": len(d)},
        }
        res["fields"][f] = row

        def fmt(c):
            return "–" if c["mean"] is None else f"{c['mean']:.3f} [{c['ci95'][0]:.3f}, {c['ci95'][1]:.3f}]"

        def fmtd(c):
            return "–" if c["mean"] is None else f"{c['mean']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}]"

        lines.append(f"| {f} | {fmt(row[na])} | {fmt(row[nb])} | {fmtd(row['diff'])} | {len(d)} |")
    md = "\n".join(lines) + "\n"
    print(md)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    if a.md:
        Path(a.md).write_text(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
