# Checks: what is verified, at which severity, and what cannot be verified

`ingest` runs these on every submitted segment; `check` re-runs them on the whole document against the final glossary.
**ERROR** = must be fixed (the segment is not accepted as done). **WARN** = a human should confirm; accepted, listed in
`review_checklist.md`. All checks are rule-based and deterministic; none calls a model.

| Check | Rule | Severity |
|---|---|---|
| empty / artifacts | empty text; markdown fences, `<think>`, ids like `[S012]` inside the translation | ERROR |
| sentence alignment | `[n]` lines must equal the number of source sentences; without `[n]`, a translation that reads as far fewer sentences | ERROR / WARN |
| table structure | same number of rows and `\|` columns as the source table | ERROR |
| numbers | every source number (decimals, thousands separators, signs, exponents; years) must appear as many times; footnote markers are compared separately | ERROR (WARN only for small whole numbers that may have been spelled out as 三/十) |
| added / reordered numbers | numbers not in the source; same numbers in a different order | WARN |
| units | units next to numbers (km, Hz, °C, %, mg/L ...) must be kept; "7.7% point" → "7.7 个百分点" is accepted | WARN |
| citations | numeric markers `[1,2]` exactly; author-year `(Li et al., 2019)` / `Li et al. (2019)` must keep name and year | ERROR (name only: WARN) |
| cross references | Figure/Table/Equation/Section/Appendix/Algorithm numbers, matched across languages (图 3 = Figure 3, 第 2.1 节 = Section 2.1) | ERROR |
| URLs / DOIs / e-mails | must be unchanged | ERROR |
| identifiers | model names, chemical/gene ids, acronyms ≥ 3 capitals, tokens with digits/hyphens must be kept (3D→三维 accepted); a term declared in the glossary may be rendered | ERROR (2-letter acronyms: WARN) |
| math symbols | Greek letters and operators must keep their counts | WARN |
| glossary | every occurrence of a locked term needs its locked rendering (plural/hyphen/space tolerant, longest match first); `avoid` forms forbidden; terms occurring ≥ 2 times must be rendered as often | ERROR (provisional terms and count mismatch: WARN) |
| omission / addition | Chinese characters per source word far below / above the typical range for English→Chinese | ERROR (< 0.7) / WARN |
| untranslated | no Chinese at all, or mostly Latin text left | ERROR / WARN |
| negation | English negation cues without any Chinese negation cue; fewer cues than the source; explicit Chinese negation (并非, 无法 ...) with none in the source | WARN |
| qualifiers | hedges, approximations, bounds (at least / up to / more than / fewer than), restriction (only), concession, cause, result, condition: cue family missing or fewer cues than the source | WARN |
| duplicates | identical translation text in different segments | ERROR (in `check`) |
| completeness | every translatable segment needs a translation; missing ones are listed and the run is `partial` | in `check`/`assemble` |

Language support: invariants (numbers, units, citations, references, identifiers, URLs, math, glossary, completeness,
alignment) work for any language pair. Length, untranslated and the negation/qualifier cue checks are implemented for
English → Chinese only; for other pairs they are skipped, not guessed.

## Measured detection (development test, not a platform score)
One error at a time was injected into correct translations and the same `validate()` used by `ingest` was run
(`dev_seeded_errors_eval.py`). Two runs: a fictional paper (23 segments, `examples/`) and 35 real segments of a public
paper translated by the developer. "caught" = any warning or error; "error" = error level.

| injected error | cases (fictional / real) | caught fict. / real | error-level fict. / real |
|---|---|---|---|
| a number deleted | 16 / 25 | 100 % / 100 % | 88 % / 96 % |
| a number changed | 16 / 25 | 100 % / 100 % | 88 % / 96 % |
| a citation deleted | 2 / 15 | 100 % / 100 % | 100 % / 100 % |
| glossary term replaced by a variant | 9 / 18 | 100 % / 83 % | 100 % / 61 % |
| figure/table/section reference deleted | 5 / 2 | 100 % / 100 % | 100 % / 100 % |
| identifier / model name deleted | 5 / 20 | 100 % / 85 % | 100 % / 85 % |
| URL / DOI deleted | 1 / 2 | 100 % / 100 % | 100 % / 100 % |
| negation deleted | 5 / 3 | 100 % / 67 % | 0 % / 0 % (warn by design) |
| hedge / bound deleted | 5 / 4 | 60 % / 75 % | 0 % / 0 % (warn by design) |
| unit deleted | 5 / 1 | 100 % / 0 % | 0 % / 0 % (warn by design) |
| segment left untranslated | 13 / 28 | 92 % / 100 % | 92 % / 100 % |
| last sentence dropped, `[n]` lines used | 9 / 18 | 100 % / 100 % | 100 % / 100 % |
| last sentence dropped, no `[n]` lines | 5 / 9 | 100 % / 89 % | 80 % / 67 % |
| two numbers swapped | 9 / 10 | 100 % / 100 % | 33 % / 10 % (warn: order changed) |
| **meaning reversed (降低→升高, 浅→深)** | 3 / 2 | 0 % / 50 % | 0 % / 0 % |

False alarms: on the correct translations 0 segments failed at error level and 1-2 per run carried a warning (an acronym
plural, a legitimately re-ordered pair of numbers).

## Blind spots (say so in the result when it matters)
- Reversed or changed meaning that keeps all numbers, ids and cue words (升高 vs 降低, wrong antecedent of a pronoun, a
  wrong causal direction). Only a human or a second model pass can see this; the checklist lists every negation/qualifier
  warning so a reviewer knows where to look.
- A wrong but consistent rendering of a term that is not in the glossary.
- Fluency, register and terminology quality beyond the glossary.
- Cue checks use word lists; unusual phrasing can slip through or raise a warning that is not a problem.
