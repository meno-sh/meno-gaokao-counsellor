"""Profiling quiz (ZH redesign 2026-06-14).

A curated set of high-information multiple-choice questions, chosen to reduce the
most uncertainty about *who the student is* across the decision-relevant axes
(risk posture · intrinsic vs extrinsic · people/things/ideas · autonomy vs
deference · depth vs outcome · time horizon). Each option carries a
dimension_vector over the 8-pole rubric, so answers fold into the PersonalityFile
that personalizes scenes + the investigator. Curated (not LLM-generated) so the
starter page is instant; can go adaptive later.
"""
from __future__ import annotations

QUIZ = [
    {"id": "image", "q": "毕业五年后,你最希望别人怎么形容你?", "options": [
        {"label": "靠谱、稳定、让人安心", "dims": {"PROTECTION": 0.6, "LOYALTY": 0.5}},
        {"label": "有想法、敢闯、走自己的路", "dims": {"AGENCY": 0.8, "VOICE": 0.5}},
        {"label": "专业、厉害、做得很深", "dims": {"RIGOR": 0.7, "PROCESS": 0.5}}]},
    {"id": "object", "q": "你更喜欢和什么打交道?", "options": [
        {"label": "人,沟通、合作、影响他人", "dims": {"OTHER": 0.7, "VOICE": 0.5}},
        {"label": "事和物,系统、技术、把东西做出来", "dims": {"PROCESS": 0.6, "OBSERVATION": 0.4}},
        {"label": "想法,理论、研究、把问题想透", "dims": {"TRUTH": 0.7, "RIGOR": 0.6}}]},
    {"id": "risk", "q": "关于风险,你更接近哪个?", "options": [
        {"label": "宁可稳一点,不想赌", "dims": {"PROTECTION": 0.8, "LATER": 0.5}},
        {"label": "愿意为更大的可能去冒险", "dims": {"AGENCY": 0.7, "NOW": 0.4}}]},
    {"id": "authority", "q": "当你的选择和父母/老师不一致?", "options": [
        {"label": "他们经验多,我会很重视他们的意见", "dims": {"LOYALTY": 0.7, "OBSERVATION": 0.4}},
        {"label": "听一听,但最终按我自己的判断来", "dims": {"AGENCY": 0.8, "VOICE": 0.6, "PRINCIPLE": 0.5}}]},
    {"id": "satisfy", "q": "下面哪种更让你满足?", "options": [
        {"label": "把一件难事做到极致", "dims": {"RIGOR": 0.8, "PROCESS": 0.6}},
        {"label": "世俗意义上的成功,名利、地位、被人认可", "dims": {"OUTCOME": 0.7, "NOW": 0.4, "MATERIAL": 0.5}},
        {"label": "实实在在帮到了具体的人", "dims": {"MERCY": 0.7, "OTHER": 0.6}}]},
]

def quiz_payload() -> list:
    """Frontend-facing quiz (no dims leaked)."""
    out = []
    for q in QUIZ:
        en = _QUIZ_EN.get(q["id"], {})
        out.append({"id": q["id"], "q": q["q"], "q_en": en.get("q", q["q"]),
                    "options": [o["label"] for o in q["options"]],
                    "options_en": en.get("options", [o["label"] for o in q["options"]])})
    return out


_QUIZ_EN = {
    "image": {"q": "Five years after graduation, how would you most want to be described?",
              "options": ["Reliable, stable, reassuring", "Original, bold, forging my own path", "Expert, impressive, deeply skilled"]},
    "object": {"q": "What do you most like working with?",
               "options": ["People, communicating, collaborating, influencing", "Things and systems, tech, building things", "Ideas, theory, research, thinking problems through"]},
    "risk": {"q": "On risk, which is closer to you?",
             "options": ["I'd rather play it safe", "I'll take risks for a bigger upside"]},
    "authority": {"q": "When your choice differs from your parents / teachers?",
                  "options": ["They have experience; I weigh their views heavily", "I'll listen, but decide for myself in the end"]},
    "satisfy": {"q": "Which is more satisfying to you?",
                "options": ["Mastering one hard thing to the extreme", "Worldly success, money, status, recognition", "Genuinely helping real people"]},
}

def answers_text(answers: dict) -> str:
    """Human-readable 'Q -> chosen answer' lines from {qid: chosen_index}, for the
    narrative synthesizer (the actual words, not the dimension vectors)."""
    by_id = {q["id"]: q for q in QUIZ}
    out = []
    for qid, ans in (answers or {}).items():
        q = by_id.get(qid)
        if not q:
            continue
        if isinstance(ans, list):   # allocation slider: % distribution over options
            parts = [f"{q['options'][i]['label']}{int(ans[i])}%"
                     for i in range(min(len(ans), len(q['options']))) if ans[i]]
            if parts:
                out.append(f"- {q['q']} → " + " / ".join(parts))
        else:
            try:
                out.append(f"- {q['q']} → {q['options'][int(ans)]['label']}")
            except (ValueError, TypeError, IndexError):
                continue
    return "\n".join(out)

def apply_answers(profile, answers: dict) -> None:
    """answers: {qid: index} (radio) OR {qid: [%,%,%]} (allocation slider). Folds dims (scaled by % for sliders)."""
    by_id = {q["id"]: q for q in QUIZ}
    for qid, ans in (answers or {}).items():
        q = by_id.get(qid)
        if not q:
            continue
        if isinstance(ans, list):   # allocation slider: fold each option's dims scaled by its %
            for i, opt in enumerate(q["options"]):
                if i < len(ans) and ans[i]:
                    w = float(ans[i]) / 100.0
                    if w > 0:
                        profile.update_from_choice({k: v * w for k, v in opt.get("dims", {}).items()})
        else:
            try:
                opt = q["options"][int(ans)]
            except (ValueError, TypeError, IndexError):
                continue
            profile.update_from_choice(opt.get("dims", {}))

# 毕业去向 (destination) — ranked in the opening questionnaire (ZH 2026-06-16).
# Data-backed axis: maps to 就业质量报告 升学/出国/就业 numbers; conditions every stage.
DESTINATIONS = [
    {"key": "保研",     "key_en": "Grad school (recommended)", "desc": "免试推荐读研，看重绩点与科研", "desc_en": "Recommended to grad school (no exam); GPA & research matter"},
    {"key": "考研",     "key_en": "Grad school (exam)",        "desc": "考试升学，深造换平台/换方向", "desc_en": "Grad school via entrance exam; switch tier/direction"},
    {"key": "出国留学", "key_en": "Study abroad",              "desc": "申请海外院校，看重语言/科研/资金", "desc_en": "Apply abroad; language / research / funding matter"},
    {"key": "就业",     "key_en": "Employment",                "desc": "本科毕业直接工作，看重实习与行业", "desc_en": "Work right after the bachelor's; internships & industry"},
    {"key": "考公考编", "key_en": "Civil / public sector",     "desc": "公务员/事业编/教师编，看重稳定", "desc_en": "Civil service / public institution / teacher posts; stability"},
    {"key": "创业",     "key_en": "Startup / early-stage",     "desc": "自己做事/加入早期团队，看重机会与风险", "desc_en": "Own venture / early-stage team; opportunity & risk"},
]

def destinations_payload() -> list:
    """Frontend-facing destination chips for the opening ranking."""
    return DESTINATIONS
