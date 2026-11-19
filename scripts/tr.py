#!/usr/bin/env python3
"""tr.py - verifiable scholarly translation workflow (segment -> glossary -> batch cards -> validated ingest -> check -> assemble).

The translating model does the translating; this tool does everything that must be deterministic: segmentation with stable
ids, which blocks are NOT translated (formulas, references, running heads), term locking and checking, number/unit/citation/
cross-reference/identifier preservation checks, batch planning inside a request/time budget, resumable state, bilingual output
with paragraph and sentence alignment, a human-review checklist, and a contract-driven result.json.

  tr.py prepare INPUT --work DIR [--case /input/case.json] [--glossary FILE] [--tgt zh] [--pages 1-4] [--range S010-S050]
  tr.py glossary DIR [--add "src => tgt" ...] [--from-file F] [--lock] [--candidates] [--lint]
  tr.py next DIR [--batch K] [--fix]          print the next batch card (or the segments that need fixing)
  tr.py ingest DIR [FILE|-]                   validate + store translations (block format or JSONL), report problems at once
  tr.py check DIR                             whole-document verification (re-checks everything against the final glossary)
  tr.py assemble DIR --out OUT [--case ...] [--answers answers.json]   bilingual files, checklist, result.json
  tr.py status DIR                            progress, budget, what is left
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tlib  # noqa: E402

VERSION = "1.0.0"
SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
CJK_NUMERALS = re.compile(r"[零一二三四五六七八九十百千万两]")


# ------------------------------------------------------------------------------------------------ io helpers
def jload(p, default=None):
    if not os.path.isfile(p):
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def jsave(p, obj):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def norm_text(s):
    """Fold typographic variants so that invariants compare equal (superscripts, ℃, ％, thin spaces ...)."""
    s = s.replace("℃", "°C").replace("℉", "°F").replace("％", "%").replace(" ", " ").replace(" ", " ").replace("×", "×")
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m: "^" + m.group(0).translate(SUPER), s)
    s = re.sub(r"[₀₁₂₃₄₅₆₇₈₉]+", lambda m: "_" + m.group(0).translate(SUB), s)
    return s


def load_state(work):
    st = jload(os.path.join(work, "state.json"), {})
    return st


def find_key(obj, names):
    if isinstance(obj, dict):
        for k in names:
            if k in obj:
                return obj[k]
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


# ------------------------------------------------------------------------------------------------ source loading
def load_source(path, work, args):
    """Return (blocks, meta). Each block: type,text,pages,page,bbox,block,section_title,level,number,rows."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        out = os.path.join(work, "parsed")
        cmd = [sys.executable, os.path.join(HERE, "parse_pdf.py"), path, "--out", out]
        if args.ocr:
            cmd += ["--ocr", args.ocr]
        res = subprocess.run(cmd, capture_output=True, text=True)
        try:
            summary = json.loads(res.stdout.strip().splitlines()[-1])
        except Exception:
            raise SystemExit("PDF parsing failed: %s" % (res.stdout[-300:] + res.stderr[-300:]))
        if summary.get("status") == "failed":
            raise SystemExit("PDF parsing failed: %s" % json.dumps(summary, ensure_ascii=False))
        doc = jload(os.path.join(out, "parsed.json"))
        tables = {t["id"]: t for t in doc.get("tables", [])}
        sect = {s["id"]: s for s in doc.get("sections", [])}
        blocks = []
        for b in doc["blocks"]:
            t = b["type"]
            blk = {"type": {"reference_block": "reference"}.get(t, t), "text": b.get("text", ""), "pages": b.get("pages") or [b["page"]],
                   "page": b["page"], "bbox": b.get("bbox"), "block": b["id"], "level": b.get("level"), "number": b.get("number"),
                   "section_title": (sect.get(b.get("section")) or {}).get("title")}
            if t == "table":
                tb = tables.get(b.get("table_id"))
                if not tb:
                    continue
                blk["text"] = tb["markdown"]
                blk["pages"] = tb["pages"]
            blocks.append(blk)
        meta = {"format": "pdf", "parser_status": doc["status"], "parser_warnings": doc.get("warnings", []), "unparsed": doc.get("unparsed", []),
                "pages": doc["source"]["pages"], "file": os.path.basename(path)}
        return blocks, meta
    if ext == ".docx":
        return docx_blocks(path), {"format": "docx", "file": os.path.basename(path)}
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    if ext == ".json":
        try:
            obj = json.loads(raw)
        except Exception:
            obj = None
        paras = None
        if obj is not None:
            paras = find_key(obj, ["paragraphs", "segments", "sections", "blocks", "content"])
            if paras is None and isinstance(obj, list):
                paras = obj
            if paras is None:
                t = find_key(obj, ["text", "body", "source_text"])
                if isinstance(t, str):
                    raw = t
                    paras = None
        if paras is not None:
            blocks = []
            for i, p in enumerate(paras):
                if isinstance(p, str):
                    blocks.append({"type": "paragraph", "text": p, "pages": [], "page": None, "bbox": None, "block": "j%d" % i})
                elif isinstance(p, dict):
                    txt = p.get("text") or p.get("content") or p.get("source") or ""
                    blocks.append({"type": p.get("type", "paragraph") if p.get("type") in ("heading", "title", "caption", "paragraph", "formula", "table", "list_item", "footnote", "reference", "abstract") else "paragraph",
                                   "text": txt, "pages": [p["page"]] if p.get("page") else [], "page": p.get("page"), "bbox": p.get("bbox"),
                                   "block": str(p.get("id", "j%d" % i)), "level": p.get("level"), "number": None, "section_title": p.get("section")})
            return blocks, {"format": "json", "file": os.path.basename(path)}
    return text_blocks(raw, ext), {"format": ext.lstrip(".") or "txt", "file": os.path.basename(path)}


def docx_blocks(path):
    """Paragraphs of a .docx (standard library only): headings from Heading styles, tables as pipe tables, equations kept as formulas."""
    import zipfile
    from xml.etree import ElementTree as ET
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
    W = "{%s}" % ns["w"]
    try:
        root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    except Exception as e:
        raise SystemExit("cannot read .docx: %s" % e)
    blocks = []

    def ptext(p):
        return "".join(t.text or "" for t in p.iter(W + "t")).strip()

    for el in root.find(W + "body"):
        if el.tag == W + "p":
            txt = ptext(el)
            has_math = el.find(".//m:oMath", ns) is not None
            if not txt and not has_math:
                continue
            style = el.find("w:pPr/w:pStyle", ns)
            sv = (style.get(W + "val") if style is not None else "") or ""
            m = re.match(r"(?i)heading\s*(\d)", sv)
            typ, lvl = "paragraph", None
            if sv.lower() == "title":
                typ, lvl = "title", 0
            elif m:
                typ, lvl = "heading", int(m.group(1))
            elif has_math and not txt:
                typ = "formula"
            elif re.match(r"^\s*(Figure|Fig\.|Table|FIG\.|TABLE)\s*[\dA-Z]+[.:]", txt) or sv.lower() == "caption":
                typ = "caption"
            elif el.find("w:pPr/w:numPr", ns) is not None:
                typ = "list_item"
            blocks.append({"type": typ, "text": txt or "[equation]", "pages": [], "page": None, "bbox": None, "block": "d%d" % len(blocks), "level": lvl, "number": None, "section_title": None})
        elif el.tag == W + "tbl":
            rows = []
            for tr_ in el.iter(W + "tr"):
                rows.append([" ".join(ptext(p) for p in tc.iter(W + "p")).replace("|", "/") for tc in tr_.findall(W + "tc")])
            if rows:
                md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
                blocks.append({"type": "table", "text": "\n".join(md), "pages": [], "page": None, "bbox": None, "block": "d%d" % len(blocks), "level": None, "number": None, "section_title": None})
    return blocks


