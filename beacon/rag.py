"""Gather sources, fit them to the brain's context budget, stream the answer."""
import re
from typing import Iterator

from . import cards

SYSTEM_PROMPT = """You are Beacon, an offline survival and field reference assistant. The internet \
may be down and the user may be dealing with a real emergency, outage, injury, repair or evacuation.

Rules:
- Write for someone who may be scared, tired or hurt: short sentences, plain words, no jargon.
- Answer from the numbered SOURCES first. Cite them inline like [1] or [2][3].
- If the sources don't cover something and you answer from general knowledge, say so plainly \
("This isn't in your library; it's general knowledge.").
- Lead with the action. Short numbered steps for procedures. Put critical warnings first.
- For medical, electrical, gas, firearm, structural or wild-food safety: be conservative. Say clearly \
when something needs a professional, and to call 911 / 112 if there's any way to reach them.
- Never invent dosages, measurements, frequencies or wiring specs. If unsure, say you're unsure.
- Never tell someone a wild plant or mushroom is safe to eat from a description alone.
- If there's an ABOUT THE PERSON section, fit the answer to their situation, people and gear. When they \
lack something, give a safe way to make do with what they have or can find.
- If there's a CURRENT UPDATES section, it's dated news from outside that may be incomplete or out of \
date. Use it for context, say where it came from, and never let it override safety steps.
"""


CARD_KEYWORDS = cards.KEYWORDS


PHRASES = ("heart attack", "carbon monoxide", "jump start", "flat tire", "heat wave", "self defense",
           "head injury", "broken bone", "snake bite", "gray man", "blend in", "bug out", "power station",
           "mutual aid", "dirty bomb", "potassium iodide", "solar panel", "duct tape", "trash bags", "bow drill",
           "rain barrel", "offline maps", "car radio")


# Words that only mean something inside a phrase ("blend in", "bug out", "gray man").
PHRASE_ONLY = {"in", "out", "man", "self", "bug", "blend"}


def match_card(question: str) -> str | None:
    words = set(re.findall(r"[a-z][a-z-]+", question.lower())) - PHRASE_ONLY
    text = " " + question.lower() + " "
    best, score = None, 0
    for card, keys in CARD_KEYWORDS:
        s = 0
        for k in keys.split():  # "word!" marks a word that points to this card strongly
            weight = 2 if k.endswith("!") else 1
            if k.rstrip("!") in words:
                s += weight
        for phrase in PHRASES:  # two-word terms count double when they belong to this card
            if phrase in text and phrase in keys.replace("!", ""):
                s += 2
        if s > score:
            best, score = card, s
    return best


def format_sources(sources: list[dict]) -> str:
    if not sources:
        return "SOURCES: none found in the local library."
    blocks = [f"[{i}] {s['book']}" + (f" — {s['title']}" if s.get("title") else "") + f"\n{s['text']}"
              for i, s in enumerate(sources, 1)]
    return "SOURCES:\n\n" + "\n\n---\n\n".join(blocks)


def _relevance(question: str, hit: dict) -> float:
    words = {w for w in re.findall(r"[a-z0-9]{4,}", question.lower())}
    if not words:
        return 0.0
    title, text = hit["title"].lower(), hit["text"][:3000].lower()
    return sum(3 * (w in title) + (w in text) for w in words) / len(words)


def gather(question: str, kiwix, manuals, profile: dict) -> list[dict]:
    """Pull candidates from manuals and every Kiwix book, then keep the best ones that fit
    the profile's source count and the model's context window."""
    per_source = profile["chars"]
    manual_hits, kiwix_hits = [], []
    if manuals is not None:
        try:
            manual_hits = manuals.search(question, profile["sources"], per_source)
        except Exception as e:
            print(f"[manuals] search skipped: {e}")
    if kiwix is not None:
        kiwix_hits = kiwix.search(question, per_book=2, max_chars=per_source)
        kiwix_hits.sort(key=lambda h: _relevance(question, h), reverse=True)

    # Interleave so neither your manuals nor the encyclopedias crowd the other out.
    merged, i, j = [], 0, 0
    while i < len(manual_hits) or j < len(kiwix_hits):
        if i < len(manual_hits):
            merged.append(manual_hits[i]); i += 1
        if j < len(kiwix_hits):
            merged.append(kiwix_hits[j]); j += 1

    budget = int(profile["num_ctx"] * 4 * 0.6)  # ~4 chars per token; leave room for the answer
    picked, used, seen = [], 0, set()
    for s in merged:
        key = (s["book"], s["title"], s["text"][:80])
        if key in seen:
            continue
        if len(picked) >= profile["sources"] or used + len(s["text"]) > budget:
            continue
        seen.add(key)
        picked.append(s)
        used += len(s["text"])
    return picked


def build_messages(question: str, sources: list[dict], history: list[dict], context: str = "") -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-6:]:  # keep a little context, not the whole night
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"]})
    about = f"{context}\n\n" if context else ""
    msgs.append({"role": "user", "content": f"{format_sources(sources)}\n\n{about}QUESTION: {question}"})
    return msgs


def answer(question, sources, history, ollama, model: str, num_ctx: int = 8192, context: str = "") -> Iterator[str]:
    yield from ollama.chat_stream(model, build_messages(question, sources, history, context),
                                  options={"num_ctx": num_ctx})
