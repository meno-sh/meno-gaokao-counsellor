"""Ranked-list + investigator model (ZH redesign 2026-06-14).

Replaces the A/B "two lives" with ONE trajectory the student steps onto (their
current #1 choice). At each factor-stage the *investigator* surfaces how their #1
fares on that factor vs one strong contender among their 5 — new information, not
a verdict (BE 2.0 / 反思均衡: help them reach their own answer, don't recommend).
The student reorders their ranked list freely; moving #1 pivots the trajectory.
End = a new ranked list + a 反思均衡 self-check + a confidence rating.
"""
from __future__ import annotations
import json, os, re, urllib.request
from core import paths
from dataclasses import dataclass, field
from core.grounding import grounding_block, yulai_major_block, yulai_scores_line, detect_province
from core import sources as _sources
from core import prompts
from core.profile import PersonalityFile

# Scene pool — the WTE selects which dimensions a given student examines (ZH
# 2026-06-17). Loaded from scenes.json (18 real-world-grounded dimensions); the
# 7 heuristic factors below are the fallback if the file is missing. STAGE_CAP
# bounds how many of the pool a single run surfaces (WTE picks the highest-VOI).
_FALLBACK_FACTORS = [
    {"key": "course",   "label": "课程与学业",   "ask": "这个专业大一大二真正要学的课、强度、能不能扛/喜不喜欢"},
    {"key": "daily",    "label": "日常与社群",   "ask": "校园日常、城市生活、社群归属——最常被忽视却影响巨大"},
    {"key": "interest", "label": "兴趣与擅长",   "ask": "做这些事到底是享受还是煎熬"},
    {"key": "finance",  "label": "经济与回报",   "ask": "学费/家庭负担、起薪与长期收入曲线"},
    {"key": "city",     "label": "城市与机会",   "ask": "城市能级、实习就业机会密度、离家远近"},
    {"key": "career",   "label": "职业前景",     "ask": "对口岗位、天花板、行业周期、年龄/晋升门槛(若该行业确有)"},
    {"key": "cost",     "label": "代价与放弃",   "ask": "选它你究竟放弃了什么(机会成本)"},
]
def _load_scenes():
    try:
        with open(paths.data("scenes.json")) as f:
            sc = json.load(f).get("scenes") or []
        out = [x for x in sc if x.get("key") and x.get("label") and x.get("ask") and not x.get("retired")]
        return out or _FALLBACK_FACTORS
    except Exception:
        return _FALLBACK_FACTORS
FACTORS = _load_scenes()
STAGE_CAP = int(os.environ.get("GAOKAO_STAGES", "18"))

_MODEL = os.environ.get("GAOKAO_TRAJECTORY_MODEL", "deepseek/deepseek-chat")

_WEBSEARCH = os.environ.get("GAOKAO_WEBSEARCH", "1") not in ("0", "", "false", "False")

def _route(model, online=False):
    """deepseek + NOT online -> official DeepSeek API (web-search plugin only exists on OpenRouter)."""
    dk=os.environ.get("DEEPSEEK_API_KEY")
    if (not online) and model and model.startswith("deepseek/") and dk:
        name={"deepseek/deepseek-chat":"deepseek-v4-flash","deepseek/deepseek-v4-pro":"deepseek-v4-pro",
              "deepseek/deepseek-v4-flash":"deepseek-v4-flash"}.get(model, model.split("/")[-1])
        return ("https://api.deepseek.com/chat/completions", dk, name)
    return ("https://openrouter.ai/api/v1/chat/completions", os.environ.get("OPENROUTER_API_KEY",""), model)

def _llm_json(prompt: str, *, max_tokens: int = 1500, temperature: float = 0.6,
              online: bool = False, model: str | None = None) -> dict:
    _url, key, _mname = _route(model or _MODEL, online)
    if not key:
        raise RuntimeError("no LLM key (OPENROUTER_API_KEY / DEEPSEEK_API_KEY)")
    payload = {"model": _mname,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens, "temperature": temperature}
    if online:
        # OpenRouter web plugin — model-agnostic search injected into context.
        payload["plugins"] = [{"id": "web", "max_results": 4}]
    body = json.dumps(payload).encode()
    req = urllib.request.Request(_url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://reflect.meno.sh", "X-Title": "reflection-game-ranked"})
    last = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=75) as resp:
                payload = json.loads(resp.read().decode())
            txt = payload["choices"][0]["message"].get("content") or ""
            txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
            return json.loads(txt)
        except Exception as e:
            import time; last = f"{type(e).__name__}:{e}"; time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"investigator gen failed: {last}")

