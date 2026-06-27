"""World-Turning Engine (WTE) — ZH 2026-06-17.

Picks the next stage from a pool by myopic value-of-information: which stage most
reduces uncertainty about THIS person's ideal-preference ranking, and/or confronts
a dimension they're avoiding (anti-confirmation-bias). Scaffolded: an LLM 'modeler'
infers an ideal-preference ledger + the best next stage; Python validates and
decides. Best-effort: any failure falls back to the first un-surfaced pool stage,
so the game never breaks. The selection prompt is editable (registry key
'wte_select').
"""
from __future__ import annotations
from core import prompts


def select_factor(profile_text, pool, seen, order, rerank_log, llm_json):
    """pool / seen: lists of factor dicts {key,label,ask}. order: list of labels.
    Returns (chosen_factor, ledger_or_None, why_str)."""
    if not pool:
        return None, None, "empty pool"
    if len(pool) == 1:
        return pool[0], None, "only one stage left"
    seen_s = "、".join(f["label"] for f in seen) or "(无)"
    def _line(f):
        extra = []
        if f.get("pattern"): extra.append(f"模式:{f['pattern']}")
        if f.get("when_relevant"): extra.append(f"高价值情形:{f['when_relevant']}")
        tail = ("  (" + " | ".join(extra) + ")") if extra else ""
        return f"- {f['key']}: {f['label']} —— {f['ask']}{tail}"
    pool_s = "\n".join(_line(f) for f in pool)
    reranks = "; ".join(f"{r['from'][0]}→{r['to'][0]}"
                        for r in (rerank_log or []) if r.get("top_changed")) or "(无改动)"
    try:
        prompt = prompts.render("wte_select", profile=profile_text, order=" > ".join(order),
                                reranks=reranks, seen=seen_s, pool=pool_s)
        r = llm_json(prompt, max_tokens=450, temperature=0.4)
    except Exception:
        return pool[0], None, "llm failed → first un-surfaced"
    nk = (r or {}).get("next_stage")
    pick = next((f for f in pool if f["key"] == nk), None) or pool[0]
    return pick, (r or {}).get("ledger"), (r or {}).get("why", "")
