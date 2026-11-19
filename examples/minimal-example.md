# Minimal example

> **EXAMPLE - illustrative only.** Produced by running this Skill on the fictional `mini_paper.md` in this folder. The
> Chinese translation in `mini_paper.zh.blocks.txt` was written by the developer to exercise the tool; it is **not** a
> platform result, not a score and not an official case. Real inputs arrive as `/input/case.json` plus the paper.

Files: `mini_paper.md` (fictional paper), `glossary.tsv` (7 terms), `mini_paper.zh.blocks.txt` (example translation in
block format), `case.example.json` (made-up contract - the real one is `/input/case.json`).

## 1. Prepare
```bash
python3 scripts/tr.py prepare examples/mini_paper.md --work work/ex --glossary examples/glossary.tsv
```
```json
{"language": "en->zh", "n_segments": 26, "n_translate": 23, "n_copy": 3, "n_omit": 0, "provided_glossary_terms": 7, "plan": {"mode": "document", "n_batches": 1, "source_tokens": 650, "est_output_tokens": 975, "est_seconds": 44, "budget_s": 900, "tok_per_s_assumed": 40.0, "overhead_s_per_batch": 20.0, "batch_tokens": 1100}}
```
(`n_copy` 3 = the display formula and the two reference entries; they are copied verbatim and never sent to the translator.)

## 2. Get the first batch card (shortened here)
```bash
python3 scripts/tr.py next work/ex
```
```
BATCH 1/1 | S001..S024 | ~650 source tokens | elapsed 0s of 900s budget
TASK: translate en -> zh, scientific register. Keep every number, unit, citation marker [n], (Author, year), Figure/Table/Eq./Section number, identifier/acronym and URL exactly; keep negation, hedges (may/suggest), bounds (at least/up to) and causal/concessive links; use the glossary renderings EXACTLY.
GLOSSARY (use exactly; never the 'avoid' forms):
  shear-wave velocity => 剪切波速度
  H/V spectral ratio => H/V 谱比
  receiver function => 接收函数
  sedimentary layer => 沉积层
  joint inversion => 联合反演
  foreland basin => 前陆盆地
  Moho => 莫霍面
SEGMENTS:
[S001] (title)
Shear-Wave Velocity Structure Beneath a Hypothetical Foreland Basin
[S002] (heading)
  ...
OUTPUT: one block per segment, nothing else:
=== S012
[1] translation of sentence 1        (use [n] lines when the segment shows [n] sentences; exactly one per source sentence)
[2] translation of sentence 2
note: why a rendering is uncertain (optional - mark doubtful choices, do not hide them)
terms: source term => chosen translation; ...   (optional - ONLY new technical terms you had to choose; they become locked for the rest of the document)
(single-sentence segments: just the translation text. Tables: same rows and | columns, translate text cells only.)
Submit with: tr.py ingest <work-dir> <<'EOF' ... EOF   (the same tr.py you used for `next`)
```

## 3. Submit a translation - mistakes are reported immediately
A sloppy first attempt for S003 (wrong term `横波速度`, dropped `± 0.3`, `41` became `14`; the flipped negation "均匀平坦" is not an ERROR but a warning for the reviewer):
```bash
python3 scripts/tr.py ingest work/ex <<'EOF'
=== S003
[1] 我们通过联合反演接收函数与 H/V 谱比曲线，估计了 TOY-Basin 台阵（42 个台站，2018-2020）下方的横波速度。
[2] 沉积层厚度为 3.4 km，莫霍面深度约为 14 km。
[3] 我们的结果表明盆地底部均匀平坦，尽管横向变化不超过 1.2 km。
EOF
```
```
stored 1 | ok 0 | warn 0 | ERROR 1 | ignored 0 | progress 0/23 segments
  S003 ERROR numbers: numbers missing/changed: 0.3, 41
  S003 ERROR glossary: term 'shear-wave velocity' must be rendered '剪切波速度' (source: shear-wave velocity)
Fix the ERROR segments: `tr.py next work/ex --fix` shows them with your previous text; resubmit only those.
```
`python3 scripts/tr.py next work/ex --fix` then prints only the failing segment with the reasons; the corrected block is
resubmitted. The full corrected translation (`mini_paper.zh.blocks.txt`) is accepted like this:
```
stored 23 | ok 22 | warn 1 | ERROR 0 | ignored 0 | progress 23/23 segments
```

