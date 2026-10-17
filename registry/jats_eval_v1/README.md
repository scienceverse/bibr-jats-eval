# jats_eval_v1: JATS-gold evaluation sets (jats_bs_v1, jats_other_v1)

> This README was written for our private validation repository. The files it names outside this folder
> (`registry/evaluation_sets.json`, `evidence/`, `gold/SEALED_IDS.txt`, `exclusion_sources.json`) are not
> published. The PDFs and JATS can be downloaded with `scripts/fetch_papers.py`.

**What these are:** behavioral-science papers (`jats_bs_v1`, N=200) and papers from other fields (`jats_other_v1`,
N=100). They come from selected open-access publishers via PMC Open Access, CC BY / CC0 only. The gold comes from
publisher JATS and was checked against the PDF text. These are not a random sample of all literature: they are
born-digital, recent (published 2026-07-02 or later), English-language journal articles from a fixed journal list, and
the gold inherits whatever the publisher's JATS says, after the PDF checks described below.

Frozen 2026-10-14 (UTC), before any GROBID or bibr output existed for a member paper. Both sets were registered in
`registry/evaluation_sets.json` as `blind_holdout` (training_excluded, development_use forbidden). Their first scored
run, the GROBID 0.9.0 baseline at 2026-10-14T22:28Z, moved them to `observed_monitor` (regression_only; still
training-excluded): `evidence/observations/jats-eval-v1-grobid090-*.json`. Every member and
pilot paper is in `gold/SEALED_IDS.txt`, so the training builders subtract them. Only DOIs, PMCIDs, hashes and scores
are committed. The PDFs and raw JATS were kept out of the repository; `scripts/fetch_papers.py` downloads them.

## Files

| file | content |
|---|---|
| `manifest.jsonl` | the 300 frozen members: set, paper_id, doi, pmcid, OpenData version, journal (+ JATS journal title), publisher, field, licence, pub date (earliest JATS electronic/print pub-date), article-type, page count, sha256 of the PDF and the JATS XML, `simulated_scan` flag |
| `pilot_manifest.jsonl` | the 25 pilot papers (same columns), disjoint from the members |
| `jats_bs_v1.ids.txt`, `jats_other_v1.ids.txt` | member ids |
| `*.scans.ids.txt` | the simulated-scan subsets (60 + 30 members) |
| `walk_*.jsonl` | every candidate the selection walk looked at, in walk order, with its eligibility verdict |
| `*.provenance.json` | the gold-backed-set source for `evidence.cohorts` (members = outcome `accepted`; strata = journal cells; pilot papers listed with outcome `pilot`, so they are sealed too) |

Scripts: `scripts/jats_eval/` (discover.py, select_sets.py, build_exclusions.py; its exclusion_sources.json is not
published), with
`scripts/project_core_from_jats.py` (gold) and `scripts/make_simulated_scans.py`.

## Source and selection rule

1. **Source.** PMC Open Access via the public `pmc-oa-opendata` S3 bucket: the latest version prefix per PMCID, with
   the PDF, the JATS XML and the metadata sidecar all from that same version (as in bibr-training's
   `corpus/sources/pmc_oa.py`).
2. **Discovery** (`discover.py`, run 2026-10-14). Europe PMC REST search per journal with `FIRST_PDATE:[2026-07-01 TO
   2026-10-14] AND IN_PMC:y AND OPEN_ACCESS:y AND (LICENSE:"cc by" OR LICENSE:"cc0")`. PLOS ONE is scoped by PLOS
   subject metadata via the PLOS search API: `subject:"Psychology"` for jats_bs_v1, and `subject:"Economics"` minus
   every Psychology-tagged DOI for jats_other_v1. 6,602 candidates.
3. **Walk** (`select_sets.py`, seed `20261015`). Within each set, each journal's candidates are sorted by PMCID and
   shuffled with `random.Random(f"20261015:{set}:{journal}")`. Journals are visited round-robin in a fixed order. At
   each visit a journal advances along its shuffled list to its next eligible paper.
   - The first 20 (bs) or 5 (other) eligible papers drawn are the **pilot**. The walk then continues, and the next
     200 / 100 eligible papers are the **members**.
   - Caps on members: per journal 35 (bs) / 20 (other); per publisher 60 (bs) / 30 (other), with BMC counted as
     Springer Nature. A journal that runs out of candidates drops out of the rotation. In practice no cap bound: the
     big journals stopped at 34 and 13 because the totals were reached.
