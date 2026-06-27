"""Enumerate the full 本科专业目录 by 学科门类 via the LLM → real_data/major_catalogue.json.

The official 普通高等学校本科专业目录 has ~800 specialties across 12 门类. We ask the
model for each 门类's full 专业 list, dedupe, and write a flat list the grounding
builder consumes. Best-effort enumeration (catalogue is public/well-represented);
re-runnable and easy to top up.
"""
from __future__ import annotations
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "real_data", "major_catalogue.json")
MODEL = os.environ.get("GROUNDING_MODEL", "deepseek/deepseek-chat")

MENLEI = ["哲学","经济学","法学","教育学","文学","历史学","理学","工学","农学","医学","管理学","艺术学"]

PROMPT = """列出中国《普通高等学校本科专业目录》中"{ml}"学科门类下的**全部本科专业名称**(尽量完整,覆盖该门类下所有专业类)。
只输出一个 JSON 对象,不要任何额外文字或代码块标记:
{{"门类":"{ml}","majors":["专业名1","专业名2", ...]}}
要求:用规范专业全称(如"计算机科学与技术""临床医学");尽量穷尽,宁多勿漏;不含专业代码。"""

def call(ml: str, key: str) -> list:
    body = json.dumps({"model": MODEL,
        "messages":[{"role":"user","content":PROMPT.format(ml=ml)}],
        "response_format":{"type":"json_object"}, "max_tokens":3000, "temperature":0.2}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, method="POST",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json",
                 "HTTP-Referer":"https://reflect.meno.sh","X-Title":"reflection-game-catalogue"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload=json.loads(resp.read().decode())
            txt=payload["choices"][0]["message"].get("content") or ""
            txt=re.sub(r"^```(json)?|```$","",txt.strip(),flags=re.M).strip()
            d=json.loads(txt)
            return [m.strip() for m in d.get("majors",[]) if m and m.strip()]
        except Exception as e:
            last=f"{type(e).__name__}:{e}"; time.sleep(3*(attempt+1))
    print(f"  ! {ml} failed: {last}", file=sys.stderr); return []

def main():
    key=os.environ.get("OPENROUTER_API_KEY")
    if not key: print("OPENROUTER_API_KEY missing",file=sys.stderr); sys.exit(1)
    by_ml={}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs={ex.submit(call,ml,key):ml for ml in MENLEI}
        for f in as_completed(futs):
            ml=futs[f]; lst=f.result(); by_ml[ml]=lst
            print(f"  {ml}: {len(lst)} majors", flush=True)
    # flat deduped, preserve order by 门类
    seen=set(); flat=[]
    for ml in MENLEI:
        for m in by_ml.get(ml,[]):
            if m not in seen: seen.add(m); flat.append(m)
    json.dump({"by_menlei":by_ml,"all":flat}, open(OUT,"w"), ensure_ascii=False, indent=2)
    print(f"\nwrote {OUT}: {len(flat)} unique majors across {len(MENLEI)} 门类")

if __name__=="__main__":
    main()
