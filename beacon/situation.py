"""Your situation: the setup questionnaire and the next steps Beacon builds from it.

The questions are data (OPTIONS), so the interface draws them and the rules below read them.
The rules are plain and deterministic on purpose: they work instantly with the AI off, they can
be tested, and every suggestion points at a card, a plan or a tool that holds the details.

The Beacon computer's answers are saved on the drive. A guest's answers stay on their own phone
and travel with each request; Beacon never stores them.
"""
import re

from .cards import LABELS as CARD_LABELS

PHASES = [("ahead", "Preparing ahead"), ("now", "It's happening now"), ("after", "Recovering after")]
PHASE_LABEL = dict(PHASES)

CONCERNS = [
    ("outage", "Power outage"), ("winter", "Winter storm"), ("heat", "Heat wave"), ("hurricane", "Hurricane or flood"),
    ("tornado", "Tornado"), ("wildfire", "Wildfire"), ("earthquake", "Earthquake"), ("outbreak", "Outbreak"),
    ("unrest", "Unrest"), ("war", "War or invasion"), ("leave", "Leaving the country"), ("offgrid", "Living off the grid"),
    ("lost", "Lost or stranded outdoors"), ("water", "Stranded by water"), ("unsure", "Not sure yet"),
]
HOMES = [("house", "House"), ("apartment", "Apartment"), ("rural", "Rural or farm"), ("vehicle", "Vehicle"),
         ("outdoors", "Outdoors")]
PEOPLE = [("adults", "Adults"), ("children", "Children"), ("elders", "Older adults"), ("pets", "Pets")]
HAVE = [
    ("Power", [("power_station", "Power station"), ("solar", "Solar panels"), ("generator", "Generator"),
               ("power_banks", "Power banks"), ("car", "A car with fuel")]),
    ("Water", [("water_stored", "Stored water"), ("filter", "Water filter"), ("bleach", "Plain bleach"),
               ("boil", "A way to boil water")]),
    ("Food", [("food_3d", "3 days of food"), ("food_2w", "2 weeks of food"), ("food_3m", "3 months or more"),
              ("garden", "A garden")]),
    ("Medical", [("first_aid", "First aid kit"), ("tourniquet", "Tourniquet"), ("meds", "2 weeks of medicines"),
                 ("med_device", "A medical device that needs power")]),
    ("Communication", [("weather_radio", "Weather or crank radio"), ("walkies", "Walkie-talkies"), ("ham", "Ham radio"),
                       ("meshtastic", "Meshtastic radios"), ("sat_phone", "Phone with satellite SOS"),
                       ("plb", "Satellite messenger or PLB"), ("starlink", "Starlink")]),
    ("Heat, light and cooking", [("heat_source", "Fireplace or wood stove"), ("camp_stove", "Camp stove or grill"),
                                 ("lights", "Flashlights and batteries"), ("co_alarm", "Carbon monoxide alarm")]),
    ("Ready to move", [("go_bags", "Go-bags packed"), ("cash", "Cash"), ("documents", "Documents and copies"),
                       ("bike", "Bicycle")]),
    ("Skills", [("skill_first_aid", "First aid training"), ("skill_hunt", "Hunting or fishing"),
                ("skill_garden", "Growing food"), ("skill_repair", "Repair and tools")]),
]
HAVE_LABEL = {k: v for _, items in HAVE for k, v in items}
CONCERN_LABEL = dict(CONCERNS)
HOME_LABEL = dict(HOMES)


def options() -> dict:
    """Everything the questionnaire asks, for the interface to draw."""
    return {"phases": PHASES, "concerns": CONCERNS, "homes": HOMES, "people": PEOPLE,
            "have": [{"group": g, "items": items} for g, items in HAVE]}


def clean(raw) -> dict:
    """Keep only known answers, so stored files and prompts never carry anything else."""
    raw = raw if isinstance(raw, dict) else {}
    people = raw.get("people") if isinstance(raw.get("people"), dict) else {}

    def count(v):
        try:
            return max(0, min(99, int(v)))
        except (TypeError, ValueError):
            return 0

    def text(v, n):
        return re.sub(r"\s+", " ", str(v or "")).strip()[:n]

    out = {
        "phase": raw.get("phase") if raw.get("phase") in PHASE_LABEL else "",
        "concerns": [c for c, _ in CONCERNS if c in (raw.get("concerns") or [])],
        "people": {k: count(people.get(k)) for k, _ in PEOPLE},
        "needs": text(raw.get("needs"), 300),
        "place": text(raw.get("place"), 120),
        "home": raw.get("home") if raw.get("home") in HOME_LABEL else "",
        "have": [k for k in HAVE_LABEL if k in (raw.get("have") or [])],
        "nothing": bool(raw.get("nothing")),
    }
    if out["nothing"]:
        out["have"] = [k for k in out["have"] if k.startswith("skill_")]
    return out


