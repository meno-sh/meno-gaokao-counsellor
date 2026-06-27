"""Intake entity-resolution for 高考志愿 — LLM-grounded against our real catalogue (Yuhe 2026-06-21).

Clean inputs hit the catalogue directly (no LLM). Anything not exactly in the catalogue
(缩写 cs/ee, 英文, 错别字, 口语 "学计算机的") is resolved by ONE LLM call that may ONLY pick
from the real lists we supply; its output is validated back against the catalogue so it
cannot invent. Category placeholders (某985/某211…) pass through. Fail-open: no key / LLM
error => passthrough the raw input as ok (never block the game). resolve_one(...) shape
unchanged so the endpoint/frontend are untouched.
"""
from __future__ import annotations
import json, os, re, difflib, functools, urllib.request
from core import paths

_HERE = os.path.dirname(__file__)
_DATA = paths.REAL_DATA
_CATEGORY_RE = re.compile(r"^(某)?(985|211|双一流|一本|二本|普通本科|本科|大学|学院)$")
_SEP = re.compile(r"\s*[@＠]\s*")

def _norm(s): return re.sub(r"[\s·、,，。.\-—_/（）()【】\[\]'\"]", "", (s or "").strip().lower())

@functools.lru_cache(maxsize=1)
def _majors():
    try: return json.load(open(os.path.join(_DATA, "major_catalogue.json"), encoding="utf-8")).get("all", [])
    except Exception: return []
@functools.lru_cache(maxsize=1)
def _schools():
    try: return list(json.load(open(os.path.join(_DATA, "school_index_sample.json"), encoding="utf-8")).keys())
    except Exception: return []
@functools.lru_cache(maxsize=1)
def _mset(): return set(_majors())
@functools.lru_cache(maxsize=1)
def _sset(): return set(_schools())
@functools.lru_cache(maxsize=1)
def _mnorm(): return {_norm(m): m for m in _majors()}
@functools.lru_cache(maxsize=1)
def _snorm(): return {_norm(s): s for s in _schools()}

def _exact_major(raw): return _mnorm().get(_norm(raw))
def _exact_school(raw): return _snorm().get(_norm(raw))
def _is_cat(raw): return bool(_CATEGORY_RE.match((raw or "").strip()))

def _llm(prompt, max_tokens=1500):
    model = os.environ.get("RESOLVE_MODEL", "openai/gpt-4o-mini")
    dk = os.environ.get("DEEPSEEK_API_KEY")
    if model.startswith("deepseek/") and dk:
        _url="https://api.deepseek.com/chat/completions"; key=dk
        model={"deepseek/deepseek-chat":"deepseek-v4-flash","deepseek/deepseek-v4-pro":"deepseek-v4-pro"}.get(model, model.split("/")[-1])
    else:
        _url="https://openrouter.ai/api/v1/chat/completions"; key=os.environ.get("OPENROUTER_API_KEY")
    if not key: return None
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0, "max_tokens": max_tokens,
                       "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(_url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    import time as _t
    for _a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(json.loads(r.read())["choices"][0]["message"]["content"])
        except Exception:
            _t.sleep(1.0 * (_a + 1))
    return None

def _resolve_llm(items):
    """items: [{i, major_raw, school_raw}] -> {i: {major:{...}, school:{...}}}.
    Resolved ONE AT A TIME — a single batch call made v4-flash mis-index the array (浙大→清华's answer)."""
    if not items: return {}
    res = {}
    for it in items:
        pool = difflib.get_close_matches((it["school_raw"] or it["major_raw"]), _schools(), n=8, cutoff=0.3)
        sl = "、".join(pool) or "(无相近)"
        prompt = (
            "你是高考志愿系统的实体解析器。从用户的原始输入里**识别出专业和学校两部分**(输入可能没有 @、把学校和专业连写在一起,如「北大哲学系」=北大+哲学、「浙大电子工程系」=浙大+电子工程,也可能只有专业)。把它们各自解析到真实清单里。"
            "**只能从给定范围选,绝不能编造。**\n\n"
            "【专业清单(专业只能从这里选)】\n" + "、".join(_majors()) + "\n\n"
            "【学校】从输入里**识别出其中的大学并给规范全称**(常见简称必须展开:北大→北京大学、清华→清华大学、浙大→浙江大学、复旦→复旦大学、上交→上海交通大学、人大→中国人民大学、华科→华中科技大学、武大→武汉大学 等);只有输入里**确实没有任何学校信息**才 notfound。下面候选池仅供参考、可能不全,不必拘泥:" + (sl or "(无)") + "。类别占位符(某985/某211/双一流/某大学)原样保留。\n\n"
            f'待解析(原始输入,可能是 专业@学校、学校与专业连写如「北大哲学系」、或任意写法):"{it["raw"]}"  (其中专业部分≈"{it["major_raw"]}",学校部分≈"{it["school_raw"] or "（未分出,自行从原始输入识别）"}")\n\n'
            "专业→最匹配的1个规范名(高置信 status=ok)或2-3候选(ambiguous)或 notfound;学校同理;常见缩写(cs→计算机科学与技术、软工→软件工程、ai→人工智能)直接 ok。\n"
            '只输出 JSON: {"major":{"canonical":"<或空>","candidates":["..."],"status":"ok|ambiguous|notfound"},'
            '"school":{"canonical":"<或空>","candidates":["..."],"status":"ok|ambiguous|notfound"}}')
        out = _llm(prompt)
        if out: res[it["i"]] = out
    return res

