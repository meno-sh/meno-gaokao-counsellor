"""PersonalityFile — a persisted per-user profile (ZH 2026-06-11 feature).

Built from the intake questionnaire (8-dim prior) + free-text + the dimension
vectors of every choice the user makes, it is injected into the generation
context so scenes are RELEVANT to this student. Guardrail (load-bearing):
it steers WHICH forks they face, never WHICH option looks good — personalize
for relevance, not affirmation, or we build an echo chamber and break the
no-right-answer principle (rules: preference has no right answer).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from human_modeling.personality import DIMENSIONS

_POLES = [p for pair in DIMENSIONS for p in pair]  # 16 pole names

@dataclass
class PersonalityFile:
    user_id: str
    free_text: str = ""                                  # intake: "我是谁/我在纠结什么"
    prior: dict = field(default_factory=dict)            # questionnaire 8-dim prior, pole->[-1,1]
    observed: dict = field(default_factory=dict)         # running mean of chosen dimension_vectors
    _counts: dict = field(default_factory=dict)
    destination_pref: list = field(default_factory=list)  # ranked 毕业去向 (most→least wanted)
    value_weights: dict = field(default_factory=dict)     # self-reported 金钱/兴趣/影响力 % (sum 100)
    narrative: str = ""                                   # LLM-synthesized NL profile (the primary signal)
    elicited: list = field(default_factory=list)          # per-scene active-identification Q&A log

    def update_from_choice(self, dimension_vector: dict) -> None:
        """Fold a chosen option's dimension_vector into the running estimate."""
        for pole, v in (dimension_vector or {}).items():
            if pole not in _POLES:
                continue
            n = self._counts.get(pole, 0)
            self.observed[pole] = (self.observed.get(pole, 0.0) * n + float(v)) / (n + 1)
            self._counts[pole] = n + 1

    def serialize_for_prompt(self) -> str:
        """The profile the generator sees. When a synthesized natural-language
        `narrative` exists it IS the profile (one rich prose portrait driving
        world / storyline / investigation); otherwise we fall back to the raw
        self-description. The numeric poles (prior/observed) are kept internally
        but NOT emitted — they were a weak signal (ZH 2026-06-17)."""
        lines = ["PLAYER PROFILE (use ONLY to make scenes relevant to this person — "
                 "NEVER to make any option look correct):"]
        if self.narrative:
            lines.append("  " + self.narrative.strip().replace("\n", " "))
        elif self.free_text:
            lines.append(f"  self-description: {self.free_text[:300]}")
        if self.destination_pref:
            lines.append("  理想毕业去向(从最想到最不想，影响每一步该看什么): "
                         + " > ".join(str(x) for x in self.destination_pref))
        vw = self.value_weights or {}
        if vw:
            _vn = {"money": "金钱", "interest": "兴趣", "influence": "影响力"}
            lines.append("  价值权重(自报,占比合计100): " + " ".join(f"{_vn.get(k,k)}{v}%" for k, v in vw.items() if v))
        if not (self.narrative or self.free_text or self.destination_pref):
            lines.append("  (no signal yet — keep scenes broadly relevant)")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "PersonalityFile":
        d = json.loads(s)
        return cls(**{k: d.get(k) for k in ("user_id", "free_text", "prior", "observed", "_counts", "destination_pref", "narrative", "value_weights", "elicited") if k in d})
