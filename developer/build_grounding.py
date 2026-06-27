"""Build the per-major grounding knowledge base (ZH 2026-06-13).

Distils a structured card per major via the LLM, with a STRICT split between
`facts` (report-corroborable: courses, destinations, paths, salary, relatedness)
and `lived` (opinion/张雪峰-style: daily reality, failure modes, pivots, reputation).
Output: real_data/major_grounding.json. Re-runnable + extensible (edit MAJORS).

Provenance is honest: v1 is LLM-distilled and labeled fact/opinion; real-report
(就业质量报告 / 麦可思) cross-check is a follow-up (ZH is handling scraping).
"""
from __future__ import annotations
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "real_data", "major_grounding.json")
MODEL = os.environ.get("GROUNDING_MODEL", "deepseek/deepseek-chat")  # V3, fast

# 50 most-deliberated undergrad majors across the 学科门类 (incl. ZH's examples).
MAJORS = [
 "计算机科学与技术","软件工程","人工智能","电子信息工程","通信工程","自动化","机械工程",
 "材料科学与工程","土木工程","电气工程及其自动化","化学工程与工艺","生物医学工程","环境工程",
 "航空航天工程","数学与应用数学","物理学","化学","生物科学","统计学",
 "临床医学","口腔医学","护理学","药学","中医学",
 "金融学","经济学","会计学","工商管理","国际经济与贸易","市场营销",
 "法学","政治学与行政学","社会学","心理学",
 "汉语言文学","英语","新闻学","网络与新媒体",
 "教育学","学前教育",
 "视觉传达设计","产品设计","环境设计","数字媒体艺术","美术学","音乐学",
 "建筑学","城乡规划","农学","食品科学与工程",
]

PROMPT = """你是中国高考志愿与专业就业领域的资深研究者。为专业「{major}」产出一张结构化知识卡片,用于给一个"人生推演"游戏提供真实 grounding。
要求:具体、写实、不空泛(给出真实课程名/岗位名/转向路径);严格区分【事实】(可被高校就业质量报告、麦可思就业蓝皮书等公开报告佐证的客观信息)与【观点/经验】(基于普遍认知的判断,如张雪峰式解读)。
只输出一个 JSON 对象,不要任何额外文字或代码块标记:
{{
 "major": "{major}",
 "aliases": ["常见简称/别名/相近专业,2-4个"],
 "facts": {{
   "core_courses": ["6-10门真实核心课程"],
   "typical_paths": {{"升学(考研/保研)":"一句:大致去向与常见性","就业":"主要行业与岗位","出国留学":"一句"}},
   "career_destinations": ["真实典型岗位/雇主类型,5-8个"],
   "first_job_salary_rmb_monthly": "一线/新一线城市应届起薪区间(如 8k-15k);不确定填 null",
   "employment_relatedness": "对口率定性(高/中/低)+一句说明"
 }},
 "lived": {{
   "daily_reality": "在校日常真实质感(课业/实验/作品集/竞赛/实习强度),2-3句",
   "failure_modes": ["这个专业真实的坑/风险,4-6条(如天坑/就业难/被劝退点);只写**对该专业确有依据**的,不要套用「35岁」这类网络梗或泛化刻板印象)"],
   "common_pivots": ["读这个专业的人常见的转向,4-6条(如转码/考公/考研换方向/转行)"],
   "reputation_note": "圈内对这个专业的普遍评价或争议,1-2句"
 }},
 "confidence": "high/medium/low(你对 facts 与公开报告一致性的信心)"
}}
不要编造精确数字;不确定就用区间或定性。lived 全部视为观点。简体中文。"""

def call(major: str, key: str) -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(major=major)}],
        "response_format": {"type": "json_object"},
        "max_tokens": 2000, "temperature": 0.4,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://reflect.meno.sh", "X-Title": "reflection-game-grounding"})
    last = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode())
            txt = payload["choices"][0]["message"].get("content") or ""
            txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
            card = json.loads(txt)
            card["provenance"] = "LLM-distilled 2026-06-13 (deepseek-v3); pending real-report cross-check"
            return card
        except Exception as e:
            last = f"{type(e).__name__}:{e}"; time.sleep(3 * (attempt + 1))
    return {"major": major, "error": last}

def _major_list():
    """Full catalogue if enumerated (real_data/major_catalogue.json), else the
    built-in 50. Union, de-duped, order-preserving."""
    cat = os.path.join(HERE, "real_data", "major_catalogue.json")
    names = list(MAJORS)
    if os.path.exists(cat):
        try:
            allm = json.load(open(cat)).get("all", [])
            seen = set(names)
            for m in allm:
                if m and m not in seen:
                    seen.add(m); names.append(m)
        except Exception as e:
            print(f"(catalogue load failed: {e}; using built-in 50)", file=sys.stderr)
    return names

def main():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY missing", file=sys.stderr); sys.exit(1)
    # incremental: keep already-distilled cards, only fill in the missing majors
    out = {}
    if os.path.exists(OUT):
        try: out = json.load(open(OUT))
        except Exception: out = {}
    majors = _major_list()
    todo = [m for m in majors if m not in out or "error" in out.get(m, {})]
    print(f"catalogue: {len(majors)} majors; already have {len(out)}; distilling {len(todo)}")
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(call, m, key): m for m in todo}
        for f in as_completed(futs):
            m = futs[f]; card = f.result(); out[m] = card; done += 1
            ok = "OK" if "error" not in card else "ERR " + card["error"][:40]
            if done % 25 == 0 or "error" in card:
                print(f"[{done}/{len(todo)}] {m}: {ok}", flush=True)
            # checkpoint every 50 so a crash doesn't lose progress
            if done % 50 == 0:
                json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=2)
    errs = [m for m, c in out.items() if "error" in c]
    print(f"\nwrote {OUT}: {len(out)} majors total, {len(errs)} errors{(': '+', '.join(errs[:10])) if errs else ''}")

if __name__ == "__main__":
    main()
