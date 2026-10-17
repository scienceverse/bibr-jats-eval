# bibr vs GROBID on JATS-gold evaluation sets (jats_eval_v1), 2026-10-15

**What was measured:** behavioral-science papers from selected open-access publishers (PMC OA, CC BY/CC0), gold from publisher JATS, checked against the PDF text.

There is also a smaller set of papers from other fields, and simulated scans of a subset, run the same way. None of
this is a random sample of the literature. The papers are recent (published 2026-07-02 to 2026-10-09),
English-language, born-digital research articles from a fixed list of 18 journals. The scans are simulated
(born-digital pages rasterised and degraded), not real scans.

{{HEADLINE}}

## Sets

| set | papers | pages | journals | of which simulated scans (pages) |
|---|---|---|---|---|
| jats_bs_v1 (behavioural science) | 200 | 3,163 | 10 (Frontiers in Psychology 34, PLOS ONE psychology 34, BMC Psychology 33, Psychological Medicine 26, JMIR Mental Health 22, Open Mind 19, Developmental Science 18, Journal of Cognition 12, Royal Society Open Science 1, Cognitive Research: P&I 1) | 60 (891) |
| jats_other_v1 (other fields) | 100 | 1,761 | 8 (Ecology and Evolution, PeerJ, Nature Communications, PLOS ONE economics: 13 each; PLOS Computational Biology, eLife, BMC Public Health, Global Health Action: 12 each) | 30 (538) |
| pilot (plumbing only) | 25 | 450 | 20 bs + 5 other | 5 (120) |

- **Source:** PMC Open Access through the public `pmc-oa-opendata` bucket. The PDF, the JATS and the metadata come
  from the same article version.
- **Licence filter:** CC BY or CC0, from the OpenData sidecar. Every selected paper turned out to be CC BY.
- **Research articles only:** JATS `article-type` research-article or brief-report, plus a heading denylist that
  removes reviews, protocols, viewpoints, tutorials and similar.
- **Date window:** earliest JATS pub-date 2026-07-02 to 2026-10-09. The latest training paper is dated 2026-07-01.
- **Gold frozen** at bibr-validation `ff3b6826` before any bibr output was scored.
- **Selection:** a fixed-seed (`20261015`) round-robin walk over the journals with a cap of 35 / 20 papers per
  journal. The sets were frozen and pushed (bibr-validation `e64f35e`) before any GROBID or bibr output existed.
- **Exclusions:** 64,986 DOI keys and 17,939 PMCIDs, collected from every bibr training source and evaluation set.
  Only 1 of the 6,602 candidates matched, and it was a pre-cutoff training paper that was never walked. A separate
  leak check (DOI, PMCID, sha256, exact and fuzzy title, 33 source groups) found 0 hits.
- **Registration:** both sets were registered as eval-only (`blind_holdout`, training excluded, development
  forbidden) and sealed in `gold/SEALED_IDS.txt`. The GROBID baseline was their first scored run, which moved them to
  `observed_monitor`. They remain excluded from training.
- **Pilot:** 25 papers plus 5 scans, disjoint from the sets, used only to debug the plumbing (projection, PDF checks,
  scorer and GROBID wiring). Neither the pilot nor the main sets changed bibr.

Full selection details: `registry/jats_eval_v1/README.md`. Gold details: `gold/jats_eval_v1/README.md`.

## Gold: publisher JATS checked against the PDF

The JATS was projected into the scorer's gold format. Every value was then looked up in the PDF text layer:

- **Front matter** was looked up on pages 1–2.
- **Reference fields** were looked up in a window around the reference itself.

Rules applied to the gold:

- Reference fields the PDF does not print are dropped. This mostly affects reference DOIs that publishers add from
  Crossref.
- Keywords and ORCIDs the PDF does not print are dropped.
- An article DOI that is not printed is not scored.
- Abbreviated last pages ("437–43") are scored on the first page only, so neither copying nor expanding the range is
  penalised.

{{AGREEMENT}}

## Results: bibr vs GROBID

Setup:

- **bibr:** PR #179 head `e8ebd73` with the merged Qwen3.5-4B student `scienceverse/bibr-extract-qwen35-4b@6ab47a4`
  (bf16 on vLLM, thinking off) and PaddleOCR-VL-1.6. Both servers ran on the workstation's RTX 5090, started with bibr's own
  managed launch arguments. bibr ran on the CPU against them, with the settings `--llm local` resolves to: batch size
  8, memory balanced, OCR paddle, references ner + geom, `--no-crossref`, cold caches. A first attempt using
  `--llm local` itself failed before producing any output, because that bibr venv has no vLLM; it was discarded and
  never scored.
- **GROBID:** 0.9.0 (the full image, CPU only), with consolidation off and `includeRawCitations`/`includeRawAffiliations`
  set to 1.
- **Scoring:** both use the same scorer (bibr-validation `evaluation.evaluate`, metrics v5).
- **paper_pass** is a paper-level pass. It requires title_soft ≥ 0.9, doi_match = 1, authors_fullname_f1 ≥ 0.9 and
  ref_matching_f1 ≥ 0.8, wherever the gold has the field. A paper with no output, or one bibr abstained on, counts as
  a fail.
- **Field means** are over the papers each tool produced output for.
- **Confidence intervals** are 95% percentile bootstrap over papers (10,000 resamples). The difference column is
  paired: papers are resampled jointly, over papers both tools scored.

GROBID has no OCR. On the image-only simulated scans it returns HTTP 500 (no text blocks), so it scores 0 on every
scan and has no field means there. The scan comparison therefore mainly measures bibr's OCR path against "no
output".

{{RESULTS}}

## Throughput

{{THROUGHPUT}}

## Caveats

- **Not a random sample.** These are 18 journals from selected OA publishers, recent papers, all born-digital and
  in English. Older papers, scans of print, non-English papers and publishers outside PMC OA are not represented.
- **The gold is the publisher's JATS.** It was filtered to what the PDF prints, but where the JATS itself is wrong,
  the gold is wrong too. Affiliations are kept even when they are not found on pages 1–2 (3% / 1% are not found
  anywhere in the PDF).
- **The scans are simulated** (200 dpi grayscale, ±1° skew, noise, JPEG q70). Real scans are harder.
- **GROBID uses consolidation off**, which matches bibr's `--no-crossref`. With consolidation on, GROBID's DOIs and
  references would differ.
- **jats_bs_v1 born-digital was run in two parts:** the 120-paper throughput run plus the remaining 80. Both used the
  same bibr commit, model, flags and cold caches (see the run consistency table), and they are scored as one run.
- **Untagged references.** Some publishers deposit some references as plain text, with no author, title or year
  elements. The gold holds an empty reference for each of these, and no tool can match it. This was found after the
  gold freeze and left unchanged.
  - Affected: 42 / 200 psych and 34 / 100 other-field papers (BMC, PLOS, Nature Communications, CRPI).
  - It lowers `ref_matching_f1` for both tools about equally.
  - About 15% of the empty references in psych, and 30% in the other fields, are instead tagged references whose
    fields were all dropped by the PDF check. They are just as unmatchable.
  - The sensitivity rows above leave out every paper with an empty gold reference, whichever the cause.
- **Per-journal failure modes differ by tool.** GROBID fails every Frontiers paper because it reads the handling
  editor and reviewers as authors. bibr fails 8 of the 34 Frontiers papers because its reference segmentation
  returns almost nothing for them; that is a bibr bug for after launch. bibr also leaves abbreviated journal names
  in references empty, which is why it trails on `ref_journal_acc`.
- **The sets are now observed:** they stay sealed from training, but these numbers have been seen.
