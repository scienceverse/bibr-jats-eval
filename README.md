# bibr JATS benchmark v1

[bibr](https://bibr.org) and GROBID 0.9.0 on 300 recent open-access research articles, scored
against the publishers' own JATS XML. Every paper is CC BY, from PMC Open Access. This repository
has the paper lists, the answer key (gold), per-paper scores for both tools, and the scripts that
built and scored them. bibr's other results, and how strong the evidence for each is, are on its
[limitations page](https://bibr.org/limitations/).

| set | papers | bibr | GROBID 0.9.0 | difference (paired, 95% CI) |
|---|---|---|---|---|
| Behavioural science, born-digital PDFs | 200 | 91.0% | 61.5% | +29.5 pts [+23.0, +36.0] |
| same, without Frontiers in Psychology | 166 | 94.0% | 74.1% | +19.9 pts [+13.3, +25.9] |
| Other fields (8 journals), born-digital PDFs | 100 | 91.0% | 63.0% | +28.0 pts [+19.0, +37.0] |
| Simulated scans of 90 of these papers | 90 | 94.4% | 0% (no OCR) | +94.4 pts [+88.9, +98.9] |

A paper passes only when its title, DOI, author names and reference list all clear their
thresholds: title similarity ≥ 0.9, DOI exact, author full-name F1 ≥ 0.9 and reference matching
F1 ≥ 0.8, each where the gold has the field. A paper a tool returns nothing for counts as a fail.
The full report, with every field, is
[`docs/reports/2026-10-15-jats-eval-v1.md`](docs/reports/2026-10-15-jats-eval-v1.md); read the
notes at its top first.

What the numbers say:

- **bibr's lead is in the front matter:** titles, author names, affiliations and abstracts.
- **References are roughly a tie.** Within matched references, GROBID is more accurate on
  journal names, volumes and pages.
- **GROBID fails every Frontiers in Psychology paper**, because it reads the handling editor and
  reviewers as authors. The row without Frontiers shows the gap without that one failure.
- **On image-only scans, bibr's result barely changes.** GROBID has no OCR, so it cannot read
  them at all.

## What this is, and what it is not

- **The answer key is the publishers' own XML.** A script turns each paper's JATS into gold,
  with no language model involved, and looks up every value in the PDF's text layer. Values the
  PDF does not print are dropped; `gold/jats_eval_v1/README.md` gives the rules. JATS is not
  perfect: where the publisher's XML is wrong, the gold is wrong too.
- **Not a random sample of the literature.** The papers are recent (earliest publication date
  2026-07-02 to 2026-10-09), English, born-digital research articles from a fixed list of 18
  journals at selected open-access publishers. Older papers, real scans of print, other
  languages and other publishers are not represented.
- **The scans are simulated:** born-digital pages rasterised and degraded. Real scans are
  harder.
- **No tool can reach 100%.** Some references are empty in the gold, mostly because the
  publisher deposited them as plain text with no tagged fields, and nothing can match an empty
  reference. Scored against itself, the gold passes 96.5% of the behavioural-science set and
  93.0% of the other-field set: 7 BMC Psychology, 5 BMC Public Health and 2 Nature
  Communications papers cannot pass. The report's sensitivity rows leave out every paper with an
  empty gold reference.
- **Frozen before scoring, not preregistered.** The paper lists and the gold were committed
  before either tool was run. Those commits are in our private validation repository, so their
  timing cannot be checked from outside yet.
- **Held out once.** The bibr numbers above are bibr's first look at these papers: bibr
  `e8ebd73`, a development build after 0.7.2, with the fine-tuned Qwen3.5 4B extractor. The
  newest paper in bibr's training data is dated 2026-07-01, and a leak check against every
  training source found none of these papers. Problems this set exposed were then fixed in bibr
  #193 and released in 0.7.3. The report gives scores after those fixes; they are not held out.
- **Now public.** New scores on this set are not held-out results.
- **bibr's other evaluation sets stay private.** They include paywalled papers or data without
  an open licence. This is the set anyone can check and rerun.

## Contents

| path | what |
|---|---|
| `papers.csv` | one row per paper, the 25 pilot papers included: set, DOI, PMCID, journal, publication date, licence, page count, PDF sha256, title, author surnames and PMC link. It is also the attribution list. |
| `gold/jats_eval_v1/<set>/<paper_id>.json` | the gold, in the format bibr's scorer reads. |
| `gold/jats_eval_v1_checks/` | per-paper results of looking up every gold value in the PDF text. |
| `registry/jats_eval_v1/` | the frozen paper lists, the selection walk, and the manifests with each paper's PMC version and file sha256s. |
| `results/jats_eval_v1/` | per-paper scores (`*.scores.csv`, `*/*.eval.v5.json`) for GROBID 0.9.0 (`grobid090/`), bibr `e8ebd73` (`bibr-e8ebd73-4b/`, the held-out run) and bibr `4077ddf` (`bibr-4077ddf-4b-gpu/`, after the fixes), plus paired comparisons and run settings (`compare*/`). |
| `scripts/` | download, selection, JATS-to-gold, scan simulation, comparison and report scripts. |
| `refsets/` | the JATS reference parser that `scripts/project_core_from_jats.py` imports. |
| `docs/reports/` | the report. |

Not included: the raw bibr and GROBID outputs, and the inputs to the training-exclusion check,
which list our internal training data.

## The papers

All 325 papers (both sets and the pilot) are CC BY. `scripts/fetch_papers.py` downloads each
paper's PDF and JATS XML from PMC Open Access, at the article version we used, and checks them
against the sha256 in the manifest:

```
python scripts/fetch_papers.py --out data/raw --pdf-dir data/pdf
```

On 16 October 2026 every PDF still matched. PMC had reissued the XML of 16 papers under the same
version; the script keeps those with a warning. Rebuilding the gold from the downloaded files with
`scripts/project_core_from_jats.py` gave exactly this repository's gold for all 325 papers,
those 16 included.

The simulated scans can be rebuilt with `scripts/make_simulated_scans.py`, which is seeded per
paper. Their ids are in `registry/jats_eval_v1/*.scans.ids.txt`:

```
python scripts/make_simulated_scans.py --raw data/raw \
    --ids registry/jats_eval_v1/jats_bs_v1.scans.ids.txt --out data/scans/jats_bs_v1
```

Rebuilt on 16 October 2026 with the library versions bibr pins (pypdfium2 5.12.1, numpy 2.3.5,
Pillow 12.3.0), 89 of the 90 scans were byte-identical to ours apart from the PDF's creation date,
and the 90th differed by 5 bytes. With pypdfium2 5.13.0 and numpy 2.5.0, 86 were identical.

Author e-mail addresses were removed from this copy of the gold. Re-scoring therefore cannot
reproduce `email_f1` in the per-paper scores. No other score uses them.

## Re-running the scores

The scorer is the `evaluation/` package of the [bibr repository](https://github.com/scienceverse/bibr),
metrics version 5. Every eval file here records an `eval_code_sha256` of `44eb1232…`, which
matches `evaluation/*.py` on bibr's main branch as of 16 October 2026.

1. Fetch the papers, as above.
2. Run the tool on `data/pdf/<set>/`, writing one bibr-format JSON per paper named
   `<paper_id>.json`. bibr's settings for the held-out run are in
   `results/jats_eval_v1/compare/run_info.json`. For GROBID, bibr's `evaluation/grobid_run.py`
   and `evaluation/grobid_tei.py` run it and convert its output; the settings we used are in
   `results/jats_eval_v1/grobid090/*.grobid_manifest.json`.
3. Score from a bibr checkout, with this repository at `<bench>`. Listing the expected papers
   makes a paper with no output count as a fail:

   ```
   python -c "import json, sys; print(json.dumps(open(sys.argv[1]).read().split()))" \
       <bench>/registry/jats_eval_v1/jats_bs_v1.ids.txt > expected.json
   uv run python -m evaluation.evaluate --results-dir <outputs> \
       --gold-dirs <bench>/gold/jats_eval_v1/jats_bs_v1 --expected-ids expected.json --output scores.json
   ```

   `scripts/jats_eval_compare.py` computes the paired differences and bootstrap intervals.

On 16 October 2026 we re-ran GROBID 0.9.0 this way, from a fresh copy of this repository and the
same image digest. Every published GROBID score came out the same on all 325 papers, apart from
`email_f1`, and GROBID again returned nothing for the scans. We have not re-run bibr this way.

## Licence and credit

- **Gold and paper metadata** are derived from the CC BY articles listed in `papers.csv`. Each
  article's own CC BY licence applies; credit its authors and publisher when you reuse it.
- **Our own additions** (lists, checks and scores) are released under CC BY 4.0.
- **Scripts** are under AGPL-3.0, like bibr.

Details are in [`LICENSE.md`](LICENSE.md).

Please cite as: scienceverse (2026). *bibr JATS benchmark v1*.
https://github.com/scienceverse/bibr-jats-eval
