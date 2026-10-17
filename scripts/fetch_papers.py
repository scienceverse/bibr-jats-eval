#!/usr/bin/env python3
"""Download the benchmark's PDFs and JATS XML from PMC Open Access, and check them.

    python scripts/fetch_papers.py --out data/raw                      # the 300 papers of both sets
    python scripts/fetch_papers.py --out data/raw --set jats_bs_v1     # one set
    python scripts/fetch_papers.py --out data/raw --pilot              # the 25 pilot papers
    python scripts/fetch_papers.py --out data/raw --pdf-dir data/pdf   # also copy the PDFs for a tool run

Every paper is CC BY; papers.csv gives the credit each one needs. The files come from the public
PMC Article Datasets bucket (https://pmc-oa-opendata.s3.amazonaws.com), at the article version
recorded in registry/jats_eval_v1/manifest.jsonl (pilot_manifest.jsonl for the pilot), and each
file is checked against the sha256 recorded there. A PDF that does not match is deleted and the
script exits non-zero. PMC sometimes reissues an article version's XML in place: an XML file that
no longer matches is kept, with a warning, because the gold in gold/ was built from the earlier
file. Files already present with the right sha256 are not downloaded again.

Layout: <out>/<paper_id>/paper.pdf and <out>/<paper_id>/jats.xml, the raw layout that
scripts/project_core_from_jats.py and scripts/make_simulated_scans.py read. --pdf-dir also copies
each PDF to <pdf-dir>/<set>/<paper_id>.pdf: bibr and GROBID name each output after its PDF, and
the scores expect <paper_id>.json. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com"
REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "jats_eval_v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dst: Path, retries: int = 3) -> None:
    tmp = dst.with_name(dst.name + ".part")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as f:
                shutil.copyfileobj(r, f)
            tmp.replace(dst)
            return
        except OSError:
            tmp.unlink(missing_ok=True)
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_paper(row: dict, out: Path, pdf_dir: Path | None) -> tuple[list[str], list[str]]:
    """Fetch one paper's PDF and XML. Returns (errors, warnings)."""
    version = row["opendata_version"]
    folder = out / row["paper_id"]
    folder.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    warnings: list[str] = []
    for ext, name, key in (("pdf", "paper.pdf", "pdf_sha256"), ("xml", "jats.xml", "xml_sha256")):
        url = f"{BUCKET}/{version}/{version}.{ext}"
        dst = folder / name
        if not (dst.exists() and sha256(dst) == row[key]):
            try:
                download(url, dst)
            except OSError as e:
                errors.append(f"{url}: {e}")
                continue
        got = sha256(dst)
        if got == row[key]:
            continue
        if ext == "pdf":
            dst.unlink()
            errors.append(f"{url}: sha256 {got}, expected {row[key]}")
        else:
            warnings.append(f"{row['paper_id']}: PMC has reissued this XML since the gold was built "
                            f"(sha256 {got}, was {row[key]}); kept, but gold rebuilt from it may differ")
    if pdf_dir is not None and not errors:
        group = "pilot" if row.get("role") == "pilot" else row["set"]
        dst = pdf_dir / group / f"{row['paper_id']}.pdf"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / "paper.pdf", dst)
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="raw dir: <out>/<paper_id>/paper.pdf and jats.xml")
    ap.add_argument("--set", choices=("jats_bs_v1", "jats_other_v1"), help="only this set (default: both)")
    ap.add_argument("--pilot", action="store_true", help="fetch the 25 pilot papers instead of the sets")
    ap.add_argument("--pdf-dir", type=Path, help="also copy each PDF to <pdf-dir>/<set>/<paper_id>.pdf")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)

    manifest = REGISTRY / ("pilot_manifest.jsonl" if a.pilot else "manifest.jsonl")
    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    if a.set:
        rows = [r for r in rows if r["set"] == a.set]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        results = list(pool.map(lambda r: fetch_paper(r, a.out, a.pdf_dir), rows))
    errors = [e for errs, _ in results for e in errs]
    warnings = [w for _, warns in results for w in warns]
    for w in warnings:
        print("WARNING", w, file=sys.stderr)
    for e in errors:
        print("FAILED", e, file=sys.stderr)
    failed = sum(bool(errs) for errs, _ in results)
    print(f"{len(rows) - failed} of {len(rows)} papers fetched and checked into {a.out}"
          + (f"; {len(warnings)} XML files were reissued by PMC since the gold was built" if warnings else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
