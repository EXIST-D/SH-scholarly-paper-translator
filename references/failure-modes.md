# Failure modes and handling

| Symptom | Cause | Action |
|---|---|---|
| `prepare`: "PDF parsing failed" | encrypted / corrupt / unreadable PDF | report the message; ask for the password or a copy; do not guess content |
| `prepare` warns that parts could not be read | scanned pages without OCR engine, image-only pages | report those pages as not processed; install/enable OCR (`pip install rapidocr`) if allowed and re-run |
| `prepare` cannot read a PDF because no PDF library is installed | neither pymupdf nor pdfplumber/pypdf | `pip install pymupdf` if allowed; otherwise extract text yourself (`pdftotext -layout in.pdf out.txt`), run `prepare` on the `.txt`, and report that page/bbox evidence is missing |
| `prepare`: "nothing to translate" | wrong file, empty range, `--pages` outside the document | check the input and `--pages` / `--range` |
| many `omit` segments | `--pages`/`--range` used, or running heads | expected; the reason is stored per segment |
| a paragraph is split in two segments | page/column break the parser could not join | usually merged automatically (continuations); otherwise translate both and `note:` the split |
| a segment ends mid-word / mid-sentence | the source is cut off at a page/range boundary | translate only what is visible, `flag=uncertain`, `note:` the cut |
| `ingest`: UNKNOWN id | id typed wrongly or from another run | use ids exactly as on the card |
| `ingest`: "not translatable" | the block is copied/omitted by design (formula, reference, header) | do not translate it |
| ERROR numbers / citations / refs / identifiers | the translation changed or dropped them | restore exactly; digits stay digits |
| ERROR glossary | locked term not used, or a forbidden variant | use the locked rendering; if the term is wrong, change the glossary and run `check` |
| ERROR omission / untranslated | too short, or still English | translate the whole segment |
| ERROR sentence_count | `[n]` lines do not match the number of source sentences | one line per source sentence; merge/split *inside* a line |
| WARN negation / qualifier | cue words not found in the translation | verify against the source; fix or leave for the human reviewer |
| WARN numbers_order | same numbers, different order | confirm each number still belongs to its quantity |
| `check` says terms inconsistent after a late `terms:` | a term was chosen after earlier segments used another rendering | re-translate those segments (listed) or keep both and report |
| `LOW TIME` | budget almost used | `assemble` now; remaining segments are reported NOT TRANSLATED |
| `assemble` exit code 2 | contract fields it cannot derive | fill them in `answers.json`, run `assemble --answers` again |
| input is another language than expected | detection by character ratio (zh vs other) | pass `--src` / `--tgt` |
| Word file with images or text boxes | only paragraphs and simple tables are read | report images/text boxes as not processed |

Reporting template for a partial run: `status`, `translated n/N`, ids not translated + reason, ids with open errors, items
needing a human, what was tried.
