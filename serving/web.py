#!/usr/bin/env python3
"""Minimal playable web app for the 高考 variant (cycle 4).

Flow: intake (two options + a short value questionnaire) -> run_pipeline runs
BOTH option-worlds (fast V3, the two lives concurrent) -> the backward-reasoning
mirror. The run takes ~minutes, so it's ASYNC: POST /start returns a job id, the
page polls /status for streamed stage events + the final result. MVP picks each
stage from the user's stated leaning (runs straight through); interactive
per-stage choice is v2.

Run: python3 -m gaokao.web --port 9930   (needs OPENROUTER_API_KEY)
"""
from __future__ import annotations
import argparse, json, os, threading, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from core.demo import run_pipeline, default_trajectory_generator

JOBS = {}  # id -> {events:[], result:dict|None, error:str|None}
_LOCK = threading.Lock()
IG = {}        # interactive sessions: sid -> InteractiveSession
_IGLOCK = threading.Lock()
_IG_DIR = "/data/reflection-game/gaokao-data/ig_sessions"

def _ig_save(sid, sess):
    """Best-effort pickle so a server restart doesn't kill an in-progress run.
    The generator isn't pickled (recreated on load)."""
    try:
        import os, pickle
        os.makedirs(_IG_DIR, exist_ok=True)
        gen = sess.gen; sess.gen = None
        try:
            with open(os.path.join(_IG_DIR, sid + ".pkl"), "wb") as f:
                pickle.dump(sess, f)
        finally:
            sess.gen = gen
    except Exception:
        pass

def _ig_load(sid):
    try:
        import os, pickle
        fp = os.path.join(_IG_DIR, sid + ".pkl")
        if not os.path.exists(fp):
            return None
        with open(fp, "rb") as f:
            sess = pickle.load(f)
        from core.demo import default_trajectory_generator
        sess.gen = default_trajectory_generator(fast=True)
        return sess
    except Exception:
        return None

RANK = {}      # ranked-list sessions: sid -> RankedSession
_RANK_DIR = "/data/reflection-game/gaokao-data/rank_sessions"

def _persist_to_box(sid, blob):
    base = _LOG_SINK.rsplit("/", 1)[0] if _LOG_SINK else ""
    if not base:
        return
    import base64, json as _j, threading, urllib.request
    def _go():
        try:
            data = _j.dumps({"sid": sid, "blob": base64.b64encode(blob).decode()}).encode()
            urllib.request.urlopen(urllib.request.Request(base + "/rank_persist", data=data, method="POST",
                headers={"Content-Type": "application/json"}), timeout=10)
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()

def _load_from_box(sid):
    base = _LOG_SINK.rsplit("/", 1)[0] if _LOG_SINK else ""
    if not base:
        return None
    try:
        import base64, json as _j, urllib.request
        with urllib.request.urlopen(base + "/rank_persist?key=" + sid, timeout=10) as r:
            b = (_j.loads(r.read().decode()) or {}).get("blob")
        return base64.b64decode(b) if b else None
    except Exception:
        return None

def _rank_save(sid, sess):
    try:
        import pickle
        blob = pickle.dumps(sess)
    except Exception:
        return
    _persist_to_box(sid, blob)        # durable off-box copy FIRST — runs even when /data isn't writable (Render)
    try:
        import os
        os.makedirs(_RANK_DIR, exist_ok=True)
        with open(os.path.join(_RANK_DIR, sid + ".pkl"), "wb") as f:
            f.write(blob)
    except Exception:
        pass

def _rank_load(sid):
    try:
        import os, pickle
        fp = os.path.join(_RANK_DIR, sid + ".pkl")
        if os.path.exists(fp):
            with open(fp, "rb") as f:
                return pickle.load(f)
        blob = _load_from_box(sid)   # local miss (restart wiped /data) -> durable box copy
        if blob:
            try:
                with open(fp, "wb") as f:
                    f.write(blob)
            except Exception:
                pass
            return pickle.loads(blob)
        return None
    except Exception:
        return None


def _render_rank_log(limit=25):
    """Human-readable trace of recent ranked sessions — intake, synthesized
    profile, per-stage WTE pick + uncertainty-map + why + investigation, reorders, ending.
    For reading test logs together (ZH 2026-06-17)."""
    import os, glob, pickle, html, time
    def esc(x): return html.escape(str(x if x is not None else ""))
    files = sorted(glob.glob(os.path.join(_RANK_DIR, "*.pkl")), key=os.path.getmtime, reverse=True)[:limit]
    cards = []
    for fp in files:
        try:
            with open(fp, "rb") as f: s = pickle.load(f)
        except Exception:
            continue
        sid = os.path.basename(fp)[:-4]
        when = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
        prof = getattr(s, "profile", None)
        ft = esc(getattr(prof, "free_text", "") or "(空)")
        dp = " > ".join(getattr(prof, "destination_pref", []) or []) or "(未排)"
        narr = esc(getattr(prof, "narrative", "") or "(未合成)")
        hist = getattr(s, "history", []) or []
        ledg = getattr(s, "_wte_ledger", []) or []
        init = " > ".join(getattr(s, "initial_order", []) or [])
        fin = " > ".join(s.current_order() if hasattr(s, "current_order") else [])
        ci = getattr(s, "confidence_initial", 0); cf = getattr(s, "confidence_final", 0)
        nrr = len(getattr(s, "rerank_log", []) or [])
        stages_html = []
        for i, h in enumerate(hist):
            wl = ledg[i] if i < len(ledg) else {}
            why = esc(wl.get("why", ""))
            led = wl.get("ledger") or []
            led_rows = "".join(
                f"<tr><td>{esc(d.get('dim'))}</td><td>{esc(d.get('uncertainty'))}</td>"
                f"<td>{'✓' if d.get('decision_relevant') else '·'}</td><td>{esc(d.get('note'))}</td></tr>"
                for d in led) if isinstance(led, list) else ""
            led_tbl = (f"<table class=led><tr><th>维度</th><th>不确定</th><th>影响排序</th><th>依据</th></tr>{led_rows}</table>") if led_rows else ""
            stages_html.append(
                f"<div class=stage><div class=sh>幕 {esc(h.get('stage'))} · WTE选了【{esc((h.get('factor') or {}).get('label'))}】"
                f"{(' — '+why) if why else ''}</div>"
                f"{led_tbl}"
                f"<div class=prose>{esc(h.get('prose'))}</div>"
                f"<div class=tk><b>{esc(h.get('top'))}</b>: {esc(h.get('top_take'))}<br>"
                f"<b>vs {esc(h.get('contender'))}</b>: {esc(h.get('contender_take'))}</div>"
                f"<div class=dyk>💡 {esc(h.get('did_you_know'))}</div>"
                f"<div class=src>来源: {esc('、'.join(h.get('sources') or []) or '—')}</div></div>")
        cards.append(
            f"<div class=card><div class=hd>{esc(sid)} <span class=mut>· {when} · {len(hist)}幕 · {nrr}次重排</span></div>"
            f"<div class=intake><b>自我描述:</b> {ft}<br><b>毕业去向:</b> {esc(dp)}<br><b>初始信心:</b> {ci} → <b>最终:</b> {cf}</div>"
            f"<div class=narr><b>🧬 合成画像:</b><br>{narr}</div>"
            f"<div class=ord><b>排序:</b> {esc(init)} <span class=mut>→</span> {esc(fin)}</div>"
            + "".join(stages_html) + "</div>")
    body = "".join(cards) or "<p>暂无会话。先去玩一局。</p>"
    return ("<!doctype html><meta charset=utf-8><title>Gaokao 测试日志</title>"
        "<style>body{font:14px/1.6 -apple-system,'PingFang SC',sans-serif;max-width:920px;margin:24px auto;padding:0 16px;background:#0f1115;color:#e8eaed}"
        ".card{border:1px solid #2a2f3a;border-radius:10px;padding:14px;margin:0 0 22px;background:#181b22}"
        ".hd{font-weight:700;font-size:15px;margin-bottom:8px}.mut{color:#9aa3af;font-weight:400}"
        ".intake,.narr,.ord{background:#0d1117;border-radius:7px;padding:9px;margin:6px 0;font-size:13px}"
        ".narr{border-left:3px solid #58a6ff}.stage{border-top:1px dashed #2a2f3a;padding:10px 0;margin-top:8px}"
        ".sh{font-weight:600;color:#58a6ff;margin-bottom:5px}.prose{color:#c9d1d9;margin:5px 0}"
        ".tk{font-size:13px;color:#adbac7}.dyk{color:#f0c674;font-size:13px;margin:4px 0}.src{color:#6e7681;font-size:11.5px}"
        "table.led{border-collapse:collapse;margin:5px 0;font-size:12px;width:100%}"
        ".led th,.led td{border:1px solid #2a2f3a;padding:3px 6px;text-align:left}.led th{color:#9aa3af}</style>"
        "<h2>高考志愿 · 测试日志 <span class=mut style=font-size:13px>(最近 " + str(len(cards)) + " 局，新→旧；含 WTE 不确定性地图)</span></h2>" + body)




