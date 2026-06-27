# Migration: reflection-game/gaokao -> meno-gaokao-counsellor

Step (1) (extraction) of the separation plan (hub.meno.sh/projects/reflection-game/gaokao-standalone-plan). **The old `reflection-game` repo is untouched.**

## Folder mapping
| old (`reflection-game/`) | new |
|---|---|
| `gaokao/{ranked,wte,profile,grounding,resolve,yulai,prompts,sources,quiz,school_tier,voice_profile,trajectory,interactive,demo,compare}.py` | `core/` |
| `gaokao/web.py`, `*.html` | `serving/` |
| `gaokao/real_data/*`, `scenes.json`, `human_dimensions.json`, `data_seed.json` | `data/` |
| `gaokao/prompts.json` (+defaults) | `prompts/` |
| `gaokao/{build_*,enrich_grounding,enumerate_majors,export_test_logs}.py`, `gaokao/eval/` | `developer/` |
| `gaokao/miniprogram/` | `miniprogram/` |
| `core/emergent.py` (generic) | `core/emergent.py` (local) |
| `human_modeling/personality.py` (pulled in `plot.arc`) | `human_modeling/personality.py` (minimal: `DIMENSIONS`/`KNOWN_DIMS`) |
| `core/state_manager.py` (~300 LOC) | **dropped** -> `core/state.py` (minimal `StateDelta` + `NullStateManager` no-op) |

## Import changes
- `from gaokao.X` -> `from core.X`
- `from core.state_manager import StateDelta` -> `from core.state import StateDelta`; `StateManager()` -> `NullStateManager()` no-op
- data/prompts paths centralised via `core/paths.py` (was `__file__`-relative)

## Dropped (TRPG legacy, unused by the ranked engine)
- `plot/` (arcs/branches/scenes), the real `StateManager` (world/character coherence), `personality.py` arc-scoring helpers.

## Verification (this extraction)
- All 18 `core/` modules import; `serving.web` imports.
- Live smoke: server serves the 4-page intake; `POST /rank_start` generates a real scene (sid + narrative + stage + grounded prose); `/intake_chat` route wired.
- **NOT yet done** (gated on review, plan steps 2-5): new serving on live data+sink, golden-replay + shadow-run vs old, cutover. Live site still runs the OLD codebase.
