#!/usr/bin/env python3
"""Summarise the end-to-end throughput run (BIBR_RUN_SPEC.md (b)) as markdown.

    python scripts/jats_eval/throughput.py ~/dev/jats-eval-2026-10-15/runs/throughput-bs120-e8ebd73-4b \
        --pages 1890 --papers 120 [--md out.md]

Wall time comes from /usr/bin/time -v (time.txt): process start to exit, so model load and server start-up are
included. Per-stage seconds and LLM tokens come from out/outcomes.jsonl; GPU utilisation from gpu_util.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def wall_seconds(time_txt: str) -> float | None:
    m = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([\d:.]+)", time_txt)
    if not m:
        return None
    parts = [float(x) for x in m.group(1).split(":")]
    s = 0.0
    for x in parts:
        s = s * 60 + x
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--pages", type=int, required=True)
    ap.add_argument("--papers", type=int, required=True)
    ap.add_argument("--md")
    ap.add_argument("--server-start", help="file holding the vLLM/OCR server start-up seconds (excluded from wall)")
    a = ap.parse_args(argv)
    T = a.run.expanduser()
    tt = (T / "time.txt").read_text() if (T / "time.txt").is_file() else ""
    wall = wall_seconds(tt)
    summ = (T / "summary.txt").read_text() if (T / "summary.txt").is_file() else ""
    if wall is None and (m := re.search(r"wall (\d+) s", summ)):
        wall = float(m.group(1))  # runner's own clock around the bibr batch call
    ss = Path(a.server_start).expanduser() if a.server_start else None
    server_s = ss.read_text().strip() if ss and ss.is_file() else None
    rows = [json.loads(l) for l in (T / "out" / "outcomes.jsonl").read_text().splitlines() if l.strip()] \
        if (T / "out" / "outcomes.jsonl").is_file() else []
    last = {}
    for r in rows:  # ledger may hold retries; keep each paper's last attempt
        last[r["paper_id"]] = r
    st = Counter(r["status"] for r in last.values())
    stage = defaultdict(float)
    for r in last.values():
        for k, v in (r.get("stage_times") or {}).items():
            stage[k] += v or 0
    dur = [r["duration_s"] for r in last.values() if r.get("duration_s")]
    tok_in = sum(r.get("llm_input_tokens") or 0 for r in last.values())
    tok_out = sum(r.get("llm_output_tokens") or 0 for r in last.values())
    util = []
    if (T / "gpu_util.csv").is_file():
        for row in csv.reader((T / "gpu_util.csv").read_text().splitlines()[1:]):
            try:
                util.append(float(row[1].strip().split()[0]))
            except (IndexError, ValueError):
                pass
    gpu = (T / "gpu.txt").read_text().splitlines()[-1] if (T / "gpu.txt").is_file() else "?"
    commit = (T / "bibr_commit.txt").read_text().strip() if (T / "bibr_commit.txt").is_file() else "?"
    warm = (T / "warm.txt").read_text().strip() if (T / "warm.txt").is_file() else "?"
    ri = json.loads((T / "out" / "run_info.json").read_text()) if (T / "out" / "run_info.json").is_file() else {}
    o, s = ri.get("options", {}), ri.get("settings", {})
    L = []
    if wall:
        h = wall / 3600
        L += [f"**{a.pages / h:,.0f} pages/hour, {a.papers / h:.1f} papers/hour** end to end: {a.papers} jats_bs_v1 "
              f"born-digital PDFs, {a.pages:,} pages, in {wall / 60:.1f} min wall clock, in one `bibr batch` "
              f"invocation on one {gpu.split(',')[0]} (bibr `{commit[:9]}`).", "",
              "Which clock this is: the wall clock runs from the start to the exit of `bibr batch` against servers that "
              "were already up (warm). Model loading and server start-up are **excluded**"
              + (f"; starting the vLLM 4B and PaddleOCR-VL servers took {server_s} s, once, before the pilot" if server_s
                 else "") + ". Caches were cold (no OCR or LLM cache, empty output dir).",
              f"Setup: {warm}", ""]
    else:
        L += ["Throughput run has not finished (no time.txt).", ""]
    if last:
        L += [f"- Outcomes: {dict(st)}. Per paper: median {statistics.median(dur):.1f} s, "
              f"p90 {sorted(dur)[int(0.9 * (len(dur) - 1))]:.1f} s (sequential sums; papers overlap under "
              f"concurrency).",
              "- Stage seconds summed over papers: " + ", ".join(f"{k} {v:,.0f}" for k, v in
                                                                 sorted(stage.items(), key=lambda kv: -kv[1])) + ".",
              f"- LLM tokens: {tok_in:,} in, {tok_out:,} out ({(tok_in + tok_out) / max(len(last), 1):,.0f} per "
              f"paper)."]
    if util:
        busy = sum(u > 0 for u in util)
        L.append(f"- GPU utilisation (nvidia-smi every 5 s): mean {statistics.mean(util):.0f}%, busy (>0%) in "
                 f"{busy} of {len(util)} samples.")
    if (T / "cpu_ram.txt").is_file():
        load = sorted(float(x.split()[1]) for x in (T / "cpu_ram.txt").read_text().splitlines() if len(x.split()) > 1)
        nproc = (T / "nproc.txt").read_text().strip() if (T / "nproc.txt").is_file() else "16"
        if load:
            bibr_gpu = 0
            if (T / "gpu_apps.csv").is_file():  # per-process VRAM samples: bibr's python process holds VRAM = ONNX on GPU
                rows_ = [x.split(", ") for x in (T / "gpu_apps.csv").read_text().splitlines()[1:]]
                bibr_gpu = sum(len(r) > 2 and "python" in r[2] and "VLLM" not in r[2] for r in rows_)
            note = ("bibr's ONNX stages (layout, segmentation, NER) ran on the GPU "
                    f"(bibr process on the GPU in {bibr_gpu} per-process samples)." if bibr_gpu else
                    "The run is CPU-bound: layout and segmentation run in the bibr process on CPU, and the GPU servers "
                    "wait for them. The figure is a floor for this machine, not a GPU limit.")
            L.append(f"- CPU: 1-min load average median {load[len(load) // 2]:.1f}, p90 {load[int(len(load) * 0.9)]:.1f} "
                     f"on {nproc} cores. " + note)
    if (T / "vmstat.txt").is_file():  # vmstat -t 5: swpd free buff cache si so in KiB / KiB/s
        vm = [x.split() for x in (T / "vmstat.txt").read_text().splitlines()]
        vm = [r for r in vm if r and r[0].isdigit() and len(r) >= 8]
        if vm:
            swpd = [int(r[2]) for r in vm]
            si, so = sum(int(r[6]) for r in vm) * 5, sum(int(r[7]) for r in vm) * 5
            L.append(f"- Swap: {min(swpd) / 1048576:.1f}–{max(swpd) / 1048576:.1f} GiB in use; swapped in "
                     f"{si / 1048576:.2f} GiB, out {so / 1048576:.2f} GiB over the run.")
    if o or s:
        L.append("- Resolved settings: batch_size " + str(o.get("batch_size")) + ", concurrency "
                 + str(o.get("concurrency")) + f" (min {o.get('min_concurrency')}, max {o.get('max_concurrency')}), "
                 f"LLM_MAX_CONCURRENCY {s.get('LLM_MAX_CONCURRENCY')}, LLM_MODEL {s.get('LLM_MODEL')}, "
                 f"OCR {s.get('OCR_BACKEND')} / {s.get('OCR_MODEL')}, CACHE_LLM {s.get('CACHE_LLM')}, "
                 f"CACHE_OCR {s.get('CACHE_OCR')}.")
    rss = re.search(r"Maximum resident set size \(kbytes\): (\d+)", tt)
    if rss:
        L.append(f"- Peak RSS of the bibr process: {int(rss.group(1)) / 1024 / 1024:.1f} GiB.")
    md = "\n".join(L) + "\n"
    print(md)
    if a.md:
        Path(a.md).write_text(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
