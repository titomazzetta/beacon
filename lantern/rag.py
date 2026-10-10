"""Gather sources, build the prompt, stream the answer."""
from typing import Iterator

SYSTEM_PROMPT = """You are Lantern, an offline field reference assistant. The internet may be down \
and the user may be dealing with a real emergency, outage, injury, or repair.

Rules:
- Answer using the numbered SOURCES first. Cite them inline like [1] or [2][3].
- If the sources don't cover something and you answer from general knowledge, say so plainly \
("not in your library — from general knowledge").
- Lead with the action. Short numbered steps for procedures. Put critical warnings first.
- For medical, electrical, gas, firearm or structural safety: be conservative. Say clearly when \
something needs a professional, and to call 911 / 112 if there's any way to reach them.
- Never invent dosages, measurements or wiring specs. If unsure, say you're unsure.
"""


def format_sources(sources: list[dict]) -> str:
    if not sources:
        return "SOURCES: none found in the local library."
    blocks = []
    for i, s in enumerate(sources, 1):
        blocks.append(f"[{i}] {s['book']} — {s['title']}\n{s['text']}")
    return "SOURCES:\n\n" + "\n\n---\n\n".join(blocks)


def gather(question: str, kiwix, manuals, cfg: dict) -> list[dict]:
    sources = []
    if manuals is not None:
        try:
            sources += manuals.search(question, cfg["manual_results"], cfg["max_chars_per_source"])
        except Exception as e:
            print(f"[manuals] search skipped: {e}")
    if kiwix is not None:
        sources += kiwix.search(question, cfg["kiwix_results_per_book"], cfg["max_chars_per_source"])
    return sources


def build_messages(question: str, sources: list[dict], history: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-6:]:  # keep a little context, not the whole night
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({"role": "user", "content": f"{format_sources(sources)}\n\nQUESTION: {question}"})
    return msgs


def answer(question: str, sources: list[dict], history: list[dict], ollama, model: str) -> Iterator[str]:
    yield from ollama.chat_stream(model, build_messages(question, sources, history))
