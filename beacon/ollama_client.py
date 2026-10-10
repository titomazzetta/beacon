"""Minimal client for the local Ollama HTTP API."""
import json
from typing import Iterator

import requests


class OllamaError(RuntimeError):
    pass


class Ollama:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def is_up(self) -> bool:
        try:
            return requests.get(f"{self.base}/api/version", timeout=2).ok
        except requests.RequestException:
            return False

    def models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base}/api/tags", timeout=5)
            r.raise_for_status()
            return sorted(m["name"] for m in r.json().get("models", []))
        except requests.RequestException:
            return []

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        try:
            r = requests.post(f"{self.base}/api/embed",
                              json={"model": model, "input": texts}, timeout=300)
            r.raise_for_status()
        except requests.RequestException as e:
            raise OllamaError(f"Embedding failed ({model}): {e}") from e
        return r.json()["embeddings"]

    def chat_stream(self, model: str, messages: list[dict], options: dict | None = None) -> Iterator[str]:
        body = {"model": model, "messages": messages, "stream": True}
        if options:
            body["options"] = options
        try:
            with requests.post(f"{self.base}/api/chat", json=body, stream=True, timeout=600) as r:
                if r.status_code == 404:
                    raise OllamaError(f"Model '{model}' isn't downloaded. Run: ollama pull {model}")
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise OllamaError(chunk["error"])
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except requests.ConnectionError as e:
            raise OllamaError("Can't reach Ollama. Is it running? Start it with: ollama serve") from e

    def pull(self, model: str) -> Iterator[dict]:
        """Download a model; yields {'status', 'completed', 'total'} progress updates."""
        try:
            with requests.post(f"{self.base}/api/pull", json={"model": model, "stream": True},
                               stream=True, timeout=None) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        msg = json.loads(line)
                        if msg.get("error"):
                            raise OllamaError(msg["error"])
                        yield msg
        except requests.RequestException as e:
            raise OllamaError(f"Couldn't download {model}: {e}") from e

    def generate_once(self, model: str, prompt: str) -> str:
        """Tiny non-streaming call, used by the library check to prove the brain answers."""
        r = requests.post(f"{self.base}/api/generate", timeout=300,
                          json={"model": model, "prompt": prompt, "stream": False,
                                "options": {"num_predict": 24}})
        r.raise_for_status()
        return r.json().get("response", "")
