# jats_eval_v1 gold (publisher JATS, checked against the PDF text layer)

Gold for `jats_bs_v1` (200), `jats_other_v1` (100) and the pilot (25), one `<paper_id>.json` per paper in the
bibr v10 shape `evaluation.evaluate` reads. Selection and the frozen paper lists: `registry/jats_eval_v1/README.md`.
Built by `scripts/project_core_from_jats.py` from the PMC OpenData JATS of the same article version as the PDF
(the raw JATS and PDFs are not in this repository; `scripts/fetch_papers.py` downloads them). `gold/jats_eval_v1_checks/`
holds the per-paper check results.

The simulated scans (`registry/jats_eval_v1/*.scans.ids.txt`) are scored against the same gold as their born-digital
PDF.

## What the gold contains

- `info`: title, DOI (only if printed in the PDF; otherwise `""` so the scorer skips `doi_match`), keywords.
- `author[]`: given/family name, affiliation text, email (removed from the public copy), ORCID, and a corresponding
  flag. Collaborations are
  authors with an empty given name.
- `text[0]`: the abstract. Structured abstracts are joined as "Heading: body". Graphical and lay summaries are left
  out.
- `bib[]`: authors (family/given), year, title, container, volume, first_page, last_page, doi, built from
  `refsets.jats.fields_from_jats` (the same parser the training sets use).

## The check against the PDF, and what it changed

The gold is publisher JATS, and the extractor sees only the PDF, so every value is looked up in the PDF text layer
(pypdfium2, normalised: casefold, NFKD, no punctuation or whitespace):

- Title, authors, abstract, keywords and affiliations are looked up on pages 1–2.
- Reference fields are looked up in a ±500-character window around the reference itself, anchored by its title,
  then its DOI, then the first author's surname plus the year. References with no anchor are checked against the
  whole text.

Policy (the docstring of the projector is the reference):

| finding | gold action |
|---|---|
| reference DOI not printed | dropped (publishers add Crossref DOIs the reference list never shows) |
| reference title / container / volume / year / pages not printed | that field dropped from that reference |
| reference author surname not printed (e.g. "et al.") | trimmed from that reference's author list |
| reference last page abbreviated in JATS ("437–43") | last page dropped, first page kept (see below) |
| reference last page not printed in full | last page dropped, first page kept |
| page with an "Article" / "p." prefix | prefix stripped; a DOI tagged as a page is dropped |
| article DOI not printed | `info.doi = ""` |
| ORCID not in the text layer | dropped (most PDFs show ORCIDs only as a linked icon) |
| keyword not inside a printed "Keywords" block | dropped: eLife and Nature Communications print no keywords, so their JATS terms are not gold |
| title / author / abstract / affiliation not found on pages 1–2 | kept and flagged only |

Abbreviated last pages: PLOS and BMC (and others) store the reference page range as printed, "437–43". The scorer
needs an exact last page. Requiring the abbreviated "43" penalises an extractor that expands it to "443", and
requiring "443" penalises one that copies the print. To stay neutral, the first page alone is scored for these
references. Before this rule, GROBID's `ref_pages_acc` on jats_bs_v1 was 0.763; after it, 0.921. Article numbers
keep their printed prefix ("e30000"), because that is what the reference list shows.

Inline formulas: `tex-math` alternatives are dropped, so only the MathML text is kept (one Nature Communications
abstract had LaTeX source in it).

## Per-field JATS-vs-PDF disagreement

"Not found in PDF" means the JATS value was not found in the text layer, in the scope given above. For reference
fields, the rate is over references that carry the field in JATS. Reference rows are before dropping, so the gold
holds only the printed part.

**jats_bs_v1** (200 papers, 11525 references)

| field | JATS values | not found in PDF | rate |
|---|---|---|---|
| title (p1-2) | 200 | 0 | 0.0% |
| article DOI (anywhere) | 200 | 0 | 0.0% |
| abstract (p1-2, 85% of chunks) | 200 | 0 | 0.0% |
| author family name (p1-2) | 1009 | 0 | 0.0% |
| author given name, full form (p1-2) | 1007 | 0 | 0.0% |
| affiliation (p1-2) | 1008 | 112 | 11.1% |
| affiliation (anywhere) | 1008 | 31 | 3.1% |
| keyword (p1-2) | 982 | 0 | 0.0% |
| keyword in a Keywords block (else dropped) | 982 | 1 | 0.1% |
| author email | 134 | 0 | 0.0% |
| author ORCID (text layer) | 463 | 420 | 90.7% |
| reference authors | 11088 | 154 | 1.4% |
| reference year | 11082 | 47 | 0.4% |
| reference title | 10969 | 16 | 0.1% |
| reference container | 10271 | 43 | 0.4% |
| reference volume | 9499 | 9 | 0.1% |
| reference pages | 9722 | 33 | 0.3% |
| reference doi | 9946 | 818 | 8.2% |

References located by title 10903, by DOI 203, by surname+year 148, unlocated 271 (2.4%; checked against the whole text). References with some but not all author surnames printed (list trimmed): 115. Last pages abbreviated in JATS (dropped, first page kept): 1313; other last pages not printed in full (dropped): 180.

**jats_other_v1** (100 papers, 6349 references)

