---
name: scholarly-paper-translator
description: Translate a scientific paper (PDF, Word, Markdown/text, LaTeX, JSON) into a verifiable bilingual result - locked glossary enforced by script, long documents split into batches with carried context, stable paragraph/sentence ids with page evidence, deterministic checks for numbers, units, citations, figure/table/equation references, identifiers, negation and qualifiers, a human-review checklist, and an honest list of anything not translated. Use whenever a task asks to translate, localise or produce a bilingual (parallel) version of research text and the result must be consistent, complete and checkable.
---

# scholarly-paper-translator

You do the translating. The tool does what must be deterministic: segmenting with stable ids, deciding which blocks are
**not** translated (formulas, reference entries, running heads), locking terminology and **checking it**, verifying that
numbers / units / citations / cross-references / identifiers / negation / qualifiers survived, planning batches inside
the request and time budget, and assembling a bilingual result with evidence. Every translated segment is validated the
moment you submit it, so errors are fixed once, not discovered at the end.

## When to use
Translating (or producing bilingual output for) research papers, sections, abstracts, captions, tables, notes; keeping
terminology consistent across a long text; any task that says "bilingual", "paragraph-aligned", "glossary", "verify the
translation". Not for casual chat translation of a sentence.

## Quick start
`SK` = the directory of this file (installed as `/skills/weekly-skill`); `W=/app/work/tr`.
```bash
python3 $SK/scripts/tr.py prepare /input/<file> --work $W --case /input/case.json      # segment, plan, candidate terms
python3 $SK/scripts/tr.py glossary $W --add "term => 译名" --add "other term => 译名"   # decide terms ONCE (skip if none)
python3 $SK/scripts/tr.py next $W                     # prints the next batch card: segments, glossary subset, context
python3 $SK/scripts/tr.py ingest $W <<'EOF'           # submit your translation of that batch (format below)
=== S012
[1] translation of sentence 1
[2] translation of sentence 2
EOF
python3 $SK/scripts/tr.py next $W --fix               # ONLY if ingest reported ERRORs: the failing segments + reasons
python3 $SK/scripts/tr.py assemble $W --out /app/output --case /input/case.json         # run early and often
```
`prepare` options: `--tgt zh|en|...` (default: from case.json, else Chinese for English sources and English for Chinese
sources), `--glossary FILE` (json / csv / tsv / "src => tgt" lines / markdown table), `--pages 3-5` or `--range S010-S040`
(only part of the document), `--translate-references`, `--budget 900` (seconds), `--ocr auto|off|force` (scanned PDFs).

## Procedure
1. **Read the task** (`/input/case.json`, `task.md`): language pair, scope (whole paper or a range), glossary, exact
   `output_contract`. Find the input under `/input` (do not assume names). `prepare` reads PDF (text layer, or OCR for
   scans), `.docx`, `.md/.txt/.tex`, `.json`. Read its printed summary: segments to translate / copied / omitted, number
   of batches, time estimate, warnings. If the plan warns about the budget, translate in the given (priority) order and
   run `assemble` after every batch or two; the rest is reported as NOT TRANSLATED - never faked.
2. **Glossary once.** Provided terms (case.json or `--glossary`) are locked automatically. For the candidate terms that
   `prepare` printed, choose one rendering each in a single request and `glossary --add` them. Never leave a term to
   chance: the checker compares every occurrence against the locked rendering. When a tempting wrong variant is
   known, forbid it: `glossary $W --avoid "term => wrong1, wrong2"`.
3. **Translate batch by batch.** `next` prints the card: the task reminder, the glossary entries that occur in this batch,
   the last translated segments as context, and the segments with sentence numbers `[n]`. Translate exactly those and
   submit with `ingest`. Do not reread the whole paper; the card is all you need.
4. **Fix at once.** `ingest` prints every ERROR immediately (missing/changed numbers, citations, figure/table/equation
   references, identifiers, URLs, glossary violations, omission, untranslated text, sentence-count mismatch). Run
   `next --fix`, correct **only** those segments, resubmit. WARN items are things to confirm (units, possibly lost
   negation/qualifier/bound, added numbers ...): fix when they are real, otherwise leave them - they appear in the
   human-review checklist; never delete a warning to hide it.
5. **Check the whole document.** `check $W` re-validates every segment against the *final* glossary (terms added later
   must be honoured earlier), reports missing segments, duplicates, term consistency and sentence alignment.
6. **Assemble.** `assemble $W --out /app/output --case /input/case.json` writes `translation.md`, `bilingual.md`,
   `bilingual.html`, `alignment.json`, `glossary.json`, `review_checklist.md`, `check_report.json` and `result.json`
   (every contract field it can derive, plus `case_id`, `status`, `sources`, `uncertainty`, `change_records`). It lists
   contract fields it cannot derive: put your values in `/app/work/answers.json` (`{"field": value}`) and run `assemble`
   again with `--answers /app/work/answers.json`. Check that nothing is left unfilled.
