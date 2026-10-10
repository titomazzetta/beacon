"""Index the manuals folder from the command line: python -m beacon.ingest_cli"""
from . import config
from .manuals import ManualIndex
from .ollama_client import Ollama


def main():
    cfg = config.load()
    ollama = Ollama(cfg["ollama_url"])
    if not ollama.is_up():
        raise SystemExit("Ollama isn't running at " + cfg["ollama_url"])
    index = ManualIndex(cfg["index_path"], ollama, cfg["embed_model"])
    print(index.ingest_dir(cfg["manuals_dir"]))


if __name__ == "__main__":
    main()
