"""Life-trajectory generation for the 高考志愿填报 variant.

Reuses the emergent world-engine (core/emergent.py) as the substrate: each
"turn" is a pivotal LIFE STAGE (大一 -> 毕业 -> 求职 -> 回望), the model invents
the scene + 2-3 value-tagged options, the StateManager keeps the life coherent
turn-to-turn, and the curated outcome seed grounds it so it dramatizes a
plausible life rather than fabricating prophecy. A trajectory is run per option;
the comparison + backward-reasoning ending lives in compare.py (next).
"""
from __future__ import annotations
import json, os
from core import paths
from core.state import NullStateManager
from core.emergent import (parse_emergent_json, validate_emergent_payload,
                           build_emergent_prompt, EmergentValidationError)

_DATA = None
def _data():
    global _DATA
    if _DATA is None:
        with open(paths.data("data_seed.json")) as f:
            _DATA = json.load(f)
    return _DATA

def build_gaokao_seed(option: dict, profile_block: str, archetype_key: str, side: str = "A") -> dict:
    """Seed for ONE option-world (side 'A' or 'B') of an archetype. Injects that
    side's AUTHORED worst-case + daily-reality as MUST-HIT nodes (the path must
    confront both 红利 and 代价 — ZH spec #3/#6), grounded in real school tier."""
    arch = _data()["archetypes"].get(archetype_key, {})
    stages = _data()["life_stages"]
    node = arch.get(side, {}) if isinstance(arch.get(side), dict) else {}
    the_choice = arch.get("option_" + side) or option.get("label", "")
    from core.school_tier import lookup, tier_phrase
    from core.grounding import grounding_block, CONCRETENESS_CONTRACT
    school_facts = tier_phrase(lookup(option.get("school", "") or the_choice))
    # prefer the student's OWN typed major/label for grounding (their real choice),
    # falling back to the archetype option only if they gave nothing.
    matched = grounding_block(option.get("major", "") or option.get("label", "") or the_choice)
    return {
        "premise": ("这是一段被压缩的多年人生模拟,不是预测。每一回合 = 这个选择之后人生的一个"
                    "关键转折点,按时间顺序推进(" + " → ".join(stages) + ")。让玩家在每个阶段做"
                    "一个真实的、价值取向的选择;不要替玩家判断对错,也不要让任何一个选项显得更'正确'。"),
        # player first: scenes must be relevant to THIS person (relevance, not affirmation)
        "player_profile": profile_block,
        "PROFILE_RULE": ("用上面这个人的身份/价值取向决定他会遇到哪些岔路与细节,让场景对他真实相关;"
                         "但绝不因此暗示哪个选项更'对'(相关性,不是迎合)。"),
        "the_choice_made": the_choice,
        "school": option.get("school", ""),
        "major": option.get("major", ""),
        # real per-major grounding — the spine of the anti-genericness fix
        "major_grounding": matched,
        "concreteness_contract": CONCRETENESS_CONTRACT,
        "MUST_HIT_worst_case": node.get("worst_case", ""),
        "MUST_HIT_daily_reality": node.get("daily_reality", ""),
        "this_path_upside": node.get("upside", ""),
        "this_path_cost": node.get("cost", ""),
        "realism_rule": ("必须在推演过程中让玩家真切地撞见上面的'最坏情况'和'日常真实',"
                         "两者都要出现(红利和代价对称呈现);具体写实生活化,可戏剧化但不可捏造,"
                         "不给数字化预测,不替玩家下结论。"),
        "school_facts": school_facts,
    }

def run_trajectory(option, archetype_key, profile, generator, *, side="A", cap=6,
                   choose=None, on_turn=None):
    """Generate one life-trajectory. `choose(turn)->index` picks an option each
    stage (default: index 0); `on_turn(turn_index, turn)` is a callback.
    Returns dict(turns=[...], dim_trace=[...]). The generator is any object with
    .generate(seed, skills_brief, state_memory, turn_index, turn_cap)->json str
    (LLMEmergentGenerator in prod; a mock in tests)."""
    turns, dim_trace = [], []
    sm = NullStateManager()
    for ti in range(1, cap + 1):
        sm.begin_turn()
        seed = build_gaokao_seed(option, profile.serialize_for_prompt(), archetype_key, side)
        turn = None; err = ""
        for attempt in range(4):  # bounded regen on validity/consistency/API failure
            try:
                raw = generator.generate(seed=seed, skills_brief="",
                                         state_memory=sm.serialize_for_prompt(),
                                         turn_index=ti, turn_cap=cap)
                turn = validate_emergent_payload(parse_emergent_json(raw))
            except EmergentValidationError as e:
                err = str(e); turn = None; continue
            except Exception as e:  # API error (429/timeout/etc) — back off + retry
                err = f"api:{type(e).__name__}"; turn = None
                import time as _t; _t.sleep(3 * (attempt + 1)); continue
            if not sm.apply(turn.state_delta).applied:
                err = "consistency"; turn = None; continue
            break
        if turn is None:
            turns.append({"stage": ti, "error": err}); break
        idx = (choose(turn) if choose else 0)
        idx = max(0, min(idx, len(turn.options) - 1))
        picked = turn.options[idx]
        profile.update_from_choice(picked.dimension_vector)
        sm.record_choice(decision_id=f"stage{ti}", branch_id=f"b{idx}", label=picked.label)
        rec = {"stage": ti, "prose": turn.prose,
               "options": [{"label": o.label, "dims": o.dimension_vector} for o in turn.options],
               "picked": idx, "picked_dims": picked.dimension_vector}
        turns.append(rec); dim_trace.append(picked.dimension_vector)
        if on_turn:
            on_turn(ti, rec)
    return {"turns": turns, "dim_trace": dim_trace}
