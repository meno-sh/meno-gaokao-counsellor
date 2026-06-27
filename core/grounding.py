"""Per-major grounding layer (ZH 2026-06-13).

Turns the distilled knowledge base (real_data/major_grounding.json) into a
concrete, fact/opinion-labeled prompt block, so scenes dramatize from REAL
major specifics instead of generic archetypes. Fixes the "被调剂到冷门专业 —
which 冷门专业?" genericness. Lookup is tolerant of messy free-text option
labels (a major named anywhere in the label triggers grounding).
"""
from __future__ import annotations
import json, os
from core import paths

_KB = None
def load_kb() -> dict:
    global _KB
    if _KB is None:
        p = paths.real_data("major_grounding.json")
        try:
            with open(p) as f:
                _KB = json.load(f)
        except FileNotFoundError:
            _KB = {}
    return _KB

_EMP = None
def load_employment() -> dict:
    """Real uni-level employment data harvested from 就业质量报告 (ZH 2026-06-16),
    keyed by full uni name. Replaces the miscalibrated distilled per-major salary."""
    global _EMP
    if _EMP is None:
        p = paths.real_data("uni_employment.json")
        try:
            with open(p) as fh:
                _EMP = json.load(fh)
        except FileNotFoundError:
            _EMP = {}
    return _EMP

def lookup_uni(label: str) -> dict | None:
    """Uni-level employment record whose name appears in the label (longest-name
    match wins, so 中国农业大学 beats 农业大学). None if unmatched or the uni has
    no published figure (honest null — many 民办/专科 publish no report)."""
    if not label:
        return None
    s = label.strip()
    best, blen = None, 0
    for uni, rec in load_employment().items():
        if uni and len(uni) >= 3 and uni in s and len(uni) > blen:
            best, blen = rec, len(uni)
    if not best:
        return None
    d = best.get("destinations", {}) or {}
    sal = best.get("salary", {}) or {}
    if not any([d.get("就业率"), d.get("升学率"), d.get("出国境率"),
                sal.get("应届平均月薪_rmb"), best.get("top_industries"),
                best.get("top_employers")]):
        return None
    return best

def uni_employment_block(label: str) -> str:
    """Report-level uni employment facts (就业率/升学率/出国率/起薪 with 口径),
    honest null where unpublished. Empty string if no uni matched the label."""
    rec = lookup_uni(label)
    if not rec:
        return ""
    d = rec.get("destinations", {}) or {}
    sal = rec.get("salary", {}) or {}
    def pct(x): return f"{x}%" if isinstance(x, (int, float)) else None
    bits = []
    if pct(d.get("就业率")): bits.append(f"就业率 {pct(d.get('就业率'))}")
    if pct(d.get("升学率")): bits.append(f"升学率 {pct(d.get('升学率'))}")
    if pct(d.get("出国境率")): bits.append(f"出国境率 {pct(d.get('出国境率'))}")
    if sal.get("应届平均月薪_rmb"):
        lvl = sal.get("level") or ""
        note = sal.get("note") or ""
        bits.append(f"应届平均月薪 {sal['应届平均月薪_rmb']}元({lvl}口径{('·'+note) if note else ''})")
    inds = "、".join((rec.get("top_industries") or [])[:4])
    emps = "、".join((rec.get("top_employers") or [])[:4])
    src = _sources.to_text(rec.get("sources"))
    year = rec.get("report_year") or ""
    lines = [f"院校就业(事实=就业质量报告{year}口径;为全校/学院级而非单一专业;缺失即不写,绝不编造):"]
    if bits: lines.append("  · 去向/起薪(事实): " + " | ".join(bits))
    if inds: lines.append(f"  · 主要行业(事实): {inds}")
    if emps: lines.append(f"  · 主要去向单位(事实): {emps}")
    if src: lines.append(f"  · 来源: {src}")
    return "\n".join(lines) if len(lines) > 1 else ""

_SUFFIXES = ["科学与工程", "科学与技术", "与应用数学", "及其自动化", "科学与技术",
             "工程与工艺", "科学与", "与工艺", "与工程", "工程", "技术", "设计", "学"]

def _stem(name: str) -> str:
    """Distinctive root of a major name, e.g. 材料科学与工程 -> 材料,
    视觉传达设计 -> 视觉传达, 计算机科学与技术 -> 计算机."""
    for suf in _SUFFIXES:
        if name.endswith(suf) and len(name) - len(suf) >= 2:
            return name[: -len(suf)]
    return name

def _match_keys(major: str, card: dict) -> list[str]:
    keys = {major, _stem(major)}
    for a in (card.get("aliases") or []):
        keys.add(a); keys.add(_stem(a))
    return [k for k in keys if k and len(k) >= 2]

