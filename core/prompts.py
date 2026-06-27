"""Editable prompt registry (ZH 2026-06-17).

The gaokao generative prompts live in `prompts.json` so developers can edit them
on the hub-linked editor and the live game picks up the change on the *next*
call — no redeploy. `prompts.defaults.json` is the read-only baseline for "reset".
If the editable file is missing/corrupt or a template loses a required
placeholder, we fall back to the baseline so the game never breaks.
"""
from __future__ import annotations
import json, os, threading, string
from core import paths

_DIR = os.path.dirname(__file__)
_LIVE = paths.prompts("prompts.json")
_BASE = paths.prompts("prompts.defaults.json")
_lock = threading.Lock()
_cache = None

def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _placeholders(tmpl: str) -> set:
    out = set()
    for _, field, _, _ in string.Formatter().parse(tmpl or ""):
        if field:
            out.add(field.split('[')[0].split('.')[0])
    return out

def _load():
    global _cache
    if _cache is None:
        base = _read(_BASE)
        live = _read(_LIVE)
        merged = {}
        for k, bv in base.items():
            v = dict(bv)
            lt = (live.get(k) or {}).get("template")
            # use the edited template only if it still has the baseline's placeholders
            if lt and _placeholders(lt) >= _placeholders(bv["template"]):
                v["template"] = lt
            merged[k] = v
        _cache = merged or live
    return _cache

def reload_prompts():
    global _cache
    _cache = None
    return _load()

def registry() -> dict:
    return _load()

def template(key: str) -> str:
    return _load()[key]["template"]

def render(key: str, **kw) -> str:
    return _load()[key]["template"].format(**kw)

def save(key: str, tmpl: str) -> dict:
    """Persist an edited template. Rejects (raises ValueError) if it drops a
    required placeholder or fails to format — protecting the live game."""
    base = _read(_BASE)
    if key not in base:
        raise ValueError(f"unknown prompt key: {key}")
    need = _placeholders(base[key]["template"])
    got = _placeholders(tmpl)
    missing = need - got
    if missing:
        raise ValueError(f"template is missing required placeholders: {sorted(missing)}")
    # dry-run format with dummy values to catch stray single braces
    try:
        tmpl.format(**{p: "x" for p in got})
    except Exception as e:
        raise ValueError(f"template does not format cleanly: {e}")
    with _lock:
        live = _read(_LIVE)
        live.setdefault(key, {"label": base[key].get("label", key), "desc": base[key].get("desc", "")})
        live[key]["template"] = tmpl
        with open(_LIVE, "w") as f:
            json.dump(live, f, ensure_ascii=False, indent=2)
    return reload_prompts()

def reset(key: str) -> dict:
    base = _read(_BASE)
    if key in base:
        return save(key, base[key]["template"])
    return _load()
