# Files and fields

## Work directory (`$W`, created by `prepare`; resumable - run `status` any time)
| file | content |
|---|---|
| `segments.json` | `meta` (languages, counts, parser status/warnings, merged continuations), `plan` (batches, token and time estimate, order), `batches` (`k`, `ids`, `tokens`), `segments` |
| segment | `id` (`S001`…, stable), `type` (title, heading, abstract, paragraph, list_item, caption, footnote, table, formula, reference, front_matter), `action` (`translate` / `copy` / `omit`) + `reason`, `text`, `pages`, `page`, `bbox`, `block` (id in the PDF parse), `merged_blocks`, `section`, `level`, `sentences`, `inv` (numbers, units, citations, refs, identifiers, urls, math, footnote markers), `tokens` |
| `glossary.json` | `entries` (src, tgt, status, avoid, alts_ok, origin) |
| `glossary_candidates.json` | suggested terms with counts |
| `translations.json` | per segment: `tr`, `ss` (per-sentence list), `status` (`ok` / `warn` / `error`), `issues`, `note`, `flag`, `proposed_terms`, `tries` |
| `state.json` | start time and budget (for the elapsed-time display) |
| `parsed/` | PDF parse (`parsed.json`, `parsed.md`) when the input was a PDF - the evidence behind page/bbox |

## Output directory (`assemble --out`)
| file | content |
|---|---|
| `translation.md` | the target text in document order (headings, captions, tables, copied formulas); untranslated segments appear as `[[NOT TRANSLATED]] source`, never silently dropped |
| `bilingual.md` / `bilingual.html` | per segment: id, type, page, section, source, target, a sentence-by-sentence table when aligned, status, issues, basis. HTML is self-contained (no external resources), dark/light aware |
| `alignment.json` | list of rows: `id, type, action, pages, page, bbox, section, source, source_block, translation, sentences[{id: "S012.2", source, target}], status, issues, note, flag, glossary_hits, basis, tries` |
| `glossary.json` | final entries and usage (occurrences, consistent, violating segments) |
| `review_checklist.md` | not translated · still failing · warnings to confirm · translator notes · terminology table · copied/omitted blocks |
| `check_report.json` | summary (`translated`, `missing`, `with_errors`, `with_warnings`, `duplicates`, `sentence_alignment`, `term_consistency`), ids, duplicates, term usage, issues |
| `result.json` | `case_id`, every field of the case's `output_contract`, plus `status`, `sources`, `uncertainty`, `change_records`, and `_meta` (contract fields, **unfilled fields**, files) |

## How `result.json` fields are derived
Contract names are matched case-insensitively. Derived automatically: `status`; `sources` / `input*`; `uncertainty` /
`limitations` / `caveats`; `change_records` / `changes`; `translation` / `translated_text` / `target_text`; `bilingual` /
`parallel*` / `alignment` / `paragraphs` / `segments`; `glossary` / `terminology` / `termbase`; `checks` / `verification` /
`qa` / `validation`; `human_review` / `needs_review` / `review_items` / `todo`; `untranslated` / `omitted`;
`evidence` / `source_locations`; `language`. Values you put in `answers.json` always win. Fields it cannot derive are
set to `null` and listed in `_meta.unfilled_fields` and on stdout (exit code 2) - they are never invented.

`status` = `success` only when every translatable segment has a translation, no segment fails a check, and the input
was read completely; otherwise `partial` (something translated) or `failed` (nothing translated).
