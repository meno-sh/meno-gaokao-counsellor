"""Emergent generation (Track B / Phase 3) — the live-generation seam.

WHAT THIS IS
------------
Track A (authored) plays hand-written `arcs/*.json` state machines. Track
B (emergent) has no authored arc at all: every turn the *model* invents
the next situation, its options, and the world change, growing the world
from a thin "world-bible seed" + the StateManager's accumulated memory.

This module is ONLY the generation layer. The turn loop that consumes it
lives in `core/world_turning_engine.py`, gated on `world_mode=="emergent"`
(authored mode never imports or runs any of this).

THE CONTRACT (one model call per turn returns ONE JSON object)
--------------------------------------------------------------
    {
      "prose":   "<the situation text shown to the player>",
      "options": [
        {"label": "<short choice text>",
         "dimension_vector": {"<DIM>": <float in [-1,1]>, ...}},
        ... (2 or 3 options)
      ],
      "state_delta": { ...StateDelta kwargs: place/time/add_facts/... }
    }

Two hard gates the engine enforces on every emergent turn:
  1. INSTRUMENT-VALIDITY gate — every option MUST carry a non-empty
     `dimension_vector`, and every key in it MUST be one of the canonical
     pole names (`_VALID_DIMENSION_TAGS`, derived from
     human_modeling.personality.DIMENSIONS). An untagged option destroys
     cross-player comparability → the turn is rejected and regenerated.
  2. CONSISTENCY gate — `state_delta` is fed to `StateManager.apply()`;
     if `.applied == False` (a structural contradiction with established
     fiction), the turn is rejected and regenerated.

DETERMINISM / SAFETY
--------------------
`MockEmergentGenerator` is a pure, offline, keyless generator: given the
same turn index + seed it returns the same canned-but-valid JSON. This is
what makes emergent mode testable under MockKP and safe on a keyless /
`--mock` deploy. `parse_emergent_json` + `validate_emergent_payload` are
pure functions with no I/O. The real-LLM generator is a thin wrapper.

Stdlib-only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from core.state import StateDelta
from human_modeling.personality import DIMENSIONS

# The canonical instrument spine: every emergent option's dimension_vector
# may only use these keys. DIMENSIONS is a list of (poleA, poleB) pairs;
# a vector keyed by EITHER pole is valid (matches the authored arcs, which
# tag branches with whichever pole the choice leans toward).
_VALID_DIMENSION_TAGS: frozenset = frozenset(
    p for pair in DIMENSIONS for p in pair
)


# ---------- typed payload ----------

@dataclass
class EmergentOption:
    """One generated choice. `dimension_vector` is the instrument tag —
    model-generated, then validated against `_VALID_DIMENSION_TAGS`."""
    label: str
    dimension_vector: dict = field(default_factory=dict)


@dataclass
class EmergentTurn:
    """A validated emergent turn: situation prose + 2-3 tagged options +
    the world change to apply via StateManager."""
    prose: str
    options: list[EmergentOption]
    state_delta: StateDelta


class EmergentValidationError(ValueError):
    """Raised when a model payload fails an instrument/consistency gate.
    The engine catches this and regenerates (bounded retries)."""


# ---------- pure validation (no I/O) ----------

def parse_emergent_json(raw: str) -> dict:
    """Parse the model's single-JSON-object response. Tolerates a ```json
    fence the way plot/skill_brief.py does. Raises EmergentValidationError
    on anything that is not a JSON object."""
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip()
    if not text:
        raise EmergentValidationError("empty model response")
    import re as _re
    m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL)
    cand = m.group(1) if m else text
    try:
        obj = json.loads(cand)
    except json.JSONDecodeError:
        m2 = _re.search(r"\{.*\}", text, _re.DOTALL)
        if not m2:
            raise EmergentValidationError("response is not JSON")
        try:
            obj = json.loads(m2.group(0))
        except json.JSONDecodeError as e:
            raise EmergentValidationError(f"malformed JSON: {e}")
    if not isinstance(obj, dict):
        raise EmergentValidationError("top-level JSON is not an object")
    return obj


def validate_emergent_payload(payload: dict) -> EmergentTurn:
    """Pure structural + instrument-validity validation of a parsed model
    payload → an EmergentTurn. Raises EmergentValidationError on any
    violation. This is the INSTRUMENT-VALIDITY gate; the CONSISTENCY gate
    (StateDelta.apply) is enforced separately by the engine because it
    needs the live StateManager.
    """
    prose = payload.get("prose")
    if not isinstance(prose, str) or not prose.strip():
        raise EmergentValidationError("missing/empty 'prose'")

    raw_opts = payload.get("options")
    if not isinstance(raw_opts, list) or not (2 <= len(raw_opts) <= 3):
        raise EmergentValidationError(
            f"'options' must be a list of 2-3 items, got {raw_opts!r}")

    options: list[EmergentOption] = []
    for i, o in enumerate(raw_opts):
        if not isinstance(o, dict):
            raise EmergentValidationError(f"option {i} is not an object")
        label = o.get("label")
        if not isinstance(label, str) or not label.strip():
            raise EmergentValidationError(f"option {i} missing 'label'")
        dv = o.get("dimension_vector")
        # INSTRUMENT-VALIDITY GATE: every option must carry a non-empty
        # dimension tag, and every tag must be a canonical pole name.
        if not isinstance(dv, dict) or not dv:
            raise EmergentValidationError(
                f"option {i} ({label!r}) has no dimension_vector — "
                "instrument-validity gate: every option MUST be tagged")
        clean: dict = {}
        for k, v in dv.items():
            if k not in _VALID_DIMENSION_TAGS:
                raise EmergentValidationError(
                    f"option {i} dimension '{k}' is not a canonical tag "
                    f"(valid: {sorted(_VALID_DIMENSION_TAGS)})")
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise EmergentValidationError(
                    f"option {i} dimension '{k}' value not numeric: {v!r}")
            if not (-1.0 <= fv <= 1.0):
                raise EmergentValidationError(
                    f"option {i} dimension '{k}'={fv} outside [-1, 1]")
            clean[k] = fv
        options.append(EmergentOption(label=label.strip(),
                                      dimension_vector=clean))

    sd = payload.get("state_delta") or {}
    if not isinstance(sd, dict):
        raise EmergentValidationError("'state_delta' must be an object")
    # Only forward keys StateDelta actually accepts — an unknown key would
    # otherwise be a TypeError at StateDelta(**sd). Silently dropping is
    # safe: the model can't smuggle behaviour through an unknown field.
    allowed = {
        "place", "time", "set_entities", "add_facts", "add_threads",
        "close_threads", "set_characters",
    }
    delta = StateDelta(**{k: v for k, v in sd.items() if k in allowed})

    return EmergentTurn(prose=prose.strip(), options=options,
                        state_delta=delta)


# ---------- prompt construction ----------

def _rubric() -> str:
    """The fixed 8-dimension rubric — part of the stable cache prefix."""
    lines = ["8-DIMENSION RUBRIC (every option must be tagged on >=1):"]
    for a, b in DIMENSIONS:
        lines.append(f"  - {a} <-> {b}")
    return "\n".join(lines)


def _seed_text(seed: object) -> str:
    """Render the world-bible seed (a plain dict or string) for the prompt."""
    if seed is None:
        return "(no seed — invent a small, coherent everyday situation)"
    if isinstance(seed, str):
        return seed
    if isinstance(seed, dict):
        return "\n".join(f"  {k}: {v}" for k, v in seed.items())
    return str(seed)


def build_emergent_prompt(seed: object, skills_brief: str,
                          state_memory: str, turn_index: int,
                          turn_cap: int) -> str:
    """Assemble the emergent turn prompt.

    Layout (per DESIGN_latency_open_world.md "Phase 3" loop):
      [STABLE PREFIX: task-skills brief + 8-dim rubric + world-bible seed]
      + state_mgr.serialize_for_prompt()
      + the ask.
    The stable prefix is byte-identical across turns of a session, so it
    sits in a provider prefix cache (the latency lever). Only the memory
    block and the turn line vary.
    """
    stable_prefix = (
        (skills_brief or "")
        + "\n" + _rubric()
        + "\n\nWORLD-BIBLE SEED:\n" + _seed_text(seed)
        + "\n"
    )
    ask = (
        f"\n--- TURN {turn_index} of at most {turn_cap} ---\n"
        "Generate the next situation. Return EXACTLY ONE JSON object:\n"
        '{"prose": "<situation>", '
        '"options": [{"label": "<choice>", '
        '"dimension_vector": {"<DIM>": <-1..1>}}, ...2-3 options...], '
        '"state_delta": {"add_facts": [...], "place": "...", ...}}\n'
        "Rules: write `prose` and every option `label` in Simplified "
        "Chinese (简体中文) — this is a Chinese-audience game; only the "
        "`dimension_vector` keys stay the English rubric pole names. "
        "Every option MUST carry a non-empty dimension_vector using "
        "ONLY the rubric pole names; state_delta must NOT contradict any "
        "established fact above; no option is a 'right answer'."
    )
    return (
        stable_prefix
        + "\nWORLD-STATE MEMORY (so far):\n"
        + (state_memory or "(empty — this is the first turn)")
        + ask
    )


# ---------- generators ----------

class MockEmergentGenerator:
    """Deterministic, offline, keyless emergent generator.

    Given the same `turn_index` it returns the same canned-but-VALID JSON
    payload (prose + 2-3 dimension-tagged options + a state_delta). This
    makes emergent mode fully testable offline and safe under MockKP / a
    keyless deploy — no network, no API key, reproducible.

    The canned content is deliberately small and generic; emergent prose
    QUALITY is an iterative follow-up (real-LLM wiring). Correctness +
    safety of the SEAM is what this proves.

    `force_contradiction_on` (a turn index, optional) makes that one turn
    emit a state_delta that contradicts established fiction — used by the
    test to exercise the reject+regenerate path; the *retry* of that turn
    is always clean.
    """

    backend_name = "mock-emergent"

    def __init__(self, force_contradiction_on: Optional[int] = None):
        self._force_contradiction_on = force_contradiction_on
        # remember which turns we've already "failed once" so a regenerate
        # call for the same turn returns a clean payload.
        self._contradicted: set = set()

    def generate(self, *, seed: object, skills_brief: str,
                 state_memory: str, turn_index: int,
                 turn_cap: int) -> str:
        """Return a JSON string for `turn_index`. Signature matches the
        real-LLM generator so the engine treats them interchangeably."""
        # Determine the rotating dimension focus so successive turns probe
        # different poles (mirrors the dimension-probe spirit).
        a, b = DIMENSIONS[(turn_index - 1) % len(DIMENSIONS)]
        c, d = DIMENSIONS[turn_index % len(DIMENSIONS)]

        if (self._force_contradiction_on is not None
                and turn_index == self._force_contradiction_on
                and turn_index not in self._contradicted):
            # First attempt at this turn: emit a deliberate contradiction.
            # The engine's apply() will reject it; we mark it so the
            # regenerate call returns the clean payload below.
            self._contradicted.add(turn_index)
            payload = {
                "prose": ("门关上的声音和上一幕里那扇门不一样了。"
                          "（这是一个故意制造的世界矛盾，引擎应当拒绝并重生成。）"),
                "options": [
                    {"label": "坚持原来的判断",
                     "dimension_vector": {a: 0.6}},
                    {"label": "改变主意",
                     "dimension_vector": {b: 0.5}},
                ],
                # contradiction: reassign an entity attr the first turn set.
                "state_delta": {
                    "set_entities": {"门": {"state": "敞开"}},
                },
            }
            return json.dumps(payload, ensure_ascii=False)

        # Normal (and post-regeneration) clean payload for this turn.
        if turn_index == 1:
            prose = ("你站在一间不大的屋子里。窗外天色将晚，桌上有一封"
                     "没有署名的信。你还没决定要不要拆它。")
            delta = {
                "place": "一间不大的屋子",
                "time": "黄昏",
                "set_entities": {"门": {"state": "关着"},
                                 "信": {"state": "未拆"}},
                "add_facts": ["桌上有一封没有署名的信"],
                "add_threads": ["这封信是谁寄的"],
            }
        else:
            prose = (f"第 {turn_index} 个转折。上一次的选择把你带到了这里，"
                     f"现在有一件事要你决定——它关于 {a} 与 {b} 之间的取舍。")
            delta = {
                "add_facts": [f"第 {turn_index} 幕：一个新的转折出现了"],
            }

        payload = {
            "prose": prose,
            "options": [
                {"label": f"倾向 {a} 的做法",
                 "dimension_vector": {a: 0.7, c: 0.3}},
                {"label": f"倾向 {b} 的做法",
                 "dimension_vector": {b: 0.7, d: 0.3}},
                {"label": "先按兵不动，再看看",
                 "dimension_vector": {d: 0.4}},
            ],
            "state_delta": delta,
        }
        return json.dumps(payload, ensure_ascii=False)


class LLMEmergentGenerator:
    """Real-LLM emergent generator (minimal wiring).

    Sends `build_emergent_prompt(...)` to a configured DeepSeek/OpenRouter
    chat completion and returns the raw response string. Per the task
    brief this wiring is intentionally minimal — correctness + safety of
    the SEAM (validation, gates, prefetch, turn loop) is the deliverable;
    emergent PROSE QUALITY is an explicit iterative follow-up.

    If no OPENROUTER_API_KEY is present, instantiation raises — the engine
    falls back to MockEmergentGenerator, so a keyless deploy is always
    safe and never silently hits the network.
    """

    backend_name = "llm-emergent"

    def __init__(self, model: Optional[str] = None):
        import os
        self._key = os.environ.get("OPENROUTER_API_KEY")
        if not self._key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set — emergent LLM generation "
                "unavailable; use MockEmergentGenerator (keyless, safe).")
        self._model = model or os.environ.get(
            "OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")

    def generate(self, *, seed: object, skills_brief: str,
                 state_memory: str, turn_index: int,
                 turn_cap: int) -> str:
        import urllib.request
        prompt = build_emergent_prompt(
            seed, skills_brief, state_memory, turn_index, turn_cap)
        body = json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            # V4-Pro has reasoning ON; reasoning tokens are billed against
            # max_tokens, so a low cap (was 2000) truncates the JSON mid-prose
            # on turns where the model reasons hard (observed: a 117s turn-1
            # call returned only 218 chars -> invalid JSON -> a wasted regen).
            # 8000 leaves room for reasoning + the full turn JSON.
            "max_tokens": 8000,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://reflect.meno.sh",
                "X-Title": "reflection-game",
            },
        )
        # 90s (down from 180s) — paired with _MAX_REGEN=2 in
        # world_turning_engine._run_emergent: worst-case sync time for one
        # emergent turn is 90×2 = 180s, not the old 180×3 = 540s. A real
        # V4-Pro reasoning call typically returns in <30s; the 90s ceiling
        # leaves 3× headroom while protecting the spinner from a stuck
        # provider connection (the original latency report — multi-minute
        # spinner hang — was partly this ceiling × MAX_REGEN).
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"].get("content") or ""
