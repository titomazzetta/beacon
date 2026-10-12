"""The quick cards: their order on the card tabs, their short names, and the words that match a
question to them. Add a card by dropping a Markdown file in library/manuals/cards and adding one line
here; a card that isn't listed still appears, at the end, under its own heading."""

# (file, tab label), in the order the tabs appear
CARDS = [
    ("first-aid-essentials.md", "First aid"),
    ("severe-weather.md", "Weather"),
    ("water.md", "Water"),
    ("fire.md", "Fire"),
    ("power-outage.md", "Power outage"),
    ("car-emergency.md", "Car"),
    ("make-do.md", "Make do"),
    ("evacuation-and-leaving.md", "Evacuate"),
    ("defensive-perimeter.md", "Perimeter"),
    ("evasion-basics.md", "Evade"),
    ("low-profile-and-self-defense.md", "Self-defense"),
    ("navigation-and-nature-signs.md", "Navigation"),
    ("sea-and-island.md", "Sea and island"),
    ("morse-and-signals.md", "Signals"),
    ("satellite-gps-car.md", "Satellite and car"),
    ("emergency-radio.md", "Radio"),
    ("sanitation-and-hygiene.md", "Sanitation"),
    ("radiation-chemical-pandemic.md", "Radiation and chemical"),
    ("off-grid-power.md", "Off-grid power"),
    ("grow-food-and-homestead.md", "Grow food"),
    ("wild-food-and-game.md", "Wild food"),
    ("community-network.md", "Community"),
    ("meshtastic.md", "Mesh radio"),
    ("digital-safety.md", "Phone safety"),
    ("firearms-safety.md", "Firearms"),
    ("mind-and-body.md", "Mind and body"),
    ("BEACON-CLIFFNOTES.txt", "Cliff notes"),
]

LABELS = dict(CARDS)

# Questions about these topics also show the matching card above the AI's answer, so a vetted, static
# version of the steps is always one tap away. "word!" counts double. On a tie, the earlier card wins.
KEYWORDS = [
    ("first-aid-essentials.md", "bleed bleeding cpr choking choke burn burns stroke allergic anaphylaxis epipen unconscious "
     "breathing heart attack fracture broken bone splint snakebite snake bite poison wound "
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
    ("wild-food-and-game.md", "forage foraging edible mushroom mushrooms plant plants berries hunt hunting fish fishing "
     "trap trapping game deer"),
    ("firearms-safety.md", "gun guns firearm firearms rifle pistol revolver shotgun ammo bow arrow archery"),
    ("mind-and-body.md", "panic anxiety stress calm breathing sleep grief depressed depression meditation workout "
     "fitness"),
    ("community-network.md", "neighbors neighbor neighborhood community mutual aid check-in checkin roster barter trade "
     "group network"),
    ("meshtastic.md", "meshtastic! mesh! lora! node nodes"),
    ("off-grid-power.md", "solar panel panels battery batteries power station anker ecoflow jackery lifepo4 inverter "
     "watts watt-hours cpap oxygen concentrator insulin off-grid hydro turbine wind alternator "
     "dynamo"),
    ("sanitation-and-hygiene.md", "sanitation! toilet! toilets! latrine! sewage! flush hygiene handwashing diarrhea cholera! "
     "trash flies bucket"),
    ("radiation-chemical-pandemic.md", "radiation! nuclear! fallout! radioactive! iodide! chemical gas spill hazmat! pandemic! "
     "outbreak quarantine dirty bomb"),
    ("digital-safety.md", "phone opsec! privacy hacked hacking surveillance tracking encryption passcode! scam scams "
     "faraday metadata"),
    ("fire.md", "fire! campfire! tinder! kindling! firewood ferro flint! spark sparks matches lighter "
     "bow-drill friction ember embers"),
    ("make-do.md", "improvise! improvised! improvising! makeshift! homemade! household diy nothing sodis! duct "
     "tape foil trash bags zeer"),
    ("sea-and-island.md", "island! ocean! sea! raft! rafts! boat! sailboat! shipwreck! adrift! stranded beach coconut! "
     "lagoon drowning swimming current tide hook! hooks! fish fishing"),
    ("satellite-gps-car.md", "satellite! starlink! gps! plb! epirb! inreach! zoleo! coordinates offline-maps"),
    ("grow-food-and-homestead.md", "garden! gardening! farm! farming! homestead! homesteading! crops seeds seed compost! soil "
     "chickens! goats! rabbits livestock! canning preserve preserving harvest permaculture! "
     "orchard"),
]
