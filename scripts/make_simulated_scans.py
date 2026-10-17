#!/usr/bin/env python3
"""Simulated scans: rebuild born-digital PDFs as image-only PDFs that look like a clean office scan.

    python scripts/make_simulated_scans.py --raw data/raw \
        --ids registry/jats_eval_v1/jats_bs_v1.scans.ids.txt --out data/scans/jats_bs_v1

Per page: render at 200 dpi grayscale (pypdfium2), rotate by a uniform random angle in [-1, +1] degrees (white fill),
add Gaussian pixel noise (sigma 6 on 0-255), JPEG-encode at quality 70, and write all pages into one PDF with no text
layer (PIL). Randomness is seeded per paper from --seed (default 20261015) and the paper id, so a rebuild gives the
same pages as long as pypdfium2 renders them the same way; the PDF's creation date always differs. Needs numpy,
pypdfium2 and Pillow.
These are SIMULATED scans of born-digital papers, not real scans: no paper warp, no bleed-through, no uneven lighting.
The gold is the same JATS-projected gold as the born-digital PDF.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image

DPI = 200
SKEW_DEG = 1.0
NOISE_SIGMA = 6.0
JPEG_QUALITY = 70


def scan_pdf(src: Path, dst: Path, seed: str) -> dict:
    rng = random.Random(seed)
    nrng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))
    doc = pdfium.PdfDocument(str(src))
    pages, angles = [], []
    for i in range(len(doc)):
        img = doc[i].render(scale=DPI / 72, grayscale=True).to_pil().convert("L")
        angle = rng.uniform(-SKEW_DEG, SKEW_DEG)
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
        arr = np.asarray(img, dtype=np.float32)
        arr = np.clip(arr + nrng.normal(0, NOISE_SIGMA, arr.shape), 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(arr, "L").save(buf, "JPEG", quality=JPEG_QUALITY)
        buf.seek(0)
        pages.append(Image.open(buf))
        angles.append(round(angle, 3))
    doc.close()
    dst.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(dst, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    check = pdfium.PdfDocument(str(dst))
    chars = sum(len(check[i].get_textpage().get_text_range().strip()) for i in range(len(check)))
    check.close()
    assert chars == 0, f"{dst} has a text layer"
    return {"pages": len(pages), "skew_deg": angles, "bytes": dst.stat().st_size,
            "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--ids", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", default="20261015")
    a = ap.parse_args(argv)
    ids = [l.strip() for l in a.ids.read_text().splitlines() if l.strip() and not l.startswith("#")]
    log = {}
    for pid in ids:
        dst = a.out / f"{pid}.pdf"
        log[pid] = scan_pdf(a.raw / pid / "paper.pdf", dst, f"{a.seed}:{pid}")
        print(pid, log[pid]["pages"], "pages", log[pid]["bytes"] // 1024, "KiB")
    params = {"dpi": DPI, "grayscale": True, "skew_deg_uniform": [-SKEW_DEG, SKEW_DEG], "noise_sigma": NOISE_SIGMA,
              "jpeg_quality": JPEG_QUALITY, "text_layer": False, "seed": a.seed}
    (a.out / "scans_manifest.json").write_text(json.dumps({"params": params, "papers": log}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