def lookup_major(label: str) -> dict | None:
    """Best-match major card for a (possibly messy) option label, e.g.
    '中山大学材料' -> 材料科学与工程. Priority: a major matching by its own
    canonical NAME beats one matching only via an alias (LLM aliases often list
    *sibling* majors, e.g. 历史学 lists 考古学), which beats a stem match. On ties,
    longer match then the shorter (canonical) name. None if nothing matches."""
    if not label:
        return None
    s = label.strip()
    best, best_key = None, (0, 0, 0)   # (tier, match_len, -name_len)
    for major, card in load_kb().items():
        if not isinstance(card, dict) or "error" in card:
            continue
        cands = []
        # tier 3 — the major's own canonical name
        if major in s or (len(s) >= 2 and s in major):
            cands.append((3, min(len(major), len(s))))
        # tier 2 — a declared alias
        for a in (card.get("aliases") or []):
            if a and len(a) >= 2 and (a in s or s in a):
                cands.append((2, min(len(a), len(s))))
        # tier 1 — the distinctive stem of the name
        st = _stem(major)
        if st and len(st) >= 2 and st in s:
            cands.append((1, len(st)))
        if not cands:
            continue
        tier, mlen = max(cands)
        key = (tier, mlen, -len(major))
        if key > best_key:
            best, best_key = card, key
    return best

def grounding_block(label: str) -> str:
    """Render the concrete grounding block for the prompt, fact/opinion labeled.
    Falls back to an honest 'no grounding — don't fabricate' note if unmatched."""
    card = lookup_major(label)
    if not card:
        return ("专业真实背景【" + (label or "未知") + "】:(本专业暂无结构化 grounding;"
                "请基于常识写实,严禁编造具体数字/雇主/录取或就业统计,宁可定性。)")
    f = card.get("facts", {}) or {}
    l = card.get("lived", {}) or {}
    sc = card.get("sourced", {}) or {}   # 阳光高考 official, trackable (ZH 2026-06-21: distinguish from distilled)
    paths = f.get("typical_paths", {}) or {}
    paths_s = "; ".join(f"{k}:{v}" for k, v in paths.items() if v)
    def j(x): return "、".join(x) if isinstance(x, list) else (x or "")
    def jc(x, n): xs = x if isinstance(x, list) else ([x] if x else []); return "、".join(xs[:n]) + ("…" if len(xs) > n else "")
    lines = [
        f"专业真实背景【{card.get('major', label)}】(三层标注来源:**事实·官方**=可追溯;**蒸馏·未核验**=仅参考;**观点**=经验判断。"
        f"叙事可写实戏剧化,但任何数字/雇主名/薪资/录取就业统计必须取自'事实·官方'层或 school_facts,否则不写——宁可定性,绝不编造):",
    ]
    # ---- 官方源层 (阳光高考, 优先) ----
    if sc.get("core_courses_official"):
        lines.append(f"  · 核心课程(事实·阳光高考官方): {jc(sc['core_courses_official'], 14)}")
    if sc.get("培养目标"):
        lines.append(f"  · 培养目标(事实·官方): {str(sc['培养目标'])[:170]}")
    if sc.get("career_directions_official"):
        lines.append(f"  · 就业方向(事实·官方): {jc(sc['career_directions_official'], 10)}")
    _meta = " ".join(x for x in ["/".join(y for y in [sc.get('学科门类'), sc.get('专业类')] if y),
                                 sc.get('修业年限'), sc.get('授予学位')] if x)
    if _meta:
        lines.append(f"  · 学科归属/学制/学位(事实·官方): {_meta}")
    if sc.get("url"):
        lines.append(f"  · 官方来源(provenance): 阳光高考 {sc['url']}")
    # ---- 蒸馏层 (未核验, 仅在没有官方对应字段时补) ----
    if not sc.get("core_courses_official") and f.get("core_courses"):
        lines.append(f"  · 核心课程(蒸馏·未核验·仅参考): {j(f.get('core_courses'))}")
    if paths_s:
        lines.append(f"  · 典型去向(蒸馏·未核验·仅参考): {paths_s}")
    if not sc.get("career_directions_official") and f.get("career_destinations"):
        lines.append(f"  · 真实岗位(蒸馏·未核验·仅参考): {j(f.get('career_destinations'))}")
    if f.get("employment_relatedness"):
        lines.append(f"  · 对口度(蒸馏·观点): {f.get('employment_relatedness','')}(蒸馏薪资数字不可靠,不写;真实起薪以下方'院校就业'报告口径为准)")
    # ---- 观点层 (经验, 无源) ----
    if l.get("daily_reality"): lines.append(f"  · 日常真实(观点): {l.get('daily_reality','')}")
    if l.get("failure_modes"): lines.append(f"  · 真实的坑(观点): {j(l.get('failure_modes'))}")
    if l.get("common_pivots"): lines.append(f"  · 常见转向(观点): {j(l.get('common_pivots'))}")
    if l.get("reputation_note"): lines.append(f"  · 圈内评价(观点): {l.get('reputation_note','')}")
    block = "\n".join(lines)
    emp = uni_employment_block(label)
    if emp:
        block += "\n" + emp
    return block

