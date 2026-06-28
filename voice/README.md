# 反思志愿 · Reflective College-Choice (voice refactor)

A voice-first reflective-equilibrium instrument for 高考志愿. The student speaks
their candidate `专业@学校` pairs, walks through "rethink stops" where two
parallel-universe future selves pose sharp questions, reranks freely, and ends
on a reflection report (bump chart of how their ranking moved, the reasons
behind each change, a list of things that would change their mind, and their
initial high-level views to compare against).

Built as a **Design Component** (`Name.dc.html`): a single streaming HTML file
that opens directly in a browser and is rendered by the small runtime in
`support.js`.

## Files

| file | what it is |
|---|---|
| `Gaokao Voice.dc.html` | the app — template + logic class (the whole UI + flow state machine + backend calls) |
| `data.js` | bilingual UI copy (`STR`) + the **mock** dataset (`PAIRS`, `INTAKE`, `STOPS`, `ENDING`). `window.GK` |
| `sketch.js` | rough.js hand-drawn primitives: stick figures, microphone, radial visualizer, bump-chart strokes |
| `support.js` | the Design-Component runtime (do not edit) |

External (loaded from CDN at runtime): `roughjs@4.6.6`, Google Fonts
(Patrick Hand, Caveat, Noto Sans SC).

## Run it

Any static server works:

```bash
python3 -m http.server 8080
# open http://localhost:8080/Gaokao%20Voice.dc.html
```

Open the file and it auto-detects whether a backend is reachable.

## Mock vs. live (this is the whole "replace mock with real" story)

The app picks a mode on launch in `onStart()` → `_detectMode()`:

1. If the prop `forceMock` is set, mode = **mock**.
2. Otherwise it does `GET {apiBase}/rank_quiz`. If that returns 200, mode =
   **live**; if it fails, mode = **mock**. A badge (`演示模式` / `已连接`) shows which.

So to go live, **serve this file from the same origin as the existing
`serving/web.py`** (or set the `apiBase` prop / `data-props` to point at it).
No code change needed — the live paths are already wired:

| step | endpoint (already called) |
|---|---|
| voice intake — pairs question | `POST /voice_profile?intake=1` → `{transcript, intake:{candidates,…}}` |
| voice intake — other questions | `POST /voice_profile?fast=1` → `{transcript}` |
| start the run | `POST /rank_start` → `{sid, stage, narrative}` |
| reorder | `POST /rank_reorder` |
| record a stop answer | `POST /rank_elicit` |
| next stop / ending | `POST /rank_next` → `{stage}` or `{phase:"ending", ending}` |

In live mode the per-stop content comes from the real `stage` object
(`prose`, `top`, `top_take`, `contender`, `contender_take`, `factor`,
`elicit`); the two future-self questions are composed from `top_take` /
`contender_take` (`getStopDisp()` → `frame()`). The mock `STOPS`/`PAIRS` in
`data.js` are bypassed entirely when live.

### Tweakable props (`data-props` on the DC, or the Tweaks panel)

- `forceMock` (boolean) — force the mock dataset even if a backend is up.
- `apiBase` (string) — base URL for the backend; empty = same origin.
- `startLang` (`cn` | `en`) — initial language (there's also an in-UI switch).

## What is real vs. still mock

**Real, computed from the actual session** (works in both modes):
- the full flow + state machine, voice capture, reranking, the 8-stops /
  5-unchanged end-of-journey rule;
- ordering history, the multi-color **bump chart**, the per-change cards;
- the post-stop "what would have changed your mind" capture and its list;
- stats: stops walked, number of reorderings, most-felt stop (longest spoken
  answer), longest-dwell stop;
- the initial high-level views captured at intake.

**Still mock / not fully implemented** — each needs an LLM call the front end
can't assume exists in production. Search the code for `MOCK` / these notes:
1. **Per-change reason** is shown as the student's *verbatim* stop transcript,
   not an LLM summary. To upgrade: add a summarize endpoint and call it in
   `renderVals()` where `changesList` is built.
2. **"Things that would change my mind"** are shown verbatim, not condensed.
   Same fix: summarize `changeMindList` server-side.
3. **Which high-level principles shifted** is not auto-detected — the report
   surfaces the student's original words (`initialViews`) with a note. To
   upgrade: diff the intake statements against the engine's running `narrative`
   (the 画像) with an LLM and render the deltas.

The mock transcripts that stand in for speech-to-text live in
`_mockTranscript()` inside `Gaokao Voice.dc.html`; in live mode they are
replaced by real STT results from `/voice_profile`.