def text_blocks(raw, ext):
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)  # HTML comments never belong to the text
    blocks, para, fence, in_math = [], [], False, False

    def flush():
        if para:
            txt = "\n".join(para).strip()
            if txt:
                typ = "paragraph"
                if re.match(r"^\s*(\|.+\|\s*\n?)+$", txt):
                    typ = "table"
                elif re.match(r"^\s*(Figure|Fig\.|Table|FIG\.|TABLE)\s*[\dA-Z]+[.:]", txt):
                    typ = "caption"
                elif re.match(r"^\s*([-*•]|\d+[.)])\s+", txt):
                    typ = "list_item"
                elif re.match(r"^\s*[¹²³⁴⁵⁶⁷⁸⁹⁰]", txt):
                    typ = "footnote"
                blocks.append({"type": typ, "text": txt if typ == "table" else re.sub(r"\s*\n\s*", " ", txt), "pages": [], "page": None, "bbox": None,
                               "block": "t%d" % len(blocks), "level": None, "number": None, "section_title": None})
            para.clear()

    in_refs = False
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("```"):
            flush()
            fence = not fence
            continue
        if fence:
            blocks.append({"type": "formula", "text": line, "pages": [], "page": None, "bbox": None, "block": "t%d" % len(blocks), "level": None, "number": None, "section_title": None})
            continue
        if len(s) > 4 and s.startswith("$$") and s.endswith("$$") or (s.startswith("$$") and s.count("$$") == 2) or re.match(r"^\\\[.*\\\]$", s):
            flush()
            blocks.append({"type": "formula", "text": line, "pages": [], "page": None, "bbox": None, "block": "t%d" % len(blocks), "level": None, "number": None, "section_title": None})
            continue
        if s in ("$$", "\\[", "\\]"):
            flush()
            in_math = not in_math
            continue
        if in_math or re.match(r"^\\begin\{(equation|align|gather|multline|eqnarray)\*?\}", s):
            flush()
            blocks.append({"type": "formula", "text": line, "pages": [], "page": None, "bbox": None, "block": "t%d" % len(blocks), "level": None, "number": None, "section_title": None})
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s) or re.match(r"^\\(section|subsection|subsubsection)\*?\{(.*)\}", s)
        if m:
            flush()
            lvl = len(m.group(1)) if m.group(1).startswith("#") else {"section": 1, "subsection": 2, "subsubsection": 3}[m.group(1)]
            title = m.group(2).strip()
            in_refs = bool(re.match(r"^(\d+[.\s]+)?(references|bibliography|参考文献)\s*$", title, re.I))
            is_title = lvl == 1 and not any(b["type"] in ("title", "heading") for b in blocks)
            blocks.append({"type": "title" if is_title else "heading", "text": title, "pages": [], "page": None, "bbox": None, "block": "t%d" % len(blocks), "level": 0 if is_title else lvl, "number": None, "section_title": None})
            continue
        if s.startswith("%") and ext == ".tex":
            continue
        if not s:
            flush()
            continue
        para.append(line)
        if in_refs:
            flush()
            blocks[-1]["type"] = "reference" if blocks and blocks[-1]["text"].startswith(s[:20]) else blocks[-1]["type"]
    flush()
    for b in blocks:
        if b["type"] == "paragraph" and re.match(r"^\s*(\[\d+\]|\d+\.)\s+[A-Z].{20,}\d{4}", b["text"]) and False:
            b["type"] = "reference"
    return blocks


# ------------------------------------------------------------------------------------------------ segments
def looks_translatable_front(text):
    if re.match(r"^\s*(key\s*words?|index terms|keywords|关键词)\b", text, re.I):
        return True
    return len(text.split()) >= 18 and len(re.findall(r"[a-z]{4,}", text)) >= 12 and "@" not in text


def parse_pages(spec):
    if not spec:
        return None
    pages = set()
    for part in str(spec).split(","):
        part = part.strip()
        if re.fullmatch(r"\d+-\d+", part):
            a, b = part.split("-")
            pages.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            pages.add(int(part))
    return pages


TERMINAL = tuple(".?!:;。？！：；”\"')]")
SKIPPABLE = ("caption", "table", "footnote", "formula", "header", "footer", "margin", "figure")


def merge_continuations(blocks):
    """Re-join a paragraph that a figure caption / table / column or page break cut in two (e.g. 'language model-' [Figure 1 ...] 'ing and ...').
    The continuation is merged into the first part; floats in between stay where they are. Soft hyphens are rejoined unless the hyphenated
    compound occurs elsewhere in the document."""
    alltext = " ".join(b.get("text", "") for b in blocks)
    words_hyph = set(w.lower() for w in re.findall(r"[A-Za-z]+-[A-Za-z]+", alltext))
    drop, merged = set(), 0
    for i, b in enumerate(blocks):
        if i in drop or b["type"] not in ("paragraph", "list_item"):
            continue
        txt = b.get("text", "").rstrip()
        if not txt or txt.endswith(TERMINAL) or len(txt) < 15:
            continue
        j = i + 1
        while j < len(blocks) and j <= i + 6 and (j in drop or blocks[j]["type"] in SKIPPABLE):
            j += 1
        if j >= len(blocks) or j > i + 6:
            continue
        q = blocks[j]
        qt = q.get("text", "").lstrip()
        if q["type"] not in ("paragraph", "list_item") or not qt or not (qt[0].islower() or qt[0] in "(,;"):
            continue
        if txt.endswith("-") and re.search(r"[A-Za-z]-$", txt):
            m1 = re.search(r"([A-Za-z]+)-$", txt)
            m2 = re.match(r"([A-Za-z]+)", qt)
            keep = bool(m1 and m2 and (m1.group(1) + "-" + m2.group(1)).lower() in words_hyph)
            joined = txt + qt if keep else txt[:-1] + qt
        else:
            joined = txt + " " + qt
        b["text"] = joined
        b["pages"] = sorted(set((b.get("pages") or []) + (q.get("pages") or [])))
        b.setdefault("merged_blocks", []).append(q.get("block"))
        drop.add(j)
        merged += 1
    return [b for k, b in enumerate(blocks) if k not in drop], merged


def build_segments(blocks, args, src_lang):
    segs, cur_sec, in_refs = [], None, False
    blocks, n_merged = merge_continuations(blocks)
    args.n_merged = n_merged
    page_filter = parse_pages(args.pages)
    for b in blocks:
        t = b["type"]
        text = (b.get("text") or "").strip()
        if not text and t != "table":
            continue
        action, reason = "translate", ""
        if t in ("header", "footer", "margin"):
            action, reason = "omit", "running header/footer/margin text"
        elif t == "formula":
            action, reason = "copy", "display formula: copied verbatim, never sent to the translator"
        elif t == "heading":
            in_refs = bool(re.match(r"^\s*(\d+[.\s]+)?(references?|bibliography|literature cited|参考文献)\s*$", text, re.I))
            cur_sec = text
        elif t == "reference" or (in_refs and t in ("paragraph", "list_item")):
            t = "reference"
            action, reason = ("translate", "") if args.translate_references else ("copy", "reference entry: copied verbatim")
        elif t == "front_matter" and not looks_translatable_front(text):
            action, reason = "copy", "author / affiliation / contact line: copied verbatim"
        elif t == "table" and not re.search(r"[A-Za-z㐀-鿿]{2,}", text):
            action, reason = "copy", "numeric table"
        if page_filter and action != "omit":
            pgs = b.get("pages") or ([b["page"]] if b.get("page") else [])
            if pgs and not (set(pgs) & page_filter):
                action, reason = "omit", "outside the requested page range"
        seg = {"id": "S%03d" % (len(segs) + 1), "type": t, "action": action, "reason": reason, "text": text, "pages": b.get("pages") or [],
               "page": b.get("page"), "bbox": b.get("bbox"), "block": b.get("block"), "merged_blocks": b.get("merged_blocks"),
               "section": b.get("section_title") or cur_sec,
               "level": b.get("level"), "number": b.get("number")}
        if action == "translate":
            if t == "table":
                seg["sentences"] = None
            else:
                sents = tlib.split_sentences(text) if t not in ("heading", "title") else [text]
                merged = []
                for s in sents:  # glue a bare caption label ("Figure 3.") to the following sentence
                    if merged and re.fullmatch(r"(?i)(fig(ure)?s?\.?|table|tab\.?)\s*[A-Z]?\d+[a-z]?[.:]?", merged[-1]):
                        merged[-1] = merged[-1] + " " + s
                    else:
                        merged.append(s)
                seg["sentences"] = merged
            seg["inv"] = tlib.extract_invariants(norm_text(text))
            seg["tokens"] = tlib.est_tokens(text)
        segs.append(seg)
    # range filter by ids (applied after numbering so ids stay stable)
    if args.range:
        m = re.match(r"S?(\d+)\s*-\s*S?(\d+)", args.range)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            for s in segs:
                n = int(s["id"][1:])
                if not (lo <= n <= hi) and s["action"] != "omit":
                    s["action"], s["reason"] = "omit", "outside the requested id range"
    return segs


def plan_batches(segs, batch_tokens, budget_s, tok_per_s, overhead_s, order="auto"):
    tr = [s for s in segs if s["action"] == "translate"]
    total_src = sum(s["tokens"] for s in tr)
    ratio = 1.5  # output tokens per source token (EN->ZH, reasoning not counted)
    est_out = int(total_src * ratio)

    def batches_of(items):
        out, cur, tok = [], [], 0
        for s in items:
            if cur and (tok + s["tokens"] > batch_tokens or len(cur) >= 30):
                out.append(cur)
                cur, tok = [], 0
            cur.append(s)
            tok += s["tokens"]
        if cur:
            out.append(cur)
        return out

    head = [s for s in tr if s["type"] in ("title", "abstract", "heading")]
    rest = [s for s in tr if s["type"] not in ("title", "abstract", "heading")]
    groups = batches_of(tr)  # document order: headings are tiny and ride along with the text they introduce
    est_time = len(groups) * overhead_s + est_out / tok_per_s
    mode = order
    if order == "auto":
        mode = "priority" if est_time > 0.8 * budget_s else "document"
    if mode == "priority":
        def pri(s):
            sec = (s.get("section") or "").lower()
            for i, kw in enumerate(["abstract", "introduction", "conclusion", "discussion", "result", "experiment", "method", "approach", "related", "background"]):
                if kw in sec:
                    return i
            return 5
        rest_sorted = sorted(rest, key=lambda s: (pri(s), int(s["id"][1:])))
        groups = batches_of(head) + batches_of(rest_sorted)
    batches = []
    for k, g in enumerate(groups, 1):
        ids = sorted((s["id"] for s in g))
        batches.append({"k": k, "ids": ids, "tokens": sum(s["tokens"] for s in g)})
    plan = {"mode": mode, "n_batches": len(batches), "source_tokens": total_src, "est_output_tokens": est_out,
            "est_seconds": int(est_time), "budget_s": budget_s, "tok_per_s_assumed": tok_per_s, "overhead_s_per_batch": overhead_s}
    return batches, plan


