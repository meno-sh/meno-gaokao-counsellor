"""Headless batch runner: each profile → synth narrative → N unified stages,
logging per-stage {scene, target_dim, question} + ranking. Concurrent. ZH 2026-06-18.
Writes eval/results.json. Usage: STAGES=4 WORKERS=6 python3 eval/run_batch.py"""
import json, os, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from concurrent.futures import ThreadPoolExecutor
from core.profile import PersonalityFile
from core.ranked import RankedSession, build_narrative

HERE=os.path.dirname(os.path.abspath(__file__))
STAGES=int(os.environ.get("STAGES","4")); WORKERS=int(os.environ.get("WORKERS","6"))
PLAYER=os.environ.get("PLAYER","")=="1"
if PLAYER:
    from core.eval.player import simulate_reorder
IN=os.environ.get("IN", os.path.join(HERE,"profiles.json"))
profs=json.load(open(IN))["profiles"]

def run_one(i, p):
    try:
        prof=PersonalityFile(user_id=f"eval{i}", free_text=p.get("free_text",""))
        prof.destination_pref=[str(x) for x in (p.get("destination_pref") or [])][:6]
        build_narrative(prof, {})
        opts=[{"label":str(l)} for l in (p.get("options") or []) if l]
        sess=RankedSession(options=opts, profile=prof)
        stages=[]
        past_orders=[tuple(sess.current_order())]
        for _ in range(STAGES):
            if sess.done(): break
            st=sess.next_stage()
            if not st or st.get("error"): break
            stages.append({"scene":st.get("factor",{}).get("label"), "scene_key":st.get("factor",{}).get("key"),
                           "question":st.get("question"), "order":st.get("order")})
            if PLAYER:
                no,changed,why=simulate_reorder(getattr(prof,"narrative",""), st, sess.current_order(), sess.rerank_log)
                if changed and tuple(no) in past_orders:   # anti-revert: kill A->B->A
                    changed=False; why=("[anti-revert] "+why)[:140]
                if changed:
                    sess.reorder(no); past_orders.append(tuple(no))
                stages[-1]["reorder"]={"changed":changed,"why":why,"order_after":sess.current_order()}
        tds=[wl.get("target_dim") for wl in getattr(sess,"_wte_ledger",[])]
        return {"i":i,"tag":p.get("tag"),"free_text":p.get("free_text"),"narrative":getattr(prof,"narrative","")[:300],
                "target_dims":tds,"stages":stages,
                "initial_order":sess.initial_order,"final_order":sess.current_order(),
                "n_reranks":len(sess.rerank_log),"top_changed":(sess.initial_order[:1]!=sess.current_order()[:1]),"reranks":sess.rerank_log,"ok":True}
    except Exception as e:
        return {"i":i,"tag":p.get("tag"),"ok":False,"error":f"{type(e).__name__}: {e}","tb":traceback.format_exc()[-300:]}

t0=time.time()
results=[None]*len(profs)
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs={ex.submit(run_one,i,p):i for i,p in enumerate(profs)}
    for f in futs:
        r=f.result(); results[r["i"]]=r
        print(f"  [{r['i']}] {'OK' if r['ok'] else 'ERR'} dims={r.get('target_dims')}", flush=True)
json.dump({"results":results,"stages":STAGES,"n":len(profs),"secs":round(time.time()-t0)}, open(os.environ.get("OUT", os.path.join(HERE,"results.json")),"w"), ensure_ascii=False, indent=2)
print(f"\nDONE {len(profs)} profiles × {STAGES} stages in {time.time()-t0:.0f}s → eval/results.json")
