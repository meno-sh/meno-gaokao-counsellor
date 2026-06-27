# meno-gaokao-counsellor

The 高考志愿 · 反思均衡 (reflective-equilibrium college-application counsellor) engine, lifted into a standalone repo from the generic `reflection-game` codebase.

## Structure
- **`core/`** — minimal engine (~2.3k LOC): `ranked`/`wte` (world-turning engine: per-stage value-dimension selection + scene generation via `unified_turn`), `profile` (load-bearing 画像 + incremental update), `grounding`/`resolve`/`yulai` (阳光高考 facts + 专业/学校 resolution), `prompts`/`sources`, `emergent` (scene-JSON parse/validate), `state` (minimal `StateDelta` container — real `StateManager` dropped), `quiz`/`school_tier`/`voice_profile`, plus `trajectory`/`interactive`/`demo`/`compare`.
- **`serving/`** — `web.py` (real-time HTTP inference server + served HTML).
- **`human_modeling/`** — `personality.py` (8 value-axis `DIMENSIONS`); home for human-model variants.
- **`data/`** — running data: `real_data/`, scenes, human_dimensions, data_seed.
- **`prompts/`** — `prompts.json` (+ defaults).
- **`developer/`** — offline tooling: build/enrich grounding, enumerate majors, export logs, `eval/`.
- **`miniprogram/`** — WeChat Mini Program client (consumes the API; shares no Python code).
- **`tests/`** — golden-replay parity tests (TODO).

## Run
```
PYTHONPATH=. OPENROUTER_API_KEY=... python3 -m serving.web --port 9930
```
Env: `OPENROUTER_API_KEY`; optional `GAOKAO_DATA_DIR`, `GAOKAO_REAL_DATA`, `GAOKAO_PROMPTS_DIR`, `GAOKAO_API_KEYS`.

See `MIGRATION.md` for lineage. Dropped: TRPG `plot/arcs`, the ~300-LOC `StateManager` (unused by the ranked self-contained-scene model).
