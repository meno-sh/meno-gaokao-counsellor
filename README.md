# meno-gaokao-counsellor

**A reflective-equilibrium instrument for high-stakes choice — not a recommender.**
高考志愿 · 反思均衡:不替你做决定,帮你想清楚自己到底想要什么。

[gaokao.meno.sh](https://gaokao.meno.sh) · part of the [Meno](https://hub.meno.sh) research program.

---

**一个用于重大选择的「反思均衡」工具 —— 不是推荐器。**
你带着纠结的几个选择来,它把每个选择往「模拟人生」里走几步,把你没掂量过的价值取舍摆出来,让**你自己**看清到底想要什么。

## 它特别在哪

市面上的高考志愿工具都是**按分数替你排学校**。这个反着来:它是一个**披着角色扮演外壳的「偏好提取」工具**。

- **价值-信息量(VOI)驱动的世界推演引擎(WTE)。** 每一站,引擎挑出它对**你**最不确定的那**一个价值维度**(主动识别),围绕它生成一个有真实数据支撑的人生场景(你的第 1 名 vs 竞争者)—— 选维度 + 调查员 + 写场景由**一次融合的 LLM 调用**完成。
- **活的人物画像(human model)。** 不是固定问卷,而是开局建一份要点式画像、**每一站根据你的言行增量重写**。
- **有据可依,不瞎编。** 场景与数字由真实公开数据兜底(阳光高考、就业质量报告);没有验证过的数字不允许上屏。
- **反思均衡的立场。** 结尾给「相互竞争的目标」报告 + 一份反思均衡检查清单 —— 呈现你的现状,不替你下结论。
- **语音优先、对话式录入。** 整个开局表单可以用一段口述替代;每一步都有「和 AI 聊一聊」的陪伴。

研究脉络:反思均衡 · 理想偏好提取 · 学习人类价值。详见 [项目主页](https://hub.meno.sh/projects/reflection-game/)。

## 信息流

```
开局(4 页,每页都能和 AI 聊;可语音)
  → 建画像(活的人物模型)
  → 每一站:WTE 选信息量最高的价值维度
            → unified_turn:有据可依的场景(第1名 vs 竞争者)+ 定制追问
            → 把回答并回画像  (随时可重排 / 对话)
  → 结尾:反思均衡检查清单
  → 自动生成、可下载的报告
```

## 快速开始

```bash
cp .env.example .env          # 填入你的 key(见下)
export $(grep -v '^#' .env | xargs)
PYTHONPATH=. python3 -m serving.web --port 9930
```
引擎纯标准库(无第三方 Python 依赖),Python 3.10+。

## 环境变量

**必需:** `OPENROUTER_API_KEY`(场景/画像/报告的 LLM)· `OPENAI_API_KEY`(语音转写,仅用语音录入时需要)。
**可选:** `GAOKAO_DATA_DIR`(会话日志目录)· `GAOKAO_LOG_SINK`(异地持久收集 URL)· `GAOKAO_API_KEYS`(设了就**要求** `Authorization: Bearer <key>`,否则 401;留空 = 开放)· `GAOKAO_ADMIN_TOKEN`(保护 prompt 编辑/日志端点)· `GAOKAO_RL_PER_HOUR`(每 IP 每小时开局上限,默认 100)· `YULAI_API_KEY`/`YULAI_BASE_URL`(调合作方证据 API 补充 grounding)· 以及若干模型覆盖项。

**密钥永不进 git** —— 放 `.env`(已 gitignore)或部署端环境(Render env vars 等)。同一份代码:开源版自带 key 跑,生产版用我们的 key 在部署端跑。

## 数据

`data/` 下的 grounding 数据来自**公开来源**(阳光高考、就业质量报告)。再分发请核对各来源条款并保留出处。

---

# English

## What makes this special

Most 高考志愿 (college-application) tools **rank schools for you** from your score. This does the opposite: it's a **preference-elicitation instrument wearing a role-play skin**. You bring the choices you're torn between; it walks each one a few steps into a *simulated life* and surfaces the value trade-offs you hadn't weighed — so **you** discover what you actually want.

What's technically unusual:

- **A world-turning engine (WTE) driven by value-of-information.** Each turn the engine picks the *one value dimension* it's most uncertain about for *you* (active identification), then generates a grounded life-scene pitting your top choice against its contender on exactly that dimension — one fused LLM call does dimension-selection + investigator + scene-writing.
- **A living human model (画像).** Instead of a fixed questionnaire, a point-form portrait of your values is built at intake and *incrementally rewritten* every scene from what you say and do.
- **Grounded, not hallucinated.** Scenes and numbers are backed by real public data (阳光高考, employment-quality reports); the model may not put a number on screen unless it's verified grounding.
- **Reflective-equilibrium framing.** It ends with a competing-objectives report + a reflective-equilibrium checklist — it presents your current state, it does not prescribe.
- **Voice-first, conversational intake.** A whole intake form can be replaced by one spoken paragraph; every step has an "talk it through with the AI" companion.

Research lineage: reflective equilibrium · ideal-preference elicitation · learning human values. See the [project hub](https://hub.meno.sh/projects/reflection-game/).

---

## How it works (info flow)

```
intake (4 pages, each with an AI chat; voice optional)
  → build 画像 (running human model)
  → per-scene loop:  WTE picks the highest-VOI value dimension
                     → unified_turn: grounded scene (top vs contender) + tailored elicitation
                     → fold the answer back into the 画像  (reorder / chat anytime)
  → ending: reflective-equilibrium checklist
  → auto-generated, downloadable report
```

## Repo structure

| dir | what |
|---|---|
| `core/` | the engine: `ranked`/`wte` (WTE + `unified_turn`), `profile` (画像), `grounding`/`resolve`/`yulai`, `prompts`, `emergent`, `checklist`, `quiz`, `voice_profile` |
| `serving/` | `web.py` — the HTTP inference server + served HTML |
| `human_modeling/` | value dimensions (the human-model spine) |
| `data/` | grounding data (majors, employment, schools), scenes, dimensions |
| `prompts/` | editable generation prompts |
| `developer/` | offline tooling (build/enrich grounding, eval) |
| `miniprogram/` | WeChat Mini-Program client (calls the API; shares no Python) |

## Quickstart

```bash
cp .env.example .env          # fill in your keys (see below)
export $(grep -v '^#' .env | xargs)
PYTHONPATH=. python3 -m serving.web --port 9930
# open http://localhost:9930
```
Stdlib-only engine (no third-party Python deps). Python 3.10+.

## Environment variables

**Required**

| key | purpose |
|---|---|
| `OPENROUTER_API_KEY` | LLM for scene generation, the 画像, and the report (via OpenRouter) |
| `OPENAI_API_KEY` | voice transcription (speech-to-text). *Only needed if you use the voice intake.* |

**Optional**

| key | default | purpose |
|---|---|---|
| `GAOKAO_DATA_DIR` | `/data/.../gaokao-data` | where session-log JSONL is written |
| `GAOKAO_LOG_SINK` | — | off-box URL to also POST each session event (durable collector) |
| `GAOKAO_API_KEYS` | *(empty = open)* | comma-sep bearer keys; if set, the API **requires** `Authorization: Bearer <key>` (→ 401 otherwise). Use for a partner/keyed deployment. |
| `GAOKAO_ADMIN_TOKEN` | — | gates the prompt-editor + log endpoints |
| `GAOKAO_RL_PER_HOUR` | `100` | per-IP `rank_start` cap per hour |
| `YULAI_API_KEY` / `YULAI_BASE_URL` | — | call a partner evidence API for extra grounding |
| `OPENROUTER_MODEL` · `GAOKAO_PROFILE_MODEL` · `VOICE_STT_MODEL` | sensible defaults | model overrides |

**Secrets never go in git** — set them in `.env` (gitignored) or your deploy's environment (Render env vars, etc.). The same code runs open-source (bring your own keys) and in production (our keys in the deploy env).

## Data

The grounding data under `data/` is compiled from **public sources** (阳光高考, employment-quality reports). If you redistribute, check each source's terms and keep attribution.

## License

TBD. © the Meno research program. Attribution appreciated.
