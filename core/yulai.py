"""雨来 (Yusoong) Partner API client — authoritative gaokao data source (ZH 2026-06-16).

Read-only data for the 反思均衡 / 志愿推演 game: 专业目录 / 相关推荐 / 专业判别 /
等位分换算 / 历年录取分 / 脱敏学生画像. Spec: developer/partner-yusoong/openapi.yaml.

Graceful by design: with no key configured (YULAI_API_KEY unset), `enabled` is False
and every method returns None — callers fall back to the grounding KB / web search, so
the live game never breaks while we wait on the key. Set YULAI_API_KEY (`yl_live_…`)
(+ optional YULAI_BASE_URL) to go live.

Source tier (investigator): 雨来 → grounding KB → web-search → qualitative.
"""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request

_BASE = os.environ.get("YULAI_BASE_URL", "https://gaokao.yusoong.com/api/v1/partner").rstrip("/")
_KEY = os.environ.get("YULAI_API_KEY", "") or os.environ.get("PARTNER_API_KEYS", "").split(",")[0].strip()
_TIMEOUT = float(os.environ.get("YULAI_TIMEOUT", "8"))


def enabled() -> bool:
    return bool(_KEY)


def _req(method: str, path: str, *, params: dict | None = None, body: dict | None = None):
    """Returns unwrapped `data` on success, None on any error / disabled. Never raises."""
    if not _KEY:
        return None
    url = _BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={"Authorization": f"Bearer {_KEY}", "Content-Type": "application/json",
                 "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                env = json.loads(r.read().decode())
            if isinstance(env, dict) and env.get("ok"):
                return {"data": env.get("data"), "meta": env.get("meta") or {}}
            return None  # {ok:false} — let caller fall back
        except urllib.error.HTTPError as e:
            if e.code == 429:  # RATE_LIMITED — back off then retry
                time.sleep(1.5 * (attempt + 1)); continue
            return None
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    return None


# --- 专业 (majors) ---
def search_majors(q=None, track=None, category=None, subcategory=None, page=1):
    return _req("GET", "/majors", params={"q": q, "track": track, "category": category,
                                          "subcategory": subcategory, "page": page})

def major_detail(major_id):
    return _req("GET", f"/majors/{urllib.parse.quote(str(major_id))}")

def majors_batch(ids):
    return _req("POST", "/majors/batch", body={"ids": list(ids)})

def majors_related(q=None, track_filter=None, hit_major_ids=None):
    return _req("GET", "/majors/related", params={"q": q, "trackFilter": track_filter,
                                                   "hitMajorIds": hit_major_ids})

def majors_facets(track=None, category=None):
    return _req("GET", "/majors/facets", params={"track": track, "category": category})

def major_decision(major_id):
    """专业判别: 误区/同类/替代/红线/核查."""
    return _req("GET", f"/majors/{urllib.parse.quote(str(major_id))}/decision")

# --- 等位分 (equivalent score) ---
def equivalent_score(*, score, subject_type, province_id, year=None):
    """subjectType is an ENGLISH enum: physics/history/arts/science. 等位分 currently
    only has 'ready' data for 云南 — check data.status before use."""
    return _req("POST", "/equivalent-score",
                body={"score": score, "subjectType": subject_type, "provinceId": province_id, "year": year})

def equivalent_score_batch(items):
    return _req("POST", "/equivalent-score/batch", body={"items": list(items)[:50]})

# --- 录取分 (admission scores) ---
def scores(*, province_id, year, college_name=None, major_name=None, page=1, page_size=20):
    """历年录取分. meta.coverage flags reliability (<prov>_verified / data_may_be_partial)."""
    return _req("GET", "/scores", params={"provinceId": province_id, "year": year,
        "collegeName": college_name, "majorName": major_name, "page": page, "pageSize": page_size})

# --- 画像 (de-identified profile; needs that student's authorization, else 403→None) ---
def student_profile(student_id):
    return _req("GET", f"/student-profile/{urllib.parse.quote(str(student_id))}")


if __name__ == "__main__":
    print(f"yulai client: base={_BASE} enabled={enabled()} (set YULAI_API_KEY to go live)")
    if enabled():
        r = search_majors(q="计算机")
        print("search_majors('计算机'):", "ok" if r else "no data / error")