## 4. Check and assemble
```bash
python3 scripts/tr.py check work/ex
python3 scripts/tr.py assemble work/ex --out out --case examples/case.example.json
```
```
{"translate_segments": 23, "translated": 23, "missing": 0, "with_errors": 0, "with_warnings": 1, "duplicates": 0, "sentence_alignment": "37/37", "terms_checked": 7, "term_consistency": "22/22"}
{"written": "work/ex_out", "status": "success", "translated": "23/23", "with_errors": 0, "with_warnings": 1, "missing": 0, "term_consistency": "22/22", "sentence_alignment": "37/37", "unfilled_contract_fields": ["unknown_extra_field"], "contract_found": true}
UNFILLED contract fields (put them in answers.json and re-run assemble): unknown_extra_field
```
`case.example.json` asks for a field (`unknown_extra_field`) that cannot be derived, so `assemble` reports it and exits
with code 2 instead of inventing a value; put it into `answers.json` and run `assemble --answers answers.json`.

## 5. What the bilingual output looks like (`out/bilingual.md`, excerpt)
```
### S003 · paragraph · p- · §Abstract

**SRC** We estimate the shear-wave velocity beneath the TOY-Basin array (42 stations, 2018-2020) by jointly inverting receiver functions and H/V spectral ratio curves. The sedimentary layer is 3.4 ± 0.3 km thick, and the Moho depth is approximately 41 km. Our results suggest that the basin floor is not uniformly flat, although the lateral variation does not exceed 1.2 km.

**TGT** 我们通过联合反演接收函数与 H/V 谱比曲线，估计了 TOY-Basin 台阵（42 个台站，2018-2020）下方的剪切波速度。 沉积层厚度为 3.4 ± 0.3 km，莫霍面深度约为 41 km。 我们的结果表明盆地底部并非均匀平坦，尽管横向变化不超过 1.2 km。

| id | source sentence | target sentence |
|---|---|---|
| S003.1 | We estimate the shear-wave velocity beneath the TOY-Basin array (42 stations, 2018-2020) by jointly inverting receiver functions and H/V spectral ratio curves. | 我们通过联合反演接收函数与 H/V 谱比曲线，估计了 TOY-Basin 台阵（42 个台站，2018-2020）下方的剪切波速度。 |
| S003.2 | The sedimentary layer is 3.4 ± 0.3 km thick, and the Moho depth is approximately 41 km. | 沉积层厚度为 3.4 ± 0.3 km，莫霍面深度约为 41 km。 |
| S003.3 | Our results suggest that the basin floor is not uniformly flat, although the lateral variation does not exceed 1.2 km. | 我们的结果表明盆地底部并非均匀平坦，尽管横向变化不超过 1.2 km。 |

> status: ok
> basis: glossary applied: shear-wave velocity→剪切波速度, H/V spectral ratio→H/V 谱比, receiver function→接收函数, sedimentary layer→沉积层, Moho→莫霍面

### S004 · heading · p-
```
`out/review_checklist.md` starts with:
```
# Human review checklist

Generated by tr.py. Automatic checks catch missing/changed numbers, units, citations, cross-references, identifiers, glossary violations, omissions and
possibly lost negation/qualifiers; they do NOT prove the translation is correct. Items below need a human decision.

## 1. Not translated (0)
- none

## 2. Still failing automatic checks (0)
- none

## 3. Warnings to confirm (1)
- S014: numbers_order: the same numbers appear in a different order (0.6 0.2 0.8 -> 0.2 0.8 0.6): check each still belongs to the same quantity

```
