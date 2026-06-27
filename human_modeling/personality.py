"""Value dimensions for the human model — the 8 value-axis pole pairs.

Extracted from the generic reflection-game's human_modeling.personality; the
TRPG arc-scoring helpers (aggregate_profile / inflection_points, which pulled in
plot.arc) were dropped as unused by the gaokao engine. Only DIMENSIONS / KNOWN_DIMS
are consumed (profile.py, voice_profile.py)."""

DIMENSIONS: list[tuple[str, str]] = [
    ("TRUTH", "PROTECTION"),
    ("PRINCIPLE", "LOYALTY"),
    ("VOICE", "SILENCE"),
    ("AGENCY", "OBSERVATION"),
    ("PROCESS", "OUTCOME"),
    ("NOW", "LATER"),
    ("SELF", "OTHER"),
    ("RIGOR", "MERCY"),
]
KNOWN_DIMS: set[str] = {p[0] for p in DIMENSIONS}