def build_narrative(profile, quiz_answers, choices_text: str = "") -> "object":
    """Synthesize the ONE natural-language profile from all sources (self-desc +
    quiz answers + 去向 ranking + in-game choices). Sets profile.narrative.
    Best-effort: on any failure the narrative stays empty and we fall back to the
    raw self-description, so the game never breaks."""
    from core.quiz import answers_text
    try:
        prompt = prompts.render("profile_narrative",
            free_text=(profile.free_text or "(未填)"),
            destinations=(" > ".join(profile.destination_pref) or "(未排)"),
            quiz_qa=(answers_text(quiz_answers) or "(未答)"),
            choices=(choices_text or "(暂无)"))
        r = _llm_json(prompt, max_tokens=1500, temperature=0.5, model=os.environ.get("GAOKAO_PROFILE_MODEL", "deepseek/deepseek-v4-pro"))
        txt = ((r or {}).get("profile") or "").strip()
        if txt:
            profile.narrative = txt
    except Exception:
        pass
    return profile

def update_narrative(profile, stage_no, scene_label, q, a) -> str:
    """Incrementally fold one scene's elicited answer into the point-form 画像
    (and correct now-stale points). Best-effort; returns the (possibly updated) narrative."""
    try:
        prompt = prompts.render("profile_update",
            narrative=(profile.narrative or "(暂无)"), stage=stage_no,
            scene=scene_label or "", q=(q or ""), a=(a or ""))
        rr = _llm_json(prompt, max_tokens=1200, temperature=0.4,
                       model=os.environ.get("GAOKAO_PROFILE_MODEL", "deepseek/deepseek-v4-pro"))
        txt = ((rr or {}).get("profile") or "").strip()
        if txt:
            profile.narrative = txt
    except Exception:
        pass
    return profile.narrative

def chat_reply(profile, top, contender, history, message) -> str:
    """Brief (1-2 sentence) multi-turn reply weighing top vs contender for THIS student. Best-effort."""
    try:
        hist = "\n".join(("你:" if h[0] == "h" else "AI:") + str(h[1]) for h in (history or [])[-6:]) or "(无)"
        prompt = prompts.render("chat", top=(top or ""), contender=(contender or ""),
            narrative=(profile.narrative or "(暂无)"), history=hist, message=(message or ""))
        rr = _llm_json(prompt, max_tokens=300, temperature=0.6)
        return ((rr or {}).get("reply") or "").strip()
    except Exception:
        return ""

def intake_chat_reply(page, state, history, message) -> str:
    """Stateless intake-page companion (pre-rank_start, no session): help the student
    think about THIS page's topic. Never decides for them. Best-effort; '' on failure."""
    try:
        import json as _json
        topics = {
            "1": "他在纠结哪些 专业@学校,以及一句话自述",
            "2": "他更看重什么(金钱/兴趣/影响力的相对权重)+ 毕业去向(升学/就业/出国)",
            "3": "更深的价值取向(几个二选一小题)+ 他对第一志愿的确定度",
        }
        topic = topics.get(str(page), "他的高考志愿纠结")
        hist = "\n".join(("你:" if h[0] == "h" else "AI:") + str(h[1]) for h in (history or [])[-6:]) or "(无)"
        st = _json.dumps(state, ensure_ascii=False)[:800] if state else "(还没填)"
        prompt = (
            "你是高考志愿决策的陪伴助手,正陪一个考生填写开场问卷,目的是帮 ta 把自己想清楚。"
            f"当前这一步的主题:{topic}。\n"
            f"ta 目前填的:{st}\n"
            f"对话历史:\n{hist}\n"
            f"ta 刚说:{message}\n\n"
            "用 1-3 句简短、温暖、口语的话回应:帮 ta 把这一步想清楚一点(可以温和反问、可以点出 ta 还没考虑的角度),"
            "但绝不替 ta 决定、不评判哪个选择对错、不下结论。只返回 JSON {\"reply\":\"...\"}。")
        rr = _llm_json(prompt, max_tokens=300, temperature=0.6)
        return ((rr or {}).get("reply") or "").strip()
    except Exception:
        return ""

def _fallback_report(profile, final_order) -> str:
    """Deterministic, LLM-free report so rank_report is never empty."""
    order = " > ".join(final_order or []) or "(暂无排序)"
    narr = (getattr(profile, "narrative", "") or "").strip() or "(暂无画像)"
    return ("## 你的反思小结\n\n"
            f"**当前排序：** {order}\n\n"
            f"**我对你的理解：**\n{narr}\n\n"
            "（这份小结是基于你这一路的选择自动生成的简版——它不替你做决定，只把你已经表露的倾向回映给你。"
            "可以再玩一次、或把上面的排序和理解拿去和家人朋友聊聊。）")

