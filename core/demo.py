"""End-to-end 高考 demo: intake -> live BOTH futures (in parallel) -> mirror.

The two option-worlds are independent, so we run them on separate threads
(within a life, stages stay serial because stage N+1 needs N's state). This
roughly halves wall-clock vs running them back-to-back — the main latency lever
for a playable flow. `run_pipeline` is the single entry the web layer (next)
will call.
"""
from __future__ import annotations
import os, threading
from core.profile import PersonalityFile


def default_trajectory_generator(fast=True):
    """Generator for life-stage gen. Trajectory generation is CREATIVE, not
    reasoning-bound, so the fast non-reasoning model (DeepSeek-V3) is ~2.5-3x
    faster per stage (~19s vs ~50s) at comparable quality — the main latency
    lever. Override with GAOKAO_TRAJECTORY_MODEL; set fast=False for V4-Pro."""
    from core.emergent import LLMEmergentGenerator
    model = os.environ.get("GAOKAO_TRAJECTORY_MODEL") or (
        "deepseek/deepseek-chat" if fast else os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"))
    return LLMEmergentGenerator(model=model)
from core.trajectory import run_trajectory
from core.compare import backward_reflection

def run_pipeline(option_A, arch_A, option_B, arch_B, *, free_text="", prior=None,
                 generator, cap=5, choose=None, on_event=None):
    """Full pipeline. Returns {life_A, life_B, ending}. `choose(turn)->idx`
    decides each stage (default index 0; the web layer passes the user's pick).
    Each life uses its OWN profile copy while playing (so the two futures don't
    cross-contaminate); the ending reasons across both dim-traces.
    on_event(kind, payload) streams progress (kind in {'stage','life_done'})."""
    pA = PersonalityFile(user_id="A", free_text=free_text, prior=dict(prior or {}))
    pB = PersonalityFile(user_id="B", free_text=free_text, prior=dict(prior or {}))
    out = {}
    def _life(key, opt, arch, prof):
        cb = (lambda ti, rec: on_event("stage", {"life": key, "stage": ti, "rec": rec})) if on_event else None
        out[key] = run_trajectory(opt, arch, prof, generator, side=key, cap=cap, choose=choose, on_turn=cb)
        if on_event: on_event("life_done", {"life": key})
    errs = {}
    def _safe(key, opt, arch, prof):
        try: _life(key, opt, arch, prof)
        except Exception as e: errs[key] = f"{type(e).__name__}: {e}"
    tA = threading.Thread(target=_safe, args=("A", option_A, arch_A, pA))
    tB = threading.Thread(target=_safe, args=("B", option_B, arch_B, pB))
    tA.start(); tB.start(); tA.join(); tB.join()
    if "A" not in out or "B" not in out:
        raise RuntimeError(f"a life failed to generate: {errs or 'unknown'}")
    # merge the two profiles' observed leanings for the mirror's profile view
    merged = PersonalityFile(user_id="merged", free_text=free_text, prior=dict(prior or {}))
    for p in (pA, pB):
        for pole, v in p.observed.items():
            merged.update_from_choice({pole: v})
    ending = backward_reflection(option_A, out["A"], option_B, out["B"], merged, use_llm=True)
    return {"life_A": out["A"], "life_B": out["B"], "ending": ending}
