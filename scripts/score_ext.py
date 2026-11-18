#!/usr/bin/env python3
"""Score links/URLs and in-text citations against gold/jats_eval_v1_ext (ext_metrics_version 1).

    PYTHONPATH=~/dev/bibr-arena BIBR_DISABLE_DOTENV=1 $PY scripts/score_ext.py --set jats_bs_v1 \
        --kind bibr --pred runs/fast/jats_bs_v1/born_digital --out results/jats_eval_v1_ext/fast/jats_bs_v1.born_digital.json
    ... --kind grobid --pred <grobid>/json --tei <grobid>/tei ...
    ... --kind oracle            (gold scored against itself: every metric must be 1.0)

Reference targets are mapped to gold through evaluation.validation_metrics.match_references, the same pass the
v5 reference metrics use, so a citation can only score if its reference was matched. Rules: gold README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ext_common import is_furniture, norm_text, norm_url, repo_key, shingles  # noqa: E402
from ext_view import bibr_view, grobid_view  # noqa: E402

from evaluation.evaluate import extract_comparable_from_json  # noqa: E402
from evaluation.validation_metrics import match_references  # noqa: E402

VERSION = 2  # v2: placeholder gold refs unwinnable -> excluded; context-free predictions ignored
LOCATE_MIN = 0.40
MIN_SHINGLES = 3


def prf(tp, n_pred, n_gold):
    p = tp / n_pred if n_pred else (1.0 if not n_gold else 0.0)
    r = tp / n_gold if n_gold else (1.0 if not n_pred else 0.0)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


# ------------------------------------------------------------------ links
def _lenient(g: str, preds: set[str]) -> str | None:
    gh = g.replace("-", "")
    for p in preds:
        if p.replace("-", "") == gh:
            return "hyphen"
    for p in preds:
        if len(p) >= 10 and g.startswith(p) and g.split("/")[0] == p.split("/")[0]:
            return "truncated"
        if len(g) >= 10 and p.startswith(g) and g.split("/")[0] == p.split("/")[0]:
            return "overrun"
    return None


def score_links(gold: dict, view: dict) -> dict:
    G = {l["url"] for l in gold["links"]}
    O = set(gold["links_optional"])
    own = gold.get("own_doi") or ""
    P = set()
    for u in view["urls"]:
        if u["in_ref_list"]:
            continue
        n = norm_url(u["href"]) or norm_url(u["text"])
        if n and n not in O and not is_furniture(n, own):
            P.add(n)
    tp = len(G & P)
    len_hits = Counter(_lenient(g, P - G) for g in G - P)
    len_hits.pop(None, None)
    GR = {repo_key(g) for g in G} - {None, ""}
    PR = {repo_key(p) for p in P} - {None, ""}
    return {"link_tp": tp, "link_pred": len(P), "link_gold": len(G),
            "link_lenient_tp": tp + sum(len_hits.values()), **{f"link_{k}": v for k, v in len_hits.items()},
            "repo_tp": len(GR & PR), "repo_pred": len(PR), "repo_gold": len(GR),
            "link_fn": sorted(G - P), "link_fp": sorted(P - G)}


# -------------------------------------------------------------- citations
class Locator:
    def __init__(self, paras: list[dict]):
        self.index: dict[str, set[int]] = defaultdict(set)
        for p in paras:
            for s in shingles(norm_text(p["text"])):
                self.index[s].add(p["para_id"])

    @staticmethod
    def too_short(ctx: str) -> bool:
        """No letters to locate on (e.g. a table cell holding only '[19, 57, 58]')."""
        return len(set(shingles(norm_text(ctx)))) < MIN_SHINGLES

    def locate(self, ctx: str) -> int | None:
        sh = set(shingles(norm_text(ctx)))
        if len(sh) < MIN_SHINGLES:
            return None
        votes = Counter()
        for s in sh:
            for pid in self.index.get(s, ()):
                votes[pid] += 1
        if not votes:
            return None
        pid, v = votes.most_common(1)[0]
        return pid if v / len(sh) >= LOCATE_MIN else None


def score_citations(gold: dict, view: dict, ext2gold: dict[int, int], n_matched_gold: set[int],
                    placeholder: set[int] = frozenset()) -> dict:
    """placeholder: v1 gold bib_ids that are bare {"bib_id": n} entries (no fields to match on). A citation to one
    is a real marker (counts for detection) but no system can be credited for its reference, so it leaves the
    strict `cite` gold, and up to that many unmatched-reference predictions in the same paragraph are forgiven."""
    paras = {p["para_id"]: p for p in gold["paras"]}
    scored_para = defaultdict(bool)
    for c in gold["citations"]:
        scored_para[c["para_id"]] |= c["scored"]
    gold_pairs = Counter((c["para_id"], c["bib_id"]) for c in gold["citations"]
                         if c["scored"] and c["bib_id"] not in placeholder)
    forgive = Counter(c["para_id"] for c in gold["citations"] if c["scored"] and c["bib_id"] in placeholder)
    gold_para_n = Counter(c["para_id"] for c in gold["citations"] if c["scored"])
    loc = Locator(list(paras.values()))
    pred_pairs, pred_para_n = Counter(), Counter()
    n_pred = n_pred_cite = unlocated = ignored = no_ctx = 0
    pred_targets_any = set()
    pred_idx_any = set()
    for c in view["citations"]:
        gb = ext2gold.get(c["bib_idx"]) if c["bib_idx"] is not None else None
        if c["bib_idx"] is not None:
            pred_idx_any.add(c["bib_idx"])
        if gb is not None:
            pred_targets_any.add(gb)
        ctx = c["ctx_left"] + " " + c["ctx_right"]
        if loc.too_short(ctx):
            no_ctx += 1
            continue
        pid = loc.locate(ctx)
        if pid is not None and pid in paras and not scored_para[pid]:
            ignored += 1
            continue
        n_pred += 1
        if pid is None:
            unlocated += 1
            n_pred_cite += 1
            continue
        pred_para_n[pid] += 1
        if gb is not None:
            pred_pairs[(pid, gb)] += 1
            n_pred_cite += 1
        elif forgive[pid] > 0:
            forgive[pid] -= 1
        else:
            n_pred_cite += 1
    tp = sum(min(v, gold_pairs[k]) for k, v in pred_pairs.items())
    tp_det = sum(min(v, gold_para_n[k]) for k, v in pred_para_n.items())
    n_gold = sum(gold_pairs.values())
    n_gold_matchable = sum(v for (p, b), v in gold_pairs.items() if b in n_matched_gold)
    cited = {c["bib_id"] for c in gold["citations"]}
    cited_scored = {c["bib_id"] for c in gold["citations"] if c["scored"]}
    hit_refs = {b for (p, b), v in pred_pairs.items() if gold_pairs[(p, b)]}
    return {"cite_tp": tp, "cite_pred": n_pred_cite, "cite_gold": n_gold, "cite_det_tp": tp_det,
            "cite_det_pred": n_pred, "cite_det_gold": sum(gold_para_n.values()),
            "cite_unlocated": unlocated, "cite_ignored_unscored": ignored, "cite_no_context": no_ctx,
            "cite_gold_matchable": n_gold_matchable,
            "ref_cited_gold": len(cited_scored), "ref_cited_hit": len(hit_refs & cited_scored),
            "cref_tp": len(pred_targets_any & cited), "cref_pred": len(pred_idx_any), "cref_gold": len(cited)}


# ------------------------------------------------------------------ main
def summarise(rows: list[dict]) -> dict:
    S = Counter()
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                S[k] += v
    out = {}
    for name, tp, npred, ngold in (("link", "link_tp", "link_pred", "link_gold"),
                                   ("repo_link", "repo_tp", "repo_pred", "repo_gold"),
                                   ("cite", "cite_tp", "cite_pred", "cite_gold"),
                                   ("cite_detect", "cite_det_tp", "cite_det_pred", "cite_det_gold"),
                                   ("cite_ref", "cref_tp", "cref_pred", "cref_gold")):
        p, r, f = prf(S[tp], S[npred], S[ngold])
        out[f"{name}_p"], out[f"{name}_r"], out[f"{name}_f1"] = round(p, 4), round(r, 4), round(f, 4)
        key = "link_gold" if name in ("link", "repo_link") else "cite_gold"
        rs = [prf(x[tp], x[npred], x[ngold]) for x in rows if x[key]]
        if rs:
            out[f"{name}_f1_macro"] = round(sum(f for _, _, f in rs) / len(rs), 4)
            out[f"{name}_r_macro"] = round(sum(r for _, r, _ in rs) / len(rs), 4)
    out["link_r_lenient"] = round(S["link_lenient_tp"] / S["link_gold"], 4) if S["link_gold"] else None
    for k in ("link_hyphen", "link_truncated", "link_overrun", "cite_unlocated", "cite_ignored_unscored",
              "cite_no_context"):
        out[k] = S[k]
    out["cite_link_acc"] = round(S["cite_tp"] / S["cite_det_tp"], 4) if S["cite_det_tp"] else None
    out["cite_r_matched_refs"] = round(S["cite_tp"] / S["cite_gold_matchable"], 4) if S["cite_gold_matchable"] else None
    out["ref_cited_recall"] = round(S["ref_cited_hit"] / S["ref_cited_gold"], 4) if S["ref_cited_gold"] else None
    out["counts"] = {k: S[k] for k in ("link_gold", "link_pred", "link_tp", "repo_gold", "cite_gold", "cite_pred",
                                       "cite_tp", "cite_det_tp")}
    out["n_papers"] = len(rows)
    out["n_papers_with_links"] = sum(1 for r in rows if r["link_gold"])
    return out


def oracle_view(gold_ext: dict) -> dict:
    paras = {p["para_id"]: p["text"] for p in gold_ext["paras"]}
    return {"urls": [{"href": l["url_raw"], "text": "", "in_ref_list": False} for l in gold_ext["links"]],
            "citations": [{"ctx_left": paras[c["para_id"]][:200], "ctx_right": "", "marker": c["marker"],
                           "bib_idx": c["bib_id"] - 1} for c in gold_ext["citations"]]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", required=True)
    ap.add_argument("--gold-ext", type=Path, default=HERE.parent / "gold/jats_eval_v1_ext")
    ap.add_argument("--v1", type=Path, default=HERE.parent / "gold/jats_eval_v1")
    ap.add_argument("--kind", choices=("bibr", "grobid", "oracle"), required=True)
    ap.add_argument("--pred", type=Path, help="bibr JSON dir, or GROBID converted-JSON dir (for its bib list)")
    ap.add_argument("--tei", type=Path, help="GROBID TEI dir ({id}.grobid.tei.xml)")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ids", type=Path, help="score only these paper ids (one per line), e.g. the scan subset")
    a = ap.parse_args(argv)
    keep = set(a.ids.read_text().split()) if a.ids else None
    rows, missing = [], []
    for gf in sorted((a.gold_ext / a.set).glob("*.json")):
        pid = gf.stem
        if keep is not None and pid not in keep:
            continue
        gext = json.loads(gf.read_text())
        v1 = json.loads((a.v1 / a.set / f"{pid}.json").read_text())
        g_refs = extract_comparable_from_json(v1, is_gold=True)["references"]
        if a.kind == "oracle":
            view, e_refs = oracle_view(gext), g_refs
        else:
            pf = a.pred / f"{pid}.json"
            if not pf.exists():
                missing.append(pid)
                view, e_refs = {"urls": [], "citations": []}, []
            else:
                data = json.loads(pf.read_text())
                e_refs = extract_comparable_from_json(data)["references"]
                if a.kind == "bibr":
                    view = bibr_view(data)
                else:
                    tf = a.tei / f"{pid}.grobid.tei.xml"
                    view = grobid_view(tf) if tf.exists() else {"urls": [], "citations": []}
        m = match_references(e_refs, g_refs)
        ext2gold = {ei: gi + 1 for gi, ei in m.pairs}
        placeholder = {i + 1 for i, r in enumerate(g_refs) if not r}
        row = {"paper_id": pid, **score_links(gext, view),
               **score_citations(gext, view, ext2gold, set(ext2gold.values()), placeholder),
               "refs_matched": len(m.pairs), "refs_gold": len(g_refs)}
        rows.append(row)
    res = {"ext_metrics_version": VERSION, "set": a.set, "kind": a.kind, "label": a.label,
           "pred": str(a.pred or ""), "missing": missing, "summary": summarise(rows), "per_paper": rows}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1) + "\n")
    s = res["summary"]
    print(f"{a.label or a.kind} {a.set}: link P/R/F1 {s['link_p']}/{s['link_r']}/{s['link_f1']} "
          f"(lenient R {s['link_r_lenient']}) repo R {s['repo_link_r']} | cite P/R/F1 {s['cite_p']}/{s['cite_r']}/"
          f"{s['cite_f1']} detect F1 {s['cite_detect_f1']} link-acc {s['cite_link_acc']} cite_ref F1 {s['cite_ref_f1']}"
          f" | missing {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
