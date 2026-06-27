"""Build the per-UNIVERSITY employment knowledge base (ZH 2026-06-16).

Web-search-grounded harvest of each school's 毕业生就业质量年度报告 (+ 麦可思 / 阳光高考):
destinations (升学/出国/就业/考公 rates), salary, top industries/employers, and
per-学院 breakdown where the report gives one. Uni-level (and 学院-level) — because
per-specific-major salary is mostly NOT published; the major dimension stays in
major_grounding.json and is stitched per session by the investigator.

Honest provenance: only authoritative sources; if no report is found, returns
{"no_report": true} rather than hallucinating. Output: real_data/uni_employment.json.
Incremental + re-runnable. `--limit N` for test runs.
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "real_data", "uni_employment.json")
IDX = os.path.join(HERE, "real_data", "school_index_sample.json")
MODEL = os.environ.get("EMPLOYMENT_MODEL", "deepseek/deepseek-chat")

PROMPT = """你是中国高校就业数据研究者。请基于大学「{uni}」最新的《毕业生就业质量年度报告》(及麦可思 MyCOS、阳光高考平台、教育部公开数据)产出一张结构化就业卡片,用于高考志愿"人生推演"游戏的真实 grounding。
铁律:① 只采信权威来源——该校就业质量报告、麦可思、阳光高考、教育部/统计局官方;② 数字只能来自真实报告,不确定一律填 null,绝不编造;③ 若检索不到「{uni}」自己的就业质量报告或可靠就业数据,诚实返回 {{"uni":"{uni}","no_report":true}};④ 正文不要插入任何引用标记或链接,来源只写进 sources。
只输出一个 JSON 对象,无额外文字、无代码块标记:
{{
 "uni": "{uni}",
 "report_year": "报告年份(如2023);无则 null",
 "destinations": {{"升学率":"百分比或null","出国境率":"百分比或null","就业率":"百分比或null","考公考编":"定性/百分比或null"}},
 "salary": {{"应届平均月薪_rmb":"数值或区间或null","level":"全校级/学院级/null","note":"一句口径说明"}},
 "top_industries": ["毕业生主要去向行业,3-6个;无则[]"],
 "top_employers": ["主要用人单位,3-6个;无则[]"],
 "by_college": [{{"college":"学院名","note":"该院去向/薪资亮点"}}],
 "sources": ["实际采信的权威来源名,如'XX大学2023届就业质量报告''麦可思2023'"],
 "no_report": false
}}
简体中文。"""

def call(uni: str, key: str) -> dict:
    payload = {"model": MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(uni=uni)}],
        "response_format": {"type": "json_object"},
        "plugins": [{"id": "web", "max_results": 4}],
        "max_tokens": 1600, "temperature": 0.3}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://reflect.meno.sh", "X-Title": "reflection-game-employment"})
    last = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                p = json.loads(resp.read().decode())
            txt = p["choices"][0]["message"].get("content") or ""
            txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
            card = json.loads(txt)
            card["provenance"] = "web-distilled 2026-06-16 (deepseek-v3 + web); authoritative-source restricted"
            return card
        except Exception as e:
            last = f"{type(e).__name__}:{e}"; time.sleep(3 * (attempt + 1))
    return {"uni": uni, "error": last}

def _uni_list():
    idx = json.load(open(IDX, encoding="utf-8"))
    # publishers first: 双一流 / 985 / 211 publish reports most reliably, then the rest.
    names = list(idx.keys())
    names.sort(key=lambda n: 0 if (idx[n].get("双一流") or idx[n].get("985") or idx[n].get("211")) else 1)
    return names

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6); a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key: print("OPENROUTER_API_KEY missing", file=sys.stderr); sys.exit(1)
    unis = _uni_list()
    out = {}
    if os.path.exists(OUT):
        try: out = json.load(open(OUT, encoding="utf-8"))
        except Exception: out = {}
    todo = [u for u in unis if u not in out or "error" in out.get(u, {})]
    if a.limit: todo = todo[:a.limit]
    print(f"index: {len(unis)} unis; have {len(out)}; harvesting {len(todo)}")
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(call, u, key): u for u in todo}
        for f in as_completed(futs):
            u = futs[f]
            try: out[u] = f.result()
            except Exception as e: out[u] = {"uni": u, "error": f"{type(e).__name__}:{e}"}
            done += 1
            if done % 10 == 0 or done == len(todo):
                json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
                print(f"  {done}/{len(todo)} saved")
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    nr = sum(1 for c in out.values() if c.get("no_report"))
    er = sum(1 for c in out.values() if "error" in c)
    print(f"DONE: {len(out)} cards | no_report={nr} | error={er}")

if __name__ == "__main__":
    main()
