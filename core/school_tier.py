"""Factual school-tier lookup from real 高考 admission data.

Data: gaokao/real_data/school_index_sample.json — built from public dataset
labolado/gaokao_2016-2020 (录取分数线 2016-2020). Sample = the 北京-文科 file
(~490 schools w/ 985/211/双一流 flags + batch). Expand by merging more province
files. Used to ground the life-trajectory seed with the school's REAL tier
instead of guessing, so the sim doesn't fabricate prestige facts.
"""
from __future__ import annotations
import json, os
from core import paths
_IDX = None
def _idx():
    global _IDX
    if _IDX is None:
        p = paths.real_data("school_index_sample.json")
        try:
            _IDX = json.load(open(p, encoding="utf-8"))
        except Exception:
            _IDX = {}
    return _IDX

def lookup(school_text: str):
    """Fuzzy substring match a free-text school name -> tier facts, or None."""
    if not school_text:
        return None
    idx = _idx()
    s = school_text.strip()
    # exact, then substring either direction (handles '顶尖985' style free text poorly,
    # so callers pass a real school name when they have one)
    if s in idx:
        return {"school": s, **idx[s]}
    for name, v in idx.items():
        if name in s or (len(s) >= 4 and s in name):
            return {"school": name, **v}
    return None

def tier_phrase(facts) -> str:
    if not facts:
        return ""
    tags = [t for t in ("985", "211", "双一流") if facts.get(t)]
    return ("真实层次:" + "/".join(tags)) if tags else "真实层次:普通本科(非985/211)"
