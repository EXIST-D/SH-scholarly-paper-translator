# Glossary: formats, fields, behaviour

## Input formats (any of these, via `--glossary FILE` or the case file's `glossary` / `terminology` / `termbase` / `terms`)
```
attention head => 注意力头                 # one per line:  =>  ->  →  TAB  ,  :
| source | target | note |                # markdown table
{"entries":[{"src":"attention head","tgt":"注意力头","avoid":["注意头"],"alts_ok":["注意力头部"]}]}   # json
[["attention head","注意力头"]]  or  {"attention head":"注意力头"}  or  [{"source":"..","target":".."}]
```
CSV/TSV: `source,target[,note]`.

## Entry fields
`src`, `tgt` (required) · `status` `locked` (provided / added by you: violations are ERRORS) or `provisional` (proposed with
`terms:` while translating: violations are WARNINGS until you re-add it with `glossary --add`) · `alts_ok` (accepted
alternatives) · `avoid` (forbidden renderings) · `case_sensitive` · `note` · `origin`.

## Matching
Case-insensitive; hyphen / space / underscore are interchangeable (`self-attention` = `self attention`); a plural `s`/`es`
is tolerated; longest term first, non-overlapping. `pre-training` does not match `pre-trained` (add that form as its own
term if it must be locked). A term is satisfied when its `tgt` or any `alts_ok` occurs in the translation of the segment
(whitespace and case ignored). Terms that occur ≥ 2 times in a segment must be rendered at least as often (WARN).

## Commands
`glossary $W --add "src => tgt"` · `--from-file F` · `--avoid "src => wrong1, wrong2"` · `--lint` (same target for different
sources, unused terms) · `--candidates` (frequent terms not yet in the glossary) · `--show`. A second, different
rendering for an existing source is ignored and reported as a conflict: the first locked rendering wins.

## Candidate terms
`prepare` proposes up to 60 candidates: acronym expansions, repeated acronyms, hyphenated compounds and repeated
2-3-word phrases (stop words excluded; tables, captions and footnotes are not mined). They are suggestions, not truth.
