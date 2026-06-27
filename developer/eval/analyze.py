"""Meta-analysis of eval/results.json. ZH 2026-06-18."""
import json, os, collections
HERE=os.path.dirname(os.path.abspath(__file__))
d=json.load(open(os.environ.get("RESULTS", os.path.join(HERE,"results.json")))); R=[r for r in d["results"] if r and r.get("ok")]
fail=[r for r in d["results"] if r and not r.get("ok")]
print(f"=== Eval meta-analysis: {len(R)} ok / {len(d['results'])} profiles, {d['stages']} stages, {d['secs']}s ===\n")
# 1. rotation health: distinct target_dims per session
rot=[len(set(r["target_dims"]))/max(1,len(r["target_dims"])) for r in R if r["target_dims"]]
distinct=[len(set(r["target_dims"])) for r in R if r["target_dims"]]
print(f"ROTATION: distinct target_dims/session = {sum(distinct)/len(distinct):.2f} of {d['stages']} (1.0=all distinct). frac-distinct mean={sum(rot)/len(rot):.2f}")
# 2. family-default rate
allt=[t for r in R for t in r["target_dims"]]
fam=sum(1 for t in allt if t=="family_expectation_vs_self")
print(f"FAMILY-DEFAULT rate: {fam}/{len(allt)} stages = {100*fam/max(1,len(allt)):.0f}% (was ~85% before fix)")
# 3. human-dim coverage across population
dc=collections.Counter(allt)
print(f"HUMAN-DIM COVERAGE: {len(dc)} distinct dims used across population. top: {dc.most_common(6)}")
# 4. scene coverage
sc=collections.Counter(s["scene"] for r in R for s in r["stages"])
print(f"SCENE COVERAGE: {len(sc)} distinct scenes used. top: {sc.most_common(6)}")
# 5. personalization: do different profiles get different dim-sets?
sets=[frozenset(r["target_dims"]) for r in R if r["target_dims"]]
print(f"PERSONALIZATION: {len(set(sets))} distinct dim-SETS across {len(sets)} profiles ({100*len(set(sets))/max(1,len(sets)):.0f}% unique)")
# 6. ranking change
chg=sum(1 for r in R if r.get("initial_order")!=r.get("final_order"))
print(f"RANKING shifted in {chg}/{len(R)} sessions")
if fail: print(f"\nFAILURES: {len(fail)} — e.g. {fail[0].get('error')}")
