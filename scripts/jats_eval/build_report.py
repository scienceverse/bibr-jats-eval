#!/usr/bin/env python3
"""Assemble the jats_eval_v1 report: bibr vs GROBID per field and paper_pass, paired-bootstrap 95% CIs.

    python scripts/jats_eval/build_report.py --work ~/dev/jats-eval-2026-10-15 --bibr-tag bibr-e8ebd73-4b \
        --out ~/dev/jats-eval-2026-10-15/REPORT.md --scores-dir results/jats_eval_v1

Reads <work>/runs/{grobid090,<bibr-tag>}/<set>/<kind>/eval.v5.json (written by score_run.sh, the v5 evaluate.py),
the throughput run <work>/runs/throughput-bs120-<tag suffix>/ and every bibr run_info.json. Writes the comparison
tables (markdown) to <work>/work/report_parts/, per-paper score CSVs (paper id + scores only) to --scores-dir, and
prints the generated sections; the narrative of REPORT.md is written by hand around them.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jats_eval_compare as cmp  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

UNTAGGED = "untagged-refs"  # exclusion key: papers with a plain-text (untagged) JATS reference, empty in the gold
GROUPS = [  # (label, [(set, kind), ...][, journal to exclude | UNTAGGED])
    ("Psychology / behavioural science (jats_bs_v1), born-digital", [("jats_bs_v1", "born_digital")]),
    ("Other fields (jats_other_v1), born-digital", [("jats_other_v1", "born_digital")]),
    ("Simulated scans (60 jats_bs_v1 + 30 jats_other_v1)", [("jats_bs_v1", "simulated_scans"),
                                                            ("jats_other_v1", "simulated_scans")]),
    ("Psychology born-digital without Frontiers in Psychology (166; GROBID fails Frontiers on editor names)",
     [("jats_bs_v1", "born_digital")], "Frontiers in Psychology"),
    ("Sensitivity: psychology born-digital, papers whose JATS has no untagged references",
     [("jats_bs_v1", "born_digital")], UNTAGGED),
    ("Sensitivity: other fields born-digital, papers whose JATS has no untagged references",
     [("jats_other_v1", "born_digital")], UNTAGGED),
    ("Simulated scans, psychology only (60)", [("jats_bs_v1", "simulated_scans")]),
    ("Simulated scans, other fields only (30)", [("jats_other_v1", "simulated_scans")]),
    ("Pilot, born-digital (25; plumbing check, not a headline number)", [("pilot", "born_digital")]),
    ("Pilot, simulated scans (5)", [("pilot", "simulated_scans")]),
]
SCORE_COLS = ["paper_pass", "abstained", "title_soft", "doi_match", "authors_fullname_f1", "abstract_rouge_l",
              "keywords_f1", "affiliation_sim", "ref_matching_f1", "ref_count_ratio", "ref_author_acc", "ref_year_acc",
              "ref_title_acc", "ref_journal_acc", "ref_volume_acc", "ref_pages_acc", "ref_doi_recall"]


def ids_of(work: Path, s: str, k: str) -> list[str]:
    return [l.strip() for l in (work / "inputs" / s / f"{k}.ids.txt").read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def merged_eval(work: Path, run: str, parts, out: Path) -> Path:
    """One eval file for a group: concatenation of the parts' per_paper rows (a missing part adds nothing)."""
    rows = []
    for s, k in parts:
        p = work / "runs" / run / s / k / "eval.v5.json"
        if p.is_file() and p.stat().st_size:
            rows += json.loads(p.read_text())["per_paper"]
    out.write_text(json.dumps({"per_paper": rows}))
    return out


