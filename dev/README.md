# dev tools (not part of the Skill)

- `seeded_errors_eval.py WORK_DIR` - injects one typical translation error at a time into a finished, correct run and measures how
  often the validator used by `tr.py ingest` catches it. Needs a work directory produced by `tr.py prepare` + `ingest`
  (for example the fictional paper in `../examples/`). Set `TR_SCRIPTS=../scripts` if the scripts are elsewhere.
  Reproduce: `python3 ../scripts/tr.py prepare ../examples/mini_paper.md --work W --glossary ../examples/glossary.tsv &&
  python3 ../scripts/tr.py ingest W ../examples/mini_paper.zh.blocks.txt && python3 seeded_errors_eval.py W`
