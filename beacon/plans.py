"""Plan templates: structured, printable plans the brain fills in from the library."""

COMMON_FIELDS = [
    {"id": "location", "label": "Where are you?", "placeholder": "City, region or coordinates"},
    {"id": "people", "label": "Who's with you?", "placeholder": "e.g. 2 adults, 1 child, 1 dog, grandma uses a walker"},
    {"id": "resources", "label": "What do you have?", "placeholder": "Vehicle, fuel, cash, gear, medical needs, skills"},
]

TEMPLATES = [
    {"id": "evacuate", "title": "Evacuation (bug-out) plan", "icon": "🚗",
     "search": "evacuation routes go bag documents rally point vehicle fuel",
     "fields": [{"id": "destination", "label": "Where would you go?", "placeholder": "Family, cabin, another city"},
                {"id": "threat", "label": "From what?", "placeholder": "Wildfire, hurricane, unrest, chemical spill"}],
     "sections": ["Decision triggers (when to leave)", "Go-bag checklist per person", "Documents & money",
                  "Primary, secondary and tertiary routes (avoid choke points)", "Rally points & communication plan",
                  "Vehicle prep & fuel", "If you have to go on foot", "First 72 hours at the destination"]},
    {"id": "leave-country", "title": "Leaving the country", "icon": "🛂",
     "search": "evacuation abroad border crossing passport documents embassy travel route",
     "fields": [{"id": "destination", "label": "Destination country (if known)", "placeholder": "Country you have citizenship, residency or family in"},
                {"id": "documents", "label": "Passports & visas you hold", "placeholder": "e.g. US + Italian passports, valid until…"}],
     "sections": ["When leaving makes sense vs. sheltering", "Documents checklist (originals, copies, digital)",
                  "Money: cash, cards, currencies", "Route options: air, land border, sea; nearest legal crossings",
                  "Low-profile travel (blending in, situational awareness)", "Communication plan with family",
                  "Arrival: registering with consulate/authorities, first week", "What to leave behind"]},
    {"id": "shelter-in-place", "title": "Shelter in place (2 weeks)", "icon": "🏠",
     "search": "shelter in place water storage food power outage sanitation two weeks",
     "fields": [{"id": "threat", "label": "Why sheltering?", "placeholder": "Unrest, pandemic, fallout, blizzard"}],
     "sections": ["Water (1 gal/person/day) and how to stretch it", "Food plan by day", "Power, heat & light",
                  "Sanitation & hygiene without running water", "Medical & medications", "Security & keeping a low profile",
                  "Information: radio monitoring schedule", "Morale and routine"]},
    {"id": "winter-storm", "title": "Winter storm / ice storm", "icon": "❄️",
     "search": "winter storm power outage heat pipes frozen carbon monoxide hypothermia",
     "fields": [{"id": "home", "label": "Home & heating", "placeholder": "Gas furnace, fireplace, all-electric, generator…"}],
     "sections": ["Before it hits (48 hours)", "Staying warm safely (carbon monoxide!)", "Pipes and the house",
                  "Food and water", "If you must drive", "Hypothermia & frostbite: signs and first aid", "After the storm"]},
    {"id": "tornado", "title": "Tornado / severe storm", "icon": "🌪️",
     "search": "tornado shelter warning severe thunderstorm lightning safe room",
     "fields": [{"id": "home", "label": "Building type", "placeholder": "House with basement, apartment, mobile home, office"}],
     "sections": ["Warning signs and alerts", "Best shelter spot in your building", "Go-kit for the shelter spot",
                  "If you're in a car or outdoors", "After: injuries, gas leaks, downed lines", "Family reunification"]},
    {"id": "heat-wave", "title": "Heat wave / high humidity", "icon": "🔥",
     "search": "heat stroke heat exhaustion hydration cooling humidity heat index",
     "fields": [{"id": "home", "label": "Cooling available", "placeholder": "AC, fans only, no power"}],
     "sections": ["Who's most at risk in your group", "Keeping the house cool without power",
                  "Water and electrolytes", "Heat exhaustion vs. heat stroke (emergency)", "Working outside safely",
                  "Pets and food safety in heat"]},
    {"id": "flood-hurricane", "title": "Hurricane / flood", "icon": "🌊",
     "search": "hurricane flood evacuation storm surge water purification mold",
     "fields": [{"id": "home", "label": "Home situation", "placeholder": "Flood zone, elevation, distance from coast"}],
     "sections": ["Evacuate or stay: decision points", "Preparing the house", "Supplies", "During the storm",
                  "Flood water dangers (never drive through)", "After: water safety, mold, generators"]},
    {"id": "get-home", "title": "Get-home plan (from work or travel)", "icon": "🥾",
     "search": "get home bag walking route navigation compass water urban",
     "fields": [{"id": "destination", "label": "Where's home?", "placeholder": "Address or area"},
                {"id": "distance", "label": "Usual distance & route", "placeholder": "e.g. 25 miles on I-85"}],
     "sections": ["Get-home bag contents", "Routes on foot (avoid highways and crowds)", "Navigation without GPS",
                  "Water and rest stops", "Communication check-ins", "When to shelter instead"]},
    {"id": "food-30", "title": "30-day food & water plan", "icon": "🥫",
     "search": "food storage calories water storage rotation canning preservation",
     "fields": [{"id": "diet", "label": "Diet needs", "placeholder": "Allergies, infants, diabetics, pets"}],
     "sections": ["Daily calorie & water targets per person", "Shopping list by category",
                  "Storage, rotation and shelf life", "Cooking without power", "Water treatment & storage",
                  "Stretching supplies after day 30"]},
    {"id": "garden", "title": "Food garden plan for where you are", "icon": "🌱",
     "search": "vegetable garden planting season climate soil seeds calories crops",
     "fields": [{"id": "space", "label": "Space & sun", "placeholder": "e.g. 20x30 ft yard, full sun, clay soil"}],
     "sections": ["Your climate & growing season (from your location)", "Highest-calorie, easiest crops for it",
                  "Planting calendar by month", "Layout", "Water & soil", "Saving seeds", "Common pests & fixes"]},
    {"id": "wilderness", "title": "Wilderness survival (lost or stranded)", "icon": "🏕️",
     "search": "lost wilderness survival priorities shelter fire water signaling rescue",
     "fields": [{"id": "terrain", "label": "Terrain & weather", "placeholder": "Forest, desert, mountains; temperature"}],
     "sections": ["STOP: Stop, Think, Observe, Plan", "Priorities in order (rule of 3s)", "Shelter for these conditions",
                  "Fire", "Water", "Signaling for rescue", "Navigation: stay or move?", "Food (only when safe)"]},
    {"id": "home-security", "title": "Home security & self-defense plan", "icon": "🛡️",
     "search": "home security situational awareness self defense deterrence safe room de-escalation",
     "fields": [{"id": "home", "label": "Home & neighborhood", "placeholder": "House/apartment, rural/urban, neighbors"}],
     "sections": ["Deterrence: lighting, locks, visibility", "Low profile: don't advertise supplies",
                  "Safe room and family plan", "Avoidance & de-escalation first", "Self-defense: know your local laws",
                  "Firearm safety & secure storage (if you own them)", "Neighbors & mutual aid"]},
    {"id": "mind-body", "title": "Mind & body routine under stress", "icon": "🧘",
     "search": "stress resilience sleep breathing meditation exercise discipline holistic health",
     "fields": [{"id": "situation", "label": "What you're dealing with", "placeholder": "Outage, isolation, grief, long crisis"}],
     "sections": ["Daily schedule (anchor the day)", "Sleep", "Breathing & meditation (5 minutes)",
                  "Bodyweight training with no equipment", "Food & hydration", "Keeping kids and others steady",
                  "Purpose, faith and connection", "Warning signs to watch for in yourself and others"]},
]