def run_info_summary(d: Path) -> dict | None:
    p = d / "run_info.json"
    if not p.is_file():
        return None
    ri = json.loads(p.read_text())
    st = ri.get("settings", {})
    cf = next((x / "bibr_commit.txt" for x in (d, d.parent) if (x / "bibr_commit.txt").is_file()), None)
    commit = cf.read_text().strip() if cf else None  # the throughput run keeps it one level above out/
    opts = {k: v for k, v in ri.get("options", {}).items() if k not in ("out",)}
    # run_info.json is rewritten by the runner's resume pass (n_ok 0), so count from the ledger: last row per paper
    last, ts = {}, []
    if (d / "outcomes.jsonl").is_file():
        for l in (d / "outcomes.jsonl").read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                last[r.get("stem") or r.get("paper_id")] = r.get("status")
                ts += [t for t in (r.get("started_at"), r.get("finished_at")) if t]
    return {"dir": str(d), "bibr_commit": commit, "bibr_version": ri.get("bibr_version"),
            "build_sha": ri.get("build_sha"),
            "model": {k: st.get(k) for k in ("LLM_MODEL", "LLM_BACKEND", "LLM_CHAT_TEMPLATE_KWARGS", "LLM_TEMPERATURE",
                                            "OCR_BACKEND", "OCR_MODEL", "OCR_PROFILE", "CACHE_LLM", "CACHE_OCR")},
            "options": opts, "n_ok": sum(v == "ok" for v in last.values()),
            "n_failed": sum(v != "ok" for v in last.values()), "reason": ri.get("reason"),
            "started_at": min(ts) if ts else None, "finished_at": max(ts) if ts else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--bibr-tag", default="bibr-e8ebd73-4b")
    ap.add_argument("--grobid-tag", default="grobid090")
    ap.add_argument("--scores-dir", type=Path)
    a = ap.parse_args(argv)
    work = a.work.expanduser()
    parts_dir = work / "work" / "report_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    out = []
    man = {}
    for f in ("manifest.jsonl", "pilot_manifest.jsonl"):
        for l in (REPO / "registry" / "jats_eval_v1" / f).read_text().splitlines():
            r = json.loads(l)
            man[r["paper_id"]] = r["journal"]
    # gold references with no scoreable field: the JATS has only an untagged <mixed-citation> string for them
    untagged = set()
    for g in (REPO / "gold" / "jats_eval_v1").glob("*/*.json"):
        if any(not any(b.get(k) for k in ("title", "authors", "year", "doi", "container"))
               for b in json.loads(g.read_text())["bib"]):
            untagged.add(g.stem)
    for label, parts, *excl in GROUPS:
        ids = [i for s, k in parts for i in ids_of(work, s, k)
               if not excl or (i not in untagged if excl[0] == UNTAGGED else man[i] != excl[0])]
        idf = parts_dir / f"{label[:20].replace(' ', '_').replace('/', '')}.ids.txt"
        idf.write_text("\n".join(ids) + "\n")
        slug = "+".join(f"{s}.{k}" for s, k in parts)
        eb = merged_eval(work, a.bibr_tag, parts, parts_dir / f"bibr.{slug}.json")
        eg = merged_eval(work, a.grobid_tag, parts, parts_dir / f"grobid.{slug}.json")
        if excl:
            slug += ".excl-" + (excl[0] if excl[0] == UNTAGGED else excl[0].split()[0].lower())
        nb = len(json.loads(eb.read_text())["per_paper"])
        md = parts_dir / f"cmp.{slug}.md"
        cmp.main(["--a", f"bibr={eb}", "--b", f"grobid={eg}", "--ids", str(idf), "--title", label,
                  "--md", str(md), "--out", str(parts_dir / f"cmp.{slug}.json")])
        out.append(md.read_text() + ("" if nb else "\n_bibr: no scored output yet._\n"))
        if a.scores_dir:
            a.scores_dir.mkdir(parents=True, exist_ok=True)
            for run, ev in (("bibr", eb), ("grobid", eg)):
                rows = cmp.load(str(ev), ids)
                with open(a.scores_dir / f"{run}.{slug}.scores.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["paper_id", "missing"] + SCORE_COLS)
                    for pid in ids:
                        r = rows[pid]
                        w.writerow([pid, int(bool(r.get("missing")))] +
                                   [cmp.passes(r) if c == "paper_pass" else r.get(c) for c in SCORE_COLS])
    # per-journal paper_pass, born-digital (descriptive; journals are 1-34 papers, no CIs)
    out.append("**paper_pass by journal, born-digital** (descriptive only; small cells)\n")
    out.append("| set | journal | n | bibr | GROBID |\n|---|---|---|---|---|")
    for s_ in ("jats_bs_v1", "jats_other_v1"):
        ids = ids_of(work, s_, "born_digital")
        A = cmp.load(str(parts_dir / f"bibr.{s_}.born_digital.json"), ids)
        Bg = cmp.load(str(parts_dir / f"grobid.{s_}.born_digital.json"), ids)
        for j in sorted({man[i] for i in ids}, key=lambda j: -sum(man[i] == j for i in ids)):
            js = [i for i in ids if man[i] == j]
            pa = sum(cmp.passes(A[i]) for i in js)
            pb = sum(cmp.passes(Bg[i]) for i in js)
            na = sum(not A[i].get("missing") for i in js)
            out.append(f"| {s_} | {j} | {len(js)} | {int(pa)}/{len(js)}" + ("" if na else " (no output)")
                       + f" | {int(pb)}/{len(js)} |")
    out.append("")
    # run_info consistency across every bibr out dir (incl. the throughput run whose exports were reused)
    tag_suffix = a.bibr_tag.removeprefix("bibr-")
    dirs = sorted(p.parent for p in (work / "runs" / a.bibr_tag).rglob("run_info.json"))
    tp = work / "runs" / f"throughput-bs120-{tag_suffix}" / "out"
    if (tp / "run_info.json").is_file():
        dirs.append(tp)
    infos = [x for x in (run_info_summary(d) for d in dirs) if x]
    keys = {json.dumps([i["bibr_commit"], i["bibr_version"], i["model"]], sort_keys=True) for i in infos}
    out.append("**bibr run consistency** (commit, version, LLM/OCR settings from each run_info.json): "
               + ("all identical" if len(keys) == 1 else f"{len(keys)} DIFFERENT configurations") + "\n")
    out.append("| out dir | commit | n_ok | n_failed | reason | started | finished |\n|---|---|---|---|---|---|---|")
    for i in infos:
        out.append(f"| {i['dir'].replace(str(work) + '/', '')} | {(i['bibr_commit'] or '?')[:9]} | {i['n_ok']} | "
                   f"{i['n_failed']} | {i['reason']} | {i['started_at']} | {i['finished_at']} |")
    if infos:
        out.append("\nLLM/OCR settings: `" + json.dumps(infos[0]["model"]) + "`\n")
    (parts_dir / "run_info.json").write_text(json.dumps(infos, indent=1) + "\n")
    md = "\n".join(out)
    (parts_dir / "results.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
