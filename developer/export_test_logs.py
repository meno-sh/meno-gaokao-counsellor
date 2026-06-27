"""Export recent ranked-game test sessions → a readable hub page (ZH 2026-06-17:
'I want the logs to go to the hub'). Reads the session pickles and writes
research-hub/.../test-logs.md. Re-run to refresh the snapshot."""
import os, glob, pickle, time, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RANK_DIR = "/data/reflection-game/gaokao-data/rank_sessions"
OUT = "/workspace/repos/research-hub/content/projects/reflection-game/test-logs.md"
LIMIT = int(os.environ.get("LOG_LIMIT", "30"))

def esc(x):
    return str(x if x is not None else "").replace("|", "\\|").replace("\n", " ")

def main():
    files = sorted(glob.glob(os.path.join(RANK_DIR, "*.pkl")), key=os.path.getmtime, reverse=True)[:LIMIT]
    out = ['---', 'title: "高考志愿 — Test Logs (会话日志)"', 'status: active',
           'tags: [project, reflection-game]', f'updated: {time.strftime("%Y-%m-%d")}', '---', '',
           '> [!info] 最近的测试会话快照(新→旧):入场 → 合成画像 → 每一幕 WTE 选了什么+不确定性地图+调查 → 重排 → 排序变化。重跑 `gaokao/export_test_logs.py` 刷新。',
           '> Snapshot of recent test sessions (newest first): intake → synthesized profile → per-stage WTE pick + uncertainty-map + investigation → reorders → ranking shift. Re-run `gaokao/export_test_logs.py` to refresh.', '']
    n = 0
    for fp in files:
        try:
            with open(fp, "rb") as f:
                s = pickle.load(f)
        except Exception:
            continue
        n += 1
        sid = os.path.basename(fp)[:-4]
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
        prof = getattr(s, "profile", None)
        hist = getattr(s, "history", []) or []
        ledg = getattr(s, "_wte_ledger", []) or []
        init = " > ".join(getattr(s, "initial_order", []) or [])
        fin = " > ".join(s.current_order() if hasattr(s, "current_order") else [])
        out.append(f"## `{sid}` · {when} · {len(hist)}幕 · {len(getattr(s,'rerank_log',[]) or [])}次重排")
        out.append("")
        out.append(f"- **自我描述 / self-desc:** {esc(getattr(prof,'free_text','') or '(空)')}")
        out.append(f"- **毕业去向:** {esc(' > '.join(getattr(prof,'destination_pref',[]) or []) or '(未排)')}")
        out.append(f"- **信心 confidence:** {getattr(s,'confidence_initial',0)} → {getattr(s,'confidence_final',0)}")
        out.append(f"- **排序 ranking:** {esc(init)} → {esc(fin)}")
        out.append("")
        narr = getattr(prof, "narrative", "") or "(未合成 / not synthesized)"
        out.append(f"> 🧬 **合成画像 synthesized profile:** {esc(narr)}")
        out.append("")
        for i, h in enumerate(hist):
            wl = ledg[i] if i < len(ledg) else {}
            why = esc(wl.get("why", "")) if isinstance(wl, dict) else ""
            out.append(f"### 幕 {esc(h.get('stage'))} · WTE 选了【{esc((h.get('factor') or {}).get('label'))}】" + (f" — {why}" if why else ""))
            led = (wl.get("ledger") if isinstance(wl, dict) else None) or []
            if isinstance(led, list) and led:
                out.append("")
                out.append("| 维度 dim | 不确定 | 影响排序 | 依据 |")
                out.append("|---|---|---|---|")
                for d in led:
                    out.append(f"| {esc(d.get('dim'))} | {esc(d.get('uncertainty'))} | {'✓' if d.get('decision_relevant') else '·'} | {esc(d.get('note'))} |")
                out.append("")
            out.append(f"> {esc(h.get('prose'))}")
            out.append("")
            out.append(f"- **{esc(h.get('top'))}:** {esc(h.get('top_take'))}")
            out.append(f"- **vs {esc(h.get('contender'))}:** {esc(h.get('contender_take'))}")
            out.append(f"- 💡 {esc(h.get('did_you_know'))}")
            srcs = '、'.join(h.get('sources') or []) or '—'
            out.append(f"- <small>来源 sources: {esc(srcs)}</small>")
            out.append("")
        out.append("---")
        out.append("")
    if n == 0:
        out.append("_暂无会话。_")
    with open(OUT, "w") as f:
        f.write("\n".join(out))
    print(f"exported {n} sessions -> {OUT}")

if __name__ == "__main__":
    main()
