"""Minimal state types for the standalone engine.

The generic reflection-game's StateManager (TRPG world/character coherence, ~300
LOC) was DROPPED — the ranked engine generates self-contained per-scene value
dilemmas, not a continuous fiction, so cross-turn world coherence is moot. What
remains: (1) StateDelta as a *pure data container* (the generation model still
emits a state_delta block; we parse it but no longer apply it), and (2) a
NullStateManager no-op so the legacy trajectory/interactive batch paths still run."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StateDelta:
    place: Optional[str] = None
    time: Optional[str] = None
    set_entities: dict = field(default_factory=dict)
    add_facts: list = field(default_factory=list)
    add_threads: list = field(default_factory=list)
    close_threads: list = field(default_factory=list)
    set_characters: dict = field(default_factory=dict)


@dataclass
class _ApplyResult:
    applied: bool = True
    reason: str = ""


class NullStateManager:
    """No-op stand-in for the dropped StateManager."""
    def begin_turn(self): pass
    def serialize_for_prompt(self) -> str: return ""
    def apply(self, delta) -> _ApplyResult: return _ApplyResult(applied=True)
    def record_choice(self, **kw): pass