7. **Report honestly**: status (`success` only if everything is translated and no ERROR remains, else `partial`), what is
   missing and why, which items need a human, which choices were uncertain.

## Block format for `ingest` (no JSON escaping needed)
```
=== S012 flag=uncertain          <- id exactly as on the card; "flag=uncertain" optional
[1] translation of sentence 1    <- when the card shows [n] sentences: ONE line per source sentence, same order
[2] translation of sentence 2
note: why a rendering is uncertain            (optional; mark doubtful choices instead of hiding them)
terms: new term => chosen translation; ...    (optional; ONLY new technical terms; they are locked for the rest of the document)
=== S013
single-sentence segments: just the translation (no [1])
```
Tables: keep the same rows and `|` columns; translate text cells only. Alternatives: `ingest $W file.txt`, or JSONL
`{"id":"S012","ss":["..",".."],"note":"","terms":{"a":"b"}}`. Re-submitting an id replaces its earlier translation.

## Translation rules (the checker enforces most of them)
- Keep exactly: numbers (Arabic numerals stay Arabic), units, citation markers `[1,2]`, `(Author et al., 2019)`, `Figure 3` /
  `Table 2` / `Eq. (4)` / `Section 2.1` numbers (write 图 3, 表 2, 式 (4), 第 2.1 节 or keep the English label), model names,
  acronyms, gene/chemical identifiers, URLs, DOIs, footnote markers (right after the punctuation, as in the source).
- Keep meaning-bearing small words: negation (not, no, without, fail to, cannot), hedges (may, suggest, appear to),
  bounds (at least, up to, more than, fewer than), restriction (only), contrast/cause/result links
  (although, because, therefore). A flipped or dropped one is an error even if the text reads smoothly.
- Use the locked rendering for **every** occurrence, in titles, headings, captions and notes too.
- Translate captions and table header/text cells; leave formulas, code, reference entries and numeric cells alone
  (the tool copies those blocks itself and never sends them to you).
- Do not add, explain or "improve" content. If the source is cut off (page break, unreadable region), translate only
  what is there and say so in a `note:`. If you cannot translate something reliably, translate best effort and flag it.
- Acronym first use: keep the acronym; adding the Chinese expansion in parentheses is fine.

## Exceptions
| Situation | Behaviour | You do |
|---|---|---|
| scanned / image-only PDF | OCR (rapidocr or tesseract) if installed; low-confidence blocks flagged; unreadable pages listed | say OCR was used, treat low confidence as uncertain; if no OCR engine, report the pages as not processed |
| encrypted / corrupt / not a PDF | `prepare` stops with the parser's message | report `refused`/`failed` with the message; do not guess content |
| no PDF library installed | `prepare` fails to parse | `pip install pymupdf`, or `pdftotext -layout` to a `.txt` and `prepare` that (no page/bbox evidence - say so) |
| formulas / tables as images | not in the text layer; listed as unparsed or missing | do not invent them; list in uncertainty |
| cut-off paragraph at a page/range boundary | translate what is visible | `note:` + `flag=uncertain` |
| reference list unparsable | copied verbatim (or not translated) | say so; do not translate half-parsed entries |
| source language ≠ expected / mixed | `prepare` prints the detected language | use `--src`/`--tgt`; mention mixed-language parts |
| budget nearly used | `next` shows `LOW TIME` | `assemble` now; report the rest as NOT TRANSLATED |
| glossary conflicts | the first locked rendering wins; conflicts are printed | decide which is right, edit `glossary.json` if needed, then run `check` |

## Dependencies
Python 3.8+, standard library only for translation workflow. PDF input uses the bundled `scripts/parse_pdf.py` (needs
`pymupdf`, or falls back to `pdfplumber`/`pypdf`); OCR needs `rapidocr` (`pip install rapidocr`) or the `tesseract` CLI.
`.docx`, `.md`, `.txt`, `.tex`, `.json` need nothing extra. No network access is needed at run time.

## Honesty rules (hard)
Never fabricate source text, numbers, pages or scientific data; never translate beyond the source; never report `success`
while segments are missing or failing; never claim scores or benchmark numbers; describe every deviation in
`change_records` / `uncertainty` (the assembler does this from the real state - do not overwrite it with optimism).

More: `README.md` (human guide, measured checker results), `references/checks.md` (every check, severity, blind spots),
`references/glossary-format.md`, `references/output-schema.md`, `references/failure-modes.md`,
`references/method-notes.md`, `examples/minimal-example.md`.
