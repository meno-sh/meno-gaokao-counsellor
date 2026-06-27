"""Central path resolution for the standalone repo: data/ and prompts/ live at the
repo root (not next to each module). Override with env GAOKAO_REAL_DATA / GAOKAO_PROMPTS_DIR."""
import os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root
REAL_DATA = os.environ.get("GAOKAO_REAL_DATA", os.path.join(_ROOT, "data", "real_data"))
DATA_DIR  = os.environ.get("GAOKAO_DATA_ROOT", os.path.join(_ROOT, "data"))
PROMPTS_DIR = os.environ.get("GAOKAO_PROMPTS_DIR", os.path.join(_ROOT, "prompts"))
def data(*p): return os.path.join(DATA_DIR, *p)
def real_data(*p): return os.path.join(REAL_DATA, *p)
def prompts(*p): return os.path.join(PROMPTS_DIR, *p)