# ------------------------------------------------------------------------------------------------ glossary io
def entries_from_any(obj):
    out = []
    if obj is None:
        return out
    if isinstance(obj, str):
        if os.path.isfile(obj):
            return load_glossary_file(obj)
        return tlib.parse_glossary_text(obj)
    if isinstance(obj, dict):
        if "entries" in obj and isinstance(obj["entries"], list):
            return entries_from_any(obj["entries"])
        for k, v in obj.items():
            if isinstance(v, str):
                out.append({"src": k, "tgt": v})
            elif isinstance(v, dict):
                e = {"src": k}
                e["tgt"] = v.get("tgt") or v.get("target") or v.get("translation") or v.get("zh") or ""
                for x in ("alts_ok", "avoid", "note", "status", "case_sensitive"):
                    if x in v:
                        e[x] = v[x]
                out.append(e)
        return [e for e in out if e.get("tgt")]
    if isinstance(obj, list):
        for it in obj:
            if isinstance(it, str):
                out += tlib.parse_glossary_text(it)
            elif isinstance(it, (list, tuple)) and len(it) >= 2:
                out.append({"src": str(it[0]), "tgt": str(it[1])})
            elif isinstance(it, dict):
                src = it.get("src") or it.get("source") or it.get("term") or it.get("en") or it.get("english") or it.get("原文") or it.get("术语")
                tgt = it.get("tgt") or it.get("target") or it.get("translation") or it.get("zh") or it.get("chinese") or it.get("译文") or it.get("译名")
                if src and tgt:
                    e = {"src": str(src), "tgt": str(tgt)}
                    for x in ("alts_ok", "avoid", "note", "status", "case_sensitive"):
                        if x in it:
                            e[x] = it[x]
                    out.append(e)
    return out


