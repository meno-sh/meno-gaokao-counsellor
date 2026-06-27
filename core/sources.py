"""Unified source / 来源 model (ZH 2026-06-19).

Every fact the game shows should carry a *tiered, optionally-linked* 来源. Historically
`sources` was a flat list of report-NAME strings (0 URLs) scattered across three data
layers (major_grounding KB, uni_employment KB, live websearch, 雨来). This coerces them
all into one shape — `{title, url, tier}` — so the whole stack speaks one language and
the frontend can render clickable links + a provenance-tier badge.

Backward compatible: `normalize()` accepts legacy strings (bare names OR embedded URLs)
and already-structured dicts. `url` stays None when we don't have a link yet (e.g. the
uni 就业质量报告 names await ZH's PDF-scrape backfill) — callers render plain text then.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

# provenance tiers, strongest → weakest
TIERS = ["雨来-verified", "就业质量报告", "麦可思", "网络检索", "AI蒸馏待核"]
_URL_RE = re.compile(r"https?://[^\s）)，,。、；;】\]]+")


def _infer_tier(title: str, url: str = "") -> str:
    t = f"{title or ''} {url or ''}"
    tl = t.lower()
    if "雨来" in t or "yusoong" in tl:
        return "雨来-verified"
    if "就业质量" in t:
        return "就业质量报告"
    if "麦可思" in t or "mycos" in tl:
        return "麦可思"
    if "蒸馏" in t or "distill" in tl or "deepseek" in tl:
        return "AI蒸馏待核"
    return "网络检索"


def normalize_one(s):
    """str | dict → {title, url, tier} | None (None when empty/junk)."""
    if s is None:
        return None
    if isinstance(s, dict):
        title = str(s.get("title") or s.get("name") or "").strip()
        url = (str(s.get("url")).strip() if s.get("url") else "") or None
        if not title and url:
            title = urlparse(url).netloc or url
        if not title and not url:
            return None
        return {"title": title, "url": url, "tier": s.get("tier") or _infer_tier(title, url or "")}
    s = str(s).strip()
    if not s:
        return None
    m = _URL_RE.search(s)
    if m:
        url = m.group(0)
        title = s.replace(url, "").strip(" -—:：·（）()") or (urlparse(url).netloc or url)
        return {"title": title, "url": url, "tier": _infer_tier(title, url)}
    return {"title": s, "url": None, "tier": _infer_tier(s)}


def normalize(srcs) -> list:
    """List of mixed str/dict → de-duped list of {title, url, tier}."""
    out, seen = [], set()
    for s in (srcs or []):
        n = normalize_one(s)
        if not n:
            continue
        k = (n["title"], n["url"])
        if k in seen:
            continue
        seen.add(k)
        out.append(n)
    return out


def to_text(srcs) -> str:
    """Compact one-line text for LLM-prompt grounding context (no markup)."""
    return "；".join(n["title"] + (f"({n['url']})" if n["url"] else "") for n in normalize(srcs))


def to_html(srcs) -> str:
    """HTML 来源 fragment for server-rendered pages (web.py admin viewer)."""
    import html
    parts = []
    for n in normalize(srcs):
        t = html.escape(n["title"])
        badge = f' <span class=srctier>{html.escape(n["tier"])}</span>' if n.get("tier") else ""
        if n["url"]:
            u = html.escape(n["url"], quote=True)
            parts.append(f'<a href="{u}" target="_blank" rel="noopener">{t}</a>{badge}')
        else:
            parts.append(f"{t}{badge}")
    return "、".join(parts)