def user_report(profile, final_order) -> str:
    """End-of-game reflective report from the 画像: present current state + competing
    objectives, never prescribe pitfalls. Retries once, then a deterministic fallback
    so the report is never empty."""
    for _attempt in range(2):
        try:
            elic = "\n".join("- 「%s」问:%s / 答:%s" % (e.get("scene",""), e.get("q",""), e.get("a",""))
                              for e in (getattr(profile, "elicited", []) or [])) or "(无)"
            prompt = prompts.render("user_report", narrative=(profile.narrative or "(暂无)"),
                elicited=elic, order=" > ".join(final_order or []))
            rr = _llm_json(prompt, max_tokens=2200, temperature=0.5,
                           model=os.environ.get("GAOKAO_PROFILE_MODEL", "deepseek/deepseek-v4-pro"))
            rep = ((rr or {}).get("report") or "").strip()
            if rep:
                return rep
        except Exception:
            pass
    return _fallback_report(profile, final_order)

def _opt_label(o) -> str:
    return (o or {}).get("label", "") if isinstance(o, dict) else str(o)

_AUTH_HINTS = ("edu.cn", "gov.cn", "mycos", "麦可思", "就业质量", "阳光高考", "chsi",
               "教育部", "统计局", "moe.", "官网", "招生", "就业")
_NEWS_BLOCK = ("sina", "sohu", "163.com", "qq.com", "baidu", "zhihu", "tieba",
               "toutiao", "ifeng", "news.", "weibo", "xhs", "xiaohongshu", "bilibili")

def _auth_sources(srcs: list) -> list:
    """Keep authoritative-looking sources, drop news/UGC/marketing. Returns NAME
    strings — objects (the websearch LLM sometimes emits {title,url,...}, which used to
    render as '[object Object]' through the frontend join) are normalized to their title.
    Clickable {title,url,tier} links ship later once URLs are backfilled (ZH 2026-06-19)."""
    out = []
    for n in _sources.normalize(srcs):
        blob = (n["title"] + " " + (n["url"] or "")).lower()
        if any(b in blob for b in _NEWS_BLOCK):
            continue
        if (n["tier"] == "雨来-verified" or any(h in blob for h in _AUTH_HINTS)
                or "报告" in n["title"] or "蓝皮书" in n["title"]):
            out.append(n["title"])
    return out[:3]

def investigate(factor: dict, options: list, profile_text: str) -> dict:
    """One investigator pass for a factor-stage: a short grounded vignette of living
    the current #1 on this factor, plus a contrast with ONE strong contender among
    the rest that differs on this factor. Returns dict(prose, contender, top_take,
    contender_take, did_you_know)."""
    top = _opt_label(options[0])
    rest = [_opt_label(o) for o in options[1:]]
    _prov = detect_province(profile_text)
    def _aug(lbl, full=False):
        b = grounding_block(lbl)
        if full:  # 雨来 lookups only for the #1 (the focus); contenders use local KB — speed
            yl = yulai_major_block(lbl)
            if yl:
                b = b + "\n" + yl
            sc = yulai_scores_line(lbl, _prov)
            if sc:
                b = b + "\n" + sc
        return b
    g_top = _aug(top, full=True)
    g_rest = "\n\n".join(f"[候选:{lbl}]\n{_aug(lbl)}" for lbl in rest)
    src_rule = ("**用网络检索核实这一步的关键事实**(只针对【" + factor['label'] + "】这一维度、"
                "针对 " + top + " 与你选定的对比项这两者)。**只采信权威来源**:高校毕业生就业质量报告、"
                "麦可思(MyCOS)就业蓝皮书、阳光高考平台、教育部/国家统计局官方数据、该校官网;"
                "**忽略营销软文、随机新闻、贴吧/营销号**。"
                "**铁律**:① 任何具体数字必须来自*明确覆盖'该校+该专业'*的权威来源;检索结果若不含该校该专业的具体数据,"
                "就**用定性描述、不要编数字**(如'对口率较高/一般')。② **绝不**把一个机构/地区的数据安到另一个机构头上"
                "(例如拿香港高校网站的数据去描述内地高校)。③ **不要在正文里插入任何引用标记/链接**,来源只写进 sources 字段,"
                "且 sources 里只列真正支持你所述事实的那个来源。检索不到可靠来源时退回到上面的 grounding。") if _WEBSEARCH else ""
    prompt = prompts.render("investigate", factor_label=factor['label'], factor_ask=factor['ask'], top=top, g_top=g_top, g_rest=g_rest, profile_text=profile_text, src_rule=src_rule)
    r = _llm_json(prompt, online=_WEBSEARCH, max_tokens=1800)
    def _clean(t):
        t = str(t or "")
        t = re.sub(r"\[[^\]]*\]\([^)]*\)", "", t)   # remove [text](url)
        t = re.sub(r"\[[^\]]*\]", "", t)              # remove bare [citation] (half-width)
        t = re.sub(r"^\s*(根据|据|依据)\s*[，,、:：]\s*", "", t)  # orphaned "根据，" after cite strip
        t = re.sub(r"(根据|据|依据)\s*[，,]\s*", "", t)
        t = re.sub(r"\s{2,}", " ", t).strip()
        return t
    _gctx = (g_top or "") + "\n" + (g_rest or "")
    for k in ("prose", "top_take", "contender_take", "did_you_know"):
        if k in r:
            r[k] = _strip_unverified_numbers(_clean(r[k]), _gctx)
    r["sources"] = _auth_sources(r.get("sources"))
    return r

