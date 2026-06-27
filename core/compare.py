"""Symmetric two-option compare + backward-reasoning ending (高考 variant).

The student lives BOTH futures (one trajectory per option), then we reason
backward from what their *choices across both lives* revealed. The signal is
DETERMINISTIC (no LLM can invent the values): a value the student pushed the
same way in BOTH option-worlds is a revealed core value (context-independent);
one that flipped is context-dependent. The LLM only writes the MIRROR prose —
it reflects those values back, never recommends an option (no-right-answer).
"""
from __future__ import annotations
import json, os, urllib.request
from human_modeling.personality import DIMENSIONS
from core.trajectory import run_trajectory

_PAIRS = list(DIMENSIONS)

def _mean_by_pole(dim_traces):
    acc, cnt = {}, {}
    for dv in dim_traces:
        for pole, v in (dv or {}).items():
            acc[pole] = acc.get(pole, 0.0) + float(v); cnt[pole] = cnt.get(pole, 0) + 1
    return {p: acc[p] / cnt[p] for p in acc}

def cross_life_signal(trace_A, trace_B):
    """Per DIMENSION pair, score the net leaning in each life and classify:
    consistent (same side in both lives -> revealed core value) vs context-
    dependent (flips). Returns sorted list of {dim, poleA_label, net_A, net_B,
    consistent, strength}."""
    mA, mB = _mean_by_pole(trace_A), _mean_by_pole(trace_B)
    out = []
    for a, b in _PAIRS:
        # signed axis value: +a / -b, averaged from whichever pole was tagged
        def axis(m):
            return (m.get(a, 0.0) - m.get(b, 0.0))
        va, vb = axis(mA), axis(mB)
        consistent = (va > 0.05 and vb > 0.05) or (va < -0.05 and vb < -0.05)
        out.append({
            "dim": f"{a}<->{b}",
            "leaning": a if (va + vb) >= 0 else b,
            "net_A": round(va, 2), "net_B": round(vb, 2),
            "consistent": consistent,
            "strength": round((abs(va) + abs(vb)) / 2, 2),
        })
    out.sort(key=lambda d: (-d["consistent"], -d["strength"]))
    return out

def _llm(prompt, max_tokens=4000):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    model = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
        method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
        return msg.get("content") or ""   # content can be null when reasoning eats max_tokens

def backward_reflection(option_A, traj_A, option_B, traj_B, profile, *, use_llm=True):
    """The mirror ending. Deterministic signal + (optional) LLM mirror prose."""
    sig = cross_life_signal(traj_A["dim_trace"], traj_B["dim_trace"])
    core = [s for s in sig if s["consistent"] and s["strength"] >= 0.2][:3]
    flips = [s for s in sig if not s["consistent"] and s["strength"] >= 0.3][:2]
    result = {"signal": sig, "revealed_core": core, "context_dependent": flips, "mirror": None}
    if not use_llm:
        return result
    def choices(traj):
        return "; ".join(t.get("options", [{}])[t.get("picked", 0)].get("label", "")
                         for t in traj["turns"] if "options" in t)
    prompt = (
        "你是一个反思的镜子,不是建议者。下面是一个学生在两种人生里(各自由一个高考志愿选择展开)"
        "所做的选择。请用简体中文写一段克制的、第二人称的反思,镜映出 ta 反复在坚持的价值取向 ——"
        "**绝对不要推荐 ta 选哪个选项,也不要说哪条路更好**。把它写成一个'供 ta 自己核对的假设',"
        "而不是结论。\n\n"
        f"【人生 A:{option_A.get('label','')}】ta 的选择:{choices(traj_A)}\n"
        f"【人生 B:{option_B.get('label','')}】ta 的选择:{choices(traj_B)}\n\n"
        "确定性分析(来自 ta 的选择,不可篡改):\n"
        f"- 跨两种人生都一致坚持的价值(核心): {[c['dim']+'→'+c['leaning'] for c in core] or '暂不明显'}\n"
        f"- 随情境改变的价值: {[f['dim'] for f in flips] or '无'}\n\n"
        "要求:150-250字;点出'当 X 和 Y 冲突时,你两次都选了 X'这种它自己可能没察觉的模式;"
        "结尾是一个让 ta 问自己的问题,不是一个答案。")
    try:
        m = _llm(prompt, max_tokens=4000)
        result["mirror"] = m if m else "(mirror empty — model returned no content)"
    except Exception as e:
        result["mirror"] = f"(mirror generation failed: {e})"
    return result