def _validate(field, pool):
    if not isinstance(field, dict): return {"status": "notfound", "candidates": []}
    seq = ([field.get("canonical")] if field.get("canonical") else []) + (field.get("candidates") or [])
    cands = list(dict.fromkeys([c for c in seq if c in pool]))
    if field.get("canonical") in pool and field.get("status") == "ok":
        return {"canonical": field["canonical"], "status": "ok", "kind": "llm", "candidates": cands or [field["canonical"]]}
    if cands: return {"status": "ambiguous", "candidates": cands[:3]}
    return {"status": "notfound", "candidates": []}

def _passthrough(major_raw, school_raw, em=None):
    mj = em or major_raw
    return {"raw": (f"{major_raw}@{school_raw}" if school_raw else major_raw),
            "major": {"canonical": mj, "status": "ok", "kind": ("exact" if em else "passthrough"), "candidates": []},
            "school": {"canonical": school_raw, "status": "ok", "kind": "passthrough", "candidates": ([school_raw] if school_raw else [])},
            "status": "ok", "canonical": (f"{mj}@{school_raw}" if school_raw else mj)}

def _difflib_field(raw, pool):
    """Fallback when the LLM call fails: catches typos (not abbreviations); flags fiction."""
    raw = (raw or "").strip()
    if not raw: return {"status": "notfound", "candidates": []}
    m = difflib.get_close_matches(raw, pool, n=3, cutoff=0.6)
    if m and difflib.SequenceMatcher(None, _norm(raw), _norm(m[0])).ratio() >= 0.86:
        return {"canonical": m[0], "status": "ok", "kind": "difflib", "candidates": m}
    if m: return {"status": "ambiguous", "candidates": m}
    return {"status": "notfound", "candidates": difflib.get_close_matches(raw, pool, n=3, cutoff=0.4)}

_ORD = {"notfound": 0, "ambiguous": 1, "ok": 2}
def resolve_options(options):
    parsed = []
    for raw in (options or []):
        if isinstance(raw, dict): raw = raw.get("label", "")
        raw = (raw or "").strip(); parts = _SEP.split(raw, 1)
        parsed.append({"raw": raw, "major_raw": (parts[0] if parts else raw).strip(),
                       "school_raw": (parts[1].strip() if len(parts) > 1 else "")})
    results = [None] * len(parsed); need = []
    for i, p in enumerate(parsed):
        em = _exact_major(p["major_raw"]); sr = p["school_raw"]
        es = _exact_school(sr) if sr else None; cat = _is_cat(sr) if sr else False
        if em and (sr == "" or es is not None or cat):
            sc = "" if sr == "" else (es if es else sr)
            results[i] = {"raw": p["raw"],
                "major": {"canonical": em, "status": "ok", "kind": "exact", "candidates": [em]},
                "school": {"canonical": sc, "status": "ok", "kind": ("category" if cat else ("exact" if es else "none")), "candidates": ([sc] if sc else [])},
                "status": "ok", "canonical": (f"{em}@{sc}" if sc else em)}
        else:
            need.append({"i": i, "raw": p["raw"], "major_raw": p["major_raw"], "school_raw": p["school_raw"]})
    llm = _resolve_llm(need) if need else {}
    for it in need:
        i = it["i"]; p = parsed[i]; got = llm.get(i); em = _exact_major(p["major_raw"])
        if got is None:                       # LLM call failed -> difflib fallback (flags fiction, doesn't blind-pass)
            m = {"canonical": em, "status": "ok", "kind": "exact", "candidates": [em]} if em else _difflib_field(p["major_raw"], _majors())
            if p["school_raw"] and _is_cat(p["school_raw"]):
                s2 = {"canonical": p["school_raw"], "status": "ok", "kind": "category", "candidates": []}
            elif p["school_raw"]:
                es2 = _exact_school(p["school_raw"]); s2 = {"canonical": es2, "status": "ok", "kind": "exact", "candidates": [es2]} if es2 else _difflib_field(p["school_raw"], _schools())
            else:
                s2 = {"canonical": "", "status": "ok", "kind": "none", "candidates": []}
            st = min([m["status"], s2["status"]], key=lambda x: _ORD[x])
            cn = None
            if st == "ok": cn = (f"{m.get('canonical','')}@{s2.get('canonical','')}".rstrip("@")) if p["school_raw"] else m.get("canonical")
            results[i] = {"raw": p["raw"], "major": m, "school": s2, "status": st, "canonical": cn}; continue
        m = {"canonical": em, "status": "ok", "kind": "exact", "candidates": [em]} if em else _validate(got.get("major"), _mset())
        if p["school_raw"] and _is_cat(p["school_raw"]):
            s = {"canonical": p["school_raw"], "status": "ok", "kind": "category", "candidates": []}
        elif p["school_raw"]:
            s = _validate(got.get("school"), _sset())
        elif got.get("school"):                 # no @, but the LLM pulled a school out of the raw string — use it
            s = _validate(got.get("school"), _sset())
        else:
            s = {"canonical": "", "status": "ok", "kind": "none", "candidates": []}
        status = min([m["status"], s["status"]], key=lambda x: _ORD[x])
        canon = None
        if status == "ok":
            canon = (f"{m.get('canonical','')}@{s.get('canonical','')}".rstrip("@")) if s.get("canonical") else m.get("canonical")
        results[i] = {"raw": p["raw"], "major": m, "school": s, "status": status, "canonical": canon}
    return results

def resolve_one(raw): return resolve_options([raw])[0]