CONCRETENESS_CONTRACT = (
    "具体性契约: 场景必须落到上面'专业真实背景'里的具体课程/岗位/转向上,不要泛泛说"
    "'一个冷门专业''一份普通工作'。可以有写实的叙事色彩,但任何数字、具体雇主名、薪资、"
    "录取或就业统计都必须来自 grounding 或 school_facts,否则一律不写(宁可定性,绝不编造)。"
    "选项必须是这个专业/身份的人真实会面对的岔路,不得引入与本专业无关的领域。"
)


# ---- 雨来 (Yusoong) authoritative tier (ZH 2026-06-17) ----
# Wired into the investigator: 专业 detail + 专业判别 (误区/红线) nationally, plus
# 录取分/等位分 gated to provinces 雨来 actually covers (currently Yunnan) so we
# never surface empty score blocks. All calls are best-effort: the client returns
# None on any error/disabled, and these helpers return "" so the game is unchanged
# when 雨来 is unavailable.
from core import yulai as _yulai
from core import sources as _sources

_YL_CACHE = {}
_PROV_MAP = {
    "云南": "yunnan", "yunnan": "yunnan", "四川": "sichuan", "安徽": "anhui",
    "吉林": "jilin", "北京": "beijing", "上海": "shanghai", "广东": "guangdong",
    "浙江": "zhejiang", "江苏": "jiangsu", "山东": "shandong", "河南": "henan",
}

def _split_label(label: str):
    """'专业@学校' -> (major, college). No '@' -> (label, None)."""
    if not label:
        return "", None
    if "@" in label:
        a, b = label.split("@", 1)
        return a.strip(), b.strip()
    return label.strip(), None

def detect_province(text: str):
    """Best-effort province pinyin id from free text (for score queries)."""
    for name, pid in _PROV_MAP.items():
        if name in (text or ""):
            return pid
    return None

def _yl_major_id(major: str):
    if not major:
        return None
    r = _yulai.search_majors(q=major)
    rows = (r or {}).get("data") or []
    return rows[0].get("majorId") if rows else None

def yulai_major_block(label: str) -> str:
    """Authoritative 专业 facts from 雨来: official summary/taxonomy + 专业判别
    (误区/红线). National, no province needed. '' if 雨来 has nothing/disabled."""
    if not _yulai.enabled():
        return ""
    major, _ = _split_label(label)
    if major in _YL_CACHE:
        return _YL_CACHE[major]
    out = ""
    try:
        mid = _yl_major_id(major)
        if mid:
            det = (_yulai.major_detail(mid) or {}).get("data") or {}
            dec = (_yulai.major_decision(mid) or {}).get("data") or {}
            lines = []
            cat = "/".join(x for x in [det.get("category"), det.get("subcategory")] if x)
            if det.get("summary"):
                lines.append(f"  · 官方简介(事实): {str(det['summary'])[:160]}")
            if cat:
                lines.append(f"  · 学科归属(事实): {cat}")
            mis = dec.get("误区") or dec.get("misconceptions")
            if mis:
                mis = mis if isinstance(mis, list) else [mis]
                lines.append("  · 常见误区(权威判别): " + "；".join(str(x) for x in mis[:3]))
            red = dec.get("redLine") or dec.get("红线") or dec.get("redlines")
            if red:
                red = red if isinstance(red, list) else [red]
                lines.append("  · 报考红线(权威判别): " + "；".join(str(x) for x in red[:3]))
            if lines:
                out = "雨来权威专业库(事实=合作平台核验,优先于本地KB):\n" + "\n".join(lines)
    except Exception:
        out = ""
    _YL_CACHE[major] = out
    return out

def yulai_scores_line(label: str, province: str, year: int = 2024) -> str:
    """录取分 for this 专业@学校 in the student's province — ONLY if 雨来 covers it
    (returns non-empty). '' otherwise, so no empty score blocks are shown."""
    if not (_yulai.enabled() and province):
        return ""
    major, college = _split_label(label)
    try:
        r = _yulai.scores(province_id=province, year=year, college_name=college, major_name=major)
        rows = (r or {}).get("data") or []
        if not rows:
            return ""
        cov = ((r or {}).get("meta") or {}).get("coverage", "")
        top = rows[0]
        bits = [f"{k}:{top[k]}" for k in ("year", "minScore", "minRank", "batch") if top.get(k) is not None]
        if not bits:
            return ""
        return (f"雨来历年录取分(事实,{province}/{cov}): " + " ".join(bits))
    except Exception:
        return ""