| field | JATS values | not found in PDF | rate |
|---|---|---|---|
| title (p1-2) | 100 | 0 | 0.0% |
| article DOI (anywhere) | 100 | 0 | 0.0% |
| abstract (p1-2, 85% of chunks) | 100 | 0 | 0.0% |
| author family name (p1-2) | 728 | 0 | 0.0% |
| author given name, full form (p1-2) | 727 | 0 | 0.0% |
| affiliation (p1-2) | 727 | 94 | 12.9% |
| affiliation (anywhere) | 727 | 10 | 1.4% |
| keyword (p1-2) | 391 | 41 | 10.5% |
| keyword in a Keywords block (else dropped) | 391 | 104 | 26.6% |
| author email | 65 | 0 | 0.0% |
| author ORCID (text layer) | 293 | 167 | 57.0% |
| reference authors | 5986 | 68 | 1.1% |
| reference year | 5980 | 13 | 0.2% |
| reference title | 5940 | 11 | 0.2% |
| reference container | 5572 | 14 | 0.3% |
| reference volume | 5425 | 6 | 0.1% |
| reference pages | 5342 | 11 | 0.2% |
| reference doi | 5273 | 1396 | 26.5% |

References located by title 5899, by DOI 123, by surname+year 66, unlocated 261 (4.1%; checked against the whole text). References with some but not all author surnames printed (list trimmed): 53. Last pages abbreviated in JATS (dropped, first page kept): 765; other last pages not printed in full (dropped): 92.

Reading the table:

- Title, DOI, authors and abstract agree completely.
- Keywords: eLife and Nature Communications print none. The other journals print all of them, except one Frontiers keyword.
- Affiliations disagree most: JATS often adds the department, city, or country in
  a different order, or the PDF prints affiliations after page 2. Those are flagged and kept.
- ORCIDs are dropped almost everywhere: they sit behind icons.
- Missing reference DOIs are concentrated in Nature Communications (765 of 805), BMC Psychology (555 of 1,440), BMC
  Public Health (283 of 577) and Ecology and Evolution (259 of 620), whose reference lists print few or no DOIs.
- Disagreement on every other reference field is under 1.5%.

## Pilot

The 25 pilot papers (`pilot/`) were projected first and scored with GROBID, to debug the plumbing only (projection,
PDF checks, scorer and GROBID wiring). The changes found that way were:

- `institution-id` text (ROR/GRID) removed from affiliations;
- the front-matter check scoped to pages 1–2;
- the reference check scoped to the reference's own window.

After the main sets were projected, three more gold-side fixes followed, all before any bibr output existed:

- `tex-math` dropped from text;
- keywords kept only inside a printed "Keywords" block;
- abbreviated last pages and "Article" page prefixes handled as above.

These were found by inspecting GROBID's scores on the **main sets**, not just the pilot: its weakest fields
(ref_pages_acc, keywords_f1, abstract_rouge_l) and the worst papers in each.

| GROBID 0.9.0 field mean | before the fixes | after |
|---|---|---|
| jats_bs_v1 ref_pages_acc | 0.763 | 0.921 |
| jats_other_v1 ref_pages_acc | 0.750 | 0.909 |
| jats_other_v1 keywords_f1 | 0.570 | 0.827 |

The other GROBID weak spots were GROBID's own errors, and the gold was left alone:

- Abstracts: jats_other_v1 abstract_rouge_l is 0.746 because GROBID returns no abstract for unlabelled Nature
  Communications and eLife abstracts. Those abstracts are printed on page 1.
- Authors: GROBID fails all 34 Frontiers papers by counting the handling editor and reviewers as authors.

The gold was frozen at the commit that adds this paragraph, before any bibr output was scored. If the bibr pilot
forces a plumbing change, GROBID is re-scored on every set and the change is logged here. The gold does not change
after bibr main-set output exists. The paper lists did not change.

## Known issue found after the freeze: empty gold references (gold left unchanged)

Some publishers deposit some references as plain text, an untagged `<mixed-citation>` with no author, title or year
elements. `refsets.jats.fields_from_jats` gets no fields from these, so the gold holds an **empty reference** for
each one. The evaluator reads only structured gold fields, so neither tool can match an empty reference. It still
counts in the gold reference total, which lowers `ref_matching_f1` for every tool on those papers.

| set | papers with at least one empty gold reference | empty / all gold references |
|---|---|---|
| jats_bs_v1 | 42 / 200 (BMC Psychology, PLOS ONE, CRPI) | 236 / 11,525 |
| jats_other_v1 | 34 / 100 (BMC Public Health, Nature Communications, PLOS Comp Biol, PLOS ONE) | 246 / 6,349 |
| pilot | 6 / 25 | 24 / 1,533 |

A second, smaller cause produces the same empty reference. Some tagged references had every field dropped by the
PDF check, because none of their fields was found in the reference's window. Neither cause was fixed.

| set | empty gold references from untagged JATS | from fields all dropped by the PDF check |
|---|---|---|
| jats_bs_v1 | 199 | 37 |
| jats_other_v1 | 173 | 73 |
| pilot | 23 | 1 |

The sensitivity analysis leaves out every paper with an empty gold reference, whichever the cause.

How this came to light: on 2026-10-15 at about 02:50Z, while reading bibr's main-set failures (BMC Psychology
papers with the right reference count but low matching).

What was done about it:

- The gold was frozen before bibr's main output existed, and it was **not changed**.
- The report adds a sensitivity analysis that leaves out these papers, applied the same way to both tools.

On jats_bs_v1, the effect is about the same for both tools. On the 42 affected papers, `ref_matching_f1` is 0.893
for bibr and 0.885 for GROBID.
