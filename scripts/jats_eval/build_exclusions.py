#!/usr/bin/env python3
"""Collect every DOI / PMCID any bibr training source or evaluation set lists, for the jats_eval_v1 exclusion rule.

    python build_exclusions.py --sources sources.json --out data/exclusion

sources.json: {"<source name>": ["<path or glob>", ...], ...}. Every file is scanned as text (parquet: every string
cell) for DOIs (``10.NNNN/...`` and the paper-id spelling ``10.NNNN_...``) and PMCIDs. This over-collects (a training
file's own reference lists are scanned too), which only makes the exclusion stricter. Gold dirs contribute their file
names (paper_id = DOI with "/" -> "_"). Keys are compared in paper-id form: lowercased DOI, every "/" -> "_".
Writes doi_keys.txt, pmcid.txt and sources_summary.json (per-source key counts and file list with sha256).
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
from pathlib import Path

DOI_RE = re.compile(r"10\.\d{4,9}[/_][^\s\"'<>,\]\[{}|\\]+", re.I)
PMC_RE = re.compile(r"\bPMC\d{5,9}\b", re.I)


def doi_key(s: str) -> str:
    s = s.strip().lower().rstrip(".;:)")
    s = re.sub(r"\.(pdf|json|xml|tei)$", "", s)
    return s.replace("/", "_")


def scan_text(t: str, dois: set, pmcs: set) -> None:
    for m in DOI_RE.finditer(t):
        dois.add(doi_key(m.group(0)))
    for m in PMC_RE.finditer(t):
        pmcs.add(m.group(0).upper())


def scan_file(p: str, dois: set, pmcs: set) -> None:
    if p.endswith(".parquet"):
        import pyarrow.parquet as pq

        t = pq.ParquetFile(p).read()  # one file, no hive partition discovery
        for col in t.column_names:
            arr = t.column(col)
            if str(arr.type) in ("string", "large_string") or "list<" in str(arr.type) or "struct<" in str(arr.type):
                for v in arr.to_pylist():
                    if v is not None:
                        scan_text(json.dumps(v) if not isinstance(v, str) else v, dois, pmcs)
        return
    with open(p, "r", errors="replace") as f:
        while True:
            chunk = f.read(1 << 24)
            if not chunk:
                break
            scan_text(chunk, dois, pmcs)


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cfg = json.loads(Path(a.sources).read_text())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    all_d, all_p, summary = set(), set(), {}
    for name, specs in cfg.items():
        d, p, files = set(), set(), []
        for spec in specs:
            hits = sorted(glob.glob(os.path.expanduser(spec), recursive=True)) or [os.path.expanduser(spec)]
            for path in hits:
                if os.path.isdir(path):
                    # a gold / pdf dir: file names are paper ids
                    for fn in os.listdir(path):
                        scan_text(fn, d, p)
                    files.append({"path": path, "kind": "dir", "n": len(os.listdir(path))})
                elif os.path.isfile(path):
                    scan_file(path, d, p)
                    files.append({"path": path, "sha256": sha(path), "bytes": os.path.getsize(path)})
                else:
                    files.append({"path": path, "missing": True})
        summary[name] = {"doi_keys": len(d), "pmcids": len(p), "files": files}
        print(f"{name:40s} dois={len(d):8d} pmcids={len(p):7d} files={len(files)} missing={sum(1 for f in files if f.get('missing'))}")
        (out / "by_source").mkdir(exist_ok=True)
        (out / "by_source" / f"{name}.doi.txt").write_text("\n".join(sorted(d)) + "\n")
        (out / "by_source" / f"{name}.pmcid.txt").write_text("\n".join(sorted(p)) + "\n")
        all_d |= d
        all_p |= p
    (out / "doi_keys.txt").write_text("\n".join(sorted(all_d)) + "\n")
    (out / "pmcid.txt").write_text("\n".join(sorted(all_p)) + "\n")
    (out / "sources_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print("total", len(all_d), "doi keys,", len(all_p), "pmcids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
