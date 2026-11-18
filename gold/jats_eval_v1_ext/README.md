# jats_eval_v1_ext: links and in-text citation gold

Gold for two targets that `jats_eval_v1` does not cover: **links (URLs and DOIs printed in the
paper body)** and **in-text citations (which reference each citation marker points to, and in
which paragraph)**. It is projected from the publisher JATS of the same public papers by
`scripts/project_ext_from_jats.py` (labeler `jats-ext-proj@1`) and scored by
`scripts/score_ext.py` (`ext_metrics_version` 2).

Only the public sets are covered (`jats_bs_v1`, 200 papers; `jats_other_v1`, 100 papers). The
sealed blind set is not projected, scored or read.

## Files

- `gold/jats_eval_v1_ext/{set}/{id}.json`: `links`, `links_optional`, `own_doi`, `citations`,
  `paras` (the paragraph texts citations are located in), `provenance`.
- `gold/jats_eval_v1_ext_checks/{set}/{id}.json`: projector counters and the list of
  unprinted links (for audit, not scored).

## Link rules

A link is gold when it is **printed in the PDF text** and sits outside the reference list:

- Sources: JATS `ext-link`, `uri`, plus a regex scan of untagged URLs/DOIs in paragraph-like
  elements (`p`, `td`, `th`, `title`, `caption`, `attrib`, `def`, `term`, `meta-value`).
- The printed form is checked against the PDF text layer. A tagged link whose target is not
  printed (word-anchored links such as RRIDs, or hidden hrefs) goes to `links_optional`.
- Optional, never counted either way: reference-list links and DOIs, the article's own DOI and
  anything extending it (`.t003`, `/supp-1`, `#supp-1`), front-matter furniture (licence, ORCID,
  affiliations, history, journal metadata, funding), `self-uri`, publisher supplement download
  links, and e-mail addresses.
- Front-matter links outside that furniture (abstract, data-availability statements) are gold.
- Matching is on a normalised form (`norm_url`: casefolded; whitespace, soft hyphens, scheme,
  `www.`, URL fragments and trailing punctuation removed; every DOI form becomes `doi:10.…`;
  OSF and Zenodo DOIs become their `osf.io/…` and `zenodo.org/records/…` URLs). `repo_link` counts only repository links
  (OSF, GitHub, Zenodo, figshare, Dryad, ...) by repository key.
- Lenient recall also accepts a prediction that is the gold link broken at a hyphen, truncated, or
  run on into the following text.

## Citation rules

- Sources: `xref ref-type="bibr"`, with `rid` mapped to the v1 `bib_id`. Single-marker ranges
  ("19–21") and adjacent dash ranges are expanded to one citation per reference.
- Scored citations are those in body, back-matter and figure/footnote paragraphs that are printed.
  Table cells and front matter are kept but unscored.
- A prediction is located to a gold paragraph by 8-character shingle votes on its context
  (≥ 3 shingles, ≥ 40% of votes). Predictions located in unscored paragraphs are ignored;
  unlocated ones count as false positives.
- Predictions whose context has fewer than 3 shingles are counted as `cite_no_context` and ignored.
- The predicted reference is mapped to gold through the same reference matcher the v1 scorer uses.
- 482 v1 gold references are placeholders (`{"bib_id": n}` with no fields), so nothing can match
  them. Citations to them are left out of `cite` but kept for `cite_detect`, and each one forgives one
  unmatched-reference prediction in its paragraph. `cite_link_acc` is still slightly biased low by them.
- `cite`: multiset match on (paragraph, gold reference). `cite_detect`: marker found in the right
  paragraph, reference ignored. `cite_link_acc`: of detected markers, the share pointing to the
  right reference. `cite_ref`: which references are cited at all, position ignored.

## Noise floor

Scoring the gold against itself (`--kind oracle`) gives link F1 1.0 and citation F1 0.996 on both
sets. The remaining gap is the locator: short or repeated paragraph texts that vote for the wrong
paragraph. Differences between systems smaller than that gap should not be read as real.