def translate_major(label: str) -> dict:
    """官方介绍 → 说人话 → 没告诉你的, for a major (叶晓阳 deck mechanic)."""
    g = grounding_block(label)
    prompt = prompts.render("translate_major", label=label, g=g)
    return _llm_json(prompt, max_tokens=900)

def frame_test(top: str, profile_text: str, lang: str = "cn") -> dict:
    """Reframe the #1 choice under fear / opportunity / authority frames, each
    tagged with the bias it exploits. Frame-invariance = 反思均衡 (叶晓阳 deck)."""
    g = grounding_block(top)
    prompt = prompts.render("frame_test", top=top, g=g)
    if lang == "en":
        prompt = prompt + ("\n\n=== OUTPUT LANGUAGE OVERRIDE (HIGHEST PRIORITY) ===\n"
                  "Despite the Chinese field descriptions above, write ALL user-facing string values in fluent ENGLISH "
                  "(render Chinese facts faithfully). No Chinese sentences in the output values.")
    return _llm_json(prompt, max_tokens=900)

_CLEAN_PATTERNS = None
def _clean(t):
    t = str(t or "")
    t = re.sub(r"\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"^\s*(根据|据|依据)\s*[，,、:：]\s*", "", t)
    t = re.sub(r"(根据|据|依据)\s*[，,]\s*", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t

# --- Fabrication guard (fix (a), ZH 2026-06-19) -----------------------------
# The model routinely invents statistics (起薪28万 / 同比上升47% / 招聘量+21%)
# with credible-looking citations, despite the prompt 铁律. This is the HARD
# enforcement of "model prose carries no fabricated numbers": a numeric
# *statistic* in any model-written field survives only if its digits appear in
# the injected grounding (g_top/g_rest) -- which holds the verified
# uni_employment / yulai figures (e.g. "就业率 94.7%" / "应届平均月薪 10360元").
# Everything else has its number+unit stripped, leaving the qualitative claim.
# Web-searched numbers can't be verified here, so they're stripped too --
# conservative by design (the fake "citations" are exactly that vector).
_NUM = r"\d+(?:\.\d+)?"
_STAT_RE = re.compile(
    r"(?:(?:同比|环比)\s*)?"
    r"(?:逆势增长|增长了|减少了|上升|下降|增长|增加|提高|提升|高出|下滑|减少|高达|达到|达|近|超|仅|约)?\s*"
    + _NUM + r"\s*(?:%|％|个百分点|倍|万元|万|元)"
)
def _verified_num(token, context):
    nums = re.findall(_NUM, token)
    return bool(nums) and all(n in context for n in nums)
def _strip_unverified_numbers(text, context):
    """Remove statistics not backed by the injected grounding; keep verified ones."""
    text = str(text or "")
    if not text:
        return text
    ctx = context or ""
    out = _STAT_RE.sub(lambda m: m.group(0) if _verified_num(m.group(0), ctx) else "", text)
    out = re.sub(r"[（(][^（）()]{0,24}(?:数据|报告|统计|蓝皮书|白皮书|平台|来源)[^（）()]{0,12}[)）]", "", out)
    out = re.sub(r"[（(]\s*[)）]", "", out)
    out = re.sub(r"([，。、；：])\s*(?=[，。、；：])", "", out)
    out = re.sub(r"^[，。、；：%％\s]+", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return out

_SRC_RULE_GENERIC = ("**用网络检索核实本幕的关键事实**(针对第1名与你选定的对比项)。**只采信权威来源**:"
  "高校毕业生就业质量报告、麦可思就业蓝皮书、阳光高考、教育部/国家统计局、院校官网;忽略营销软文、随机新闻、贴吧/营销号。"
  "铁律:① 数字必须来自*明确覆盖该校+该专业*的权威来源,否则用定性、不要编数字;② 绝不把一个机构的数据安到另一个头上;"
  "③ 正文里不插任何引用标记/链接,来源只写进 sources 字段。检索不到可靠来源时退回 grounding。")

_HUMAN_DIMS = None
def load_human_dims():
    global _HUMAN_DIMS
    if _HUMAN_DIMS is None:
        try:
            with open(paths.data("human_dimensions.json")) as f:
                _HUMAN_DIMS = json.load(f).get("human_dimensions") or []
        except Exception:
            _HUMAN_DIMS = []
    return _HUMAN_DIMS

def _dim_label(key):
    for d in load_human_dims():
        if d.get("key") == key:
            return f"{d.get('pole_a','')}↔{d.get('pole_b','')}"
    return str(key)

_CITE_RULE = ("【务必·引用】上面【参考资料】是真实的「专业@学校」资料。写 top_take / contender_take / prose 时,"
              "**优先改用其中的具体事实**(具体课程、出路去向、真实就读体验等)把两条路写得具体可信,不要泛泛而谈。"
              "并在输出的 JSON 里**额外加一个字段 `cites`**,形如 "
              "{\"top_take\":[\"R1\"],\"contender_take\":[\"R3\"],\"prose\":[],\"investigator\":[]} —— "
              "列出每个正文字段**实际采信了哪些参考资料编号**(只列真用到的;没用到就留空数组 [];不要编造编号)。"
              "记住要输出 cites 字段 —— 现在按前面的 schema 输出 JSON。")

def _rag_refs(top, rest, considerations, cap=8, per_pick=3):
    """Build the 【参考资料】 block + a tag->piece map for the candidates. Fail-safe:
    returns ('', {}) if the RAG module / corpus / embedding is unavailable (so generation
    proceeds exactly as before when the corpus isn't deployed)."""
    try:
        import re as _re, json as _json
        from core import rag
        def _split(lbl):
            parts = _re.split(r"[@＠]", lbl or "", 1)
            return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else "")
        qvec = rag.embed(considerations) if considerations else []
        seen, lines, cmap, n = set(), [], {}, 1
        for lbl in ([top] + list(rest)):
            if len(cmap) >= cap:
                break
            maj, uni = _split(lbl)
            for rr in rag.retrieve(maj, uni, considerations, stop_factor="", k=per_pick, _qvec=qvec):
                if rr["id"] in seen or len(cmap) >= cap:
                    continue
                seen.add(rr["id"]); tag = "R%d" % n; n += 1
                cmap[tag] = {"major": rr["major"], "university": rr["university"], "full_text": rr["full_text"]}
                lines.append("[%s] (%s@%s): %s" % (tag, rr["major"], rr["university"], rr["full_text"][:600]))
        if not lines:
            return "", {}
        return ("【参考资料】(真实的「专业@学校」介绍 —— 用来让两条路的描述更具体可信;不是非用不可)\n" + "\n".join(lines)), cmap
    except Exception:
        return "", {}

def _extract_citations(result, cmap):
    """Read the structured `cites` field (per-field ref lists). Returns the citations map
    (tag -> {major, university, full_text}) for refs actually cited. Also normalizes
    result["cites"] to only-valid tags for the frontend."""
    if not cmap:
        result.pop("cites", None); return {}
    try:
        cites = result.get("cites") or {}
        used = set()
        clean = {}
        for field, tags in cites.items():
            kept = [t for t in (tags or []) if t in cmap]
            if kept: clean[field] = kept
            used.update(kept)
        # fallback: also catch any inline [Rn] the model left in the prose
        import re as _re, json as _json
        used.update(t for t in _re.findall(r"\[(R\d+)\]", _json.dumps(result, ensure_ascii=False)) if t in cmap)
        result["cites"] = clean
        return {t: cmap[t] for t in used}
    except Exception:
        return {}

def unified_turn(top, rest, profile_text, seen_keys, rerank_log, examined_dims=None, scene_history=None, student_views=None, lang="cn"):
    """ONE inference doing WTE (pick scene) + investigator (contender/question/
    investigate) + story-writer (prose), driven by a human-dimension uncertainty
    map. Returns the result dict with `_factor` resolved to the chosen scene.
    Best-effort — raises only if the LLM call ultimately fails."""
    seen = set(seen_keys or [])
    pool = [s for s in FACTORS if s.get("key") not in seen] or list(FACTORS)
    hd = load_human_dims()
    hd_s = "\n".join(f"- {d['key']}: {d.get('label','')}({d.get('pole_a','')}↔{d.get('pole_b','')}) — {d.get('note','')}"
                      for d in hd) or "(尚未定义)"
    _dlab = {d.get("key"): f"{d.get('pole_a','')}↔{d.get('pole_b','')}" for d in hd}
    def _scline(s):
        pr = "、".join(_dlab.get(k, k) for k in (s.get("probes") or []))
        return f"- {s['key']}: {s['label']} —— {s['ask']}" + (f"  (可照见维度: {pr})" if pr else "")
    sc_s = "\n".join(_scline(s) for s in pool)
    prov = detect_province(profile_text)
    g_top = grounding_block(top)
    yl = yulai_major_block(top)
    if yl: g_top = g_top + "\n" + yl
    ysc = yulai_scores_line(top, prov)
    if ysc: g_top = g_top + "\n" + ysc
    g_rest = "\n\n".join(f"[候选:{l}]\n{grounding_block(l)}" for l in rest)
    reranks = "; ".join(f"{r['from'][0]}→{r['to'][0]}" for r in (rerank_log or []) if r.get("top_changed")) or "(无改动)"
    seen_lbl = "、".join(s["label"] for s in FACTORS if s["key"] in seen) or "(无)"
    prompt = prompts.render("unified_turn", profile=profile_text, order=" > ".join([top] + rest),
        reranks=reranks, seen=seen_lbl, human_dims=hd_s, scene_pool=sc_s, top=top,
        g_top=g_top, g_rest=g_rest, src_rule=(_SRC_RULE_GENERIC if _WEBSEARCH else ""),
        examined_dims=("、".join(_dim_label(x) for x in (examined_dims or [])) or "(无)"),
        scene_history=("；".join(scene_history or []) or "(无)"),
        student_views=(student_views or "(无)"))
    if lang == "en":
        prompt = prompt + ("\n\n=== OUTPUT LANGUAGE OVERRIDE (HIGHEST PRIORITY) ===\n"
                  "The field descriptions above are written in Chinese, but you MUST write the actual VALUES of "
                  "prose / top_take / contender_take / question / scene_gist in fluent, natural ENGLISH — the user selected English. "
                  "Translate every Chinese fact faithfully into English. Major & school names may remain Chinese with a short "
                  "English gloss in parentheses. Absolutely NO Chinese sentences in those fields — Chinese prose here is a hard error.")
    _refs, _cmap = _rag_refs(top, rest, (profile_text or "")[:500])   # RAG grounding (fail-safe no-op if corpus absent)
    if _refs:
        prompt = prompt + "\n\n" + _refs + "\n" + _CITE_RULE
    r = _llm_json(prompt, online=_WEBSEARCH, max_tokens=2000)
    _gctx = (g_top or "") + "\n" + (g_rest or "")
    for k in ("prose", "top_take", "contender_take", "question"):
        if k in r:
            r[k] = _strip_unverified_numbers(_clean(r[k]), _gctx)
    r["sources"] = _auth_sources(r.get("sources"))
    if not r.get("contender"):                       # the contender label is the #2 option, not LLM-optional
        r["contender"] = rest[0] if rest else ""
    if not r.get("top"):
        r["top"] = top
    if not (r.get("prose") and r.get("contender_take")):   # rare LLM field-drop -> one re-gen, keep if better
        try:
            r2 = _llm_json(prompt, online=_WEBSEARCH, max_tokens=2000)
            for _k in ("prose", "top_take", "contender_take", "question"):
                if _k in r2: r2[_k] = _strip_unverified_numbers(_clean(r2[_k]), _gctx)
            if r2.get("prose") and r2.get("contender_take"):
                r2["sources"] = _auth_sources(r2.get("sources"))
                r2["contender"] = r2.get("contender") or (rest[0] if rest else "")
                r2["top"] = r2.get("top") or top
                r = r2
        except Exception:
            pass
    r["citations"] = _extract_citations(r, _cmap)
    sk = r.get("scene")
    scene = next((s for s in pool if s["key"] == sk), None) or pool[0]
    r["_factor"] = {"key": scene["key"], "label": scene["label"]}
    return r

@dataclass
class RankedSession:
    options: list                 # ordered list of {"label": "专业@学校"}; index 0 = current #1
    profile: PersonalityFile
    confidence_initial: int = 0   # 0-100
    lang: str = "cn"              # "cn" | "en" — UI + generated-content language (ZH 2026-06-22)
    confidence_final: int = 0
    stage: int = 0                # how many factor-stages consumed
    history: list = field(default_factory=list)
    rerank_log: list = field(default_factory=list)
    conf_traj: list = field(default_factory=list)  # per-stage confidence (path-dependence signal)
    initial_order: list = field(default_factory=list)
    frame_results: list = field(default_factory=list)   # [{frame, bias, swayed}]
    _prefetch: dict = field(default_factory=dict)        # (stage_idx, top) -> investigate() result
    _pending: dict = field(default_factory=dict)
    _stage_pick: dict = field(default_factory=dict)      # stage_idx -> WTE-chosen factor (memoized)
    _wte_ledger: list = field(default_factory=list)      # per-stage ideal-preference ledger + why

    def __post_init__(self):
        if not self.initial_order:
            self.initial_order = [_opt_label(o) for o in self.options]

    def _pf(self):
        """Lazy-init the prefetch cache — robust to sessions pickled before the
        _prefetch field existed (unpickling won't restore new fields)."""
        if not hasattr(self, "_prefetch") or self._prefetch is None:
            self._prefetch = {}
        return self._prefetch

    def _sp(self):
        if not hasattr(self, "_stage_pick") or self._stage_pick is None:
            self._stage_pick = {}
        return self._stage_pick

    def _factor_for_stage(self):
        """The WTE pick for the current stage — chosen by value-of-information from
        the un-surfaced factor pool, memoized per stage index so prefetch and the
        real serve agree (and the prefetch cache key stays valid)."""
        sp = self._sp()
        if self.stage in sp:
            return sp[self.stage]
        seen_keys = {f["key"] for f in sp.values()}
        pool = [f for f in FACTORS if f["key"] not in seen_keys] or list(FACTORS)
        seen = [f for f in FACTORS if f["key"] in seen_keys]
        from core import wte
        factor, ledger, why = wte.select_factor(
            self.profile.serialize_for_prompt(), pool, seen,
            self.current_order(), self.rerank_log, _llm_json)
        sp[self.stage] = factor
        if ledger is not None or why:
            self._wte_ledger.append({"stage": self.stage, "pick": factor["key"],
                                     "why": why, "ledger": ledger})
        return factor

    def _seen_keys(self):
        return [h.get("factor", {}).get("key") for h in self.history if h.get("factor")]

    def _examined_dims(self):
        return [wl.get("target_dim") for wl in (self._wte_ledger or []) if wl.get("target_dim")]

    def _scene_gists(self):
        # within-game scene history (imagery tags) so generation avoids repeating scenes
        return [h.get("scene_gist") for h in self.history if h.get("scene_gist")]

    def _student_views(self):
        # student's own stated understanding per major — treated as high-trust (Yuhe 2026-06-21):
        # students often know their major better than scraped data; respect + build on, don't correct.
        parts = []
        for o in self.options:
            nt = (o.get("note") or "").strip() if isinstance(o, dict) else ""
            if nt:
                parts.append(f"「{_opt_label(o)}」: {nt}")
        return "；".join(parts)

    def _turn(self, top_label):
        """One unified call as if top_label were #1. Returns the result dict."""
        rest = [l for l in self.current_order() if l != top_label]
        return unified_turn(top_label, rest, self.profile.serialize_for_prompt(),
                            self._seen_keys(), self.rerank_log, self._examined_dims(), self._scene_gists(), self._student_views(), getattr(self, 'lang', 'cn'))

    def cap(self) -> int: return min(STAGE_CAP, len(FACTORS))
    def replay(self):
        """Start a fresh round from the user's current (updated) ranking + confidence,
        keeping their profile/options. Resets only the station walk."""
        self.initial_order = self.current_order()
        if self.confidence_final:
            self.confidence_initial = self.confidence_final
        self.stage = 0
        self.history = []
        self.rerank_log = []
        self.frame_results = []
        self._prefetch = {}
        self._pending = {}
        self._stage_pick = {}
        self._wte_ledger = []

    def done(self) -> bool: return self.stage >= self.cap()
    def current_order(self) -> list: return [_opt_label(o) for o in self.options]

    def reorder(self, new_order: list):
        """Apply a user reorder (list of labels). Logs it; flags if #1 changed."""
        old = self.current_order()
        by = {_opt_label(o): o for o in self.options}
        self.options = [by[l] for l in new_order if l in by] + [o for o in self.options if _opt_label(o) not in set(new_order)]
        new = self.current_order()
        if old != new:
            _p = self._pending or {}
            self.rerank_log.append({"stage": self.stage, "from": old, "to": new,
                                    "top_changed": old[0] != new[0],
                                    "factor": (self._sp().get(self.stage) or {}).get("label"),  # triggering tension
                                    "saw": {              # what the user was looking at when they changed their mind (the "why")
                                        "dim": (_p.get("factor") or {}).get("label"),
                                        "question": _p.get("question"),
                                        "top": _p.get("top"), "contender": _p.get("contender"),
                                        "top_take": _p.get("top_take"), "contender_take": _p.get("contender_take"),
                                    }})
            # NB: do NOT clear the prefetch cache — it's keyed per-option (stage, label),
            # so the new #1's next stage is already cached → re-rank stays instant.

    def prefetch_next(self) -> bool:
        """Speculatively generate the NEXT stage for the current #1, called during
        the user's read-time. Cached by (stage_index, top); served instantly by
        next_stage() if #1 is unchanged. Best-effort — silently no-ops on error."""
        if self.done():
            return False
        top = self.current_order()[0]
        key = (self.stage, top)
        if key in self._pf():
            return True
        try:
            self._pf()[key] = self._turn(top)
            return True
        except Exception:
            return False

    def prefetch_all(self, max_workers: int = 3):
        """Prefetch the NEXT stage for ALL current options (priority = current order),
        so any re-rank is instant — re-ranking is the core interaction, and that's
        exactly when a cold generate would hurt. Each = investigate() as if that
        option were #1. Bounded concurrency (provider throttles a single key)."""
        if self.done():
            return
        from concurrent.futures import ThreadPoolExecutor
        labels = self.current_order()
        def gen(lbl):
            key = (self.stage, lbl)
            if key in self._pf():
                return
            try:
                self._pf()[key] = self._turn(lbl)
            except Exception:
                pass
        # #1 first (synchronously) so the no-rerank path is ready ASAP, then the rest.
        gen(labels[0])
        rest = labels[1:]
        if rest:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                list(ex.map(gen, rest))

    def next_stage(self) -> dict | None:
        if self.done():
            return None
        top = self.current_order()[0]
        result = self._pf().pop((self.stage, top), None)
        cached = result is not None
        if result is None:
            result = self._turn(top)
        factor = result.get("_factor") or {"key": "?", "label": "?"}
        if result.get("human_dims") is not None or result.get("target_dim"):
            self._wte_ledger.append({"stage": self.stage + 1, "pick": factor["key"],
                                     "why": result.get("question", ""), "target_dim": result.get("target_dim"),
                                     "ledger": result.get("human_dims")})
        self.stage += 1
        self._pending = {"stage": self.stage, "factor": factor, **result,
                         "order": self.current_order(), "top": self.current_order()[0]}
        self.history.append(self._pending)
        return {"stage": self.stage, "cap": self.cap(), "prefetched": cached,
                "factor": {"key": factor["key"], "label": factor["label"]},
                "question": result.get("question", ""), "elicit": result.get("elicit", ""),
                "prose": result.get("prose", ""), "top": self.current_order()[0],
                "contender": result.get("contender", ""),
                "top_take": result.get("top_take", ""),
                "contender_take": result.get("contender_take", ""),
                "did_you_know": result.get("did_you_know", ""),
                "sources": result.get("sources", []),
                "citations": result.get("citations", {}),
                "order": self.current_order(), "last": self.done()}

    def ending(self) -> dict:
        """Final: the new ranked list, the 反思均衡 self-check, initial→final shift."""
        from core.checklist import REFLECTIVE_EQUILIBRIUM_CHECKLIST
        stable = sum(1 for f in self.frame_results if not f.get("swayed"))
        swayed_biases = [f.get("bias") for f in self.frame_results if f.get("swayed")]
        return {
            "initial_order": self.initial_order,
            "final_order": self.current_order(),
            "top_changed": self.initial_order[:1] != self.current_order()[:1],
            "n_reranks": len(self.rerank_log),
            "confidence_initial": self.confidence_initial,
            "checklist": REFLECTIVE_EQUILIBRIUM_CHECKLIST,
            "frames_total": len(self.frame_results),
            "frames_stable": stable,
            "swayed_biases": swayed_biases,
            "options": self.current_order(),
            "scenes_visited": [h.get("factor", {}).get("label") for h in self.history if h.get("factor")],
            "portrait": (getattr(self.profile, "narrative", "") or getattr(self.profile, "free_text", "") or "")[:220],
        }
