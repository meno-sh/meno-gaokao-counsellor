"""Voice intake -> Whisper STT -> LLM auto-profile (Yuhe's idea; ZH-approved).

Flow: 1-min recording -> OpenAI Whisper transcription -> one LLM call that maps
the transcript onto the invariant 8-dim spine (the measurement) + tags + an
EDITABLE natural-language summary + per-dim quote-backed justifications. The UI
shows the summary + pre-filled sliders for the user to freely modify and verify
BEFORE any trajectory runs (relevance-not-affirmation; verbal-in/verify). The
transcript is kept (also reused as grounding for the generator).
"""
from __future__ import annotations
import json, os, uuid, urllib.request, tempfile
from human_modeling.personality import DIMENSIONS

_POLES = [p for pair in DIMENSIONS for p in pair]
TRANSCRIPT_DIR = os.path.join(os.environ.get("GAOKAO_DATA_DIR", "/data/reflection-game/gaokao-data"), "voice_transcripts")

def transcribe(audio_bytes: bytes, filename: str = "rec.webm", language: str = "zh", model: str | None = None) -> str:
    """OpenAI Whisper transcription. Returns the transcript text."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    boundary = "----rgvoice" + uuid.uuid4().hex
    def part(name, value):
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    def _sniff_ext(a):
        if a[:4] == b"RIFF": return "wav"
        if a[:4] == b"OggS": return "ogg"
        if a[:3] == b"ID3" or a[:2] == b"\xff\xfb": return "mp3"
        if a[:4] == b"\x1aE\xdf\xa3": return "webm"   # EBML (webm/mkv) — Chrome/Firefox MediaRecorder
        if a[4:8] == b"ftyp": return "mp4"   # Safari MediaRecorder → mp4/m4a (was mislabeled webm → STT failed)
        return "webm"
    ext = _sniff_ext(audio_bytes)
    filename = f"rec.{ext}"
    _ctype = {"wav": "audio/wav", "ogg": "audio/ogg", "mp3": "audio/mpeg", "webm": "audio/webm", "mp4": "audio/mp4"}.get(ext, "application/octet-stream")
    model = model or os.environ.get("VOICE_STT_MODEL", "gpt-4o-mini-transcribe")  # faster than whisper-1
    body = part("model", model) + part("language", language) + part("response_format", "json")
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
             f'Content-Type: {_ctype}\r\n\r\n').encode() + audio_bytes + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("text", "").strip()  # json works for whisper-1 AND gpt-4o-mini-transcribe

def _llm_json(prompt, max_tokens=8000):
    key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "response_format": {"type": "json_object"}, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
        return json.loads(msg.get("content") or "{}")

def profile_from_transcript(transcript: str) -> dict:
    """Map a transcript onto the 8-dim spine + editable summary + tags + quote-
    backed justifications. The spine is the measurement; tags/summary are the
    relatable surface. Steers relevance, never tells the user an option is right."""
    rubric = "\n".join(f"  {a} <-> {b}" for a, b in DIMENSIONS)
    prompt = (
        "你是一个把口述自我介绍映射成价值取向画像的助手 —— 只用于让题目更贴合这个人,"
        "*绝不*用来判断 ta 该选哪个。下面是一个学生(纠结高考志愿)的1分钟口述转写。\n\n"
        f"口述转写:\n{transcript}\n\n"
        f"把 ta 映射到这8个价值维度(每个轴 -1..1,正=前者,负=后者):\n{rubric}\n\n"
        "只返回一个 JSON 对象:\n"
        '{"sliders": {"SELF": 0.7, "VOICE": 0.5, "...": "键必须是上面某个轴的极名(如 SELF/OTHER/VOICE/SILENCE/PROCESS/OUTCOME/NOW/LATER/TRUTH/PROTECTION/PRINCIPLE/LOYALTY/AGENCY/OBSERVATION/RIGOR/MERCY),值-1..1,正=该极名方向;一个轴只给一个极名"}, '
        '"tags": ["<3-6个贴合的关键词标签>"], '
        '"summary": "<一段第二人称、可编辑的自我画像,80-150字,用 ta 自己的话回映,'
        '让 ta 能一眼看出对不对、好修改>", '
        '"justifications": [{"dim": "<轴>", "quote": "<转写里的原话片段>", "reading": "<你的解读>"}, ...最多5条]}\n'
        "要求:summary 用'你'开头,贴着原话,不下结论不推荐;justifications 的 quote 必须是转写里真实出现的话。")
    out = _llm_json(prompt)
    out["sliders"] = _normalize_sliders(out.get("sliders"), out.get("justifications"))
    return out


def extract_intake_from_transcript(transcript: str) -> dict:
    """Parse a spoken self-intro into the 志愿 intake form (candidates + weights +
    confidence + destination), so the whole landing form can be replaced by one
    voice input. Best-effort; the client shows a light confirm screen over this."""
    prompt = (
        "下面是一个考生关于高考志愿的口述转写。请抽取他做志愿决策需要的输入。\n\n"
        f"口述:\n{transcript}\n\n"
        "只返回一个 JSON:\n"
        '{"candidates": ["专业@学校", ...], '
        '"confidence_initial": 50, '
        '"value_weights": {"money": 33, "interest": 34, "influence": 33}, '
        '"destination_pref": ["还没想好"], '
        '"free_text": "<值得保留的自述,一两句>"}\n'
        "说明:candidates = 他在纠结的候选(2-6个,尽量补成'专业@学校');confidence_initial = 他对第1志愿的确定度(0-100,说不清给50);"
        "value_weights 三者和≈100(说不清给 33/34/33);destination_pref 取 升学/就业/出国/还没想好。"
        "要求:candidates 必须是他真提到的;补全学校/专业别瞎编,不确定就用他的原词。")
    try:
        out = _llm_json(prompt, max_tokens=1500)
    except Exception:
        out = {}
    cands = [str(c).strip() for c in (out.get("candidates") or []) if str(c).strip()]
    resolved = []
    try:
        from core.resolve import resolve_options
        for r in resolve_options(cands):
            resolved.append({"raw": r.get("raw"), "label": r.get("canonical") or r.get("raw"), "status": r.get("status")})
    except Exception:
        resolved = [{"raw": c, "label": c, "status": "unresolved"} for c in cands]
    vw = out.get("value_weights") or {}
    def _i(x, d):
        try: return int(x)
        except Exception: return d
    return {
        "candidates": resolved,
        "confidence_initial": _i(out.get("confidence_initial"), 50),
        "value_weights": {"money": _i(vw.get("money"), 33), "interest": _i(vw.get("interest"), 34), "influence": _i(vw.get("influence"), 33)},
        "destination_pref": out.get("destination_pref") or ["还没想好"],
        "free_text": (out.get("free_text") or transcript[:200]),
    }

_AXIS_FIRST = {a: (a, b) for a, b in DIMENSIONS}
_AXIS_SECOND = {b: (a, b) for a, b in DIMENSIONS}

def _normalize_sliders(raw, justifications):
    """Accept {pole: v} or {'A <-> B': v} (+>A) and coerce to {pole: v in -1..1}.
    If empty, infer a coarse vector from the justifications' dims."""
    out = {}
    for k, v in (raw or {}).items():
        try: v = float(v)
        except Exception: continue
        v = max(-1.0, min(1.0, v))
        key = str(k).strip()
        if key in _POLES:
            out[key] = v
        elif "<->" in key or "<→" in key:  # axis form
            a = key.split("<")[0].strip()
            if a in _AXIS_FIRST: out[a] = v
    if not out and justifications:  # fallback: coarse vector from justifications
        for j in justifications:
            dim = str(j.get("dim", "")).strip()
            a = dim.split("<")[0].strip() if "<" in dim else dim
            if a in _POLES:
                out[a] = 0.55  # moderate lean toward the named pole
    return out

def save_transcript(session_id: str, transcript: str, profile: dict) -> str:
    """Best-effort persist. Never breaks the voice flow if the target dir is not
    writable (e.g. Render has no /data disk -> Errno 13); falls back to a temp dir."""
    payload = {"session_id": session_id, "transcript": transcript, "profile": profile}
    for d in (TRANSCRIPT_DIR, os.path.join(tempfile.gettempdir(), "gaokao_voice_transcripts")):
        try:
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, f"{session_id}.json")
            with open(path, "w") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            return path
        except Exception:
            continue
    return ""
