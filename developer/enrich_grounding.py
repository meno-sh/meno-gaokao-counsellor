"""Enrich major_grounding.json with 雨来 (Yusoong) authoritative data (ZH 2026-06-19).

The static KB was 100% LLM-distilled ("pending real-report cross-check"). 雨来 is now
live, so this does a NON-DESTRUCTIVE cross-check pass per major:
  • resolve Chinese name → majorId via search (EXACT-name match only — никаких guesses)
  • pull major_detail (courses/careers/summary/taxonomy/evidenceStatus) + decision
    (misconceptions/redLine/substitutes/sameClass/checks)
  • where detail.evidenceStatus == verified: replace facts.core_courses with 雨来's
    authoritative courses and flip provenance → "雨来核验 (verified)" + confidence high
  • attach a `yulai` block (authoritative, separately sourced — does NOT overwrite the
    LLM `lived` opinion fields) and a structured `sources` entry (tier 雨来-verified)
Resumable: skips majors that already carry a `yulai` block (unless --force). Honest:
no match / source_limited is recorded in provenance, never silently upgraded.
"""
from __future__ import annotations
import json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import yulai

HERE = os.path.dirname(os.path.abspath(__file__))
GROUND = os.path.join(HERE, "real_data", "major_grounding.json")
STAMP = "2026-06-19"
YL_SOURCE = {"title": "雨来 Yusoong 专业核验库", "url": "https://gaokao.yusoong.com", "tier": "雨来-verified"}


def resolve_id(name):
    """EXACT-name match only → (name, majorId|None)."""
    r = yulai.search_majors(q=name)
    rows = (r or {}).get("data") or []
    for row in rows:
        if row.get("name") == name:
            return name, row.get("majorId")
    return name, None


def fetch(mid):
    det = (yulai.major_detail(mid) or {}).get("data") or {}
    dec = (yulai.major_decision(mid) or {}).get("data") or {}
    return det, dec


def enrich_card(card, det, dec):
    es = det.get("evidenceStatus")
    yl = {
        "majorId": det.get("majorId"),
        "track": det.get("track"), "category": det.get("category"),
        "subcategory": det.get("subcategory"),
        "summary": det.get("summary"), "courses": det.get("courses"),
        "careers": det.get("careers"), "evidenceStatus": es,
        "decision": {
            "misconceptions": dec.get("misconceptions"),
            "redLine": dec.get("redLine"),
            "sameClass": dec.get("sameClass"),
            "substitutes": dec.get("substitutes"),
            "checks": dec.get("checks"),
            "evidenceStatus": dec.get("evidenceStatus"),
        },
        "synced": STAMP,
    }
    card["yulai"] = yl
    # authoritative replace of core_courses ONLY when verified + non-empty
    if es == "verified" and det.get("courses"):
        card.setdefault("facts", {})["core_courses"] = det["courses"]
        card["confidence"] = "high"
        card["provenance"] = (f"雨来核验 (verified) {STAMP}; core_courses+分类来自雨来合作平台;"
                              " lived 字段仍为 LLM 蒸馏(观点)")
        card.setdefault("sources", [])
        if YL_SOURCE not in card["sources"]:
            card["sources"].insert(0, dict(YL_SOURCE))
    else:
        base = (card.get("provenance") or "").split("；雨来")[0].split("; 雨来")[0]
        card["provenance"] = f"{base}; 雨来匹配:{es or 'source_limited'} {STAMP}"
    return card


def main():
    force = "--force" in sys.argv
    limit = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    if not yulai.enabled():
        print("雨来 not enabled (no key). Export PARTNER_API_KEYS / YULAI_API_KEY.", file=sys.stderr)
        sys.exit(1)
    data = json.load(open(GROUND, encoding="utf-8"))
    names = [n for n, c in data.items() if "error" not in c and (force or "yulai" not in c)]
    if limit:
        names = names[:limit]
    print(f"{len(data)} majors; enriching {len(names)} (skip {len(data)-len(names)} done/errored)")

    # phase 1: resolve ids (exact-name) concurrently
    ids = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed([ex.submit(resolve_id, n) for n in names]):
            n, mid = fut.result()
            if mid:
                ids[n] = mid
    print(f"resolved {len(ids)}/{len(names)} via exact-name match")

    # phase 2: detail+decision concurrently, enrich, checkpoint
    matched = verified = 0
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch, mid): n for n, mid in ids.items()}
        for fut in as_completed(futs):
            n = futs[fut]
            try:
                det, dec = fut.result()
            except Exception as e:
                print(f"  fetch fail {n}: {e}"); continue
            if not det:
                continue
            enrich_card(data[n], det, dec)
            matched += 1
            if det.get("evidenceStatus") == "verified":
                verified += 1
            done += 1
            if done % 100 == 0:
                json.dump(data, open(GROUND, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                print(f"  …{done} enriched (checkpoint)", flush=True)

    # mark the no-match ones honestly
    nomatch = [n for n in names if n not in ids]
    for n in nomatch:
        c = data[n]
        base = (c.get("provenance") or "").split("；雨来")[0].split("; 雨来")[0]
        c["provenance"] = f"{base}; 雨来无匹配 {STAMP}"

    json.dump(data, open(GROUND, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nDONE: matched {matched}, verified {verified}, no-match {len(nomatch)}. wrote {GROUND}")


if __name__ == "__main__":
    main()