def load_glossary_file(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    if path.endswith(".json"):
        try:
            return entries_from_any(json.loads(raw))
        except Exception:
            pass
    if path.endswith((".csv", ".tsv")):
        sep = "\t" if path.endswith(".tsv") else ","
        ents = []
        for ln in raw.splitlines():
            parts = [p.strip().strip('"') for p in ln.split(sep)]
            if len(parts) >= 2 and parts[0].lower() not in ("source", "src", "term", "english"):
                ents.append({"src": parts[0], "tgt": parts[1], "note": parts[2] if len(parts) > 2 else ""})
        return ents
    return tlib.parse_glossary_text(raw)


def load_glossary(work):
    g = jload(os.path.join(work, "glossary.json"), {"entries": []})
    return tlib.Glossary(g.get("entries", []))


def save_glossary(work, gl, extra=None):
    d = {"entries": gl.entries}
    if extra:
        d.update(extra)
    jsave(os.path.join(work, "glossary.json"), d)


# ------------------------------------------------------------------------------------------------ validation
def counter_missing(src_list, tgt_list):
    return list((Counter(src_list) - Counter(tgt_list)).elements())


def validate(seg, tr_text, ss, gl, pair):
    """Return a list of issues [{severity, kind, detail}]. severity: error (must fix) | warn (human should confirm)."""
    issues = []
    src = seg["text"]
    t = tr_text.strip()
    if not t:
        return [{"severity": "error", "kind": "empty", "detail": "empty translation"}]
    if re.search(r"```|<think|</think|\[S\d{3}\]|^===", t, re.M):
        issues.append({"severity": "error", "kind": "artifact", "detail": "output contains markup/ids that do not belong in the translation"})
    n_sent = len(seg.get("sentences") or [])
    if ss is None and n_sent >= 3 and seg["type"] != "table" and pair[1] == "zh":
        n_t = len([x for x in re.split(r"(?<=[。！？!?])", t) if x.strip()])
        if n_t < n_sent - 1:
            issues.append({"severity": "warn", "kind": "sentence_count_unaligned", "detail": "source has %d sentences but the translation reads as ~%d: a sentence may be missing (use [n] lines to align)" % (n_sent, n_t)})
    if ss is not None and n_sent >= 1 and len(ss) != n_sent:
        issues.append({"severity": "error", "kind": "sentence_count", "detail": "source has %d sentences, translation gives %d ([n] lines must map 1:1; merge/split inside a sentence line instead)" % (n_sent, len(ss))})
    if seg["type"] == "table":
        sl, tl = [l for l in src.splitlines() if l.strip()], [l for l in t.splitlines() if l.strip()]
        if len(sl) != len(tl) or any(a.count("|") != b.count("|") for a, b in zip(sl, tl)):
            issues.append({"severity": "error", "kind": "table_structure", "detail": "table must keep the same rows and pipe-separated columns (%d lines in source, %d in translation)" % (len(sl), len(tl))})
    s_inv = seg["inv"]
    t_inv = tlib.extract_invariants(norm_text(t))
    miss = counter_missing(s_inv["numbers"], t_inv["numbers"])
    if miss:
        # only small whole numbers can be legitimately spelled out in Chinese (3 -> 三); decimals, years, percentages, large values never
        spelled_ok = [m for m in miss if re.fullmatch(r"\d{1,2}", m)]
        n_cjk = len(CJK_NUMERALS.findall(t))
        excused = len(spelled_ok) == len(miss) and n_cjk >= len(miss)
        issues.append({"severity": "warn" if excused else "error", "kind": "numbers",
                       "detail": "numbers missing/changed: %s%s" % (", ".join(miss[:8]), " (small integers may have been spelled out - keep Arabic numerals)" if excused else "")})
    elif len(s_inv["numbers"]) >= 2 and sorted(s_inv["numbers"]) == sorted(t_inv["numbers"]) and s_inv["numbers"] != t_inv["numbers"]:
        issues.append({"severity": "warn", "kind": "numbers_order", "detail": "the same numbers appear in a different order (%s -> %s): check each still belongs to the same quantity" % (
            " ".join(s_inv["numbers"][:6]), " ".join(t_inv["numbers"][:6]))})
    extra = counter_missing(t_inv["numbers"], s_inv["numbers"])
    if extra and seg["type"] != "heading":
        issues.append({"severity": "warn", "kind": "numbers_added", "detail": "numbers not in the source: %s" % ", ".join(extra[:6])})
    fm = counter_missing(s_inv.get("footnote_markers", []), t_inv.get("footnote_markers", []))
    if fm:
        issues.append({"severity": "warn", "kind": "footnote_markers", "detail": "footnote markers missing: %s (keep them right after the punctuation, as in the source)" % ", ".join(fm)})
    um = counter_missing(s_inv["units"], t_inv["units"])
    if um and "%" in um and re.search(r"百分点|百分之|个点", t):
        um = [u for u in um if u != "%"]  # "7.7% point" -> "7.7 个百分点" is a correct rendering
    if um:
        issues.append({"severity": "warn", "kind": "units", "detail": "units missing: %s" % ", ".join(um[:6])})
    cm = counter_missing(s_inv["citations"], t_inv["citations"])
    if cm:
        issues.append({"severity": "error", "kind": "citations", "detail": "citation markers missing: %s" % ", ".join(cm[:6])})
    rm = [tuple(x) for x in s_inv["refs"] if list(x) not in t_inv["refs"]]
    if rm:
        issues.append({"severity": "error", "kind": "cross_refs", "detail": "figure/table/equation/section references missing: %s" % ", ".join("%s %s" % r for r in rm[:6])})
    um2 = [u for u in s_inv["urls"] if u not in t]
    if um2:
        issues.append({"severity": "error", "kind": "urls", "detail": "URLs/DOIs/e-mails missing: %s" % ", ".join(um2[:3])})
    ay_miss = [p for p in s_inv.get("ay_pairs", []) if p.split("|")[1] not in t]
    if ay_miss:
        issues.append({"severity": "error", "kind": "citations", "detail": "author-year citations changed/missing: %s" % ", ".join(p.replace("|", " ") for p in ay_miss[:5])})
    names = [n for n in s_inv["author_year"] if n not in t]
    if names:
        issues.append({"severity": "warn", "kind": "author_names", "detail": "cited author names not found in Latin form: %s" % ", ".join(names[:5])})
    gl_srcs = {e["src"].lower() for e, _ in gl.find(src)}
    DIM = {"2D": "二维|2 ?维", "3D": "三维|3 ?维", "1D": "一维|1 ?维"}  # "3D" -> "三维" is a correct rendering
    idm = [i for i in s_inv["identifiers"] if i not in t and i.lower() not in gl_srcs and not (i.endswith("s") and i[:-1] in t)
           and not (i in DIM and re.search(DIM[i], t))]
    if idm:
        strong = [i for i in idm if re.search(r"\d|-|[a-z][A-Z]", i) or re.fullmatch(r"[A-Z]{3,}", i)]
        if strong:
            issues.append({"severity": "error", "kind": "identifiers", "detail": "model names/acronyms/identifiers missing: %s (keep them, or declare the rendering with a `terms:` line)" % ", ".join(strong[:6])})
        weak = [i for i in idm if i not in strong]
        if weak:
            issues.append({"severity": "warn", "kind": "acronyms", "detail": "acronyms not kept: %s" % ", ".join(weak[:6])})
    mm = {c: n - t_inv["math"].get(c, 0) for c, n in s_inv["math"].items() if n > t_inv["math"].get(c, 0) and c not in "°^_"}
    if mm:
        issues.append({"severity": "warn", "kind": "math_symbols", "detail": "math symbols missing: %s" % "".join(mm)})
    for v in gl.check(src, t):
        if v["kind"] == "glossary_count":
            issues.append({"severity": "warn", "kind": "glossary_count", "detail": "term '%s' => '%s': %s (use the locked rendering for every occurrence)" % (v["term"], v["expected"], v["matched"])})
        elif v["kind"] == "glossary":
            issues.append({"severity": v["severity"], "kind": "glossary", "detail": "term '%s' must be rendered '%s' (source: %s)" % (v["term"], v["expected"], v["matched"])})
        else:
            issues.append({"severity": "error", "kind": "glossary", "detail": "forbidden rendering '%s' used for '%s' (use '%s')" % (v["found"], v["term"], v["expected"])})
    words = len(re.findall(r"[A-Za-z]{2,}", tlib.URL_RE.sub(" ", src)))
    if pair == ("en", "zh") and words >= 8 and seg["type"] not in ("table",):
        cjk = len(tlib.CJK_RE.findall(t))
        ratio = cjk / max(1, words)
        if ratio < 0.7 and words >= 12:
            issues.append({"severity": "error", "kind": "omission", "detail": "translation is far too short (%.2f Chinese chars per source word; typical 1.3-2.4): likely omitted content" % ratio})
        elif ratio < 0.95:
            issues.append({"severity": "warn", "kind": "length", "detail": "translation is short (%.2f chars/word): check for omissions" % ratio})
        elif ratio > 3.6:
            issues.append({"severity": "warn", "kind": "length", "detail": "translation is long (%.2f chars/word): check for additions" % ratio})
        keep = set(s_inv["identifiers"]) | set(s_inv["author_year"])
        rest = t
        for k in keep:
            rest = rest.replace(k, " ")
        rest = re.sub(r"https?://\S+|\[[\d,\-–\s]+\]|\([^)]*\d{4}[^)]*\)", " ", rest)
        letters = len(re.findall(r"[A-Za-z]", rest))
        if cjk and letters / max(1, letters + cjk) > 0.5 and words >= 8:
            issues.append({"severity": "warn", "kind": "untranslated", "detail": "much Latin text remains in the translation"})
        elif not cjk and words >= 6:
            issues.append({"severity": "error", "kind": "untranslated", "detail": "no Chinese in the translation: segment looks untranslated"})
        for kind, msg in tlib.cue_findings(src, t):
            issues.append({"severity": "warn", "kind": "cue:" + kind, "detail": msg})
    elif pair[1] == "en" and pair[0] == "zh":
        w2 = len(re.findall(r"[A-Za-z]{2,}", t))
        c2 = len(tlib.CJK_RE.findall(src))
        if c2 >= 12 and w2 < 0.25 * c2:
            issues.append({"severity": "error", "kind": "omission", "detail": "translation is far too short for the source length"})
    return issues


def status_of(issues):
    if any(i["severity"] == "error" for i in issues):
        return "error"
    return "warn" if issues else "ok"


# ------------------------------------------------------------------------------------------------ prepare
def cmd_prepare(a):
    work = a.work
    os.makedirs(work, exist_ok=True)
    case = jload(a.case) if a.case and os.path.isfile(a.case) else None
    path = a.input
    if not os.path.isfile(path):
        raise SystemExit("input not found: " + path)
    blocks, meta = load_source(path, work, a)
    body = "\n".join(b["text"] for b in blocks if b["type"] in ("paragraph", "abstract", "title", "heading"))
    src_lang = a.src if a.src != "auto" else tlib.detect_lang(body)
    tgt = a.tgt
    if not tgt and case:
        v = find_key(case, ["target_language", "target_lang", "tgt_lang", "tgt", "to_language", "target"])
        if isinstance(v, str) and v:
            tgt = v
    tgt = (tgt or ("en" if src_lang == "zh" else "zh")).lower()
    tgt = {"chinese": "zh", "zh-cn": "zh", "中文": "zh", "简体中文": "zh", "english": "en", "英文": "en", "英语": "en"}.get(tgt, tgt)
    segs = build_segments(blocks, a, src_lang)
    if not any(s["action"] == "translate" for s in segs):
        raise SystemExit("nothing to translate was found in the input (check the file, --pages / --range)")
    batches, plan = plan_batches(segs, a.batch_tokens, a.budget, a.tok_per_s, a.overhead, a.order)
    bt = a.batch_tokens
    while len(batches) > 14 and bt < 2400 and not a.fixed_batches:  # many small batches waste requests: use bigger ones (response limit is 16k tokens)
        bt = min(2400, int(bt * 1.8))
        batches, plan = plan_batches(segs, bt, a.budget, a.tok_per_s, a.overhead, a.order)
    plan["batch_tokens"] = bt
    # glossary
    gl = tlib.Glossary()
    given = []
    if a.glossary:
        given += load_glossary_file(a.glossary)
    if case:
        v = find_key(case, ["glossary", "terminology", "termbase", "term_list", "terms", "term_table"])
        given += entries_from_any(v)
    n_conflict = 0
    for e in given:
        e = dict(e)
        e["status"] = e.get("status", "locked")
        e["origin"] = "provided"
        if not gl.add(e):
            n_conflict += 1
    save_glossary(work, gl)
    cands = tlib.term_candidates([s["text"] for s in segs if s["action"] == "translate" and s["type"] not in ("table", "caption", "footnote", "list_item")], 60)
    have = {e["src"].lower() for e in gl.entries}
    cands = [c for c in cands if c["src"].lower() not in have]
    jsave(os.path.join(work, "glossary_candidates.json"), cands)
    meta.update({"source_file": os.path.basename(path), "src_lang": src_lang, "tgt_lang": tgt, "version": VERSION,
                 "continuations_merged": getattr(a, "n_merged", 0), "n_segments": len(segs), "n_translate": sum(1 for s in segs if s["action"] == "translate"),
                 "n_copy": sum(1 for s in segs if s["action"] == "copy"), "n_omit": sum(1 for s in segs if s["action"] == "omit")})
    jsave(os.path.join(work, "segments.json"), {"meta": meta, "plan": plan, "batches": batches, "segments": segs})
    jsave(os.path.join(work, "state.json"), {"t0": time.time(), "budget_s": a.budget})
    if not os.path.isfile(os.path.join(work, "translations.json")):
        jsave(os.path.join(work, "translations.json"), {})
    print(json.dumps({"ok": True, "work": work, "language": "%s->%s" % (src_lang, tgt), **{k: meta[k] for k in ("n_segments", "n_translate", "n_copy", "n_omit")},
                      "provided_glossary_terms": len(gl.entries), "glossary_conflicts": n_conflict, "term_candidates": len(cands),
                      "plan": plan, "parser_status": meta.get("parser_status")}, ensure_ascii=False))
    if plan["est_seconds"] > a.budget * 0.8:
        print("WARNING: estimated %ds of generation for a %ds budget: batches are ordered by priority (%s). Translate in order, run `assemble` early "
              "and often; whatever is left is reported as NOT TRANSLATED." % (plan["est_seconds"], a.budget, plan["mode"]))
    if meta.get("unparsed"):
        print("WARNING: parts of the input could not be read (%s). They are NOT in the segments; report them as unprocessed." % json.dumps(meta["unparsed"][:3]))
    if cands:
        print("Top term candidates (decide target renderings once, then `glossary --add`):")
        print("  " + "; ".join("%s (%d)" % (c["src"], c["count"]) for c in cands[:25]))


# ------------------------------------------------------------------------------------------------ glossary cmd
def cmd_glossary(a):
    work = a.work
    gl = load_glossary(work)
    added = 0
    items = []
    for s in a.add or []:
        items += tlib.parse_glossary_text(s)
    if a.from_file:
        items += load_glossary_file(a.from_file)
    conflicts = []
    for e in items:
        e["status"] = "locked"
        e["origin"] = e.get("origin", "added")
        if gl.add(e):
            added += 1
        else:
            old = next((o for o in gl.entries if o["src"].lower() == e["src"].lower()), None)
            if old and old["tgt"] != e["tgt"]:
                conflicts.append("%s: keeps '%s' (ignored '%s')" % (e["src"], old["tgt"], e["tgt"]))
    avoided = 0
    for spec in a.avoid or []:  # "term => wrong1, wrong2": renderings that must never be used for this term
        src, _, bad = spec.partition("=>")
        for e in gl.entries:
            if e["src"].lower() == src.strip().lower():
                e["avoid"] = sorted(set(e.get("avoid", [])) | {b.strip() for b in re.split(r"[,，;；]", bad) if b.strip()})
                avoided += 1
                items.append(e)
                break
        else:
            conflicts.append("avoid: no glossary entry for '%s'" % src.strip())
    if items:
        save_glossary(work, gl)
    out = {"entries": len(gl.entries), "added": added, "avoid_set": avoided, "conflicts": conflicts}
    if a.lint:
        tg = {}
        for e in gl.entries:
            tg.setdefault(e["tgt"], []).append(e["src"])
        out["same_target_for_different_sources"] = {k: v for k, v in tg.items() if len(v) > 1}
        segs = jload(os.path.join(work, "segments.json"))["segments"]
        used = Counter()
        for s in segs:
            if s["action"] == "translate":
                for e, _ in gl.find(s["text"]):
                    used[e["src"]] += 1
        out["unused_terms"] = [e["src"] for e in gl.entries if used[e["src"]] == 0]
    if a.candidates:
        c = jload(os.path.join(work, "glossary_candidates.json"), [])
        have = {e["src"].lower() for e in gl.entries}
        out["candidates"] = [x for x in c if x["src"].lower() not in have][:60]
    if a.show:
        out["terms"] = [{"src": e["src"], "tgt": e["tgt"], "status": e["status"]} for e in gl.entries]
    print(json.dumps(out, ensure_ascii=False))


# ------------------------------------------------------------------------------------------------ next
def load_all(work):
    d = jload(os.path.join(work, "segments.json"))
    if d is None:
        raise SystemExit("no segments.json in %s: run `prepare` first" % work)
    return d, jload(os.path.join(work, "translations.json"), {}), load_glossary(work), load_state(work)


def seg_card(seg, tr=None):
    head = "[%s] (%s%s%s)" % (seg["id"], seg["type"], ", p%s" % ",".join(str(p) for p in seg["pages"]) if seg.get("pages") else "",
                              ", §" + seg["section"][:40] if seg.get("section") and seg["type"] != "heading" else "")
    if seg["type"] == "table":
        return head + "\n" + seg["text"]
    ss = seg.get("sentences") or []
    if len(ss) <= 1:
        return head + "\n" + (ss[0] if ss else seg["text"])
    return head + "\n" + "\n".join("[%d] %s" % (i, s) for i, s in enumerate(ss, 1))


def cmd_next(a):
    d, trs, gl, st = load_all(a.work)
    segs = {s["id"]: s for s in d["segments"]}
    meta = d["meta"]
    elapsed = int(time.time() - st.get("t0", time.time()))
    budget = st.get("budget_s", 900)
    left = budget - elapsed
    if a.fix:
        bad = [i for i, r in trs.items() if r.get("status") == "error" and i in segs]
        if not bad:
            print("No segments need fixing.")
            return
        print("FIX %d segment(s) | elapsed %ds of %ds budget" % (len(bad), elapsed, budget))
        for i in sorted(bad)[: a.limit]:
            r = trs[i]
            print("\n" + seg_card(segs[i]))
            print("  YOUR PREVIOUS TRANSLATION: " + (r.get("tr") or "")[:600])
            for iss in r.get("issues", []):
                if iss["severity"] == "error":
                    print("  ERROR %s: %s" % (iss["kind"], iss["detail"]))
        print("\nResubmit ONLY these segments with `ingest` (same block format).")
        return
    if a.batch:
        b = next((x for x in d["batches"] if x["k"] == a.batch), None)
    else:
        b = next((x for x in d["batches"] if any(trs.get(i, {}).get("status") not in ("ok", "warn") for i in x["ids"])), None)
    if b is None:
        print("ALL BATCHES DONE. Next: `check`, fix remaining errors with `next --fix`, then `assemble`.")
        return
    seg_ids = b["ids"]
    text_all = "\n".join(segs[i]["text"] for i in seg_ids)
    found = gl.find(text_all)
    seen, terms = set(), []
    for e, m in found:
        if e["src"].lower() in seen:
            continue
        seen.add(e["src"].lower())
        terms.append(e)
    prev = []
    ordered = [s for s in d["segments"] if s["action"] == "translate"]
    first_idx = next(i for i, s in enumerate(ordered) if s["id"] == seg_ids[0])
    for s in reversed(ordered[:first_idx]):
        if s["id"] in seg_ids:
            continue
        prev.append(s)
        if len(prev) >= a.context:
            break
    prev.reverse()
    print("BATCH %d/%d | %s | ~%d source tokens | elapsed %ds of %ds budget%s" % (
        b["k"], len(d["batches"]), "%s..%s" % (seg_ids[0], seg_ids[-1]), b["tokens"], elapsed, budget,
        " | LOW TIME: finish this batch, then `assemble`" if left < 150 else ""))
    print("TASK: translate %s -> %s, scientific register. Keep every number, unit, citation marker [n], (Author, year), Figure/Table/Eq./Section number,"
          " identifier/acronym and URL exactly; keep negation, hedges (may/suggest), bounds (at least/up to) and causal/concessive links; use the glossary renderings EXACTLY."
          % (meta["src_lang"], meta["tgt_lang"]))
    if terms:
        print("GLOSSARY (use exactly; never the 'avoid' forms):")
        for e in terms:
            print("  %s => %s%s%s" % (e["src"], e["tgt"], "  [provisional]" if e["status"] != "locked" else "",
                                     "  (avoid: %s)" % ", ".join(e["avoid"]) if e.get("avoid") else ""))
    if prev:
        print("CONTEXT (already translated; do not repeat):")
        for s in prev:
            r = trs.get(s["id"], {})
            print("  [%s] %s" % (s["id"], s["text"][:200] + ("..." if len(s["text"]) > 200 else "")))
            if r.get("tr"):
                print("       => %s" % (r["tr"][:200] + ("..." if len(r["tr"]) > 200 else "")))
    print("SEGMENTS:")
    for i in seg_ids:
        print(seg_card(segs[i]))
    print("""
OUTPUT: one block per segment, nothing else:
=== S012
[1] translation of sentence 1        (use [n] lines when the segment shows [n] sentences; exactly one per source sentence)
[2] translation of sentence 2
note: why a rendering is uncertain (optional - mark doubtful choices, do not hide them)
terms: source term => chosen translation; ...   (optional - ONLY new technical terms you had to choose; they become locked for the rest of the document)
(single-sentence segments: just the translation text. Tables: same rows and | columns, translate text cells only.)
Submit with: tr.py ingest <work-dir> <<'EOF' ... EOF   (the same tr.py you used for `next`)""")


# ------------------------------------------------------------------------------------------------ ingest
def parse_blocks(text):
    recs = []
    cur = None
    for ln in text.splitlines():
        s = ln.rstrip()
        m = re.match(r"^===\s*(S\d{3,})\b\s*(.*)$", s)
        if m:
            cur = {"id": m.group(1), "lines": [], "note": "", "terms": "", "flag": ""}
            fl = re.search(r"flag\s*=\s*(\w+)", m.group(2))
            if fl:
                cur["flag"] = fl.group(1)
            recs.append(cur)
            continue
        if cur is None:
            continue
        mm = re.match(r"^\s*(?:note|备注|注)\s*[:：]\s*(.*)$", s, re.I)
        if mm:
            cur["note"] = (cur["note"] + " " + mm.group(1)).strip()
            continue
        mm = re.match(r"^\s*(?:terms?|术语)\s*[:：]\s*(.*)$", s, re.I)
        if mm:
            cur["terms"] = (cur["terms"] + ";" + mm.group(1)).strip(";")
            continue
        cur["lines"].append(s)
    out = []
    for r in recs:
        lines = r["lines"]
        while lines and not lines[-1].strip():
            lines.pop()
        while lines and not lines[0].strip():
            lines.pop(0)
        ss = None
        body = [l for l in lines]
        if any(re.match(r"^\s*\[\d+\]\s*", l) for l in body):
            ss, cur_s = [], None
            for l in body:
                m = re.match(r"^\s*\[(\d+)\]\s*(.*)$", l)
                if m:
                    cur_s = [m.group(2)]
                    ss.append(cur_s)
                elif cur_s is not None and l.strip():
                    cur_s.append(l.strip())
            ss = [" ".join(x).strip() for x in ss]
            tr = " ".join(ss)
        else:
            tr = "\n".join(body).strip() if r.get("table") else "\n".join(body).strip()
        out.append({"id": r["id"], "tr": tr, "ss": ss, "note": r["note"], "terms": r["terms"], "flag": r["flag"], "_raw_lines": body})
    return out


def parse_jsonl(text):
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        ss = o.get("ss") or o.get("sentences")
        tr = o.get("tr") or o.get("t") or o.get("translation") or (" ".join(ss) if ss else "")
        terms = o.get("terms") or ""
        if isinstance(terms, dict):
            terms = ";".join("%s => %s" % kv for kv in terms.items())
        out.append({"id": o.get("id"), "tr": tr, "ss": ss, "note": o.get("note", ""), "terms": terms, "flag": o.get("flag", "")})
    return out


def cmd_ingest(a):
    d, trs, gl, st = load_all(a.work)
    segs = {s["id"]: s for s in d["segments"]}
    pair = (d["meta"]["src_lang"], d["meta"]["tgt_lang"])
    text = sys.stdin.read() if (not a.file or a.file == "-") else open(a.file, encoding="utf-8").read()
    recs = parse_jsonl(text) if text.lstrip().startswith("{") else parse_blocks(text)
    if not recs:
        raise SystemExit("no records found: use blocks that start with '=== S012' (or JSONL)")
    n = Counter()
    lines = []
    for r in recs:
        sid = r["id"]
        seg = segs.get(sid)
        if seg is None:
            lines.append("%s UNKNOWN id (ignored)" % sid)
            n["unknown"] += 1
            continue
        if seg["action"] != "translate":
            lines.append("%s is not translatable (%s): ignored" % (sid, seg["reason"] or seg["action"]))
            n["skipped"] += 1
            continue
        if seg["type"] == "table":
            r["tr"] = "\n".join(r["_raw_lines"]) if "_raw_lines" in r else r["tr"]
        # new terms proposed by the translator are locked for the rest of the document
        proposed = []
        for pair_s in re.split(r"[;；]", r.get("terms", "") or ""):
            for e in tlib.parse_glossary_text(pair_s):
                e["status"] = "provisional"
                e["origin"] = "proposed at %s" % sid
                if gl.add(e):
                    proposed.append("%s => %s" % (e["src"], e["tgt"]))
                else:
                    old = next((o for o in gl.entries if o["src"].lower() == e["src"].lower()), None)
                    if old and old["tgt"] != e["tgt"]:
                        lines.append("%s term conflict: '%s' is already locked as '%s' (your '%s' ignored)" % (sid, e["src"], old["tgt"], e["tgt"]))
        if r["ss"] is None and len(seg.get("sentences") or []) == 1 and seg["type"] != "table":
            r["ss"] = [r["tr"].strip()]  # a one-sentence segment is aligned 1:1 by construction
        issues = validate(seg, r["tr"], r["ss"], gl, pair)
        stt = status_of(issues)
        trs[sid] = {"id": sid, "tr": r["tr"], "ss": r["ss"], "note": r["note"], "flag": r["flag"], "status": stt, "issues": issues,
                    "proposed_terms": proposed, "ts": int(time.time()), "tries": trs.get(sid, {}).get("tries", 0) + 1}
        n[stt] += 1
        for iss in issues:
            if iss["severity"] == "error" or a.verbose:
                lines.append("%s %s %s: %s" % (sid, iss["severity"].upper(), iss["kind"], iss["detail"]))
    jsave(os.path.join(a.work, "translations.json"), trs)
    save_glossary(a.work, gl)
    total = sum(1 for s in d["segments"] if s["action"] == "translate")
    done = sum(1 for i, r in trs.items() if r["status"] in ("ok", "warn") and i in segs)
    print("stored %d | ok %d | warn %d | ERROR %d | ignored %d | progress %d/%d segments" % (len(recs), n["ok"], n["warn"], n["error"], n["unknown"] + n["skipped"], done, total))
    for ln in lines[:40]:
        print("  " + ln)
    if n["error"]:
        print("Fix the ERROR segments: `tr.py next %s --fix` shows them with your previous text; resubmit only those." % a.work)
    sys.exit(2 if n["error"] else 0)


# ------------------------------------------------------------------------------------------------ check
def run_check(work):
    d, trs, gl, st = load_all(work)
    segs = {s["id"]: s for s in d["segments"]}
    pair = (d["meta"]["src_lang"], d["meta"]["tgt_lang"])
    translate = [s for s in d["segments"] if s["action"] == "translate"]
    missing = [s["id"] for s in translate if s["id"] not in trs]
    errors, warns, rechecked = [], [], {}
    for s in translate:
        r = trs.get(s["id"])
        if not r:
            continue
        iss = validate(s, r["tr"], r.get("ss"), gl, pair)  # re-check against the FINAL glossary
        rechecked[s["id"]] = iss
        if any(i["severity"] == "error" for i in iss):
            errors.append(s["id"])
        elif iss:
            warns.append(s["id"])
    dup = {}
    for i, r in trs.items():
        key = re.sub(r"\s+", "", r["tr"])
        if len(key) >= 30:
            dup.setdefault(key, []).append(i)
    dups = [v for v in dup.values() if len(v) > 1]
    usage = []
    for e in gl.entries:
        occ = ok = 0
        bad = []
        for s in translate:
            r = trs.get(s["id"])
            if not r:
                continue
            hits = [x for x, _ in gl.find(s["text"]) if x is e]
            if hits:
                occ += 1
                viol = [v for v in gl.check(s["text"], r["tr"]) if v["term"] == e["src"]]
                if viol:
                    bad.append(s["id"])
                else:
                    ok += 1
        if occ:
            usage.append({"src": e["src"], "tgt": e["tgt"], "status": e["status"], "segments": occ, "consistent": ok, "violations": bad})
    n_sent = sum(len(s.get("sentences") or []) for s in translate)
    n_aligned = sum(len(s.get("sentences") or []) for s in translate if trs.get(s["id"], {}).get("ss"))
    summary = {"translate_segments": len(translate), "translated": len(translate) - len(missing), "missing": len(missing), "with_errors": len(errors), "with_warnings": len(warns),
               "duplicates": len(dups), "sentence_alignment": "%d/%d" % (n_aligned, n_sent), "terms_checked": len(usage),
               "term_consistency": "%d/%d" % (sum(u["consistent"] for u in usage), sum(u["segments"] for u in usage))}
    return {"summary": summary, "missing": missing, "error_segments": errors, "warning_segments": warns, "duplicates": dups, "term_usage": usage,
            "checked_ids": sorted(rechecked), "issues": {i: v for i, v in rechecked.items() if v}}


def apply_recheck(trs, rep):
    """Store the re-check result for EVERY checked segment (also those that became clean)."""
    for sid in rep["checked_ids"]:
        if sid in trs:
            trs[sid]["issues"] = rep["issues"].get(sid, [])
            trs[sid]["status"] = status_of(trs[sid]["issues"])


def cmd_check(a):
    rep = run_check(a.work)
    jsave(os.path.join(a.work, "check_report.json"), rep)
    d, trs, gl, st = load_all(a.work)
    apply_recheck(trs, rep)
    jsave(os.path.join(a.work, "translations.json"), trs)
    print(json.dumps(rep["summary"], ensure_ascii=False))
    if rep["missing"]:
        print("MISSING (no translation yet): " + ", ".join(rep["missing"][:30]) + (" ..." if len(rep["missing"]) > 30 else ""))
    for sid in rep["error_segments"][:20]:
        for iss in rep["issues"][sid]:
            if iss["severity"] == "error":
                print("  %s ERROR %s: %s" % (sid, iss["kind"], iss["detail"]))
    if rep["duplicates"]:
        print("DUPLICATE translations: %s" % rep["duplicates"][:5])
    bad_terms = [u for u in rep["term_usage"] if u["violations"]]
    for u in bad_terms[:10]:
        print("  TERM '%s' => '%s' not used in: %s" % (u["src"], u["tgt"], ", ".join(u["violations"][:8])))
    sys.exit(2 if (rep["missing"] or rep["error_segments"] or rep["duplicates"]) else 0)


# ------------------------------------------------------------------------------------------------ assemble
def md_cell(s):
    return (s or "").replace("\n", " ")


def build_alignment(d, trs, gl):
    rows = []
    for s in d["segments"]:
        r = trs.get(s["id"])
        row = {"id": s["id"], "type": s["type"], "action": s["action"], "pages": s["pages"], "page": s["page"], "bbox": s["bbox"], "section": s.get("section"),
               "source": s["text"], "source_block": s.get("block"), "reason": s.get("reason") or None}
        if s["action"] == "translate":
            if r:
                row.update({"translation": r["tr"], "status": r["status"], "note": r.get("note") or None, "flag": r.get("flag") or None,
                            "issues": r.get("issues", []), "tries": r.get("tries", 1)})
                ss = s.get("sentences") or []
                if r.get("ss") and len(r["ss"]) == len(ss):
                    row["sentences"] = [{"id": "%s.%d" % (s["id"], i), "source": a, "target": b} for i, (a, b) in enumerate(zip(ss, r["ss"]), 1)]
                seen_terms, hits = set(), []
                for e, _ in gl.find(s["text"]):
                    if e["src"].lower() not in seen_terms:
                        seen_terms.add(e["src"].lower())
                        hits.append({"src": e["src"], "tgt": e["tgt"]})
                row["glossary_hits"] = hits
                basis = []
                if row["glossary_hits"]:
                    basis.append("glossary applied: " + ", ".join("%s→%s" % (h["src"], h["tgt"]) for h in row["glossary_hits"][:6]))
                if r.get("note"):
                    basis.append("translator note: " + r["note"])
                row["basis"] = "; ".join(basis) or "direct translation; invariants (numbers/units/citations/refs/identifiers) verified by script"
            else:
                row.update({"translation": None, "status": "not_translated", "issues": [], "basis": "NOT TRANSLATED (no translation was submitted for this segment)"})
        rows.append(row)
    return rows


def checklist(rows, rep, meta):
    L = ["# Human review checklist", "",
         "Generated by tr.py. Automatic checks catch missing/changed numbers, units, citations, cross-references, identifiers, glossary violations, omissions and",
         "possibly lost negation/qualifiers; they do NOT prove the translation is correct. Items below need a human decision.", ""]
    nt = [r for r in rows if r["action"] == "translate" and r.get("status") == "not_translated"]
    err = [r for r in rows if r.get("status") == "error"]
    warn = [r for r in rows if r.get("status") == "warn"]
    flagged = [r for r in rows if r.get("flag") or r.get("note")]
    L += ["## 1. Not translated (%d)" % len(nt)]
    L += ["- %s (p%s, %s): %s" % (r["id"], ",".join(map(str, r["pages"])) or "?", r["type"], md_cell(r["source"])[:90]) for r in nt] or ["- none"]
    L += ["", "## 2. Still failing automatic checks (%d)" % len(err)]
    for r in err:
        L.append("- %s: %s" % (r["id"], "; ".join("%s: %s" % (i["kind"], i["detail"]) for i in r["issues"] if i["severity"] == "error")))
    if not err:
        L.append("- none")
    L += ["", "## 3. Warnings to confirm (%d)" % len(warn)]
    for r in warn:
        L.append("- %s: %s" % (r["id"], "; ".join("%s: %s" % (i["kind"], i["detail"]) for i in r["issues"])[:300]))
    if not warn:
        L.append("- none")
    L += ["", "## 4. Translator notes / uncertain renderings (%d)" % len(flagged)]
    for r in flagged:
        L.append("- %s [%s]: %s" % (r["id"], r.get("flag") or "note", r.get("note") or ""))
    if not flagged:
        L.append("- none")
    L += ["", "## 5. Terminology", "| source | translation | status | consistent / occurrences | violations |", "|---|---|---|---|---|"]
    for u in rep["term_usage"]:
        L.append("| %s | %s | %s | %d / %d | %s |" % (u["src"], u["tgt"], u["status"], u["consistent"], u["segments"], ", ".join(u["violations"]) or "-"))
    L += ["", "## 6. Copied / omitted blocks", "- copied verbatim: %d (formulas, reference entries, author lines, numeric tables)" % sum(1 for r in rows if r["action"] == "copy"),
          "- omitted: %d (running headers/footers, out-of-range blocks)" % sum(1 for r in rows if r["action"] == "omit")]
    return "\n".join(L) + "\n"


def render_translation_md(rows):
    out = []
    for r in rows:
        if r["action"] == "omit":
            continue
        txt = r.get("translation") if r["action"] == "translate" else r["source"]
        if r["action"] == "translate" and txt is None:
            txt = "[[NOT TRANSLATED]] " + r["source"]
        if r["type"] == "title":
            out.append("# " + txt)
        elif r["type"] == "heading":
            out.append("#" * min(6, (r.get("level") or 1) + 1) + " " + txt)
        elif r["type"] == "caption":
            out.append("*" + txt + "*")
        elif r["action"] == "copy" and r["type"] == "formula":
            out.append("```\n" + txt + "\n```")
        else:
            out.append(txt)
    return "\n\n".join(out) + "\n"


def render_bilingual_md(rows, meta):
    out = ["# Bilingual paragraph alignment (%s → %s)" % (meta["src_lang"], meta["tgt_lang"]), "",
           "Every block has a stable id; pages and the source block id point back into the original (see alignment.json).", ""]
    for r in rows:
        if r["action"] == "omit":
            continue
        pg = ",".join(map(str, r["pages"])) if r["pages"] else "-"
        out.append("### %s · %s · p%s%s" % (r["id"], r["type"], pg, " · §" + r["section"][:50] if r.get("section") and r["type"] != "heading" else ""))
        if r["action"] == "copy":
            out += ["", "_copied verbatim (%s)_" % (r.get("reason") or "not translated by design"), "", "> " + md_cell(r["source"]), ""]
            continue
        out += ["", "**SRC** " + md_cell(r["source"]), ""]
        if r.get("translation") is None:
            out += ["**TGT** [[NOT TRANSLATED]]", ""]
            continue
        out += ["**TGT** " + md_cell(r["translation"]), ""]
        if r.get("sentences"):
            out += ["| id | source sentence | target sentence |", "|---|---|---|"] + ["| %s | %s | %s |" % (s["id"], md_cell(s["source"]).replace("|", "\\|"), md_cell(s["target"]).replace("|", "\\|")) for s in r["sentences"]] + [""]
        flags = ["status: " + r["status"]] + (["note: " + r["note"]] if r.get("note") else []) + ["%s: %s" % (i["kind"], i["detail"]) for i in r.get("issues", [])][:4]
        out += ["> " + " | ".join(flags), "> basis: " + r["basis"], ""]
    return "\n".join(out)


def render_bilingual_html(rows, meta):
    e = htmllib.escape
    css = ("body{font:15px/1.55 system-ui,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;color:#1b1f23}table{border-collapse:collapse;width:100%}"
           "td,th{border:1px solid #d0d7de;padding:8px;vertical-align:top}th{background:#f6f8fa;text-align:left}.id{white-space:nowrap;font-family:monospace;font-size:12px}"
           ".error td{background:#fff1f0}.warn td.t{background:#fffbe6}.nt td.t{background:#ffe7e7}.copy td{color:#57606a;background:#f6f8fa}.meta{color:#57606a;font-size:12px}"
           "@media(prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}td,th{border-color:#30363d}th,.copy td{background:#161b22}.error td{background:#3d1d1d}.warn td.t{background:#3a3000}.nt td.t{background:#4a1d1d}}")
    h = ["<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Bilingual alignment</title><style>%s</style>" % css,
         "<h1>Bilingual alignment (%s → %s)</h1><p class='meta'>source: %s · ids are stable; hover a row for the translator's basis</p>" % (e(meta["src_lang"]), e(meta["tgt_lang"]), e(meta.get("source_file", ""))),
         "<table><tr><th>id</th><th>source</th><th>target</th></tr>"]
    for r in rows:
        if r["action"] == "omit":
            continue
        cls = "copy" if r["action"] == "copy" else ({"error": "error", "warn": "warn", "not_translated": "nt"}.get(r.get("status"), ""))
        tgt = r["source"] if r["action"] == "copy" else (r.get("translation") or "[[NOT TRANSLATED]]")
        if r.get("sentences"):
            tgt_html = "".join("<div><span class='meta'>%s</span> %s</div>" % (e(s["id"].split(".")[-1]), e(s["target"])) for s in r["sentences"])
            src_html = "".join("<div><span class='meta'>%s</span> %s</div>" % (e(s["id"].split(".")[-1]), e(s["source"])) for s in r["sentences"])
        else:
            tgt_html, src_html = e(tgt).replace("\n", "<br>"), e(r["source"]).replace("\n", "<br>")
        title = e(r.get("basis") or r.get("reason") or "")
        h.append("<tr id='%s' class='%s' title='%s'><td class='id'>%s<br><span class='meta'>%s p%s</span></td><td>%s</td><td class='t'>%s</td></tr>" % (
            e(r["id"]), cls, title, e(r["id"]), e(r["type"]), e(",".join(map(str, r["pages"])) or "-"), src_html, tgt_html))
    h.append("</table></html>")
    return "".join(h)


def contract_fields(case):
    oc = find_key(case, ["output_contract", "outputContract", "output_schema", "outputs"]) if case else None
    fields = []

    def add(x):
        if isinstance(x, str) and x not in fields:
            fields.append(x)
    if isinstance(oc, list):
        for it in oc:
            add(it if isinstance(it, str) else (it.get("name") or it.get("field") or it.get("key")) if isinstance(it, dict) else None)
    elif isinstance(oc, dict):
        inner = oc.get("fields") or oc.get("required") or oc.get("properties") or oc.get("required_fields")
        if isinstance(inner, list):
            for it in inner:
                add(it if isinstance(it, str) else (it.get("name") or it.get("field") or it.get("key")) if isinstance(it, dict) else None)
        elif isinstance(inner, dict):
            for k in inner:
                add(k)
        else:
            for k in oc:
                if k not in ("type", "description", "title", "version", "schema", "$schema", "additionalProperties"):
                    add(k)
    return fields


def derive_field(name, ctx):
    n = name.lower()
    rows, rep, meta, gl = ctx["rows"], ctx["rep"], ctx["meta"], ctx["glossary"]
    if n in ("status", "run_status", "state", "outcome"):
        return True, ctx["status"]
    if n in ("sources", "source", "input", "inputs", "input_id", "input_identification", "input_files", "inputs_used"):
        return True, [{"file": meta.get("source_file"), "format": meta.get("format"), "pages": meta.get("pages"), "src_lang": meta["src_lang"], "tgt_lang": meta["tgt_lang"],
                       "parser": "scholarly-paper-translator %s" % VERSION}]
    if n in ("uncertainty", "uncertainties", "limitations", "limits", "unresolved", "caveats", "risks", "uncertain_items"):
        return True, ctx["uncertainty"]
    if n in ("change_records", "changes", "change_log", "modifications", "edits", "revisions"):
        return True, ctx["changes"]
    if n in ("translation", "translated_text", "target_text", "full_translation", "translated", "target", "output_text", "translation_text", "译文"):
        return True, render_translation_md(rows)
    if n in ("bilingual", "bilingual_text", "parallel", "parallel_text", "aligned", "aligned_paragraphs", "paragraph_alignment", "alignment", "bilingual_alignment", "paragraphs", "segments", "bilingual_pairs", "对照"):
        return True, [{k: r.get(k) for k in ("id", "type", "pages", "bbox", "section", "source", "translation", "sentences", "status", "basis", "note", "issues", "glossary_hits", "source_block")}
                      for r in rows if r["action"] != "omit"]
    if n in ("glossary", "terminology", "term_table", "termbase", "terms", "glossary_terms", "术语表"):
        return True, [{"source": u["src"], "target": u["tgt"], "status": u["status"], "occurrences": u["segments"], "consistent": u["consistent"], "violations": u["violations"]} for u in rep["term_usage"]] or \
            [{"source": e["src"], "target": e["tgt"], "status": e["status"]} for e in gl.entries]
    if n in ("checks", "verification", "qa", "validation", "quality_checks", "self_check", "checklist", "check_report", "译文核验"):
        return True, {"summary": rep["summary"], "error_segments": rep["error_segments"], "warning_segments": rep["warning_segments"], "missing": rep["missing"], "duplicates": rep["duplicates"]}
    if n in ("human_review", "needs_review", "review_items", "todo", "manual_review", "to_confirm", "human_confirmation", "需人工确认"):
        return True, ctx["review_items"]
    if n in ("untranslated", "omitted", "not_translated", "missing_segments"):
        return True, rep["missing"]
    if n in ("evidence", "evidence_locations", "source_locations", "locations", "references_to_source"):
        return True, [{"id": r["id"], "pages": r["pages"], "bbox": r["bbox"], "source_block": r.get("source_block"), "section": r.get("section")} for r in rows if r["action"] != "omit"]
    if n in ("language", "languages", "language_pair"):
        return True, {"source": meta["src_lang"], "target": meta["tgt_lang"]}
    return False, None


def cmd_assemble(a):
    d, trs, gl, st = load_all(a.work)
    meta = d["meta"]
    rep = run_check(a.work)
    apply_recheck(trs, rep)
    jsave(os.path.join(a.work, "translations.json"), trs)
    rows = build_alignment(d, trs, gl)
    out = a.out
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "translation.md"), "w", encoding="utf-8") as fh:
        fh.write(render_translation_md(rows))
    with open(os.path.join(out, "bilingual.md"), "w", encoding="utf-8") as fh:
        fh.write(render_bilingual_md(rows, meta))
    with open(os.path.join(out, "bilingual.html"), "w", encoding="utf-8") as fh:
        fh.write(render_bilingual_html(rows, meta))
    with open(os.path.join(out, "review_checklist.md"), "w", encoding="utf-8") as fh:
        fh.write(checklist(rows, rep, meta))
    jsave(os.path.join(out, "alignment.json"), rows)
    jsave(os.path.join(out, "glossary.json"), {"entries": gl.entries, "usage": rep["term_usage"]})
    jsave(os.path.join(out, "check_report.json"), rep)
    s = rep["summary"]
    complete = s["missing"] == 0 and s["with_errors"] == 0 and not meta.get("unparsed")
    status = "success" if complete else ("partial" if s["translated"] > 0 else "failed")
    unc = []
    for i in rep["missing"]:
        unc.append({"kind": "not_translated", "segment": i, "detail": "no translation submitted"})
    for i in rep["error_segments"]:
        unc.append({"kind": "failed_check", "segment": i, "detail": "; ".join(x["detail"] for x in rep["issues"][i] if x["severity"] == "error")[:300]})
    for u in meta.get("unparsed", []):
        unc.append({"kind": "unparsed_input", "page": u.get("page"), "detail": "%s %s" % (u.get("reason"), u.get("detail", ""))})
    for w in meta.get("parser_warnings", []):
        unc.append({"kind": "parser_warning", "detail": w})
    for r in rows:
        if r.get("flag") or r.get("note"):
            unc.append({"kind": "translator_note", "segment": r["id"], "detail": r.get("note") or r.get("flag")})
    n_w = len(rep["warning_segments"])
    if n_w:
        unc.append({"kind": "warnings", "detail": "%d segment(s) carry warnings (possible lost negation/qualifier, changed unit, added number ...): see review_checklist.md" % n_w})
    changes = [{"change": "blocks copied verbatim (not translated by design)", "count": sum(1 for r in rows if r["action"] == "copy")},
               {"change": "blocks omitted (running headers/footers, out of range)", "count": sum(1 for r in rows if r["action"] == "omit")},
               {"change": "segments re-translated after failing automatic checks", "count": sum(1 for r in trs.values() if r.get("tries", 1) > 1)},
               {"change": "terms added during translation (provisional, then locked)", "count": sum(1 for e in gl.entries if e.get("origin", "").startswith("proposed"))}]
    review = []
    for r in rows:
        if r.get("status") in ("error", "not_translated"):
            review.append({"segment": r["id"], "why": r["status"], "detail": "; ".join(x["detail"] for x in r.get("issues", []) if x["severity"] == "error") or "not translated"})
        elif r.get("status") == "warn":
            review.append({"segment": r["id"], "why": "warning", "detail": "; ".join("%s: %s" % (x["kind"], x["detail"]) for x in r["issues"])[:300]})
        elif r.get("note"):
            review.append({"segment": r["id"], "why": "translator_note", "detail": r["note"]})
    ctx = {"rows": rows, "rep": rep, "meta": meta, "glossary": gl, "status": status, "uncertainty": unc, "changes": changes, "review_items": review}
    case = jload(a.case) if a.case and os.path.isfile(a.case) else None
    fields = contract_fields(case)
    answers = jload(a.answers, {}) if a.answers else {}
    cid = (find_key(case, ["case_id", "caseId"]) or find_key(case, ["id"])) if case else None
    result = {"case_id": cid}
    unfilled = []
    for f in fields:
        if f == "case_id":
            continue
        if f in answers:
            result[f] = answers[f]
            continue
        ok, v = derive_field(f, ctx)
        result[f] = v if ok else None
        if not ok:
            unfilled.append(f)
    ALIGN_FAMILY = {"bilingual", "bilingual_text", "parallel", "parallel_text", "aligned", "aligned_paragraphs", "paragraph_alignment", "alignment", "bilingual_alignment", "paragraphs", "segments", "bilingual_pairs", "对照"}
    has_align = any(f.lower() in ALIGN_FAMILY for f in fields)
    for nm in ("status", "sources", "uncertainty", "change_records", "translation", "alignment", "glossary", "checks", "human_review"):
        if nm == "alignment" and has_align:
            continue
        if nm not in result:
            key = {"alignment": "bilingual_alignment", "human_review": "human_review"}.get(nm, nm)
            result[nm] = answers.get(nm, derive_field(key, ctx)[1])
    for k, v in answers.items():
        result.setdefault(k, v)
    if case is not None and cid is None:
        unfilled.append("case_id")
    result["_meta"] = {"generator": "scholarly-paper-translator/tr.py %s" % VERSION, "contract_fields": fields, "unfilled_fields": unfilled, "contract_found": bool(fields),
                       "files": ["translation.md", "bilingual.md", "bilingual.html", "alignment.json", "glossary.json", "review_checklist.md", "check_report.json"]}
    jsave(os.path.join(out, "result.json"), result)
    print(json.dumps({"written": out, "status": status, "translated": "%d/%d" % (s["translated"], s["translate_segments"]), "with_errors": s["with_errors"], "with_warnings": s["with_warnings"],
                      "missing": s["missing"], "term_consistency": s["term_consistency"], "sentence_alignment": s["sentence_alignment"],
                      "unfilled_contract_fields": unfilled, "contract_found": bool(fields)}, ensure_ascii=False))
    if not fields and a.case:
        print("WARNING: no output_contract found in the case file: read /input/case.json and task.md and add the fields by hand via --answers")
    if unfilled:
        print("UNFILLED contract fields (put them in answers.json and re-run assemble): " + ", ".join(unfilled))
    sys.exit(0 if (not unfilled and fields) or not a.case else 2)