4. **Eligibility,** checked in this order; the first failing rule is the recorded reason:
   - no OpenData version; retracted; historical OCR; author manuscript;
   - licence not CC BY / CC0 (from the OpenData sidecar);
   - no canonical PDF in the same version;
   - JATS `article-type` not `research-article` or `brief-report`;
   - Royal Society Open Science only: no psychology / cognitive-neuroscience heading;
   - earliest JATS electronic or print pub-date before the cutoff;
   - no DOI;
   - PDF unreadable, or first page with fewer than 200 text-layer characters;
   - a JATS heading that marks non-research content: a denylist covering review, protocol, perspective, opinion,
     editorial, correction, commentary, viewpoint, tutorial, primer, education, letter, reply, news, obituary, case
     report and hypothesis;
   - DOI or PMCID in the exclusion lists;
   - (members only) one of the 25 papers already scored by the plumbing dry run (`never_main`; none was hit).
5. **Freeze.** The manifests, walks and registration were committed and pushed before any member paper was projected,
   run or scored.

### Date cutoff

The cutoff is **published 2026-07-02 or later**, by the earliest JATS `pub-date` that is not a collection date. The
latest publication date in the training data of bibr's fine-tuned extraction models is 2026-07-01, the epub date of
PMC13322780. Training rows carry no dates of their own, so these dates were read from the papers' JATS. Every
evaluation set is excluded by DOI, whatever its dates.

The cutoff is applied to the JATS date, not Europe PMC's first-publication date. Because of that, Springer journals
that deposit in PMC weeks after online publication lost most candidates: Psychonomic Bulletin & Review 31 of 42,
Behavior Research Methods 59 of 61. Their remaining candidates were not research articles, so both contribute 0.

### Journal list (what changed from the default and why)

Default list: Frontiers in Psychology, PLOS ONE (psychology), Collabra: Psychology, Royal Society Open Science
(psychology section), BMC Psychology, JMIR Mental Health, Cognitive Research: P&I, Journal of Cognition.

- **Collabra: Psychology** has 0 papers in PMC OA (it is not deposited in PMC). **Open Mind** (MIT Press, diamond OA)
  replaced it.
- Several defaults are thin after the cutoff: RSOS has 1 eligible psychology paper beyond the pilot, CRPI 1, Journal
  of Cognition 12. Four comparable OA psychology journals in PMC were added to make up N without letting Frontiers or
  PLOS dominate: **Psychonomic Bulletin & Review** and **Behavior Research Methods** (Springer, both contributed 0, see
  above), **Developmental Science** (Wiley) and **Psychological Medicine** (Cambridge).
- jats_other_v1: Ecology and Evolution (ecology/evolution), PLOS Computational Biology (computational
  biology/bioinformatics), eLife (biomedicine), BMC Public Health and Global Health Action (public health), PeerJ
  (life/environmental sciences), Nature Communications (multidisciplinary natural sciences), and PLOS ONE with the
  Economics subject (economics/social science).


**jats_bs_v1**

| journal | publisher | field | PMC OA pool | walked | ineligible (reasons) | pilot | main | scans |
|---|---|---|---|---|---|---|---|---|
| Frontiers in Psychology | Frontiers | psychology | 2225 | 47 | 11 (article_type 10, published_before_cutoff 1) | 2 | 34 | 11 |
| PLOS ONE (Psychology) | PLOS | psychology | 1111 | 38 | 2 (published_before_cutoff 2) | 2 | 34 | 10 |
| BMC Psychology | Springer Nature (BMC) | psychology | 58 | 42 | 7 (article_type 7) | 2 | 33 | 10 |
| Psychological Medicine | Cambridge University Press | psychology | 38 | 38 | 10 (article_type 10) | 2 | 26 | 8 |
| JMIR Mental Health | JMIR Publications | psychology | 46 | 46 | 22 (article_type 12, heading 10) | 2 | 22 | 6 |
| Open Mind | MIT Press | psychology | 21 | 21 | 0 () | 2 | 19 | 6 |
| Developmental Science | Wiley | psychology | 35 | 35 | 15 (published_before_cutoff 15) | 2 | 18 | 6 |
| Journal of Cognition | Ubiquity Press | psychology | 18 | 18 | 4 (published_before_cutoff 2, heading 2) | 2 | 12 | 3 |
| Royal Society Open Science | The Royal Society | psychology | 48 | 48 | 45 (subject 43, article_type 2) | 2 | 1 | 0 |
| Cognitive Research: Principles and Implications | Springer Nature | psychology | 5 | 5 | 2 (article_type 1, published_before_cutoff 1) | 2 | 1 | 0 |
| Psychonomic Bulletin & Review | Springer Nature | psychology | 42 | 42 | 42 (published_before_cutoff 31, article_type 11) | 0 | 0 | 0 |
| Behavior Research Methods | Springer Nature | psychology | 61 | 61 | 61 (published_before_cutoff 59, article_type 2) | 0 | 0 | 0 |
| **total** | | | 3708 | 441 | 221 | 20 | 200 | 60 |

