"""Diverse synthetic gaokao profiles by DETERMINISTIC GRID ENUMERATION (scales to
hundreds/thousands with guaranteed structural diversity; the LLM only fleshes
surface text). 6 axes = 3×2×2×4×3×5 = 720 cells. ZH 2026-06-18.
N_PROFILES profiles → eval/profiles.json (sample N distinct cells; >720 reuses cells w/ variation)."""
import json, os, re, random, itertools, urllib.request
random.seed(7)
N = int(os.environ.get("N_PROFILES", "24"))
KEY = os.environ["OPENROUTER_API_KEY"]
AXES = {
 "家庭压力": ["无", "中", "强"],
 "自我清晰度": ["清晰", "迷茫"],
 "风险": ["稳健", "冒险"],
 "价值倾向": ["物质回报", "意义", "声望标签", "技能内核"],
 "地域": ["一线城市", "省会", "县城农村"],
 "去向倾向": ["考公考编", "就业", "创业", "考研保研", "出国"],
}
cells = list(itertools.product(*AXES.values()))           # 720
random.shuffle(cells)
keys = list(AXES.keys())
pick = [cells[i % len(cells)] for i in range(N)]          # >720 reuses (LLM variation differentiates)
def cell_str(c): return " · ".join(f"{k}={v}" for k, v in zip(keys, c))

def flesh(batch):
    spec = "\n".join(f"{i+1}. {cell_str(c)}" for i, c in enumerate(batch))
    prompt = f"""把下面每个**轴组合**充实成一个真实口吻的高三学生 profile。严格贴合它的组合(家庭压力/自我清晰度/风险/价值/地域/去向),彼此要不一样。
{spec}

只输出 JSON: {{"profiles":[{{"tag":"轴组合","free_text":"1-2句自我描述","destination_pref":["去向",...3-5个],"options":["专业@学校",...3个真实校专业]}}, ...按上面顺序]}}"""
    payload={"model":"deepseek/deepseek-chat","messages":[{"role":"user","content":prompt}],"response_format":{"type":"json_object"},"max_tokens":4000,"temperature":0.85}
    req=urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json","HTTP-Referer":"https://reflect.meno.sh","X-Title":"gaokao-eval-grid"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req,timeout=120) as r: out=json.loads(r.read())
            return json.loads(re.sub(r"^```(json)?|```$","",out["choices"][0]["message"]["content"].strip(),flags=re.M).strip())["profiles"]
        except Exception as e: import time;print("retry",e);time.sleep(3)
    return []

from concurrent.futures import ThreadPoolExecutor
B=12; batches=[pick[i:i+B] for i in range(0,len(pick),B)]
profs=[]
with ThreadPoolExecutor(max_workers=4) as ex:
    for res in ex.map(flesh, batches): profs.extend(res or [])
profs=[p for p in profs if p.get("free_text") and len(p.get("options") or [])>=2]
json.dump({"profiles":profs,"n_cells":len(cells)}, open(os.environ.get("OUT", os.path.join(os.path.dirname(__file__),"profiles.json")),"w"), ensure_ascii=False, indent=2)
print(f"{len(profs)} profiles from {len(cells)}-cell grid (sampled {N})")
for p in profs[:6]: print(f"  [{(p.get('tag') or '')[:38]}] {p['free_text'][:46]}")
