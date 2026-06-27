"""Interactive A/B path simulation (ZH spec #1: step-by-step, not auto-run).

The student LIVES each option-world one stage at a time, *choosing* at every
"假如…你怎么办?" node — "这是我自己走出来的路." Sequence: live A to its end,
then B, then the backward-reasoning compare + the 反思均衡 cost-acceptance gate
(#2). Stages are generated on demand (one LLM call per click) so the pacing is
deliberate, as the spec wants ("不要一次性给出所有结果").
"""
from __future__ import annotations
from core.state import NullStateManager
from core.emergent import parse_emergent_json, validate_emergent_payload, EmergentValidationError
from core.trajectory import build_gaokao_seed, _data
from core.profile import PersonalityFile

class InteractiveSession:
    def __init__(self, option_A, option_B, archetype_key, profile: PersonalityFile, generator, cap=5):
        self.opts = {"A": option_A, "B": option_B}
        self.arch = archetype_key
        self.gen = generator
        self.cap = max(1, int(cap))
        self.profile = profile  # shared; accumulates across both lives
        self.sm = {"A": NullStateManager(), "B": NullStateManager()}
        self.turn = {"A": 0, "B": 0}
        self.history = {"A": [], "B": []}
        self.dim_trace = {"A": [], "B": []}
        self._pending = {"A": None, "B": None}

    def side_done(self, side): return self.turn[side] >= self.cap
    def both_done(self): return self.side_done("A") and self.side_done("B")

    def _gen(self, side):
        sm = self.sm[side]
        seed = build_gaokao_seed(self.opts[side], self.profile.serialize_for_prompt(), self.arch, side)
        last = ""
        for attempt in range(4):
            try:
                raw = self.gen.generate(seed=seed, skills_brief="",
                                        state_memory=sm.serialize_for_prompt(),
                                        turn_index=self.turn[side] + 1, turn_cap=self.cap)
                turn = validate_emergent_payload(parse_emergent_json(raw))
            except EmergentValidationError as e:
                last = str(e); continue
            except Exception as e:
                import time; last = f"api:{type(e).__name__}"; time.sleep(3 * (attempt + 1)); continue
            if not sm.apply(turn.state_delta).applied:
                last = "consistency"; continue
            return turn
        raise RuntimeError(f"generation failed: {last}")

    def next_stage(self, side):
        """Generate + return the next scene+options for `side`, or None if done."""
        if self.side_done(side):
            return None
        self.turn[side] += 1
        self.sm[side].begin_turn()
        turn = self._gen(side)
        self._pending[side] = turn
        return {"side": side, "stage": self.turn[side], "prose": turn.prose,
                "options": [{"label": o.label, "dims": o.dimension_vector} for o in turn.options],
                "last": self.side_done(side)}

    def record_choice(self, side, idx):
        turn = self._pending.get(side)
        if turn is None:
            raise RuntimeError("no pending stage for side")
        idx = max(0, min(int(idx), len(turn.options) - 1))
        o = turn.options[idx]
        self.profile.update_from_choice(o.dimension_vector)
        self.sm[side].record_choice(decision_id=f"{side}{self.turn[side]}", branch_id=f"b{idx}", label=o.label)
        self.history[side].append({"stage": self.turn[side], "prose": turn.prose,
                                   "options": [{"label": op.label} for op in turn.options], "picked": idx})
        self.dim_trace[side].append(o.dimension_vector)
        self._pending[side] = None

    def path_costs(self):
        """The authored cost/worst-case per side, for the acceptance gate (#2)."""
        arch = _data()["archetypes"].get(self.arch, {})
        out = {}
        for side in ("A", "B"):
            node = arch.get(side, {}) if isinstance(arch.get(side), dict) else {}
            out[side] = {"option": arch.get("option_" + side) or self.opts[side].get("label", ""),
                         "cost": node.get("cost", ""), "worst_case": node.get("worst_case", "")}
        return out

    def ending(self):
        """Both lives done -> backward-reasoning mirror over both dim-traces."""
        from core.compare import backward_reflection
        tA = {"turns": self.history["A"], "dim_trace": self.dim_trace["A"]}
        tB = {"turns": self.history["B"], "dim_trace": self.dim_trace["B"]}
        res = backward_reflection(self.opts["A"], tA, self.opts["B"], tB, self.profile)
        res["path_costs"] = self.path_costs()
        return res