Pages (main): 3163; licences: {'CC BY': 200}; article types: {'research-article': 199, 'brief-report': 1}; pub dates 2026-07-02 to 2026-10-08.

**jats_other_v1**

| journal | publisher | field | PMC OA pool | walked | ineligible (reasons) | pilot | main | scans |
|---|---|---|---|---|---|---|---|---|
| Ecology and Evolution | Wiley | ecology/evolution | 531 | 19 | 5 (article_type 4, published_before_cutoff 1) | 1 | 13 | 4 |
| PeerJ | PeerJ | life/environmental sciences | 283 | 14 | 1 (heading 1) | 0 | 13 | 4 |
| Nature Communications | Springer Nature | multidisciplinary natural sciences | 1092 | 17 | 4 (published_before_cutoff 2, article_type 2) | 0 | 13 | 3 |
| PLOS ONE (Economics) | PLOS | economics/social science | 204 | 14 | 1 (published_before_cutoff 1) | 0 | 13 | 4 |
| PLOS Computational Biology | PLOS | computational biology/bioinformatics | 281 | 14 | 1 (heading 1) | 1 | 12 | 4 |
| eLife | eLife Sciences Publications | biomedicine/life sciences | 299 | 14 | 1 (article_type 1) | 1 | 12 | 6 |
| BMC Public Health | Springer Nature (BMC) | public health | 129 | 14 | 1 (heading 1) | 1 | 12 | 1 |
| Global Health Action | Taylor & Francis | public health | 75 | 18 | 5 (article_type 5) | 1 | 12 | 4 |
| **total** | | | 2894 | 124 | 19 | 5 | 100 | 30 |

Pages (main): 1761; licences: {'CC BY': 100}; article types: {'research-article': 100}; pub dates 2026-07-02 to 2026-10-09.

## Exclusions

The sources are 12 groups: the training data of bibr's fine-tuned models, bibr's training corpus, and every
evaluation set and benchmark frame, RenoBench included. The list of sources names internal data, so it is not
published. Every DOI and PMCID listed anywhere in them was collected by `build_exclusions.py`: **64,986** DOI keys and
**17,939** PMCIDs. Every file is scanned as text, so cited DOIs inside training rows are collected too, which only
makes the rule stricter. Keys are compared in paper-id form (lowercased, `/` -> `_`).

**Result.** 1 of the 6,602 discovered candidates matched an exclusion source: PMC13322780, the 2026-07-01 training
paper. It fails the cutoff anyway and was never walked. 0 walked candidates were excluded by DOI or PMCID.

**Independent check.** A separate leak check was run on all 325 papers (members and pilot) against 33 groups of
training and evaluation sources. It matched on DOI, PMCID, sha256, exact title and fuzzy title, and found 0 hits in
every group.

## Pilot

Before freezing, a fixed-seed pilot was drawn from the same walk: the first 20 eligible jats_bs_v1 papers (2 per
journal) and the first 5 jats_other_v1 papers, plus 5 simulated scans made from 5 of the pilot bs papers. The pilot
is disjoint from the members and listed in `pilot_manifest.jsonl`.

The pilot was allowed to change **plumbing only**:
- the JATS-to-gold projection;
- the JATS-vs-PDF checks;
- the scorer wiring;
- the GROBID wiring.

It was not used to change bibr. The member list was frozen before any member was projected or scored, and later
plumbing fixes do not change it.

An earlier plumbing dry run at a provisional cutoff (2026-07-01) scored 25 papers with GROBID. Two of them are not
in the final pilot: 10.2196_98660 (now excluded by the heading rule) and 10.5334_joc.507 (pub date 2026-07-01). The
walk's `never_main` rule kept all 25 out of the members.

## Simulated scans

60 jats_bs_v1 and 30 jats_other_v1 members were drawn with fixed seeds (`20261015:<set>:simulated-scans`), plus the 5
pilot scans. Each page was:
- rendered at 200 dpi in grayscale;
- skewed uniformly within ±1°;
- given Gaussian noise (σ = 6 on a 0–255 scale);
- JPEG-encoded at quality 70.

The pages were rebuilt into image-only PDFs with no text layer. These are **simulated scans of born-digital papers**,
not real scans: there is no paper warp, bleed-through, uneven lighting or old typefaces. The gold is the same as for
the born-digital PDF.

## Gold and JATS-vs-PDF agreement

See `gold/jats_eval_v1/README.md` (added with the gold).