def is_empty(sit: dict) -> bool:
    return not (sit.get("phase") or sit.get("concerns") or sit.get("have") or sit.get("place") or sit.get("nothing")
                or any((sit.get("people") or {}).values()))


def _join(words: list[str]) -> str:
    words = [w for w in words if w]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1] if words else ""


def _people_text(p: dict) -> str:
    bits = []
    for key, one, many in (("adults", "adult", "adults"), ("children", "child", "children"),
                           ("elders", "older adult", "older adults"), ("pets", "pet", "pets")):
        n = p.get(key, 0)
        if n:
            bits.append(f"{n} {one if n == 1 else many}")
    return _join(bits)


POWERED_DEVICE = re.compile(r"\b(c-?pap|bi-?pap|apnea|oxygen|concentrator|ventilator|dialysis|nebuli[sz]er|suction|"
                            r"feeding pump|infusion pump|power(ed)? wheelchair|scooter|lift chair|hospital bed)\b", re.I)
INSULIN = re.compile(r"\binsulin\b", re.I)


def needs_power(sit: dict) -> bool:
    """A medical device that runs on power, ticked or named in the needs box."""
    return "med_device" in sit.get("have", []) or bool(POWERED_DEVICE.search(sit.get("needs", "")))


def headcount(sit: dict) -> int:
    p = sit.get("people") or {}
    return max(1, p.get("adults", 0) + p.get("children", 0) + p.get("elders", 0))


def headline(sit: dict) -> str:
    """'It's happening now: winter storm and power outage. 2 adults and 1 child in Denver.'"""
    if is_empty(sit):
        return ""
    concerns = [CONCERN_LABEL[c].lower() for c in sorted(sit["concerns"], key=URGENCY.index) if c != "unsure"]
    moment = PHASE_LABEL[sit.get("phase") or "ahead"] if concerns or sit.get("phase") else ""
    first = f"{moment}: {_join(concerns)}." if moment and concerns else f"{moment}." if moment else ""
    who = _people_text(sit.get("people") or {})
    where = sit.get("place", "")
    second = f"{who} in {where}." if who and where else f"{who}." if who else f"In {where}." if where else ""
    third = "Starting with almost nothing." if sit.get("nothing") else ""
    return " ".join(x for x in (first, second[:1].upper() + second[1:], third) if x)


def context_text(sit: dict) -> str:
    """A short note for the AI, so answers fit this person's situation and gear."""
    if is_empty(sit):
        return ""
    lines = []
    if sit.get("phase"):
        lines.append(f"Timing: {PHASE_LABEL[sit['phase']].lower()}.")
    if sit.get("concerns"):
        lines.append("Facing: " + ", ".join(CONCERN_LABEL[c].lower() for c in sit["concerns"]) + ".")
    who = _people_text(sit.get("people") or {})
    if who:
        lines.append(f"People: {who}.")
    if sit.get("needs"):
        lines.append(f"Medical or special needs: {sit['needs']}.")
    where = " ".join(x for x in (HOME_LABEL.get(sit.get("home"), "").lower(), ("in " + sit["place"]) if sit.get("place") else "") if x)
    if where:
        lines.append(f"Where: {where}.")
    if sit.get("nothing"):
        lines.append("Has almost nothing: favor ways to make do with household items and what's around.")
    have = [HAVE_LABEL[k].lower() for k in sit.get("have", [])]
    if have:
        lines.append("Has: " + ", ".join(have) + ".")
    missing = [HAVE_LABEL[k].lower() for k in ("water_stored", "filter", "first_aid", "lights", "weather_radio", "power_station")
               if k not in sit.get("have", [])]
    if missing and not sit.get("nothing"):
        lines.append("Doesn't have: " + ", ".join(missing) + ".")
    return "ABOUT THE PERSON ASKING (from their setup answers): " + " ".join(lines)


# ---------------------------------------------------------------- what to open for each concern