def _spawn_prefetch(sess):
    """Kick off speculative generation of the next stage in the background, so it's
    ready by the time the user clicks. In-memory cache only (no pickle race)."""
    def run():
        try:
            sess.prefetch_all()
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()

_LOG_PATH = os.path.join(os.environ.get("GAOKAO_DATA_DIR", "/data/reflection-game/gaokao-data"), "session_log.jsonl")
_LOG_SINK = os.environ.get("GAOKAO_LOG_SINK", "")
_API_KEYS = set(k.strip() for k in os.environ.get("GAOKAO_API_KEYS", "").split(",") if k.strip())  # non-empty => API requires Bearer key (yulai/雨来 deployment); empty (main/public) => open
import time as _time, collections as _collections
_RL = _collections.defaultdict(list)                       # ip -> [rank_start timestamps], last hour
_RL_MAX = int(os.environ.get("GAOKAO_RL_PER_HOUR", "100")) # per-IP game cap (tunable via env)  # off-box durable collector: POST one json line per session event

def _log_session(rec):
    """Append one JSON line — the research dataset of how each session went.
    Local write is best-effort (silently no-ops where /data isn't writable, e.g. Render);
    GAOKAO_LOG_SINK ships each line off-box to a durable collector on a host we control
    (threaded so it never blocks or breaks the request)."""
    import time
    rec = {"ts": time.time(), **rec}
    line = json.dumps(rec, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if _LOG_SINK:
        def _ship():
            try:
                import urllib.request
                urllib.request.urlopen(urllib.request.Request(
                    _LOG_SINK, data=line.encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST"), timeout=6)
            except Exception:
                pass
        threading.Thread(target=_ship, daemon=True).start()

# the 8 axes as plain-language questionnaire sliders (pole_a is +1)
AXES = [
    ("VOICE", "SILENCE", "更愿意把想法说出来 / 更愿意先沉住气"),
    ("SELF", "OTHER", "更跟随自己的方向 / 更顾及他人与家庭"),
    ("PROCESS", "OUTCOME", "更看重过程与体验 / 更看重结果与回报"),
    ("NOW", "LATER", "更想现在就投入 / 更愿为以后铺垫"),
    ("PRINCIPLE", "LOYALTY", "更守原则 / 更重关系与忠诚"),
    ("TRUTH", "PROTECTION", "更求真实 / 更求稳妥保护"),
    ("AGENCY", "OBSERVATION", "更主动行动 / 更先观察等待"),
    ("RIGOR", "MERCY", "更讲较真严谨 / 更讲体谅宽和"),
]

def _run_job(jid, payload):
    try:
        prior = {}
        for (a, b, _), v in zip(AXES, payload.get("sliders", [])):
            v = float(v)
            if v >= 0: prior[a] = v
            else: prior[b] = -v
        leaning = {**prior}
        def choose(turn):
            def sc(o):
                return sum(o.dimension_vector.get(p, 0) * (1 if p in prior else 0) * prior.get(p, 0)
                           for p in o.dimension_vector)
            return max(range(len(turn.options)), key=lambda i: sc(turn.options[i]))
        def on_event(kind, p):
            if kind == "stage":
                with _LOCK:
                    JOBS[jid]["events"].append({"life": p["life"], "stage": p["stage"],
                                                "prose": p["rec"]["prose"], "picked": p["rec"]["picked"],
                                                "options": p["rec"]["options"]})
        gen = default_trajectory_generator(fast=True)
        res = run_pipeline(payload["option_A"], payload.get("arch_A", "prestige_school_weak_major"),
                           payload["option_B"], payload.get("arch_B", "weak_school_strong_major"),
                           free_text=payload.get("free_text", ""), prior=prior,
                           generator=gen, cap=int(payload.get("cap", 5)), choose=choose, on_event=on_event)
        with _LOCK:
            JOBS[jid]["result"] = {"revealed_core": res["ending"]["revealed_core"],
                                   "mirror": res["ending"]["mirror"],
                                   "signal": res["ending"]["signal"][:6]}
    except Exception as e:
        with _LOCK:
            JOBS[jid]["error"] = f"{type(e).__name__}: {e}"

class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype)
        if ctype.startswith("text/html"):
            self.send_header("Cache-Control", "no-cache, must-revalidate")  # always re-fetch HTML so updates show
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def _admin_ok(self):
        tok = os.environ.get("GAOKAO_ADMIN_TOKEN", "")
        if not tok:
            return False   # no token configured -> dev/editor endpoints disabled in production
        from urllib.parse import urlparse, parse_qs
        given = parse_qs(urlparse(self.path).query).get("t", [""])[0] or self.headers.get("X-Admin-Token", "")
        return given == tok

    def do_GET(self):
        _gp = self.path.split("?")[0]
        if _gp in ("/prompts", "/prompts_data", "/rank_log") and not self._admin_ok():
            return self._send(403, json.dumps({"error": "forbidden"}))
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, _RANK_PAGE, "text/html; charset=utf-8")
        elif self.path == "/ab" or self.path.startswith("/ab?"):
            self._send(200, _PAGE, "text/html; charset=utf-8")
        elif self.path.startswith("/rank_quiz"):
            from core.quiz import quiz_payload, destinations_payload
            self._send(200, json.dumps({"quiz": quiz_payload(), "destinations": destinations_payload()}, ensure_ascii=False))
        elif self.path.startswith("/status"):
            jid = self.path.split("job=")[-1]
            with _LOCK:
                j = JOBS.get(jid)
                self._send(200 if j else 404, json.dumps(j or {"error": "no job"}, ensure_ascii=False))
        elif self.path.startswith("/rank_revisit"):
            from urllib.parse import urlparse, parse_qs
            key = (parse_qs(urlparse(self.path).query).get("key") or [""])[0]
            sink = os.environ.get("GAOKAO_LOG_SINK", "")
            base = sink.rsplit("/", 1)[0] if sink else ""
            if not key or not base:
                return self._send(200, json.dumps({"error": "no key/sink"}, ensure_ascii=False), "application/json; charset=utf-8")
            try:
                import urllib.request as _u
                with _u.urlopen(base + "/rank_revisit?key=" + key, timeout=12) as r:
                    return self._send(200, r.read().decode("utf-8"), "application/json; charset=utf-8")
            except Exception as e:
                return self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False), "application/json; charset=utf-8")
        elif self.path == "/loading_preview":
            self._send(200, _LOADING_PREVIEW, "text/html; charset=utf-8")
        elif self.path == "/rank_log" or self.path.startswith("/rank_log?"):
            self._send(200, _render_rank_log(), "text/html; charset=utf-8")
        elif self.path == "/prompts" or self.path.startswith("/prompts?"):
            self._send(200, _PROMPTS_PAGE, "text/html; charset=utf-8")
        elif self.path.startswith("/prompts_data"):
            from core import prompts as _pr
            self._send(200, json.dumps(_pr.registry(), ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))
    def _handle_voice(self):
        from urllib.parse import urlparse, parse_qs
        _q = parse_qs(urlparse(self.path).query)
        fast = _q.get("fast", ["0"])[0] == "1"
        intake = _q.get("intake", ["0"])[0] == "1"
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b""
        if "json" in (self.headers.get("Content-Type", "") or "").lower():
            import base64
            try:
                audio = base64.b64decode(((json.loads(raw or b"{}")) or {}).get("audio_b64", ""))
            except Exception:
                audio = b""
        else:
            audio = raw
        if not audio:
            return self._send(400, json.dumps({"error": "empty audio"}, ensure_ascii=False))
        from core.voice_profile import transcribe, profile_from_transcript, save_transcript
        try:
            transcript = transcribe(audio, filename="rec.webm", language="zh")
        except Exception as e:
            return self._send(500, json.dumps({"error": f"转写失败: {type(e).__name__}: {e}"}, ensure_ascii=False))
        if not transcript.strip():
            return self._send(200, json.dumps({"error": "没听清,请再说一次"}, ensure_ascii=False))
        if fast:   # transcript-only (note/free-text mics) — skip the slow profile LLM
            return self._send(200, json.dumps({"transcript": transcript}, ensure_ascii=False))
        if intake:  # voice-as-whole-form: extract the志愿 intake from the speech
            from core.voice_profile import extract_intake_from_transcript
            try:
                intake_data = extract_intake_from_transcript(transcript)
            except Exception as e:
                return self._send(200, json.dumps({"transcript": transcript, "error": f"抽取失败: {e}"}, ensure_ascii=False))
            return self._send(200, json.dumps({"transcript": transcript, "intake": intake_data}, ensure_ascii=False))
        # full mode: profile gen is best-effort, never fatal (still return the transcript)
        profile, sid = {}, ""
        try:
            profile = profile_from_transcript(transcript)
            sid = uuid.uuid4().hex[:10]
            save_transcript(sid, transcript, profile)
        except Exception as e:
            log.warning("voice profile gen failed (transcript still returned): %r", e) if "log" in dir() else None
        self._send(200, json.dumps({"transcript": transcript, **profile, "sid": sid}, ensure_ascii=False))

    def _ig(self, sid):
        with _IGLOCK:
            sess = IG.get(sid)
        if sess is None and sid:                       # survive server restarts
            sess = _ig_load(sid)
            if sess is not None:
                with _IGLOCK:
                    IG[sid] = sess
        return sess

    def _handle_ig_start(self, body):
        from core.demo import default_trajectory_generator
        from core.profile import PersonalityFile
        from core.interactive import InteractiveSession
        prior = {}
        try:
            from core.web import AXES as _AX
        except Exception:
            _AX = AXES
        for (a, b, _), v in zip(_AX, body.get("sliders", []) or []):
            v = float(v); prior[a if v >= 0 else b] = abs(v)
        prof = PersonalityFile(user_id="ig", free_text=body.get("free_text", ""), prior=prior)
        sess = InteractiveSession(body.get("option_A", {}), body.get("option_B", {}),
                                  body.get("archetype_key", "prestige_vs_major"),
                                  prof, default_trajectory_generator(fast=True), cap=int(body.get("cap", 4)))
        sid = uuid.uuid4().hex[:10]
        with _IGLOCK:
            IG[sid] = sess
        stage = sess.next_stage("A")
        _ig_save(sid, sess)
        return self._send(200, json.dumps({"sid": sid, "stage": stage, "phase": "play"}, ensure_ascii=False))

    def _handle_ig_profile(self, body):
        """Update the session's shared profile mid-run. Edits feed the NEXT
        scene the LLM builds (the profile is the shared ground; ZH 2026-06-12)."""
        sess = self._ig(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        prof = sess.profile
        if body.get("free_text") is not None:
            prof.free_text = str(body["free_text"])[:600]
        if body.get("sliders") is not None:
            prior = {}
            for (a, b, _), v in zip(AXES, body["sliders"]):
                v = float(v); prior[a if v >= 0 else b] = abs(v)
            prof.prior = prior
        _ig_save(body.get("sid"), sess)
        return self._send(200, json.dumps({"ok": True}, ensure_ascii=False))

    def _handle_ig_choose(self, body):
        sess = self._ig(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        side = body.get("side", "A")
        try:
            sess.record_choice(side, int(body.get("idx", 0)))
        except Exception as e:
            return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
        # advance: same side until done, then switch to B, then ending
        if not sess.side_done(side):
            st = sess.next_stage(side); _ig_save(body.get('sid'), sess)
            return self._send(200, json.dumps({"stage": st, "phase": "play"}, ensure_ascii=False))
        other = "B" if side == "A" else "A"
        if not sess.side_done(other):
            st = sess.next_stage(other); _ig_save(body.get('sid'), sess)
            return self._send(200, json.dumps({"stage": st, "phase": "play", "switch": other}, ensure_ascii=False))
        # both done -> ending (mirror + per-path cost gate)
        end = sess.ending()
        return self._send(200, json.dumps({"phase": "ending", "ending": end}, ensure_ascii=False))

    def _rank(self, sid):
        with _IGLOCK:
            sess = RANK.get(sid)
        if sess is None and sid:
            sess = _rank_load(sid)
            if sess is not None:
                with _IGLOCK:
                    RANK[sid] = sess
        return sess

    def _handle_rank_start(self, body):
        _xff = self.headers.get("X-Forwarded-For", "")
        _ip = (_xff.split(",")[0].strip() if _xff else (self.client_address[0] if self.client_address else "?"))
        _now = _time.time()
        _hist = [tt for tt in _RL.get(_ip, []) if _now - tt < 3600]
        if len(_hist) >= _RL_MAX:                                     # one source spamming new games -> 429 (real users behind other IPs unaffected)
            return self._send(429, json.dumps({"error": "rate_limited", "retry_after": 3600}, ensure_ascii=False))
        _hist.append(_now); _RL[_ip] = _hist
        if len(_RL) > 20000:                                          # crude memory bound: drop empties
            for _k in [k for k, v in list(_RL.items()) if not [t2 for t2 in v if _now - t2 < 3600]]:
                _RL.pop(_k, None)
        from core.ranked import RankedSession, build_narrative
        from core.quiz import apply_answers
        from core.profile import PersonalityFile
        opts = [o for o in (body.get("options") or []) if (o or {}).get("label")]
        if len(opts) < 2:
            return self._send(400, json.dumps({"error": "至少 2 个选择"}, ensure_ascii=False))
        prof = PersonalityFile(user_id="rank", free_text=str(body.get("free_text", ""))[:600])
        apply_answers(prof, body.get("quiz", {}))
        dp = body.get("destination_pref") or []
        prof.destination_pref = [str(x) for x in dp if x][:6]
        _vw = body.get("value_weights") or {}
        if isinstance(_vw, dict):
            prof.value_weights = {k: int(v) for k, v in _vw.items() if isinstance(v, (int, float))}
        build_narrative(prof, body.get("quiz", {}))  # synthesize the one NL profile
        sess = RankedSession(options=opts, profile=prof,
                             confidence_initial=int(body.get("confidence_initial", 0)),
                             lang=("en" if str(body.get("lang", "cn")).lower().startswith("en") else "cn"))
        sid = uuid.uuid4().hex[:10]
        with _IGLOCK:
            RANK[sid] = sess
        try:
            stage = sess.next_stage()
        except Exception as e:
            return self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        _rank_save(sid, sess)
        _log_session({"event": "start", "sid": sid, "options": [o.get("label") for o in opts],
                      "notes": [o.get("note", "") for o in opts],
                      "initial_order": sess.initial_order, "confidence_initial": sess.confidence_initial,
                      "quiz": body.get("quiz", {}), "free_text": prof.free_text,
                      "destination_pref": prof.destination_pref})
        _spawn_prefetch(sess)
        return self._send(200, json.dumps({"sid": sid, "stage": stage, "narrative": getattr(prof, "narrative", "")}, ensure_ascii=False))

    def _handle_rank_next(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        try:
            _c = int(body.get("confidence"))
            if 0 <= _c <= 100:
                if not hasattr(sess, "conf_traj") or sess.conf_traj is None: sess.conf_traj = []
                sess.conf_traj.append({"stage": sess.stage, "confidence": _c, "dwell_ms": body.get("dwell_ms")})
        except Exception:
            pass
        if body.get("end") or sess.done():   # user can end anytime
            return self._send(200, json.dumps({"phase": "ending", "ending": sess.ending()}, ensure_ascii=False))
        try:
            st = sess.next_stage()
        except Exception as e:
            return self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        _rank_save(body.get("sid"), sess)
        _spawn_prefetch(sess)
        if st is None:
            return self._send(200, json.dumps({"phase": "ending", "ending": sess.ending()}, ensure_ascii=False))
        return self._send(200, json.dumps({"stage": st}, ensure_ascii=False))

    def _handle_rank_reorder(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        sess.reorder(body.get("order", []))
        _rank_save(body.get("sid"), sess)
        _spawn_prefetch(sess)  # reorder changes #1 → warm the new top's next stage
        order = sess.current_order()
        return self._send(200, json.dumps({"order": order, "top": order[0] if order else ""}, ensure_ascii=False))

    def _handle_rank_profile(self, body):
        """Live profile edit (free_text) — feeds the NEXT stage's generation."""
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        if body.get("narrative") is not None:
            sess.profile.narrative = str(body["narrative"])[:2000]
        if body.get("free_text") is not None:
            sess.profile.free_text = str(body["free_text"])[:600]
        # profile changed → the pending stage must regenerate on the new profile:
        # drop its prefetch cache + WTE pick so it re-picks + re-investigates, then re-warm.
        try:
            sess._prefetch = {}
            if hasattr(sess, "_stage_pick") and sess._stage_pick:
                sess._stage_pick.pop(sess.stage, None)
        except Exception:
            pass
        _rank_save(body.get("sid"), sess)
        _spawn_prefetch(sess)
        return self._send(200, json.dumps({"ok": True, "profile": sess.profile.serialize_for_prompt()}, ensure_ascii=False))

    def _handle_rank_translate(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        from core.ranked import translate_major
        top = sess.current_order()[0] if sess.current_order() else ""
        try:
            t = translate_major(top)
        except Exception as e:
            return self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return self._send(200, json.dumps({"major": top, **t}, ensure_ascii=False))

    def _handle_rank_replay(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}, ensure_ascii=False))
        sess.replay()
        try:
            stage = sess.next_stage()
        except Exception as e:
            return self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        _rank_save(body.get("sid"), sess)
        _spawn_prefetch(sess)
        return self._send(200, json.dumps({"stage": stage, "confidence_initial": sess.confidence_initial}, ensure_ascii=False))

    def _handle_rank_report(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}, ensure_ascii=False))
        from core.ranked import user_report
        rep = user_report(sess.profile, sess.current_order())
        _log_session({"event": "report", "sid": body.get("sid"), "len": len(rep), "report": rep})
        return self._send(200, json.dumps({"report": rep}, ensure_ascii=False))

    def _handle_intake_chat(self, body):
        msg = str(body.get("message", "")).strip()[:1000]
        if not msg:
            return self._send(400, json.dumps({"error": "empty"}, ensure_ascii=False))
        from core.ranked import intake_chat_reply
        reply = intake_chat_reply(body.get("page", ""), body.get("state") or {}, body.get("history") or [], msg)
        return self._send(200, json.dumps({"reply": reply}, ensure_ascii=False))

    def _handle_rank_chat(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}, ensure_ascii=False))
        msg = str(body.get("message", "")).strip()[:1000]
        if not msg:
            return self._send(400, json.dumps({"error": "empty"}, ensure_ascii=False))
        from core.ranked import chat_reply, update_narrative
        pend = getattr(sess, "_pending", {}) or {}
        top = pend.get("top") or (sess.current_order()[0] if sess.current_order() else "")
        contender = pend.get("contender", ""); scene = (pend.get("factor") or {}).get("label", "")
        ctx = body.get("ctx", "scene")
        cap = 5 if ctx == "end" else 3
        ckey = "end" if ctx == "end" else ("scene:" + str(pend.get("stage")))
        if not hasattr(sess, "chat_counts") or sess.chat_counts is None: sess.chat_counts = {}
        used = sess.chat_counts.get(ckey, 0)
        if used >= cap:   # anti token-burn + keep it from getting distracting
            return self._send(200, json.dumps({"error": "limit", "turns_left": 0, "reply": ""}, ensure_ascii=False))
        sess.chat_counts[ckey] = used + 1
        if not hasattr(sess, "chat") or sess.chat is None: sess.chat = []
        sess.chat.append(("h", msg))
        reply = chat_reply(sess.profile, top, contender, sess.chat, msg)
        if reply: sess.chat.append(("a", reply))
        narrative = update_narrative(sess.profile, pend.get("stage"), scene, "(chat)", msg)
        _rank_save(body.get("sid"), sess)
        _log_session({"event": "chat", "sid": body.get("sid"), "stage": pend.get("stage"), "msg": msg, "reply": reply})
        return self._send(200, json.dumps({"reply": reply, "narrative": narrative, "turns_left": cap - sess.chat_counts[ckey]}, ensure_ascii=False))

    def _handle_rank_elicit(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}, ensure_ascii=False))
        ans = str(body.get("answer", "")).strip()[:1000]
        if not ans:
            return self._send(400, json.dumps({"error": "empty"}, ensure_ascii=False))
        from core.ranked import update_narrative
        stg, scene, q = body.get("stage"), str(body.get("scene", "")), str(body.get("q", ""))
        if not hasattr(sess.profile, "elicited") or sess.profile.elicited is None:
            sess.profile.elicited = []
        sess.profile.elicited.append({"stage": stg, "scene": scene, "q": q, "a": ans})
        narrative = update_narrative(sess.profile, stg, scene, q, ans)
        _rank_save(body.get("sid"), sess)
        _log_session({"event": "elicit", "sid": body.get("sid"), "stage": stg, "scene": scene, "q": q, "a": ans})
        return self._send(200, json.dumps({"narrative": narrative}, ensure_ascii=False))

    def _handle_rank_feedback(self, body):
        sess = self._rank(body.get("sid"))
        fb = str(body.get("feedback", "")).strip()
        if not fb:
            return self._send(400, json.dumps({"error": "empty feedback"}, ensure_ascii=False))
        _log_session({"event": "feedback", "sid": body.get("sid"), "feedback": fb[:4000],
                      "order": sess.current_order() if sess else None})
        return self._send(200, json.dumps({"ok": True}, ensure_ascii=False))

    def _handle_rank_frametest(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        from core.ranked import frame_test
        top = sess.current_order()[0] if sess.current_order() else ""
        try:
            ft = frame_test(top, sess.profile.serialize_for_prompt(), getattr(sess, 'lang', 'cn'))
        except Exception as e:
            return self._send(200, json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return self._send(200, json.dumps({"top": top, **ft}, ensure_ascii=False))

    def _handle_rank_end(self, body):
        sess = self._rank(body.get("sid"))
        if not sess:
            return self._send(404, json.dumps({"error": "no session"}))
        sess.confidence_final = int(body.get("confidence_final", 0))
        try:
            sess.checklist_done = list(body.get("checklist", []))
        except Exception:
            pass
        try:
            sess.frame_results = list(body.get("frame_results", []) or [])
        except Exception:
            pass
        _rank_save(body.get("sid"), sess)
        try:
            steps = [{"stage": h.get("stage"), "factor": (h.get("factor") or {}).get("label"),
                      "top": h.get("top"), "contender": h.get("contender"),
                      "top_take": h.get("top_take"), "contender_take": h.get("contender_take"),
                      "did_you_know": h.get("did_you_know"), "sources": h.get("sources")}
                     for h in sess.history]
            _log_session({"event": "end", "sid": body.get("sid"),
                          "narrative": getattr(sess.profile, "narrative", ""),
                          "wte_ledger": getattr(sess, "_wte_ledger", []),
                          "free_text": getattr(sess.profile, "free_text", ""),
                          "destination_pref": getattr(sess.profile, "destination_pref", []),
                          "initial_order": sess.initial_order, "final_order": sess.current_order(),
                          "top_changed": sess.initial_order[:1] != sess.current_order()[:1],
                          "n_reranks": len(sess.rerank_log), "rerank_log": sess.rerank_log,
                          "confidence_initial": sess.confidence_initial, "confidence_final": sess.confidence_final,
                          "conf_traj": getattr(sess, "conf_traj", []),
                          "frame_results": [{"frame": f.get("frame"), "bias": f.get("bias"), "swayed": f.get("swayed")} for f in sess.frame_results],
                          "checklist_done": getattr(sess, "checklist_done", []),
                          "free_text": sess.profile.free_text, "steps": steps})
        except Exception:
            pass
        return self._send(200, json.dumps({"ending": sess.ending()}, ensure_ascii=False))

    def do_POST(self):
        try:
            _clen = int(self.headers.get("Content-Length", "0") or "0")
        except Exception:
            _clen = 0
        _cap = 16 * 1024 * 1024 if self.path.split("?")[0] == "/voice_profile" else 2 * 1024 * 1024
        if _clen > _cap:
            return self._send(413, json.dumps({"error": "payload too large"}))
        if _API_KEYS:                                  # yulai/雨来 deployment: require a Bearer API key
            _a = self.headers.get("Authorization", "")
            if (_a[7:] if _a.startswith("Bearer ") else "") not in _API_KEYS:
                return self._send(401, json.dumps({"error": "unauthorized"}, ensure_ascii=False))
        if self.path in ("/prompts_save", "/prompts_reset") and not self._admin_ok():
            return self._send(403, json.dumps({"error": "forbidden"}))
        if self.path == "/resolve_options":
            n = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send(200, json.dumps({"results": [], "error": "bad json"}, ensure_ascii=False))
            try:
                from core import resolve
                return self._send(200, json.dumps({"results": resolve.resolve_options(body.get("options") or [])}, ensure_ascii=False))
            except Exception as e:
                # fail-open: empty results -> frontend proceeds with raw input
                return self._send(200, json.dumps({"results": [], "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        if self.path in ("/prompts_save", "/prompts_reset"):
            n = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send(400, json.dumps({"error": "bad json"}))
            from core import prompts as _pr
            try:
                if self.path == "/prompts_save":
                    _pr.save(body["key"], body["template"])
                else:
                    _pr.reset(body["key"])
                return self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
            except Exception as e:
                return self._send(400, json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        if self.path.split("?")[0] == "/voice_profile":
            return self._handle_voice()
        if self.path in ("/ig_start", "/ig_choose", "/ig_profile"):
            n = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send(400, json.dumps({"error": "bad json"}))
            if self.path == "/ig_start": return self._handle_ig_start(body)
            if self.path == "/ig_profile": return self._handle_ig_profile(body)
            return self._handle_ig_choose(body)
        if self.path in ("/rank_start", "/rank_next", "/rank_reorder", "/rank_end", "/rank_translate", "/rank_frametest", "/rank_profile", "/rank_feedback", "/rank_replay", "/rank_elicit", "/rank_report", "/rank_chat", "/intake_chat"):
            n = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send(400, json.dumps({"error": "bad json"}))
            if self.path == "/rank_start": return self._handle_rank_start(body)
            if self.path == "/rank_next": return self._handle_rank_next(body)
            if self.path == "/rank_reorder": return self._handle_rank_reorder(body)
            if self.path == "/rank_translate": return self._handle_rank_translate(body)
            if self.path == "/rank_frametest": return self._handle_rank_frametest(body)
            if self.path == "/rank_profile": return self._handle_rank_profile(body)
            if self.path == "/rank_feedback": return self._handle_rank_feedback(body)
            if self.path == "/rank_replay": return self._handle_rank_replay(body)
            if self.path == "/rank_elicit": return self._handle_rank_elicit(body)
            if self.path == "/rank_chat": return self._handle_rank_chat(body)
            if self.path == "/intake_chat": return self._handle_intake_chat(body)
            if self.path == "/rank_report": return self._handle_rank_report(body)
            return self._handle_rank_end(body)
        if self.path != "/start":
            return self._send(404, json.dumps({"error": "not found"}))
        n = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, json.dumps({"error": "bad json"}))
        jid = uuid.uuid4().hex[:10]
        with _LOCK:
            JOBS[jid] = {"events": [], "result": None, "error": None}
        threading.Thread(target=_run_job, args=(jid, payload), daemon=True).start()
        self._send(200, json.dumps({"job": jid}))
    def log_message(self, *a): pass

_PAGE = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>高考志愿 · 两种人生</title>
<link rel=preconnect href="https://fonts.googleapis.com"><link rel=preconnect href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Caveat:wght@600;700&family=Patrick+Hand&family=Noto+Sans+SC:wght@400;500;700&display=swap" rel=stylesheet>
<script src="https://cdn.jsdelivr.net/npm/roughjs@4.6.6/bundled/rough.min.js"></script><style>
:root{--bg:#FBF6EA;--paper:#FFFDF4;--ink:#2A2218;--soft:#6B6151;--faint:#B0A48E;--green:#53984F;--blue:#3873A8;--red:#C44536;--terra:#BC6242;--blueL:#DCEAF5;--greenL:#DDEEDA}
*{box-sizing:border-box}
body{font-family:"Patrick Hand","Noto Sans SC",system-ui,sans-serif;max-width:780px;margin:1.2rem auto;padding:0 1rem;line-height:1.55;color:var(--ink);background:var(--bg);font-size:18px;-webkit-font-smoothing:antialiased}
h1{font-family:"Caveat","Noto Sans SC",cursive;font-size:2.1rem;margin:.1rem 0 .3rem}
label{display:block;margin:.6rem 0 .2rem;font-size:.95rem;color:var(--soft)}
input[type=text],textarea,select{width:100%;box-sizing:border-box;padding:.55rem;border:1.5px solid var(--faint);border-radius:10px;background:var(--paper);color:var(--ink);font-family:"Noto Sans SC",inherit;font-size:1rem}
.axis{display:flex;align-items:center;gap:.6rem;font-size:.9rem;margin:.3rem 0}
.axis input[type=range]{flex:1;accent-color:var(--terra)}.axis span{flex:0 0 auto;color:var(--soft);font-size:.82rem}
button{margin-top:.6rem;padding:.5rem 1rem;border:2px solid var(--ink);border-radius:14px;background:var(--green);color:#fff;font-family:"Noto Sans SC",inherit;font-size:1rem;cursor:pointer;box-shadow:2px 2px 0 var(--ink);transition:transform .08s,box-shadow .08s}
button:hover{transform:translate(-1px,-1px);box-shadow:3px 3px 0 var(--ink)}
button:active{transform:translate(1px,1px);box-shadow:1px 1px 0 var(--ink)}
.life,.mirror{background:var(--paper);border:2px solid var(--ink);border-radius:16px;padding:.9rem 1rem;margin:.7rem 0;box-shadow:3px 3px 0 rgba(42,34,24,.12)}
.life{border-left:6px solid var(--terra)}
.mirror{background:#FCF7E8}.mirror>div{white-space:pre-wrap}
.stage{margin:.5rem 0;font-size:1.05rem;color:var(--ink)}
.igopt{display:block;width:100%;text-align:left;margin:.45rem 0;background:var(--paper);color:var(--ink);border:2px solid var(--soft);border-radius:12px;box-shadow:2px 2px 0 var(--faint);padding:.55rem .8rem}
.igopt:hover{background:var(--blueL);border-color:var(--blue)}
#startBtn{background:var(--terra);font-size:1.1rem;padding:.6rem 1.2rem}
.acc{background:var(--green)}
#prog{color:var(--soft);font-family:"Caveat","Noto Sans SC",cursive;font-size:1.15rem}
.muted{color:var(--soft);font-size:.85rem}
#tree{filter:saturate(1.05)}
</style></head><body>
<h1>两种人生 — 帮你倒推现在的选择</h1>
<p class=muted>填两个你在纠结的志愿,简单描述你自己,再用滑块标出你的价值取向。我们会让你<b>分别活过</b>两种未来,再从你的选择里照见你真正在乎的东西 —— 这是一面镜子,不替你做决定。</p>
<div id=intakeOnly>
<label>选项 A(例:顶尖985 + 调剂的材料工程)</label><input id=optA type=text value="顶尖985 + 调剂材料工程(不喜欢)">
<label>选项 B(例:普通一本 + 心仪的数字媒体艺术)</label><input id=optB type=text value="普通一本 + 心仪的数字媒体艺术">
<label>你纠结的是哪一类两难?</label>
<select id=arch style="width:100%;padding:.5rem;border:1px solid #ccc;border-radius:6px">
<option value=prestige_vs_major>名校光环 vs 核心专业</option>
<option value=city_vs_tier>地域红利 vs 院校层级</option>
<option value=passion_vs_bread>理想热爱 vs 现实面包</option>
<option value=reach_vs_safe>放手一搏 vs 稳妥保底</option>
<option value=system_vs_market>一眼望到头 vs 充满未知</option>
</select>
</div>
<div id=profilePanel style="border:2px dashed var(--blue);border-radius:16px;padding:.7rem;margin:.7rem 0;background:var(--paper);box-shadow:3px 3px 0 rgba(56,115,168,.12)">
<div class=muted style="margin-bottom:.3rem"><b>🪞 你和 AI 共同理解的你</b> —— 每一幕都基于这个画像。随时可以改、或重新语音;更新后,下一幕就会用上。</div>
<textarea id=ft rows=3 style="width:100%;box-sizing:border-box;padding:.5rem;border:1px solid #ccc;border-radius:6px">从小喜欢画画讲故事,家里希望读稳定专业,怕选错后悔</textarea>
<div style="margin:.4rem 0"><button type=button id=voiceBtn onclick=toggleRec() style="background:var(--soft)">🎙 语音描述(约1分钟)</button> <span id=voiceStatus class=muted></span> <button type=button id=updBtn onclick=updateProfile() style="display:none;background:var(--blue)">✓ 更新画像</button></div>
<div id=profileBox></div>
<div id=axes></div>
</div>
<button id=startBtn onclick=startIG()>开始推演 ▷ 一步步走你的两种人生</button>
<canvas id=tree width=720 height=430 style="max-width:100%;width:100%;margin:.6rem 0;display:none;border:2px solid var(--ink);border-radius:16px;background:var(--paper);box-shadow:3px 3px 0 rgba(42,34,24,.12)"></canvas>
<div id=out></div>
<script>
const AXES=%AXES%;
const ax=document.getElementById('axes');
AXES.forEach((a,i)=>{ax.insertAdjacentHTML('beforeend',
 `<div class=axis><span>${a[1]}</span><input type=range min=-1 max=1 step=.25 value=0 id=s${i}><span>${a[0]}</span> <span class=muted>${a[2]}</span></div>`)});
let IGSID=null, CURSIDE='A', OPT_A='', OPT_B='';
let PROG={A:0,B:0,cap:4,side:'A',stage:0};
const STAGE_LABELS=['大一','大二','大三','毕业','工作','回望'];
function wrapText(ctx,txt,x,y,maxW,lh,maxLines){
 const chars=[...(txt||'')]; let line='',ly=y,lines=0;
 for(let i=0;i<chars.length;i++){ const t=line+chars[i];
   if(ctx.measureText(t).width>maxW){ ctx.fillText(line,x,ly); line=chars[i]; ly+=lh; lines++;
     if(maxLines&&lines>=maxLines-1){ // last line: clip with ellipsis
       let rest=chars.slice(i).join(''); while(ctx.measureText(rest+'…').width>maxW&&rest.length>1)rest=rest.slice(0,-1);
       ctx.fillText(rest+'…',x,ly); return ly+lh; } }
   else line=t; }
 ctx.fillText(line,x,ly); return ly+lh;
}
let SCENE={prose:'',side:'A',stage:0,q:''};
function drawTree(){ drawScene(); }
function drawScene(){
 const cv=document.getElementById('tree'); if(!cv)return; cv.style.display='block';
 const W=720,H=430,dpr=window.devicePixelRatio||1;
 const cssW=cv.clientWidth||W, cssH=cssW*H/W; cv.style.height=cssH+'px';
 const bw=Math.round(cssW*dpr), bh=Math.round(cssH*dpr);
 if(cv.width!==bw||cv.height!==bh){cv.width=bw;cv.height=bh;}
 const ctx=cv.getContext('2d');
 const sc=(cssW/W)*dpr; ctx.setTransform(sc,0,0,sc,0,0); ctx.clearRect(0,0,W,H);
 const RG=window.rough?rough.canvas(cv):null;
 const rc={line:(a,b,c,d,o)=>{o=o||{};if(RG)RG.line(a,b,c,d,o);else{ctx.strokeStyle=o.stroke||'#888';ctx.beginPath();ctx.moveTo(a,b);ctx.lineTo(c,d);ctx.stroke();}},circle:(x,y,dia,o)=>{o=o||{};if(RG)RG.circle(x,y,dia,o);else{ctx.strokeStyle=o.stroke||'#888';ctx.fillStyle=o.fill||'#fff';ctx.beginPath();ctx.arc(x,y,dia/2,0,7);ctx.fill();ctx.stroke();}},rectangle:(x,y,w,h,o)=>{o=o||{};if(RG)RG.rectangle(x,y,w,h,o);else{ctx.strokeStyle=o.stroke||'#888';ctx.fillStyle=o.fill||'#fff';ctx.fillRect(x,y,w,h);ctx.strokeRect(x,y,w,h);}}};
 // --- top: the two-path journey with fog ---
 const n=PROG.cap,x0=80,x1=W-30;
 [['A',34,'#BC6242',OPT_A],['B',82,'#3873A8',OPT_B]].forEach(([side,y,col,opt])=>{
   ctx.fillStyle='#2A2218'; ctx.font='bold 13px "Noto Sans SC",sans-serif'; ctx.textAlign='left';
   ctx.fillText('人生'+side,8,y-4); ctx.fillStyle='#6B6151'; ctx.font='10px "Noto Sans SC"';
   {const l=(opt||'');ctx.fillText(l.length>8?l.slice(0,8)+'…':l,8,y+9);}
   for(let i=0;i<n;i++){ const x=x0+(x1-x0)*(n<2?0:i/(n-1));
     const done=PROG[side]>i, cur=(PROG.side===side&&PROG[side]===i&&PROG.stage>0);
     if(i>0){const px=x0+(x1-x0)*((i-1)/(n-1));
       rc.line(px+8,y,x-8,y,{stroke:done?col:'#D8CFBE',strokeWidth:done?2.5:1,strokeLineDash:done?[]:[4,4],roughness:1.3});}
     rc.circle(x,y,cur?22:15,{stroke:cur?'#C44536':(done?col:'#C9BFAC'),strokeWidth:cur?3:1.5,
       fill:done?col:'#FFFDF4',fillStyle:'solid',roughness:1.5});
   }
 });
 ctx.fillStyle='#B0A48E'; ctx.font='10px "Noto Sans SC"'; ctx.textAlign='right'; ctx.fillText('迷雾随你走过而散开 →',x1,18); ctx.textAlign='left';
 // --- middle: hand-drawn scene card ---
 const cx=24,cy=120,cw=W-48,ch=H-150;
 rc.rectangle(cx,cy,cw,ch,{stroke:'#2A2218',strokeWidth:2,fill:'#FFFEF8',fillStyle:'solid',roughness:1.6,bowing:1.5});
 const lab=(SCENE.side==='A'?'人生 A':'人生 B')+' · 第 '+SCENE.stage+' 幕';
 ctx.fillStyle=(SCENE.side==='A'?'#BC6242':'#3873A8'); ctx.font='bold 14px "Noto Sans SC"'; ctx.fillText(lab,cx+22,cy+30);
 ctx.fillStyle='#2A2218'; ctx.font='16px "Noto Sans SC",sans-serif';
 const endY=wrapText(ctx,SCENE.prose,cx+22,cy+58,cw-44,25,Math.floor((ch-90)/25));
 ctx.fillStyle='#6B6151'; ctx.font='italic 15px "Noto Sans SC"'; ctx.fillText('假如是你,你怎么办? ↓',cx+22,cy+ch-18);
}
async function startIG(){
 const sliders=AXES.map((_,i)=>+document.getElementById('s'+i).value);
 const body={option_A:{label:optA.value},option_B:{label:optB.value},free_text:ft.value,
   sliders,archetype_key:document.getElementById('arch').value,cap:4};
 document.getElementById('intakeOnly').style.display='none'; document.getElementById('startBtn').style.display='none'; document.getElementById('updBtn').style.display='inline-block';
 out.innerHTML='<p id=prog class=muted>正在展开你的第一条人生…(每一步约 20 秒)</p><div id=stageBox></div>';
 try{ const r=await fetch('/ig_start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   const d=await r.json(); if(d.error){prog.textContent='出错:'+d.error;return;}
   IGSID=d.sid; OPT_A=optA.value||'选项A'; OPT_B=optB.value||'选项B'; PROG={A:0,B:0,cap:(body.cap||4),side:'A',stage:0}; renderStage(d.stage,null);
 }catch(e){ prog.textContent='网络错误:'+e.message; }
}
async function updateProfile(){
 if(!IGSID){ return; }
 const sliders=AXES.map((_,i)=>+document.getElementById('s'+i).value);
 const st=document.getElementById('voiceStatus');
 try{ await fetch('/ig_profile',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({sid:IGSID,free_text:document.getElementById('ft').value,sliders})});
   st.textContent='✓ 画像已更新,下一幕会用上'; setTimeout(()=>{st.textContent='';},2500);
 }catch(e){ st.textContent='更新失败:'+e.message; }
}
function lifeName(s){return (s==='A'?'人生 A · ':'人生 B · ')+(s==='A'?OPT_A:OPT_B);}
function renderStage(stage, switchTo){
 if(!stage){return;}
 CURSIDE=stage.side; prog.textContent=''; PROG.side=stage.side; PROG.stage=stage.stage;
 SCENE={prose:stage.prose,side:stage.side,stage:stage.stage}; drawScene();
 const sb=document.getElementById('stageBox');
 const head=switchTo?`<div class=mirror style="margin:.6rem 0;border-color:var(--terra)"><b>这条路走完了。现在,换一种人生 —— 假如你当初选了另一个。</b></div>`:'';
 sb.innerHTML=head+stage.options.map((o,i)=>`<button class=igopt onclick=choose(${i})>${o.label}</button>`).join('');
}
async function choose(idx){
 PROG[CURSIDE]=Math.max(PROG[CURSIDE],PROG.stage); drawTree();
 document.querySelectorAll('.igopt').forEach(b=>b.disabled=true);
 prog.textContent='…(生成下一步,约 20 秒)';
 try{ const r=await fetch('/ig_choose',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({sid:IGSID,side:CURSIDE,idx})});
   const d=await r.json();
   if(d.error){ prog.innerHTML=(d.error.indexOf('session')>=0?'会话丢失了(服务可能刚更新)。':('出错:'+d.error))+' <button onclick=location.reload()>重新开始</button>'; return; }
   if(d.phase==='ending'){ renderEnding(d.ending); return; }
   renderStage(d.stage, d.switch||null);
 }catch(e){ prog.textContent='网络错误:'+e.message; }
}
let ACCEPTED={};
function renderEnding(end){
 PROG.A=PROG.cap;PROG.B=PROG.cap;PROG.stage=0;drawTree();
 const sb=document.getElementById('stageBox');
 const core=(end.revealed_core||[]).map(c=>c.dim+'→'+c.leaning).join(' · ')||'(暂不明显)';
 let html='<div class=mirror><b>两种人生你都走过了。在做出最终选择之前 —— 你愿意承担每条路的代价吗?</b></div>';
 const pc=end.path_costs||{};
 ['A','B'].forEach(side=>{ const p=pc[side]||{};
   html+=`<div class=life><b>${lifeName(side)}:${p.option||''}</b>`
    +`<div class=muted>这条路的代价:${p.cost||'—'}</div>`
    +`<div class=muted>最坏的时候:${p.worst_case||'—'}</div>`
    +`<div><button class=acc onclick="accept('${side}')" id=acc${side} class=acc style="margin:.3rem 0">我能接受,我不后悔</button> <span id=accs${side} class=muted></span></div></div>`;
 });
 html+=`<div id=equil></div>`;
 html+=`<div class=mirror style="margin-top:.6rem"><b>这面镜子照见的你(不是答案,是一个供你核对的假设):</b><div style="margin:.3rem 0">你反复坚持的:<b>${core}</b></div><div style="white-space:pre-wrap">${end.mirror||''}</div></div>`;
 sb.innerHTML=html;
}
function accept(side){
 ACCEPTED[side]=true;
 document.getElementById('acc'+side).disabled=true;
 document.getElementById('accs'+side).textContent='✓ 已接受';
 if(ACCEPTED.A&&ACCEPTED.B){ document.getElementById('equil').innerHTML=
   '<div class=mirror style="border:3px solid var(--green)"><b>反思均衡达成。</b>你不只是想要某个结果 —— 你已经看过两条路的代价,并且愿意承担。现在的选择,是你自己走出来的。</div>'; }
}

let mediaRec=null, chunks=[], recording=false;
async function toggleRec(){
 const btn=document.getElementById('voiceBtn'), st=document.getElementById('voiceStatus');
 if(!recording){
   try{ const stream=await navigator.mediaDevices.getUserMedia({audio:true});
     mediaRec=new MediaRecorder(stream); chunks=[];
     mediaRec.ondataavailable=e=>chunks.push(e.data);
     mediaRec.onstop=async()=>{ stream.getTracks().forEach(t=>t.stop()); await sendVoice(new Blob(chunks,{type:'audio/webm'})); };
     mediaRec.start(); recording=true; btn.textContent='⏹ 停止并识别'; st.textContent='录音中…说说你是谁、在纠结什么';
   }catch(e){ st.textContent='无法录音(权限/设备):'+e.message; }
 } else { recording=false; btn.textContent='🎙 语音描述(可选)'; st.textContent='识别中…'; mediaRec.stop(); }
}
async function sendVoice(blob){
 const st=document.getElementById('voiceStatus');
 try{
   const r=await fetch('/voice_profile',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:blob});
   const d=await r.json();
   if(d.error){ st.textContent=d.error; return; }
   document.getElementById('ft').value=d.summary||d.transcript||'';   // editable summary
   // pre-fill sliders from the AI vector (user can still adjust)
   if(d.sliders) AXES.forEach((a,i)=>{ const pos=a[0],neg=a[1];
     let v=0; if(d.sliders[pos]!=null)v=d.sliders[pos]; else if(d.sliders[neg]!=null)v=-d.sliders[neg];
     document.getElementById('s'+i).value=Math.max(-1,Math.min(1,v)); });
   const pb=document.getElementById('profileBox');
   pb.innerHTML='<div class=mirror style="font-size:.85rem"><b>AI 听到的画像(可自由修改上面的文字和滑块):</b>'
     +'<div style="margin:.3rem 0">标签:'+((d.tags||[]).join(' · ')||'—')+'</div>'
     +(d.justifications||[]).map(j=>`<div class=muted>· ${j.dim}:「${(j.quote||'').slice(0,24)}」→ ${(j.reading||'').slice(0,40)}</div>`).join('')
     +'<div class=muted style="margin-top:.3rem">对了就直接开始,不对就改文字/拖滑块。</div></div>';
   st.textContent='✓ 识别完成,请核对';
 }catch(e){ st.textContent='识别失败:'+e.message; }
}
async function start(){
 const sliders=AXES.map((_,i)=>+document.getElementById('s'+i).value);
 const body={option_A:{label:optA.value},option_B:{label:optB.value},free_text:ft.value,sliders,cap:5};
 document.getElementById('intakeOnly').style.display='none'; document.getElementById('startBtn').style.display='none'; document.getElementById('updBtn').style.display='inline-block';
 out.innerHTML='<p id=prog>正在生成你的两种人生…(约 2 分钟,请稍候)</p><div id=ev></div>';
 const r=await fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const {job}=await r.json(); poll(job);
}
async function poll(job){
 const r=await fetch('/status?job='+job); const j=await r.json();
 if(j.error){prog.textContent='出错了:'+j.error;return;}
 ev.innerHTML=['A','B'].map(L=>`<div class=life><b>人生 ${L}</b>`+
   j.events.filter(e=>e.life==L).map(e=>`<div class=stage>阶段${e.stage}:${e.prose.slice(0,120)}…<br><span class=muted>选了:${e.options[e.picked].label}</span></div>`).join('')+`</div>`).join('');
 if(j.result){
   prog.textContent='完成。';
   const core=(j.result.revealed_core||[]).map(c=>c.dim+'→'+c.leaning).join(' · ')||'(暂不明显)';
   out.insertAdjacentHTML('beforeend',`<p class=muted>你跨两种人生反复坚持的:<b>${core}</b></p><div class=mirror>${(j.result.mirror||'')}</div>`);
   return;
 }
 setTimeout(()=>poll(job),3000);
}
</script></body></html>"""
_RANK_PAGE = open(os.path.join(os.path.dirname(__file__), "rank_page.html"), encoding="utf-8").read()
_PROMPTS_PAGE = open(os.path.join(os.path.dirname(__file__), "prompts_editor.html"), encoding="utf-8").read()
_LOADING_PREVIEW = open(os.path.join(os.path.dirname(__file__), "loading_preview.html"), encoding="utf-8").read()
_PAGE = _PAGE.replace("%AXES%", json.dumps(AXES, ensure_ascii=False))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=9930)
    a = ap.parse_args()
    print(f"[gaokao.web] http://{a.host}:{a.port}  (key={'set' if os.environ.get('OPENROUTER_API_KEY') else 'MISSING'})")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()

if __name__ == "__main__":
    main()
