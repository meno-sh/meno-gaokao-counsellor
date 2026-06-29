"""RAG over 专业@学校 student write-ups, for grounding per-stop generation.

Ranking (per Tianyi): major-proximity is LEXICOGRAPHIC (a hard bucket that strictly
dominates), then a WEIGHTED SUM of normalized {tier-proximity, stop-factor, embedding-sim}
breaks ties within a bucket. All sub-scores normalized to [0,1] before weighting.
Pure-python (the engine runs on a numpy-less interpreter); corpus lives in /data.
"""
import json, os, math, urllib.request

_DIR = os.environ.get("RAG_CORPUS_DIR") or next(
    (d for d in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag-corpus"),
                 "/data/reflection-game/gaokao-data/rag-corpus")
     if os.path.exists(os.path.join(d, "pieces.jsonl"))),
    "/data/reflection-game/gaokao-data/rag-corpus")
_EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "google/gemini-embedding-2")
_PIECES = None      # id -> piece dict
_EMB = None         # id -> [floats]
_MAJ2MEN = None     # major name -> 门类 (from the corpus)

def _load():
    global _PIECES, _EMB, _MAJ2MEN
    if _PIECES is not None:
        return
    _PIECES, _MAJ2MEN = {}, {}
    with open(os.path.join(_DIR, "pieces.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            p = json.loads(line)
            _PIECES[p["id"]] = p
            if p.get("keyed") and p.get("menlei"):
                _MAJ2MEN.setdefault(p["major"], p["menlei"])
    with open(os.path.join(_DIR, "embeddings.json"), encoding="utf-8") as fh:
        _EMB = json.load(fh)

def _menlei_of(major):
    _load()
    if major in _MAJ2MEN:
        return _MAJ2MEN[major]
    for m, men in _MAJ2MEN.items():          # loose: shared stem (e.g. 计算机科学与技术 ~ 计算机)
        if major and (major in m or m in major):
            return men
    return None

def _tier_rank(tier):
    if not tier:
        return 0
    return (2 if tier.get("985") else 0) + (1 if tier.get("211") else 0) + (1 if tier.get("双一流") else 0)  # 0..4

def _pick_tier_rank(uni):
    if not uni:
        return 0
    try:
        from core import school_tier
        f = school_tier.lookup(uni) or {}
        return _tier_rank({"985": f.get("985"), "211": f.get("211"), "双一流": f.get("双一流")})
    except Exception:
        return 0

def _cos01(a, b):
    if not a or not b:
        return 0.0
    s = da = db = 0.0
    for x, y in zip(a, b):
        s += x * y; da += x * x; db += y * y
    if da == 0 or db == 0:
        return 0.0
    return (s / (math.sqrt(da) * math.sqrt(db)) + 1.0) / 2.0   # cosine -> [0,1]

def embed(text):
    """Embed one string via the configured embedding model. Returns [] on failure."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    try:
        body = json.dumps({"model": _EMBED_MODEL, "input": text}).encode("utf-8")
        req = urllib.request.Request("https://openrouter.ai/api/v1/embeddings", data=body,
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        return d["data"][0]["embedding"]
    except Exception:
        return []

def _major_bucket(piece, pick_major, pick_menlei):
    if piece.get("major") == pick_major:
        return 2                              # exact major
    if pick_menlei and piece.get("menlei") == pick_menlei:
        return 1                              # same 门类
    return 0                                  # other

def _stop_factor_score(piece, factor):
    if not factor:
        return 0.0
    blob = piece.get("full_text", "") + " " + " ".join((piece.get("sections") or {}).values())
    terms = [t for t in factor.replace("/", " ").replace("、", " ").split() if len(t) >= 2]
    if not terms:
        terms = [factor]
    hit = sum(1 for t in terms if t in blob)
    return hit / float(len(terms))

def retrieve(pick_major, pick_uni, considerations, stop_factor="", k=5,
             w_tier=0.5, w_sf=0.25, w_emb=0.25, _qvec=None):
    """Rank keyed (专业@学校) pieces for one pick. Lexicographic major-bucket, then the
    weighted sum. `considerations` = a paragraph describing what this stop weighs (the
    embedding query, matched against full-text). Pass _qvec to reuse an embedding."""
    _load()
    pmen = _menlei_of(pick_major)
    ptr = _pick_tier_rank(pick_uni)
    qvec = _qvec if _qvec is not None else (embed(considerations) if considerations else [])
    scored = []
    for pid, piece in _PIECES.items():
        if not piece.get("keyed"):
            continue
        bucket = _major_bucket(piece, pick_major, pmen)
        tier_prox = 1.0 - abs(ptr - _tier_rank(piece.get("tier"))) / 4.0
        sf = _stop_factor_score(piece, stop_factor)
        es = _cos01(qvec, _EMB.get(pid)) if qvec else 0.0
        weighted = w_tier * tier_prox + w_sf * sf + w_emb * es
        scored.append((bucket, weighted, pid, piece, tier_prox, sf, es))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    out = []
    for bucket, weighted, pid, piece, tp, sf, es in scored[:k]:
        out.append({"id": pid, "major": piece["major"], "university": piece["university"],
                    "menlei": piece.get("menlei"), "full_text": piece["full_text"],
                    "_bucket": bucket, "_score": round(weighted, 4),
                    "_tier": round(tp, 3), "_sf": round(sf, 3), "_emb": round(es, 3)})
    return out

def stop_agnostic_pool(picks, considerations="", k=5):
    """Phase A: precompute a stop-agnostic pool per pick (no stop-factor) the moment the
    user finishes the uni-major list. picks = [{major, university}]."""
    qvec = embed(considerations) if considerations else []
    return {("%s@%s" % (p.get("major", ""), p.get("university", ""))):
            retrieve(p.get("major", ""), p.get("university", ""), considerations,
                     stop_factor="", k=k, _qvec=qvec)
            for p in picks}
