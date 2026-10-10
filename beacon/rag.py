"""Gather sources, fit them to the brain's context budget, stream the answer."""
import re
from typing import Iterator

SYSTEM_PROMPT = """You are Beacon, an offline survival and field reference assistant. The internet \
may be down and the user may be dealing with a real emergency, outage, injury, repair or evacuation.

Rules:
- Write for someone who may be scared, tired or hurt: short sentences, plain words, no jargon.
- Answer from the numbered SOURCES first. Cite them inline like [1] or [2][3].
- If the sources don't cover something and you answer from general knowledge, say so plainly \
("not in your library — from general knowledge").
- Lead with the action. Short numbered steps for procedures. Put critical warnings first.
- For medical, electrical, gas, firearm, structural or wild-food safety: be conservative. Say clearly \
when something needs a professional, and to call 911 / 112 if there's any way to reach them.
- Never invent dosages, measurements, frequencies or wiring specs. If unsure, say you're unsure.
- Never tell someone a wild plant or mushroom is safe to eat from a description alone.
"""


# Questions about these topics also show the matching quick card above the AI's answer,
# so a vetted, static version of the steps is always one tap away.
CARD_KEYWORDS = [
    ("first-aid-essentials.md", "bleed bleeding cpr choking choke burn burns stroke allergic anaphylaxis epipen "
     "unconscious breathing heart attack fracture broken bone splint snakebite snake bite poison wound "
     "tourniquet frostbite hypothermia seizure concussion head injury"),
    ("severe-weather.md", "tornado lightning thunder hurricane flood flooding earthquake wildfire smoke heat wave "
     "heatwave humidity hail storm blizzard"),
    ("water.md", "water purify purification boil bleach drinking dehydration rehydration"),
    ("power-outage.md", "power outage blackout generator inverter electricity freezer fridge carbon monoxide"),
    ("car-emergency.md", "car vehicle stuck snow jump start battery flat tire overheating brakes submerged"),
    ("emergency-radio.md", "radio frequency frequencies ham gmrs frs noaa scanner walkie"),
    ("morse-and-signals.md", "morse sos signal signaling mirror whistle rescue helicopter aircraft flare"),
    ("navigation-and-nature-signs.md", "lost north compass navigate navigation stars shadow map bearing"),
    ("evacuation-and-leaving.md", "evacuate evacuation leave country border passport go-bag bug out flee"),
    ("defensive-perimeter.md", "perimeter defend defense defensive intruder intruders security watch guard looters"),
    ("evasion-basics.md", "evade evasion hide hiding escape pursued checkpoint occupied invasion"),
    ("low-profile-and-self-defense.md", "self-defense self defense attacked mugging robbery gray man blend in"),
    ("wild-food-and-game.md", "forage foraging edible mushroom mushrooms plant plants berries hunt hunting "
     "fish fishing trap trapping game deer"),
    ("firearms-safety.md", "gun guns firearm firearms rifle pistol revolver shotgun ammo bow arrow archery"),
    ("mind-and-body.md", "panic anxiety stress calm breathing sleep grief depressed depression meditation workout fitness"),
    ("community-network.md", "neighbors neighbor neighborhood community mutual aid check-in checkin roster barter trade group network"),
    ("meshtastic.md", "meshtastic! mesh! lora! node nodes"),
    ("off-grid-power.md", "solar panel panels battery batteries power station anker ecoflow jackery lifepo4 inverter watts watt-hours "
     "cpap oxygen concentrator insulin"),
    ("sanitation-and-hygiene.md", "sanitation! toilet! toilets! latrine! sewage! flush hygiene handwashing diarrhea cholera! trash flies bucket"),
    ("radiation-chemical-pandemic.md", "radiation! nuclear! fallout! radioactive! iodide! chemical gas spill hazmat! pandemic! outbreak "
     "quarantine dirty bomb"),
    ("digital-safety.md", "phone opsec! privacy hacked hacking surveillance tracking encryption passcode! scam scams "
     "faraday metadata"),
]


PHRASES = ("heart attack", "carbon monoxide", "jump start", "flat tire", "heat wave", "self defense",
           "head injury", "broken bone", "snake bite", "gray man", "blend in", "bug out", "power station",
           "mutual aid", "dirty bomb", "potassium iodide", "solar panel")


def match_card(question: str) -> str | None:
    words = set(re.findall(r"[a-z][a-z-]+", question.lower()))
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


def build_messages(question: str, sources: list[dict], history: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history[-6:]:  # keep a little context, not the whole night
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            msgs.append({"role": turn["role"], "content": turn["content"]})
    msgs.append({"role": "user", "content": f"{format_sources(sources)}\n\nQUESTION: {question}"})
    return msgs


def answer(question, sources, history, ollama, model: str, num_ctx: int = 8192) -> Iterator[str]:
    yield from ollama.chat_stream(model, build_messages(question, sources, history),
                                  options={"num_ctx": num_ctx})
