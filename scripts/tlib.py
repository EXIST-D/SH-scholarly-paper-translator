"""tlib - text analysis helpers for the scholarly translation workflow (standard library only).

Sentence splitting, invariant extraction (numbers, units, citations, cross references, identifiers, URLs, math symbols),
glossary matching, and rule-based cue checks (negation, qualifiers, bounds, connectives). Nothing here calls a model.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# --------------------------------------------------------------------------------------------- language
CJK_RE = re.compile(r"[㐀-鿿豈-﫿]")
LATIN_RE = re.compile(r"[A-Za-z]")


def cjk_ratio(text):
    letters = len(CJK_RE.findall(text)) + len(LATIN_RE.findall(text))
    return (len(CJK_RE.findall(text)) / letters) if letters else 0.0


def detect_lang(text):
    return "zh" if cjk_ratio(text) > 0.3 else "en"


def est_tokens(text):
    """Rough LLM token estimate: ~1.3 tokens per Latin word, ~1 per CJK character."""
    cjk = len(CJK_RE.findall(text))
    rest = CJK_RE.sub(" ", text)
    return int(math.ceil(len(rest.split()) * 1.3 + cjk * 1.0))


# --------------------------------------------------------------------------------------------- sentences
ABBR = {"e.g", "i.e", "et al", "al", "fig", "figs", "eq", "eqs", "vs", "approx", "dr", "prof", "no", "sec", "ref", "refs", "cf", "ca",
        "inc", "ltd", "resp", "etc", "viz", "st", "mr", "mrs", "ms", "jr", "sr", "vol", "pp", "ed", "eds", "dept", "univ", "jan", "feb",
        "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "col", "ch", "chap", "tab", "est", "max", "min", "avg",
        "ie", "eg", "u.s", "u.k", "ph.d", "m.sc", "b.sc", "p", "pp", "sp", "spp", "var", "subsp", "cm", "mm"}


def split_sentences(text):
    """Split a paragraph into sentences; keeps abbreviations, decimals, initials and 'et al.' intact."""
    text = text.strip()
    if not text:
        return []
    out, start = [], 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch in "。！？":
            j = i + 1
            while j < n and text[j] in "”’）」』\"')":
                j += 1
            out.append(text[start:j].strip())
            start = j
            i = j
            continue
        if ch in ".!?":
            j = i + 1
            while j < n and text[j] in "\"'”’)]":
                j += 1
            if j >= n:
                i = j
                continue
            if not text[j].isspace():
                i = j
                continue
            k = j
            while k < n and text[k].isspace():
                k += 1
            if k >= n:
                i = j
                continue
            c = text[k]
            boundary = c.isupper() or c.isdigit() or c in "\"“'‘([" or CJK_RE.match(c) is not None
            if ch == ".":
                m = re.search(r"([A-Za-z.]+)$", text[start:i])
                word = (m.group(1) if m else "").lower().rstrip(".")
                if word in ABBR:
                    boundary = False
                elif len(word) == 1 and word.isalpha() and text[i - 1].isupper():
                    boundary = False  # an initial: "J. Smith"
                elif re.search(r"(^|\s)\d+$", text[start:i]) and start == 0 and not out:
                    boundary = False  # "3. Results"
                elif c.islower():
                    boundary = False
            if boundary:
                out.append(text[start:j].strip())
                start = k
            i = j
            continue
        i += 1
    if start < n:
        rest = text[start:].strip()
        if rest:
            out.append(rest)
    return out


# --------------------------------------------------------------------------------------------- invariants
UNITS = ["km/s", "m/s", "mg/L", "g/L", "g/cm3", "g/cm³", "kg/m3", "kg/m³", "mol/L", "ppm", "ppb", "µm", "μm", "nm", "mm", "cm", "km", "kg", "mg", "µg", "μg",
         "ms", "µs", "μs", "ns", "min", "GHz", "MHz", "kHz", "Hz", "kPa", "MPa", "GPa", "Pa", "kJ", "MJ", "J", "kW", "MW", "mW", "W", "mV", "kV", "V", "mA",
         "A", "mT", "T", "mol", "mM", "µM", "μM", "mL", "µL", "μL", "L", "eV", "keV", "MeV", "GeV", "TeV", "dB", "bar", "atm", "Gyr", "Myr", "kyr", "Ga", "Ma",
         "ka", "yr", "yrs", "°C", "°F", "°", "K", "%", "‰", "Å", "GB", "MB", "KB", "TB", "FLOPs", "FLOPS", "GFLOPs", "TFLOPs", "fps", "rpm", "px", "g", "m", "s", "h", "d"]
UNIT_ALT = "|".join(sorted({re.escape(u) for u in UNITS}, key=len, reverse=True))
NUM = r"(?<![\w.])[-−–+±]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-−–+±]?\d+(?:\.\d+)?(?:[eE][-+−]?\d+)?(?!D\b)"
NUM_RE = re.compile(NUM)
UNIT_RE = re.compile(r"(?<=\d)\s?(%s)(?![A-Za-z])" % UNIT_ALT)
CITE_NUM_RE = re.compile(r"\[\s*\d+(?:\s*[-–,;]\s*\d+)*\s*\]")
CITE_AY_RE = re.compile(r"\(([A-Z][A-Za-z'’\-]+(?:,? (?:and|&) [A-Z][A-Za-z'’\-]+)?(?: et al\.?)?,? \d{4}[a-z]?(?:[;,] ?[A-Z][A-Za-z'’\-]+(?:,? (?:and|&) [A-Z][A-Za-z'’\-]+)?(?: et al\.?)?,? \d{4}[a-z]?)*)\)")
CITE_NARR_RE = re.compile(r"\b([A-Z][A-Za-z'’\-]+(?: et al\.?|,? (?:and|&) [A-Z][A-Za-z'’\-]+))\s*\(?(\d{4}[a-z]?)\)?")
URL_RE = re.compile(r"https?://[^\s)\]>,;]+|www\.[^\s)\]>,;]+|\b10\.\d{4,9}/[^\s)\]>,;]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
REF_EN = re.compile(r"\b(Figures?|Figs?\.?|Tables?|Tabs?\.?|Equations?|Eqs?\.?|Sections?|Secs?\.?|§|Appendix|Appendices|Algorithms?|Theorems?|Lemmas?|Propositions?|Definitions?|Panels?|Boxes?|Scheme)\s*\(?([A-Z]?\d+(?:\.\d+)*[a-z]?(?:\s*(?:[-–,]|and)\s*[A-Z]?\d+[a-z]?)*)\)?", re.I)
REF_ZH = re.compile(r"(图|表|式|公式|方程|等式|节|章|附录|算法|定理|引理|命题|定义|框|Figures?|Figs?\.?|Tables?|Tabs?\.?|Equations?|Eqs?\.?|Sections?|Secs?\.?|§|Appendix|Algorithms?)\s*\(?\s*第?([A-Z]?\d+(?:\.\d+)*[a-z]?(?:\s*(?:[-–,，、]|和|与|and)\s*[A-Z]?\d+[a-z]?)*)\)?")
REF_ZH2 = re.compile(r"第\s*(\d+(?:\.\d+)*)\s*(节|章|图|表)")
REF_CANON = {"figure": "fig", "figures": "fig", "fig": "fig", "figs": "fig", "图": "fig", "table": "tab", "tables": "tab", "tab": "tab", "tabs": "tab", "表": "tab",
             "equation": "eq", "equations": "eq", "eq": "eq", "eqs": "eq", "式": "eq", "公式": "eq", "方程": "eq", "等式": "eq",
             "section": "sec", "sections": "sec", "sec": "sec", "secs": "sec", "§": "sec", "节": "sec", "章": "sec",
             "appendix": "app", "appendices": "app", "附录": "app", "algorithm": "alg", "algorithms": "alg", "算法": "alg",
             "theorem": "thm", "定理": "thm", "lemma": "lem", "lemmas": "lem", "引理": "lem", "proposition": "prop", "propositions": "prop", "命题": "prop",
             "definition": "def", "definitions": "def", "定义": "def", "panel": "panel", "box": "box", "框": "box", "scheme": "scheme"}
ACRONYM_RE = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|[A-Za-z]+-\d+[A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|[A-Z][a-z]+[A-Z][A-Za-z0-9]+(?:-[A-Za-z0-9]+)*|[A-Z][a-z]*\d+[A-Za-z0-9]*|[23]D)\b")
MATH_CHARS = set("ħℏαβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ∑∏∫∂∇∞≈≠≤≥≪≫±×÷∝∈∉⊂⊃⊆⊇∪∩→←↔⇒⇔∀∃√∠⊥∥°′″·⋅⊗⊕ℝℕℤℚℂ^_")
STOP_UPPER = {"I", "A", "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "OK", "US", "UK", "EU", "AND", "OR", "THE", "FOR", "ET", "AL"}


def norm_num(s):
    s = s.replace("−", "-").replace("–", "-").replace(",", "").strip()
    if s.startswith("+"):
        s = s[1:]
    if re.fullmatch(r"-?\d+\.\d+", s):
        s = s.rstrip("0").rstrip(".") if "." in s else s
    return s


def norm_cite(s):
    return re.sub(r"\s+", "", s.replace("–", "-").replace("；", ";").replace("，", ","))


def canon_ref(word, num):
    w = word.lower().rstrip(".")
    t = REF_CANON.get(w) or REF_CANON.get(word) or w
    ids = re.findall(r"[A-Z]?\d+(?:\.\d+)*[a-z]?", num)
    return [(t, i.lower()) for i in ids]


def extract_refs(text):
    out = []
    for m in REF_EN.finditer(text):
        out += canon_ref(m.group(1), m.group(2))
    for m in REF_ZH.finditer(text):
        out += canon_ref(m.group(1), m.group(2))
    for m in REF_ZH2.finditer(text):
        out += canon_ref(m.group(2), m.group(1))
    return out


FOOTNOTE_RE = re.compile(r"(?<!\d\.)(?<=[.!?”\"’)\]。！？）])(\d{1,2})(?![\d.,]*\d)(?=\s|$|[A-Z\u3400-\u9fff])")


def extract_invariants(text):
    """What must survive translation unchanged. Returns a JSON-serialisable dict."""
    work = text
    foot = FOOTNOTE_RE.findall(work)
    work = FOOTNOTE_RE.sub(" ", work)
    urls = [u.rstrip(".") for u in URL_RE.findall(work)]
    work = URL_RE.sub(" ", work)
    cites = [norm_cite(c) for c in CITE_NUM_RE.findall(work)]
    work = CITE_NUM_RE.sub(" ", work)
    ay = []
    for m in CITE_AY_RE.finditer(work):
        ay.append(m.group(1))
    names, years, pairs = [], [], []
    for m in CITE_NARR_RE.finditer(text):
        first = None
        for nm in re.split(r",? (?:and|&) | et al\.?", m.group(1)):
            if nm.strip():
                names.append(nm.strip())
                first = first or nm.strip()
        years.append(m.group(2))
        if first:
            pairs.append("%s|%s" % (first, m.group(2)))
    for a in ay:
        for part in re.split(r"[;]", a):
            nm = re.match(r"([A-Z][A-Za-z'’\-]+)", part.strip())
            yrs = re.findall(r"\d{4}[a-z]?", part)
            if nm:
                names.append(nm.group(1))
            for yr in yrs:
                years.append(yr)
                if nm:
                    pairs.append("%s|%s" % (nm.group(1), yr))
    refs = sorted(set(extract_refs(work)))
    work = REF_ZH.sub(" ", REF_EN.sub(" ", work))
    work = REF_ZH2.sub(" ", work)
    nums = [norm_num(x) for x in NUM_RE.findall(work)]
    nums = [x for x in nums if x not in ("", "-", "+")]
    units = [u.replace("μ", "µ") for u in UNIT_RE.findall(work)]
    ids = [t for t in ACRONYM_RE.findall(work) if t not in STOP_UPPER and len(t) >= 2 and not re.fullmatch(r"\d+", t)]
    math = Counter(c for c in text if c in MATH_CHARS)
    return {"numbers": nums, "units": units, "citations": cites, "author_year": sorted(set(names)), "years": sorted(set(years)), "ay_pairs": sorted(set(pairs)), "refs": [list(r) for r in refs],
            "urls": urls, "identifiers": ids, "math": dict(math), "footnote_markers": foot}


# --------------------------------------------------------------------------------------------- cues (EN -> ZH)
NEG_EN = re.compile(r"\b(not|no|never|neither|nor|none|nothing|without|cannot|can't|isn't|aren't|don't|doesn't|didn't|won't|wasn't|weren't|fail(?:s|ed|ing)? to|unable|lack(?:s|ed|ing)?|absence|absent|hardly|barely|rarely|seldom|insufficient|insignificant|non-?[a-z]{3,}|unlikely|nowhere)\b", re.I)
NEG_ZH = re.compile(r"不(?!同|仅|断|论|管|过|如|妨|禁|免|外|时|久|少|但|光|料|然|止|愧|一|已|确定性|确定度)|没|未(?!来|知)|无(?!论|数|穷|限|线|机|量纲|人|损)|非(?!常|洲)|否(?!则)|缺乏|缺少|缺失|难以|尚未|从未|并非|很少|罕见|几乎不|几乎没有|拒绝|禁止|而非|低估|少有|鲜有")
NEG_ZH_STRONG = re.compile(r"并非|并未|没有|不能|不会|不是|无法|难以|不存在|从未|尚未|从不|未能|不应|不可能|不再|不支持|不超过|无需|不需要")
QUAL = {  # family -> (EN pattern, ZH pattern)
    "possibility/hedge": (r"\b(may|might|could|possibly|perhaps|probably|likely|suggest(?:s|ed)?|appear(?:s|ed)? to|seem(?:s|ed)?|tend(?:s|ed)? to|potentially|presumably|indicat(?:e|es|ed|ing))\b",
                          r"可能|或许|也许|大概|似乎|看起来|倾向|表明|提示|显示|暗示|推测|估计|有望|有助于|很可能|应当|潜在|指示|说明"),
    "approximation": (r"\b(approximately|roughly|about|around|nearly|almost|circa|ca\.|~)\b|~", r"约|大约|大概|左右|近|几乎|接近|将近|上下|~|∼|差不多"),
    "frequency/extent": (r"\b(generally|typically|usually|often|mostly|largely|mainly|partly|partially|slightly|marginally|somewhat|sometimes|occasionally|commonly)\b",
                         r"通常|一般|往往|常常|常|多数|大多|主要|大部分|部分|略|轻微|稍|有时|偶尔|普遍|在一定程度"),
    "restriction": (r"\b(only|merely|solely|exclusively|just)\b", r"仅|只|唯一|才|仅仅|单独|专门|惟|而已|不过"),
    "lower bound": (r"\b(at least|no less than|more than|greater than|exceed(?:s|ed|ing)?|larger than|higher than)\b", r"至少|不少于|不低于|超过|多于|大于|高于|以上|逾|大于等于|不小于|≥|>|上回"),
    "upper bound": (r"\b(at most|no more than|up to|less than|fewer than|smaller than|lower than|not exceed(?:ing)?)\b", r"至多|最多|不超过|不多于|少于|低于|小于|以下|不足|未超过|不大于|≤|<|以内|至高"),
    "concession": (r"\b(although|though|despite|whereas|even though|nevertheless|nonetheless|however)\b", r"虽然|尽管|虽|然而|但是|但|却|而|不过|可是|然|仍|仍然|即使|即便"),
    "cause": (r"\b(because|due to|owing to|as a result of|caused by|thanks to|attributed to)\b", r"因为|由于|因|鉴于|归因|源于|导致|造成|得益于|缘于|取决"),
    "result": (r"\b(therefore|thus|hence|consequently|thereby|so that|as a result|leading to|results? in)\b", r"因此|所以|故|从而|由此|因而|于是|进而|使得|导致|致使|结果|为此|以便"),
    "condition": (r"\b(if|unless|provided that|only if)\b", r"如果|若|倘若|除非|假如|只要|当|一旦|只有|凡|在.{0,12}时|时|则|即"),
}
QUAL_RE = {k: (re.compile(v[0], re.I), re.compile(v[1])) for k, v in QUAL.items()}


COUNT_FAMILIES = ("approximation", "restriction", "lower bound", "upper bound")  # precise-quantity cues: compare counts, not just presence


def cue_findings(src, tgt):
    """Warnings (never errors) about possibly lost or added negation / qualifiers / bounds / connectives for EN->ZH."""
    out = []
    src_neg = re.sub(r"(?i)\b(not only|not just|not merely|no matter|not least|nothing but|not to mention)\b", " ", src)
    sn = [m if isinstance(m, str) else m[0] for m in NEG_EN.findall(src_neg)]
    tn = NEG_ZH.findall(tgt)
    if sn and not tn:
        out.append(("negation", "source has negation (%s) but the translation shows no negation cue" % ", ".join(sorted(set(sn))[:4])))
    elif len(sn) >= 2 and len(tn) < len(sn):
        out.append(("negation", "source has %d negation cues (%s), the translation only %d: one may be lost" % (len(sn), ", ".join(sorted(set(sn))[:4]), len(tn))))
    elif not sn and NEG_ZH_STRONG.search(tgt):
        out.append(("negation", "the translation contains a negation (%s) but the source has none: check it was not added" % NEG_ZH_STRONG.search(tgt).group(0)))
    for fam, (en_re, zh_re) in QUAL_RE.items():
        ms = en_re.findall(src)
        if not ms:
            continue
        if fam in COUNT_FAMILIES:
            nt = len(zh_re.findall(tgt))
            if nt < len(ms):
                out.append((fam, "source has %d cue(s) of %s (%s), the translation %d" % (len(ms), fam, ", ".join(sorted({m if isinstance(m, str) else m[0] for m in ms})[:3]), nt)))
        elif not zh_re.search(tgt):
            m = en_re.search(src)
            out.append((fam, "source cue %r (%s) has no matching cue in the translation" % (m.group(0), fam)))
    return out


# --------------------------------------------------------------------------------------------- glossary
def _term_regex(src, case_sensitive=False):
    parts = [re.escape(w) for w in re.split(r"[\s\-_]+", src.strip()) if w]
    if not parts:
        return None
    body = r"[\s\-_]+".join(parts)
    if re.search(r"[A-Za-z]$", src.strip()):
        body += r"(?:s|es)?"
    flags = 0 if case_sensitive else re.I
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", flags)


class Glossary:
    def __init__(self, entries=None):
        self.entries = []
        self._rx = []
        for e in entries or []:
            self.add(e)

    def add(self, e):
        e = dict(e)
        if not e.get("src") or not e.get("tgt"):
            return False
        e.setdefault("status", "locked")
        e.setdefault("alts_ok", [])
        e.setdefault("avoid", [])
        e.setdefault("case_sensitive", False)
        for old in self.entries:
            if old["src"].lower() == e["src"].lower():
                if old["tgt"] != e["tgt"]:
                    e["_conflict_with"] = old["tgt"]
                return False
        self.entries.append(e)
        self._rx.append(_term_regex(e["src"], e["case_sensitive"]))
        return True

    def find(self, text):
        """Non-overlapping matches, longest term first. Returns [(entry, matched_text)]."""
        taken, found = [], []
        order = sorted(range(len(self.entries)), key=lambda i: -len(self.entries[i]["src"]))
        for i in order:
            rx = self._rx[i]
            if rx is None:
                continue
            for m in rx.finditer(text):
                if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append((self.entries[i], m.group(0)))
        return found

    def check(self, src_text, tgt_text):
        """Violations of locked/provisional terms in one segment. Returns list of dicts."""
        out = []
        tn = re.sub(r"\s+", "", tgt_text).lower()
        seen = set()
        found = self.find(src_text)
        counts = Counter(e["src"].lower() for e, _ in found)
        for e, matched in found:
            if e["src"].lower() in seen:
                continue
            seen.add(e["src"].lower())
            ok = [e["tgt"]] + list(e.get("alts_ok", []))
            if not any(re.sub(r"\s+", "", t).lower() in tn for t in ok):
                out.append({"severity": "error" if e["status"] == "locked" else "warn", "kind": "glossary",
                            "term": e["src"], "expected": e["tgt"], "matched": matched})
            k = counts[e["src"].lower()]
            if k >= 2 and not out:
                have = sum(tn.count(re.sub(r"\s+", "", t).lower()) for t in ok)
                if have < k:
                    out.append({"severity": "warn", "kind": "glossary_count", "term": e["src"], "expected": e["tgt"], "matched": "%d occurrences in the source, %d rendered" % (k, have)})
            for bad in e.get("avoid", []):
                if bad and re.sub(r"\s+", "", bad).lower() in tn and re.sub(r"\s+", "", e["tgt"]).lower() not in re.sub(r"\s+", "", bad).lower():
                    out.append({"severity": "error", "kind": "glossary_avoid", "term": e["src"], "expected": e["tgt"], "found": bad})
        return out


def parse_glossary_text(text):
    """Accept: 'src => tgt', 'src -> tgt', 'src<TAB>tgt', 'src,tgt', markdown tables '| src | tgt |', one per line."""
    entries = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or re.fullmatch(r"[|\-:\s]+", ln):
            continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower() not in ("source", "src", "term", "英文", "原文", "术语"):
                entries.append({"src": cells[0], "tgt": cells[1], "note": cells[2] if len(cells) > 2 else ""})
            continue
        for sep in ("=>", "->", "→", "\t", "=", ",", "，", "：", ":"):
            if sep in ln:
                a, b = ln.split(sep, 1)
                if a.strip() and b.strip() and a.strip().lower() not in ("source", "src", "term"):
                    entries.append({"src": a.strip(), "tgt": b.strip().split(sep)[0].strip() if sep in (",", "，") else b.strip()})
                break
    return entries


STOPWORDS = set("a an the of in on at to for from by with without within into onto over under between among across about as is are was were be been being this that these those it its their our we you they he she i and or but nor so yet if then than which who whom whose what when where while although because since not no can could may might will would shall should must also such more most less least both either each other another same different new one two three first second third".split())


def term_candidates(segments_text, top=60):
    """Frequent domain-term candidates: acronym expansions, capitalised/hyphenated phrases, repeated noun-ish bigrams/trigrams."""
    text = "\n".join(segments_text)
    cands = Counter()
    kinds = {}
    for m in re.finditer(r"\b((?:[A-Z][A-Za-z\-]+\s+){1,6}[A-Za-z\-]+)\s+\(([A-Z][A-Za-z0-9\-]{1,10}s?)\)", text):
        cands[m.group(1)] += 3
        kinds[m.group(1)] = "acronym_expansion (%s)" % m.group(2)
    for m in re.finditer(r"\b([a-z][a-z]+(?:\s+[a-z]+){0,3})\s+\(([A-Z][A-Za-z0-9\-]{1,10}s?)\)", text):
        words = m.group(1).split()
        k = min(len(m.group(2)), len(words))
        phrase = " ".join(words[-k:]) if k >= 2 else m.group(1)
        cands[phrase] += 3
        kinds[phrase] = "acronym_expansion (%s)" % m.group(2)
    for acr, n in Counter(re.findall(r"\b[A-Z]{2,}[A-Za-z0-9\-]*\b", text)).items():
        if n >= 2 and acr not in STOP_UPPER:
            cands[acr] += n
            kinds.setdefault(acr, "acronym")
    for m in re.finditer(r"\b[a-z]+(?:-[a-z]+)+\b", text):
        cands[m.group(0)] += 1
        kinds.setdefault(m.group(0), "hyphenated")
    words = re.findall(r"[A-Za-z][A-Za-z\-]+", text.lower())
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            g = words[i:i + n]
            if g[0] in STOPWORDS or g[-1] in STOPWORDS or any(len(w) < 3 for w in g) or len(set(g)) < len(g):
                continue
            cands[" ".join(g)] += 1
            kinds.setdefault(" ".join(g), "ngram")
    out = []
    for term, c in cands.most_common():
        if kinds.get(term) == "ngram" and c < 3:
            continue
        if kinds.get(term) == "hyphenated" and c < 2:
            continue
        out.append({"src": term, "count": c, "kind": kinds.get(term, "")})
    # drop n-grams contained in a longer, equally frequent candidate
    out2 = []
    for e in out:
        if any(e is not o and e["src"].lower() in o["src"].lower() and o["count"] >= e["count"] and e["kind"] == "ngram" for o in out):
            continue
        out2.append(e)
    return out2[:top]
