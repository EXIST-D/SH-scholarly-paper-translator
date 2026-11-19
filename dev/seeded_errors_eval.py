#!/usr/bin/env python3
"""Seeded-error evaluation of the validator (a development tool, not part of the Skill runtime).

Takes a finished, correct run (segments.json + translations.json + glossary.json in a work dir), injects one typical translation
error at a time into otherwise correct translations, runs the same validate() that `ingest` uses, and reports how often the
error is caught (any issue / error-level issue). Mutations marked BLIND are errors this kind of rule-based check cannot see.

usage: python3 dev_seeded_errors_eval.py WORK_DIR
"""
import json
import os
import re
import sys

sys.path.insert(0, os.environ.get("TR_SCRIPTS") or next(p for p in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")) if os.path.isdir(p)))
import tr  # noqa: E402
import tlib  # noqa: E402

VARIANTS = {"剪切波速度": "横波速度", "接收函数": "接受函数", "莫霍面": "莫氏面", "沉积层": "沉积岩层", "联合反演": "共同反演", "前陆盆地": "山前盆地", "预训练": "前训练",
            "微调": "精调", "语言模型": "言语模型", "自注意力": "自我注意", "双向": "二向"}
NEG = ["并未", "并非", "不能", "不支持", "不超过", "很少", "不", "未", "无需"]


def first_num(t):
    m = re.search(r"(?<![\w.])\d+(?:\.\d+)?", t)
    return m


def mutate(kind, seg, tr_text, gl=None):
    t = tr_text
    if kind == "drop_number":
        m = first_num(t)
        return t[:m.start()] + t[m.end():] if m and seg["inv"]["numbers"] else None
    if kind == "change_number":
        m = first_num(t)
        if not m or not seg["inv"]["numbers"]:
            return None
        d = m.group(0)
        new = d[:-1] + str((int(d[-1]) + 1) % 10)
        return t[:m.start()] + new + t[m.end():]
    if kind == "drop_citation":
        m = re.search(r"\[\d[\d,\-–]*\]|\([^()]*\d{4}[a-z]?\)", t)
        return t[:m.start()] + t[m.end():] if m and (seg["inv"]["citations"] or seg["inv"]["author_year"]) else None
    if kind == "term_variant":
        for e, _ in (gl.find(seg["text"]) if gl else []):  # only terms the glossary really constrains in this segment
            a = e["tgt"]
            if a in VARIANTS and a in t:
                return t.replace(a, VARIANTS[a], 1)
        return None
    if kind == "drop_last_sentence_aligned":
        return None  # handled with ss
    if kind == "drop_figure_ref":
        m = re.search(r"[图表式]\s?\d+(?:\.\d+)?|第\s?\d+(?:\.\d+)?\s?[节章]", t)
        return t[:m.start()] + t[m.end():] if m and seg["inv"]["refs"] else None
    if kind == "drop_identifier":
        for tok in seg["inv"]["identifiers"]:
            if tok in t and re.search(r"\d|-|[a-z][A-Z]|^[A-Z]{3,}$", tok):
                return t.replace(tok, "该对象", 1)
        return None
    if kind == "drop_url":
        m = re.search(r"https?://\S+|10\.\d{4,}/\S+", t)
        return t[:m.start()] + t[m.end():] if m else None
    if kind == "drop_negation":
        if not tlib.NEG_EN.search(seg["text"]):
            return None
        m = tlib.NEG_ZH.search(t)  # remove a REAL negation cue (not the 不 in 不同)
        return t[:m.start()] + t[m.end():] if m else None
    if kind == "drop_hedge_or_bound":
        if not any(rx[0].search(seg["text"]) for k, rx in tlib.QUAL_RE.items() if k in ("possibility/hedge", "approximation", "lower bound", "upper bound", "restriction")):
            return None
        for w in ("可能", "约", "至少", "至多", "少于", "仅", "表明", "大约", "超过", "不超过"):
            if w in t:
                return t.replace(w, "", 1)
        return None
    if kind == "drop_unit":
        m = re.search(r"(?<=\d)\s?(km|Hz|°|%)", t)
        return t[:m.start()] + t[m.end():] if m and seg["inv"]["units"] else None
    if kind == "untranslated":
        return seg["text"] if len(seg["text"].split()) >= 8 else None
    if kind == "blind_swap_numbers":
        nums = re.findall(r"(?<![\w.])\d+(?:\.\d+)?", t)
        if len(nums) >= 2 and nums[0] != nums[1]:
            a, b = nums[0], nums[1]
            return t.replace(a, "\0", 1).replace(b, a, 1).replace("\0", b, 1)
        return None
    if kind == "blind_reverse_meaning":
        for a, b in (("降低", "升高"), ("浅", "深"), ("一致", "不一致"), ("增加", "减少"), ("大于", "小于")):
            if a in t:
                return t.replace(a, b, 1)
        return None
    return None


def main(work):
    d = tr.jload(os.path.join(work, "segments.json"))
    trs = tr.jload(os.path.join(work, "translations.json"))
    gl = tr.load_glossary(work)
    pair = (d["meta"]["src_lang"], d["meta"]["tgt_lang"])
    segs = {s["id"]: s for s in d["segments"] if s["action"] == "translate"}
    kinds = ["drop_number", "change_number", "drop_citation", "term_variant", "drop_figure_ref", "drop_identifier", "drop_url", "drop_negation",
             "drop_hedge_or_bound", "drop_unit", "untranslated", "drop_last_sentence_aligned", "drop_sentence_unaligned",
             "blind_swap_numbers", "blind_reverse_meaning"]
    rows = []
    base_bad = [i for i, r in trs.items() if i in segs and tr.validate(segs[i], r["tr"], r.get("ss"), gl, pair) and any(x["severity"] == "error" for x in tr.validate(segs[i], r["tr"], r.get("ss"), gl, pair))]
    for kind in kinds:
        n = any_hit = err_hit = 0
        for sid, r in trs.items():
            seg = segs.get(sid)
            if seg is None or seg["type"] in ("table",):
                continue
            ss = r.get("ss")
            if kind == "drop_last_sentence_aligned":
                if not ss or len(ss) < 2:
                    continue
                new_ss = ss[:-1]
                new_t = " ".join(new_ss)
                iss = tr.validate(seg, new_t, new_ss, gl, pair)
            elif kind == "drop_sentence_unaligned":
                if not ss or len(ss) < 3:
                    continue
                new_t = " ".join(ss[:-1])
                iss = tr.validate(seg, new_t, None, gl, pair)
            else:
                new_t = mutate(kind, seg, r["tr"], gl)
                if new_t is None or new_t == r["tr"]:
                    continue
                new_ss = None
                iss = tr.validate(seg, new_t, new_ss, gl, pair)
            n += 1
            if iss:
                any_hit += 1
            if any(x["severity"] == "error" for x in iss):
                err_hit += 1
        rows.append((kind, n, any_hit, err_hit))
    print("baseline: %d correct translations already failing at error level: %d" % (len(trs), len(base_bad)))
    print("%-28s %6s %10s %12s" % ("injected error", "cases", "caught", "caught(err)"))
    for kind, n, a, e in rows:
        tag = " BLIND: meaning reversal cannot be seen by rules" if kind == "blind_reverse_meaning" else (" (swapped numbers: warn only)" if kind == "blind_swap_numbers" else "")
        print("%-28s %6d %9.0f%% %11.0f%%%s" % (kind, n, 100.0 * a / n if n else 0, 100.0 * e / n if n else 0, tag))
    json.dump([{"error": k, "cases": n, "caught_any": a, "caught_error": e} for k, n, a, e in rows], open(os.path.join(work, "seeded_eval.json"), "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