CONCERN_PLANS = {
    "outage": ["power", "shelter-in-place"], "winter": ["winter-storm", "power"], "heat": ["heat-wave"],
    "hurricane": ["flood-hurricane", "evacuate"], "tornado": ["tornado"], "wildfire": ["evacuate"],
    "earthquake": ["shelter-in-place"], "outbreak": ["shelter-in-place"], "unrest": ["perimeter", "community"],
    "war": ["evade", "leave-country"], "leave": ["leave-country"], "offgrid": ["homestead", "power", "food-30"],
    "lost": ["wilderness"], "water": ["island"], "unsure": ["food-30", "evacuate"],
}
CONCERN_CARDS = {
    "outage": ["power-outage.md", "off-grid-power.md"], "winter": ["severe-weather.md", "power-outage.md"],
    "heat": ["severe-weather.md"], "hurricane": ["severe-weather.md", "evacuation-and-leaving.md"],
    "tornado": ["severe-weather.md"], "wildfire": ["evacuation-and-leaving.md", "severe-weather.md"],
    "earthquake": ["first-aid-essentials.md", "severe-weather.md"],
    "outbreak": ["radiation-chemical-pandemic.md", "sanitation-and-hygiene.md"],
    "unrest": ["defensive-perimeter.md", "low-profile-and-self-defense.md", "digital-safety.md"],
    "war": ["evasion-basics.md", "digital-safety.md", "evacuation-and-leaving.md", "radiation-chemical-pandemic.md"],
    "leave": ["evacuation-and-leaving.md", "digital-safety.md"],
    "offgrid": ["off-grid-power.md", "grow-food-and-homestead.md", "wild-food-and-game.md", "water.md"],
    "lost": ["navigation-and-nature-signs.md", "fire.md", "morse-and-signals.md"],
    "water": ["sea-and-island.md", "fire.md", "water.md"],
    "unsure": ["water.md", "make-do.md"],
}
CONCERN_BANDS = {
    "outage": ["civil-defense", "power"], "winter": ["shelter-winter", "civil-defense"], "heat": ["civil-defense"],
    "hurricane": ["civil-defense"], "tornado": ["civil-defense"], "wildfire": ["civil-defense"],
    "earthquake": ["civil-defense", "medical"], "outbreak": ["medical", "civil-defense"],
    "unrest": ["security", "comms"], "war": ["security", "comms", "civil-defense"], "leave": ["civil-defense", "security"],
    "offgrid": ["grow-hunt", "power", "water-food", "hunt-fish", "vehicles"], "lost": ["wilderness"],
    "water": ["wilderness"], "unsure": ["medical", "water-food"],
}


# When several concerns are picked, plans and cards for the most specific, most dangerous one come first.
URGENCY = ["war", "water", "lost", "wildfire", "hurricane", "tornado", "earthquake", "winter", "heat", "outbreak",
           "leave", "unrest", "outage", "offgrid", "unsure"]


def _act(kind: str, ident: str, label: str = "") -> dict:
    return {"type": kind, "id": ident, "label": label}


def _card(file: str) -> dict:
    """An action that opens a quick card, named as its tab is (cards.py), so names never drift apart."""
    return _act("card", file, CARD_LABELS.get(file, file))