PLAN_INSTRUCTIONS = """Write a practical, printable plan titled "{title}".
Use these sections as headings, in this order: {sections}.
Under each heading give short, specific numbered steps or checklists tailored to the details below.
Cite SOURCES inline like [2]. Put life-safety warnings first. If a detail is missing, state the \
assumption you made in one line. End with a 5-line "If you only remember this" summary.

DETAILS:
{details}"""


def get(template_id: str) -> dict | None:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)


def public_list() -> list[dict]:
    return [{"id": t["id"], "title": t["title"], "icon": t["icon"],
             "fields": COMMON_FIELDS + t["fields"]} for t in TEMPLATES]


def build(template: dict, answers: dict, place_context: str = "") -> tuple[str, str]:
    """Returns (search_query, instruction) for the brain."""
    lines = []
    for f in COMMON_FIELDS + template["fields"]:
        v = (answers.get(f["id"]) or "").strip()
        lines.append(f"- {f['label']} {v if v else '(not given)'}")
    if answers.get("notes"):
        lines.append(f"- Extra notes: {answers['notes'].strip()}")
    if place_context:
        lines.append(f"- Location facts: {place_context}")
    instruction = PLAN_INSTRUCTIONS.format(title=template["title"],
                                           sections="; ".join(template["sections"]),
                                           details="\n".join(lines))
    query = f"{template['search']} {answers.get('threat', '')} {answers.get('location', '')}".strip()
    return query, instruction