# ------------------------------------------------------------------------------------------------ status
def cmd_status(a):
    d, trs, gl, st = load_all(a.work)
    translate = [s for s in d["segments"] if s["action"] == "translate"]
    c = Counter(trs.get(s["id"], {}).get("status", "todo") for s in translate)
    elapsed = int(time.time() - st.get("t0", time.time()))
    nxt = next((b["k"] for b in d["batches"] if any(trs.get(i, {}).get("status") not in ("ok", "warn") for i in b["ids"])), None)
    print(json.dumps({"segments": len(translate), "ok": c["ok"], "warn": c["warn"], "error": c["error"], "todo": c["todo"], "next_batch": nxt, "batches": len(d["batches"]),
                      "elapsed_s": elapsed, "budget_s": st.get("budget_s"), "glossary_terms": len(gl.entries), "language": "%s->%s" % (d["meta"]["src_lang"], d["meta"]["tgt_lang"])}))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("input")
    p.add_argument("--work", required=True)
    p.add_argument("--case")
    p.add_argument("--glossary")
    p.add_argument("--src", default="auto")
    p.add_argument("--tgt")
    p.add_argument("--pages")
    p.add_argument("--range")
    p.add_argument("--batch-tokens", type=int, default=1100)
    p.add_argument("--fixed-batches", action="store_true", help="do not enlarge batches automatically when there are more than 14")
    p.add_argument("--budget", type=int, default=900)
    p.add_argument("--tok-per-s", type=float, default=40.0)
    p.add_argument("--overhead", type=float, default=20.0)
    p.add_argument("--order", choices=["auto", "document", "priority"], default="auto")
    p.add_argument("--translate-references", action="store_true")
    p.add_argument("--ocr", choices=["auto", "off", "force"])
    p.set_defaults(fn=cmd_prepare)
    p = sub.add_parser("glossary")
    p.add_argument("work")
    p.add_argument("--add", action="append")
    p.add_argument("--from-file")
    p.add_argument("--avoid", action="append", help='forbid renderings: "term => wrong1, wrong2"')
    p.add_argument("--lock", action="store_true")
    p.add_argument("--candidates", action="store_true")
    p.add_argument("--lint", action="store_true")
    p.add_argument("--show", action="store_true")
    p.set_defaults(fn=cmd_glossary)
    p = sub.add_parser("next")
    p.add_argument("work")
    p.add_argument("--batch", type=int)
    p.add_argument("--fix", action="store_true")
    p.add_argument("--context", type=int, default=2)
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(fn=cmd_next)
    p = sub.add_parser("ingest")
    p.add_argument("work")
    p.add_argument("file", nargs="?")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_ingest)
    p = sub.add_parser("check")
    p.add_argument("work")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("assemble")
    p.add_argument("work")
    p.add_argument("--out", required=True)
    p.add_argument("--case")
    p.add_argument("--answers")
    p.set_defaults(fn=cmd_assemble)
    p = sub.add_parser("status")
    p.add_argument("work")
    p.set_defaults(fn=cmd_status)
    a, extra = ap.parse_known_args(argv)
    if extra:  # allow "-v" before or after the optional FILE argument
        if a.cmd == "ingest" and extra == ["-v"]:
            a.verbose = True
        elif a.cmd == "ingest" and len(extra) == 1 and not a.file:
            a.file = extra[0]
        else:
            ap.error("unrecognized arguments: " + " ".join(extra))
    a.fn(a)


if __name__ == "__main__":
    main()