def assess(sit: dict, supplies: dict | None = None, plan_titles: dict | None = None,
           card_titles: dict | None = None, library: list[dict] | None = None, host: bool = True) -> dict:
    """Next steps for this situation: do first, what your gear is good for, what's missing (and how
    to make do meanwhile), and the plans, cards and library items that fit. host=False is a guest on
    the Wi-Fi, who can't fill in Your household on the Beacon computer."""
    sit = clean(sit)
    have = set(sit["have"])
    phase = sit["phase"] or "ahead"
    concerns = sorted(sit["concerns"] or ["unsure"], key=URGENCY.index)  # the most specific threat leads
    n = headcount(sit)
    plan_titles = plan_titles or {}
    card_titles = card_titles or {}
    phase_label = PHASE_LABEL[phase]

    # what the supplies tracker says, if it's been filled in
    water_gal = food_kcal = 0.0
    for it in (supplies or {}).get("items", []):
        if it.get("cat") == "water":
            water_gal += it.get("qty", 0) * it.get("gal", 0)
        elif it.get("cat") == "food":
            food_kcal += it.get("qty", 0) * it.get("kcal", 0)
    if water_gal:
        have.add("water_stored")
    if food_kcal >= n * 2000 * 3:
        have.add("food_3d")

    plans_out, seen = [], set()
    for c in concerns:
        for pid in CONCERN_PLANS.get(c, []):
            if pid not in seen and pid in plan_titles:
                seen.add(pid)
                plans_out.append({"id": pid, "title": plan_titles[pid], "phase": phase_label})
    cards_out, seen = [], set()
    lead = (["first-aid-essentials.md"] if phase == "now" else []) + (["make-do.md", "water.md"] if sit["nothing"] else [])
    for f in lead + [f for c in concerns for f in CONCERN_CARDS.get(c, [])]:
        if f not in seen and f in card_titles:
            seen.add(f)
            cards_out.append({"file": f, "label": card_titles[f]})

    # ------------------------------------------------ do first
    first = []
    top_plan = plans_out[0] if plans_out else None
    top_card = next((c for c in cards_out if c["file"] != "first-aid-essentials.md"), None)
    if phase == "now":
        first.append({"text": "Anyone hurt or in danger? Call 911 or 112 if you can, and open the First aid card.",
                      "action": _card("first-aid-essentials.md")})
        if top_card:
            first.append({"text": f"Open the {top_card['label']} card: steps you can follow right now.",
                          "action": _card(top_card["file"])})
        if "water_stored" not in have:
            first.append({"text": "Fill bathtubs, pots and bottles with water now, while the taps still run.",
                          "action": _card("make-do.md")})
        if top_plan:
            first.append({"text": f"Make a plan for right now: {top_plan['title']}.",
                          "action": _act("plan", top_plan["id"], top_plan["title"])})
    elif phase == "after":
        first.append({"text": "Safety checks first: gas smell, downed power lines, damaged walls or roof, injuries.",
                      "action": _card("first-aid-essentials.md")})
        first.append({"text": "Treat tap water as unsafe until officials say otherwise: boil or bleach it.",
                      "action": _act("tool", "bleach", "Bleach for drinking water")})
        if top_plan:
            first.append({"text": f"Make a recovery plan: {top_plan['title']}.",
                          "action": _act("plan", top_plan["id"], top_plan["title"])})
    else:
        if top_plan:
            first.append({"text": f"Make your plan: {top_plan['title']}. It's saved on the drive and prints as a PDF.",
                          "action": _act("plan", top_plan["id"], top_plan["title"])})
        if host:
            first.append({"text": "Fill in Your household (contacts, medicines, meeting places), then print the binder.",
                          "action": _act("household", "", "Your household")})
        else:
            first.append({"text": "Write down your contacts, medicines and meeting places, and save the quick cards "
                                  "on this phone for when the Wi-Fi is gone.",
                          "action": _act("paper", "", "Paper backup")})
        if any(c in concerns for c in ("unrest", "war", "offgrid", "outage", "winter", "hurricane")):
            first.append({"text": "Agree on check-in times and a meeting place with family and neighbors.",
                          "action": _act("plan", "community", plan_titles.get("community", "Neighborhood network"))})
    if sit["nothing"]:
        first.insert(1 if phase == "now" else 0,
                     {"text": "Start with water: find the hidden water at home and make it safe (Make do card).",
                      "action": _card("make-do.md")})
    fuel = have & {"generator", "camp_stove", "heat_source"}
    if fuel and "co_alarm" not in have:
        first.insert(1 if phase == "now" else 0, {"text": "Run generators, grills and camp stoves outdoors only, 20 feet from windows. Headache, "
                                 "dizziness or nausea means fresh air now: it can be carbon monoxide.",
                         "action": _card("power-outage.md")})

    # ------------------------------------------------ what you have, and what it's good for
    notes = {
        "power_station": ("Runs phones, lights, a router and a laptop for days, or a fridge for about a day.",
                          _act("tool", "power", "Power budget")),
        "solar": ("Recharges batteries on sunny days: roughly 300 Wh a day for each 100 W of panels.",
                  _act("tool", "power", "Power budget")),
        "generator": ("Runs big loads. Outdoors only, 20 feet from windows, with a carbon monoxide alarm inside.",
                      _card("off-grid-power.md")),
        "power_banks": ("Keeps phones and radios going. Top them up whenever there's power.", None),
        "car": ("A charger, an AM/FM radio for emergency alerts and a warm shelter, used safely.",
                _card("satellite-gps-car.md")),
        "water_stored": (f"About {water_gal / n:.0f} days of water for {n}." if water_gal else
                         "Drinking water: plan on 1 gallon per person per day.", _act("tool", "water", "Water to store")),
        "filter": ("Makes stream and rain water safer. Most filters don't stop viruses: add bleach or boil when in doubt.",
                   _card("water.md")),
        "bleach": ("Treats drinking water: 8 drops of 6% bleach per gallon.", _act("tool", "bleach", "Bleach for drinking water")),
        "boil": ("Boiling for 1 minute makes clear water safe.", _card("water.md")),
        "food_2w": ("Two weeks of food covers most disasters.", None),
        "food_3m": ("Three months or more: rotate it and keep a list.", _act("tool", "supplies", "Supplies")),
        "garden": ("Fresh food. Grow calorie crops too: potatoes, squash, beans.", _card("grow-food-and-homestead.md")),
        "first_aid": ("Open it now and know what's inside.", _card("first-aid-essentials.md")),
        "tourniquet": ("Practice putting it on before you ever need it.", _act("tool", "tourniquet", "Tourniquet timer")),
        "med_device": ("Plan its power first.", _act("tool", "power", "Power budget")),
        "weather_radio": ("Official alerts with no internet.", _card("emergency-radio.md")),
        "walkies": ("Agree on a channel and check-in times.", _act("tool", "radio", "Radio channels")),
        "ham": ("Look up local repeaters and nets now.", _act("tool", "radio", "Radio channels")),
        "meshtastic": ("Plug one into this Mac to bring the mesh onto the Board.", _card("meshtastic.md")),
        "sat_phone": ("Try the satellite demo in your phone's settings now.", _card("satellite-gps-car.md")),
        "plb": ("Register it and check the battery date.", _card("satellite-gps-car.md")),
        "starlink": ("Internet where networks are down. Budget its power: 25 to 40 W for the Mini.", _act("tool", "power", "Power budget")),
        "heat_source": ("Heat without the grid. Keep dry wood and a carbon monoxide alarm.", None),
        "camp_stove": ("Cooking without power. Outdoors only.", None),
        "go_bags": ("Check them twice a year: water, medicine, documents, chargers.", _card("evacuation-and-leaving.md")),
    }
    have_out = [{"label": HAVE_LABEL[k], "text": notes[k][0], "action": notes[k][1]} for k in HAVE_LABEL if k in have and k in notes]
    if food_kcal:
        have_out.insert(0, {"label": "Food", "text": f"About {food_kcal / (n * 2000):.0f} days of food for {n}, from your supplies list.",
                            "action": _act("tool", "supplies", "Supplies")})

    # ------------------------------------------------ what's missing, most important first
    gaps = []

    def gap(priority, label, text, make_do, action=None):
        gaps.append({"priority": priority, "label": label, "text": text, "make_do": make_do, "action": action})

    days = 14 if phase == "ahead" else 3
    device_gap = needs_power(sit) and not have & {"power_station", "solar", "generator"}
    if device_gap:
        gap(0, "Power for the medical device", "A power station sized for the device, or a battery from its supplier. "
            "Register with your power company as someone who depends on it.",
            "The car can charge some devices through an inverter. Ask the supplier what's safe.", _act("tool", "power", "Power budget"))
    if fuel and "co_alarm" not in have:
        gap(0, "Carbon monoxide alarm", "A battery carbon monoxide alarm on every floor, and one where you sleep.",
            "Never run fuel-burning equipment indoors. Fresh air at the first headache or dizziness.")
    if "water_stored" not in have:
        gap(1, "Water", f"Store {n * days} gallons: 1 gallon per person per day for {days} days.",
            "Fill tubs and pots now. A water heater tank holds 30 to 80 gallons.", _act("tool", "water", "Water to store"))
    if not have & {"filter", "bleach", "boil"}:
        gap(1, "A way to make water safe", "Plain unscented bleach and a water filter.",
            "Sunlight works: clear plastic bottles in full sun for 6 hours.", _card("make-do.md"))
    if not have & {"food_3d", "food_2w", "food_3m"}:
        gap(2, "Food", f"Two weeks of food you already eat for {n}: about 2,000 calories per person per day.",
            "Eat the fridge first, then the freezer, then the pantry.", _act("tool", "supplies", "Supplies"))
    elif phase == "ahead" and not have & {"food_2w", "food_3m"}:
        gap(3, "More food", "Build up from 3 days to 2 weeks, a little each shopping trip.", "", _act("tool", "supplies", "Supplies"))
    if "first_aid" not in have:
        gap(2, "First aid kit", "Gloves, gauze, bandages, tape, pain relievers and any medicines you need.",
            "A clean cloth and firm pressure stop most bleeding.", _card("first-aid-essentials.md"))
    if "tourniquet" not in have and (any(c in concerns for c in ("war", "unrest", "lost", "offgrid")) or phase == "ahead"):
        gap(4, "Tourniquet", "A CAT or SOF-T Wide tourniquet, and a Stop the Bleed class.",
            "An improvised tourniquet is a last resort: see the Make do card.")
    if INSULIN.search(sit["needs"]):
        gap(1, "Insulin without a fridge", "In an emergency, insulin can stay unrefrigerated at 59 to 86 °F (15 to 30 °C) "
            "for up to 28 days (FDA). Keep it out of sun and heat, and never use insulin that froze.",
            "In dry air, a wet cloth around a clay pot keeps it cooler than the room.", _card("off-grid-power.md"))
    if (sit["needs"] or "med_device" in have) and "meds" not in have:
        gap(1, "Medicines", "Refill prescriptions early to keep two weeks on hand, and write down every dose.",
            "Ask your pharmacist about emergency refills.", _act("household", "", "Your household"))
    if "lights" not in have:
        gap(3, "Light", "A flashlight or headlamp for each person, with spare batteries.",
            "Solar garden lights brought inside make night lights.", None)
    if "weather_radio" not in have:
        gap(3, "Radio for news", "A battery or hand-crank AM/FM radio with the NOAA weather band.",
            "Your car radio gets AM and FM emergency broadcasts.", _card("emergency-radio.md"))
    if any(c in concerns for c in ("outage", "winter", "heat", "offgrid")) and not have & {"power_station", "solar", "generator"} \
            and not device_gap:  # the medical device's power covers it
        gap(2, "Backup power", "A power station (1,000 to 2,000 Wh) and a folding solar panel.",
            "Charge from the car, use power banks, and keep phones in airplane mode.", _act("tool", "power", "Power budget"))
    if "winter" in concerns and "heat_source" not in have:
        gap(2, "Safe heat", "Warm bedding for everyone, and a heat plan that doesn't put fuel indoors.",
            "One small room, blankets over windows, layers and hats.", _card("make-do.md"))
    if any(c in concerns for c in ("unrest", "war", "offgrid", "outage", "hurricane")) and not have & {"walkies", "ham", "meshtastic"}:
        gap(3, "Radios for your group", "Walkie-talkies or Meshtastic radios, with an agreed channel.",
            "Agree on meeting places and times, and use the Board here over Wi-Fi.", _act("tool", "radio", "Radio channels"))
    if any(c in concerns for c in ("lost", "offgrid", "water", "war")) and not have & {"sat_phone", "plb"}:
        gap(3, "A way to call for help without cell service", "A phone with satellite SOS, a satellite messenger or a PLB.",
            "Signal with a mirror, whistle or three fires.", _card("satellite-gps-car.md"))
    if any(c in concerns for c in ("leave", "war", "wildfire", "hurricane", "unrest")):
        if "go_bags" not in have:
            gap(2, "Go-bags", "A packed bag for each person: water, food, medicine, documents, chargers, cash.",
                "A backpack or pillowcase with the essentials beats nothing.", _card("evacuation-and-leaving.md"))
        if "documents" not in have:
            gap(3, "Documents", "Copies of IDs, passports and insurance in a waterproof bag, and scans on this drive.",
                "Photograph them with your phone now.")
        if "cash" not in have:
            gap(4, "Cash", "Small bills: card readers and ATMs fail when the power does.", "")
    if "skill_first_aid" not in have:
        gap(5, "First aid training", "Take CPR, first aid and Stop the Bleed classes.", "The First aid card covers the basics.",
            _card("first-aid-essentials.md"))
    gaps.sort(key=lambda g: g["priority"])

    # ------------------------------------------------ library items that fit (only installable ones are passed in)
    lib_out = []
    if library:
        wanted = [b for c in concerns for b in CONCERN_BANDS.get(c, [])]
        if sit["needs"] or "med_device" in have:
            wanted.insert(1, "medical")
        queues = {b: sorted((it for it in library if it.get("band") == b), key=lambda it: it.get("rank", 9))
                  for b in dict.fromkeys(wanted)}
        picks = []
        while len(picks) < 8 and any(queues.values()):
            for q in queues.values():  # one from each band in turn, most fitting band first
                if q and len(picks) < 8:
                    picks.append(q.pop(0))
        lib_out = [{"id": it["id"], "title": it["title"]} for it in picks]

    return {"headline": headline(sit), "phase": phase_label, "first": first[:5], "have": have_out,
            "gaps": gaps[:8], "plans": plans_out[:4], "cards": cards_out[:6], "library": lib_out,
            "people": n, "empty": is_empty(sit)}
