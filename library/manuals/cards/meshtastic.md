# Meshtastic Mesh Radio Card

Meshtastic radios send short text messages and locations by long-range radio (LoRa), from radio to radio, with no cell service, no internet and, on the standard settings, no license. Every radio repeats messages for the others, so a few radios can cover a neighborhood or a valley.

## What you need
- One Meshtastic radio per person or household, plus the Meshtastic app on a phone (it talks to the radio by Bluetooth).
- The version for your region: **915 MHz** in the US and Canada, **868 MHz** in Europe.
- A spare battery, or a small solar panel for radios left on all the time.

## Set it up while you still have internet
1. Update the firmware (the web flasher needs internet once).
2. In the app, set the **Region** first (US in the United States). The radio won't transmit until you do.
3. Give the radio a name your people will recognize.
4. Leave the role on **CLIENT**. Use **CLIENT_MUTE** for an indoor radio that only talks to one better-placed radio. **CLIENT_BASE** suits one well-placed radio (attic or roof) that relays for your household's other radios: mark those as its favorites. Avoid ROUTER and REPEATER unless your local mesh asks for them; used without need, they cause problems for everyone.
5. Leave the hop limit at **3**.

## Make a private channel for your group
- The default channel (LongFast) uses a publicly known key, so anyone can read it. Use it to reach the wider mesh, not for private talk.
- Add a secondary channel with a **random 256-bit key** and share it by QR code in the app. Every radio in the group needs the same channel name and key.
- Your position goes to everyone on the primary channel. Turn position sharing off there, or share it only on your private channel (firmware 2.7.1 and later).
- Leave internet bridging (MQTT) off unless you mean to publish to the internet: it can put your mesh's locations online.

## Placement and range
- Height beats power. A radio in a high window, an attic or on a hilltop reaches much farther. Hills, buildings and thick trees block it.
- Expect under a mile in a dense town, and many miles with a clear line of sight.

## With Beacon
- Plug a radio into the Mac running Beacon with a **data** USB cable and connect it on the Board. Mesh messages appear on the Board, and Board posts can go out over the mesh.
- Anyone with a radio can check in: **SAFE The Garcias** or **HELP Unit 4B: out of insulin**.

## Troubleshooting
- Can't send anything: is the region set? Are both radios on the same channel name and key?
- Messages don't arrive: move a radio higher, check its battery, and keep the hop limit at 3.
- The Mac doesn't see the radio: some USB cables only charge. Try another cable and another port.

Sources: Meshtastic documentation (Initial Configuration, Channel Configuration, Configuration Tips); FCC Part 15 (license-free use of the 902–928 MHz band).
