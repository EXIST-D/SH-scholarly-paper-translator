# Method notes

## Why this design
The evaluation compares an agent that has this Skill with the same agent without it, inside a fixed budget (64 model
requests, 900 s, 16 384 tokens per response including reasoning). A plain agent typically tries to translate the whole
paper in one answer: it runs into the response limit, drops paragraphs, drifts on terminology and silently changes
numbers. This Skill moves everything that does not need a language model into scripts and keeps the model's job small
and checkable:

| problem in the task | what the Skill does |
|---|---|
| 术语稳 - same term, same rendering everywhere | locked glossary (provided + decided once); each batch card carries only the entries occurring in it; every submitted segment is checked against the locked rendering (and `avoid` forms); `check` re-validates the whole document against the final glossary, so a term chosen late is also enforced early |
| 段落全 - no missing / duplicated / shifted paragraphs | stable ids `S001…`; a plan of batches; resumable state; a segment counts as done only after it passes the checks; missing, duplicated and failing segments are listed; the result is `partial`, never `success`, while anything is missing |
| 关系准 - numbers, units, formulas, citations, negation, qualifiers | formulas, reference entries and running heads are copied/omitted by the tool, never sent to the model; numbers, units, citation markers, cross-references, identifiers, URLs, math symbols are extracted from the source and must reappear; negation/hedge/bound/connective cues are compared; warnings go to a human checklist |
| 可核验 - every paragraph traceable, doubtful parts marked | each row carries id, pages, bbox and the parser block id; sentence-level alignment (`[n]` lines); a `note:`/`flag=uncertain` channel for doubtful renderings; `basis` text per row; review checklist |
| long text, cross-page, cross-column | PDF parsed with reading-order recovery; a paragraph cut by a figure caption, column or page break is re-joined (soft hyphens only where the document does not use the hyphenated compound); previous segments (source and translation) are carried as context in each batch card; batches respect the budget |

## Budget model
`prepare` estimates tokens (≈1.3 per English word, ≈1 per Chinese character), output ≈1.5× the source tokens, a per-batch
overhead of 20 s and 40 tokens/s (assumptions, adjustable with `--tok-per-s`, `--overhead`, `--budget`). If the estimate
exceeds 80 % of the budget, batches are ordered by priority (abstract, introduction, conclusion, discussion, results,
methods, related work) and enlarged (up to ~2 400 source tokens, within the 16 k response limit). A typical request flow is
1 prepare + 1 glossary + one translate/ingest request per batch + a few fix requests + assemble. `assemble` can be run
after any batch, so an honest partial deliverable always exists. These are estimates, not measurements of the evaluation
model's speed.

## Research basis (public sources; search summaries, not re-verified in full)
- BabelDOC / PDFMathTranslate (ACL/EMNLP demo papers) treat formulas and special characters as placeholders outside the
  text the model sees and add terminology extraction and cross-page context: this Skill goes further for formulas (they
  never reach the model) and verifies the rest after the fact.
- Terminology-controlled LLM translation systems inject the glossary at every stage and judge compliance
  deterministically per occurrence (e.g. TermJudge, WMT 2026; AIDAterm, ACL 2026 industry): the glossary here is
  injected per batch and enforced per segment and per document.
- Metric studies on number / named-entity errors and critical errors (ACES; WMT QE critical-error sets) show that
  learned metrics are weak exactly there, and that a direct source-vs-target comparison is the practical check: the
  invariant checks are that comparison.

## Known limits
- The checker is rule-based. It cannot see a reversed meaning, a wrong pronoun antecedent, wrong causality direction,
  or an inconsistent rendering of a term that is not in the glossary (see `checks.md`, measured blind spots).
- Negation/qualifier cue checks exist for English → Chinese only; other pairs get the language-independent checks.
- Sentence alignment relies on a rule-based splitter (abbreviations, initials, decimals handled); unusual text can be
  split differently from the author's intention - the `[n]` mapping is then still 1:1 with the tool's sentences.
- PDF quality limits everything: scanned pages need OCR; formulas/tables that are images are not in the text layer;
  complex tables are reconstructed heuristically.
- Not tested: a real run by the evaluation model (DeepSeek harness) under its budget; languages other than
  English ↔ Chinese; very long (> 30 page) documents beyond planning and parsing; `.tex` sources beyond paragraph handling;
  `.docx` with images or text boxes.
- Development evidence (see `README.md`): the example and 35 real segments of a public paper were translated by the
  developer through the tool; error injection measured the checker. No comparison against a model without the Skill
  was run, so no gain over a baseline is claimed.
