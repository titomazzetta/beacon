"""Settings, loaded from config.json next to the app (created on first run)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "ollama_url": "http://127.0.0.1:11434",
    "chat_model": "",  # empty = auto: strongest installed model this Mac's RAM can run
    "embed_model": "nomic-embed-text",
    "zim_dir": "library/zim",
    "manuals_dir": "library/manuals",
    "index_path": "data/manuals_index.sqlite",
    "kiwix_results_per_book": 2,
    "manual_results": 4,
    "max_chars_per_source": 2500,
    "host": "127.0.0.1",
    "port": 8642,
}


def load() -> dict:
    path = ROOT / "config.json"
    cfg = dict(DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    else:
        path.write_text(json.dumps(DEFAULTS, indent=2))
    # Environment overrides (the USB launcher uses these)
    env_map = {"LANTERN_OLLAMA_URL": "ollama_url", "LANTERN_CHAT_MODEL": "chat_model",
               "LANTERN_PORT": "port"}
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = int(os.environ[env]) if key == "port" else os.environ[env]
    # On the USB drive the library/models/data sit beside the app, not inside it.
    data_root = Path(os.environ.get("LANTERN_DATA_ROOT", ROOT))
    for key in ("zim_dir", "manuals_dir", "index_path"):
        p = Path(cfg[key])
        cfg[key] = str(p if p.is_absolute() else data_root / p)
    return cfg


def save(updates: dict) -> None:
    path = ROOT / "config.json"
    current = json.loads(path.read_text()) if path.exists() else dict(DEFAULTS)
    current.update({k: v for k, v in updates.items() if k in DEFAULTS})
    path.write_text(json.dumps(current, indent=2))
