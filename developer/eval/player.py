"""Simulated player for the eval harness. An LLM acting AS the profile reads each
stage and decides whether to reorder its 志愿 ranking — like a real human reacting
to the investigation. Without it the headless run never reorders (ranking-shift=0).
Enable in run_batch with PLAYER=1. ZH 2026-06-18.

v2 (stickiness): default is KEEP. A reorder is only accepted when the player says
this stage gave *materially new, option-specific* information (materially_new gate),
and it is told about its last move so it won't flip back. run_batch adds a hard
anti-revert guard (no returning to an already-visited order) to kill A->B->A."""
from core.ranked import _llm_json

def simulate_reorder(narrative: str, stage: dict, current_order: list, rerank_log=None):
    """Return (new_order, changed, why). Conservative: keeps order unless the stage
    is judged to carry materially new, ranking-changing info."""
    rerank_log = rerank_log or []
    hist = ""
    if rerank_log:
        last = rerank_log[-1]
        hist = (f"\n【你上一站刚把排序从 {'、'.join(last.get('from',[]))} 调成了 "
                f"{'、'.join(last.get('to',[]))}】除非这一站给出**明确相反**的实质信息,"
                f"否则**别又改回去**——真人不会反复横跳。")
    fac = (stage.get("factor") or {}).get("label", "")
    opts = "、".join(current_order)
    prompt = f"""你就是下面这个人(第一人称代入),正在做高考志愿填报。读完这一站,决定要不要调整你当前的志愿排序。

【你是谁】{narrative}

【当前排序·从最想到最不想】{opts}{hist}

【这一站让你看到的】
场景:{fac}
问题:{stage.get('question','')}
故事:{stage.get('prose','')}
{stage.get('top','')} 的视角:{stage.get('top_take','')}
{stage.get('contender','')} 的视角:{stage.get('contender_take','')}

**默认是「不变」。** 真实的人不会每一站都改主意。只有当这一站给出**针对某个具体选项、能改变你权衡**的实质新信息时才重排;若只是泛泛而谈、或只是「碰巧聚焦了某个选项」,就保持原样。先判断这一站有没有这种信息。
只输出 JSON:{{"materially_new": true/false, "new_order": [按新偏好从高到低的全部选项标签,原样], "changed": true/false, "why": "一句话"}}
若 materially_new 为 false,则 new_order 必须等于当前排序、changed=false。new_order 必须是当前选项的一个排列,不增不减。"""
    r = _llm_json(prompt, max_tokens=400, temperature=0.3) or {}
    no = [str(x) for x in (r.get("new_order") or [])]
    why = str(r.get("why", ""))[:140]
    if r.get("materially_new") and sorted(no) == sorted(current_order) and no != list(current_order):
        return no, True, why
    return list(current_order), False, why
