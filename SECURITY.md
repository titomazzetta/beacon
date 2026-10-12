# Security

Beacon is meant to be used in a crisis: on a Mac that may belong to someone else, on a Wi-Fi network shared with neighbors, by people who are scared and in a hurry. So the goal is protection that works without anyone configuring it, plus enough visibility that the person running Beacon always knows who is connected.

This document covers what Beacon protects, who it protects against, how each control works, what it deliberately doesn't do, and how to check all of it yourself. Every control listed here has an automated test in [`tests/test_beacon.py`](tests/test_beacon.py); the test names are given so you can read the proof.

## What Beacon protects

| Asset | Where it lives | Why it matters |
|---|---|---|
| Household info: people, medical needs, contacts, meeting places | `data/household.json` on the drive | Tells a stranger who lives where and who is vulnerable |
| Setup answers: what you're facing, who's with you, special needs, what you have, where | `data/situation.json` on the drive; a guest's answers stay in their own browser | The same, plus what's missing |
| Supplies inventory | `data/supplies.json` | Tells a stranger what you have |
| Saved plans and answers | `data/archive/` | Plans can include routes, destinations and documents |
| Board posts and the check-in roster | `data/board.json` | Shows who needs help |
| Linked Beacons and their sessions | `data/links.json` | A session lets one Beacon post to another's Board |
| Cached alerts and headlines | `data/updates.json` | They shape answers, so a bad feed must not become a way in |
| The Mac running Beacon, and its AI engine | the Mac | Must never become a server for strangers |
| The library: manuals, medical references, maps | `library/`, `maps/` | Tampered medical or safety text can hurt people |
| Availability | everything | It has to work with no internet, on battery, when it counts |

## Who it protects against

| Threat | Example | Main defenses |
|---|---|---|
| Someone who finds or steals the drive | Drive left in a car | Drive encryption check and instructions; one-click erase of household info |
| Someone on the same Wi-Fi | A neighbor's laptop, a guest's phone, a script | Off the network by default; code plus session tokens; rate limits; host-only actions; the connections monitor |
| A malicious website open in the same browser | A page that tries to talk to `127.0.0.1:8642` | Host-name allowlist (DNS rebinding); required request header (CSRF); strict Content-Security-Policy |
| Booby-trapped library content | A ZIM page with scripts; a prompt-injection paragraph | Sandboxed library pages; scripts served as inert text; all text escaped before display; an AI with no tools |
| Tampered downloads | A compromised mirror or network | HTTPS everywhere; publisher checksums; hash-locked packages; a pinned map tool; fingerprints rechecked by the health check |
| Someone with a Meshtastic radio | Spam or fake check-ins over the air | Radio text is untrusted input; private channels; guests can't transmit unless allowed |
| A linked Beacon, or a device pretending to be one | A script on the Wi-Fi with the code, posing as a Beacon | Links sign in with the code like a phone and get guest rights; what they send is checked and capped; each link shows in Connections and can be signed out |
| A hostile or broken feed | A malformed or spoofed alert feed | Off by default; HTTPS; size cap; entity declarations refused; plain text only; shown with its source and time |
| Beacon itself | Telemetry, over-logging | No analytics or accounts; the security log never records questions or answers |

## Controls

### Off the network by default

- Beacon's web server listens only on `127.0.0.1:8642`, and the AI engine (Ollama) only on `127.0.0.1:11435`, its own port so it never collides with another Ollama install.
- The health check (**Library > Health check**) doesn't just read the configuration: it connects to both ports through the Mac's own network address and passes only if the connection is refused. *Test: `test_health_check_knocks_on_its_own_ports_from_the_network_side`, `test_health_check_includes_security`.*

### Sharing on the Wi-Fi

Sharing is off until the person running Beacon turns it on. Then a second server listens on the local network (port 80, or 8643 if 80 is taken), advertised as `beacon.local` over Bonjour.

- **Joining**: a guest enters a 4-digit code shown on the Mac (or scans a QR code that contains it). The code comes from a cryptographic random generator and is compared in constant time.
- **Sessions**: a correct code is exchanged for a random 192-bit session token in an `HttpOnly`, `SameSite=Lax` cookie. Tokens live only in memory: stopping sharing, quitting Beacon or pressing **Sign everyone out** ends every session and issues a new code. The host can also sign out one device at a time. *Test: `test_guest_sessions_end_when_signed_out_or_stopped`.*
- **Guessing**: 5 wrong codes from one device within 5 minutes locks that device out. After 25 wrong codes from any devices, the code changes by itself and the host is alerted. So whoever is guessing gets at most 25 tries per code (a 1 in 400 chance), and every reset raises an alert on the Mac. *Test: `test_wrong_codes_are_rate_limited_and_rotate_the_code`.*
- **What guests can do**:

| | Beacon computer | Guests on the Wi-Fi |
|---|---|---|
| Ask, plans, quick cards, tools, maps, read the library | Yes | Yes |
| Post and check in on the Board | Yes | Yes, up to 12 posts per 10 minutes |
| Mark a post resolved | Any post | Only their own |
| Pin or remove posts | Yes | No |
| Save answers and plans | Private by default | Shared with everyone, up to 10 per hour |
| See saved items | All | Shared items only |
| See other people's network addresses on posts | Yes | No |
| Household info and supplies | Yes | No |
| Setup answers (Your next steps) | Saved on the drive | Kept on their own phone; Beacon never stores them |
| Updates from outside | Turn on, check now | Read only |
| Linked Beacons | Link, rename, unlink | No |
| Downloads, AI models, maps, indexing, choosing the AI model | Yes | No |
| Sharing settings, connections log, signing devices out | Yes | No |
| Mesh radio | Connect and configure | Send only if the host allows it |
| Quit, low power mode | Yes | No |

*Tests: `test_guests_need_the_code_and_cant_change_things`, `test_guests_share_answers_with_limits`, `test_plans_are_archived_privately_and_can_be_shared`, `test_board_checkins_posts_and_moderation`, `test_supplies_are_saved_for_the_host_only`.*

### Your setup answers

- The Beacon computer's answers are saved in `data/situation.json` and used for its own questions, plans and next steps. Guests asking for them get an empty answer; they can't save over them either.
- A guest's answers are kept in their phone's browser storage and sent along with each of their questions. Beacon uses them for that one answer and never writes them anywhere.
- Answers are cleaned on arrival: only known choices are kept, counts are bounded, and free text is trimmed, so a stored file or a prompt never carries anything else.
- **Erase all of it** (**Plan > Your household**) removes the setup answers too.

*Tests: `test_situation_is_private_and_shapes_answers`, `test_situation_answers_are_cleaned`.*

### Updates from outside

- **Off by default**, and only the Beacon computer can turn them on or start a check. While they're off, Beacon doesn't even check whether the Mac is online for them.
- When on, Beacon checks the feeds listed in `catalog.json` over HTTPS, at most every 30 minutes. Each request names the app, never the person or the Mac. The weather service also receives the setup's place as coordinates rounded to about a kilometer, and only for places in the US.
- Every answer is capped at 2 MB. XML with a document type or entity declaration is refused (that's how XML bombs work), and everything else is parsed as data, stripped to plain text, trimmed, and stored with its source and time. Only `http` and `https` links are kept, and they open in a new tab with no referrer.
- Phones on the Wi-Fi and the AI read the cached copy. The AI is told the updates may be incomplete or out of date and must never override safety steps.

*Tests: `test_updates_are_parsed_ranked_and_cached`, `test_updates_are_opt_in_host_controlled_and_reach_the_ai`.*

### Linked Beacons

- Linking needs the other Beacon's current code, and creates the same kind of session a phone gets, with the same guest limits. On the other Beacon, the link shows in **Connections** as "Linked Beacon (its name)" and can be signed out like any device.
- Only the Board crosses a link: check-ins and posts. Household info, setup answers, saved plans, settings and logs never do.
- Posts arriving over a link are untrusted input: each needs a well-formed origin (the Beacon it started on and its ID there), posts claiming to come from the receiving Beacon are dropped, times are held between a month ago and now, and anything that isn't a real number becomes now, text is trimmed like any post, and one device can add at most 200 posts per 10 minutes.
- Links stay on the local network and use the same plain HTTP as phones (see Accepted risks).

*Test: `test_linked_beacons_share_one_board`.*

### The connections monitor

The **Connections** panel (**Share > Connections**) shows, live:

- every signed-in device: type and browser, network address, hardware (MAC) address, when it joined, whether it's active, with a **Sign out** button;
- every security event: sign-ins, wrong codes, lockouts, automatic code changes, visits without the code, guests trying host-only actions, requests blocked as cross-site, and requests that used a host name Beacon doesn't answer to;
- devices nearby, read from the Mac's own address (ARP) table. Beacon never probes or scans other devices.

Warnings and alerts light up the Share button, play a tone, and raise a macOS notification (at most one every 20 seconds), so the host hears about them even with the browser hidden. Repeated identical events within a minute are counted rather than flooding the log.

Events are written to `data/logs/security.log` (one JSON object per line, capped at 1 MB) and can be exported as CSV for a report. Cells that start like a spreadsheet formula are neutralized in the export. **The log never contains questions, answers, searches, board text or codes**, and Beacon turns off the web server's own request log for the same reason. *Tests: `test_connections_are_logged_and_alerted`, `test_repeated_attempts_are_counted_not_flooded`, `test_security_log_never_holds_questions_or_answers`, `test_library_scripts_stay_inert_and_log_exports_are_formula_safe`.*

### Defenses against other websites

A web page in the same browser can try to send requests to `127.0.0.1:8642`. Beacon blocks the three standard routes:

- **DNS rebinding**: Beacon answers only to `localhost`, IP addresses, `beacon.local` and other `.local` names. A request under any other host name gets a 403 and an alert. *Test: `test_only_answers_to_its_own_names`.*
- **Cross-site request forgery**: every request that changes something must carry an `X-Beacon: 1` header and, if the browser sends an `Origin`, it must match. Other sites can't add that header without a CORS preflight, which Beacon never approves. *Test: `test_actions_need_beacons_own_header`.*
- **Script injection and clickjacking**: Beacon's pages ship a Content-Security-Policy with `script-src 'self'` (and no inline scripts at all), `connect-src 'self'`, `object-src 'none'`, `base-uri 'none'` and `frame-ancestors 'self'`. Every response also sets `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: SAMEORIGIN` and a Permissions-Policy that turns off camera, microphone, payment and USB access. API responses are `Cache-Control: no-store`. *Test: `test_security_headers_and_sandboxed_library_pages`.*

### Untrusted content

- **Library pages** (Kiwix/ZIM archives) are third-party HTML. They're served with a `sandbox` Content-Security-Policy that gives them a throwaway origin, no scripts, no network access and no form posts, so they can't read Beacon's data or call its API. Script files inside archives are served as plain text, so they can't run even if something tried to load them.
- **Your own files**: in the manuals folder, PDFs, Markdown and text open in the browser; anything else (HTML, SVG) downloads instead of rendering as a Beacon page.
- **AI output and everything else shown on screen** is HTML-escaped before Markdown formatting is applied, in the app and in printable pages.
- **Prompt injection**: library text goes into the AI's prompt, so a hostile paragraph could try to steer an answer. The AI has no tools: it can't open files, browse, run commands or change settings, so the worst case is a wrong answer. That's why every answer cites its sources and the interface tells people to check critical steps against them.
- **Size limits**: requests are capped at 2 MB, and questions, chat history, titles, board posts and saved items are trimmed to fixed lengths. *Test: `test_requests_are_size_limited`.*

### Downloads and the supply chain

| What | How it's checked |
|---|---|
| Portable Python (python-build-standalone) | SHA-256 against the release's published `SHA256SUMS` before unpacking |
| Ollama engine | SHA-256 against the release's `sha256sum.txt` |
| Python packages | `pip --require-hashes` with locked versions and hashes for Apple Silicon and Intel ([`scripts/requirements-mac.lock`](scripts/requirements-mac.lock)); binary wheels only |
| Meshtastic add-on | Its own hash lock, installed with `--no-deps` |
| Map tool (go-pmtiles) | Pinned to one release; the archive's SHA-256 is in the code and checked before the tool is saved or run |
| Kiwix archives | Checked against the publisher's `.sha256` file; a mismatch deletes the download |
| Every other download | SHA-256 fingerprint recorded on arrival; the health check re-hashes files up to 1 GB and flags any that changed |
| AI models | Pulled through Ollama, which verifies each layer's SHA-256 digest |
| Map viewer, fonts, QR code library | Vendored in the repo with versions in [`static/vendor/VERSIONS.txt`](static/vendor/VERSIONS.txt); nothing loads from a CDN |

All downloads use HTTPS. The drive builder writes a software bill of materials, `Beacon/data/SBOM.txt`, listing every program with its version and hash. *Tests: `test_downloads_are_fingerprinted_and_checked_against_the_publisher`, `test_integrity_check_spots_changed_files`, `test_map_tool_is_pinned_and_checked_before_it_runs`.*

### Data on the drive

- Beacon doesn't encrypt files itself; it relies on macOS drive encryption (APFS Encrypted, AES-XTS), which is stronger and better tested than anything an app could add. The drive builder, the health check and the status panel (the status button at the top of Beacon) all warn when the drive isn't encrypted, and [`START-HERE.txt`](START-HERE.txt) explains how to turn it on.
- **Erase all of it** (**Plan > Your household**) deletes the household file and the setup answers. *Test: `test_household_info_can_be_erased`.*
- Conversations aren't stored unless someone saves them. Browsers keep only small preferences (theme, text size, units, tool settings, the name used on the Board, running timers) and, on a guest's phone, that guest's own setup answers.
- No analytics, accounts or telemetry. Beacon contacts the internet only from the Beacon computer, and only for things a person started or turned on: in the Library tab, an "are we online?" check at most once a minute, catalog lookups and downloads; and, if updates are on, the update feeds at most every 30 minutes.

### Meshtastic radio (optional add-on)

- Messages from radios are untrusted text: length-limited, escaped on screen, never executed. Check-ins are parsed with a strict pattern (`SAFE name` or `HELP name: details`).
- Posts go out over the mesh only from the Beacon computer, or from guests if the host switches that on. *Test: `test_meshtastic_bridge_with_a_simulated_radio`.*
- With the add-on installed, Beacon looks for a newly plugged-in radio every few seconds by listing the Mac's USB serial devices (nothing is sent, and built-in ports such as Bluetooth are ignored) and connects to the one that just appeared. **Disconnect** sticks until the radio is unplugged, and **Connect automatically** on the Board turns this off. *Tests: `test_mesh_radio_plugs_and_plays_and_lends_its_gps`, `test_mesh_only_looks_at_usb_serial_ports`.*
- A radio with GPS gives the Mac its location for the Map and the radio tool. Signed-in guests can see that position, which is where the Beacon computer is.
- The Meshtastic library is GPL-3.0 and optional: build with `--no-mesh` to leave it out.

## Accepted risks

These are deliberate trade-offs, written down so nobody has to discover them.

- **Plain HTTP on the local network.** Traffic between phones and Beacon isn't encrypted by Beacon. Someone who can capture Wi-Fi traffic (an open network, or a WPA2 network whose password they know) could read answers and copy a session cookie. HTTPS with a self-signed certificate would make every phone show a full-page security warning, and teaching frightened people to click through security warnings does more harm than good. Mitigations: share only on a network your group controls (your own router, or the Mac's or a phone's hotspot; WPA3 if available), keep sharing on only while needed, and watch the connections monitor. No passwords or personal accounts ever cross the network: the only credential is the code and the session it buys. Optional HTTPS with a locally installed certificate is on the roadmap for groups that can set it up.
- **A 4-digit code.** It's short so people can type it from across a room. Its strength comes from the rate limits and automatic resets above, not from its length.
- **Werkzeug's built-in server.** It's fine for a household or a street, but not hardened against a determined flood. A hostile device on the Wi-Fi could slow Beacon down; the host can stop sharing, which closes the network port.
- **Device identity is approximate.** Network and hardware addresses can be spoofed, and phones often use a private hardware address per network. They help tell devices apart; they don't prove who someone is.
- **Everyone signed in sees the Board and roster.** That's its purpose. Share the code only with people you'd trust with that list, and don't post addresses, supplies or when a house will be empty.
- **Linked Beacons trust each other's Board.** A linked Beacon's posts appear as they were sent, labeled with the Beacon they came through, and that label is the sender's claim, not proof. Anyone with the code can link, just as anyone with it can post. Link only Beacons you know, and sign out any link you don't recognize.
- **Update feeds are third-party content.** A feed can be wrong, late, or compromised at its source. Beacon shows every item with its source and time, never acts on one, and tells the AI it may be out of date.
- **Mesh check-ins can be faked** by anyone who has the channel's key. On the public default channel that's everyone. Use a private channel with a random key, and confirm a "safe" in person when it matters.
- **Programs on the Mac itself are trusted.** Anything running as the same user can read the drive and talk to `127.0.0.1`. Beacon doesn't defend against malware already on the Mac.
- **Checksums come from the publisher's own site.** They catch corrupted or tampered mirrors and networks, not a compromised publisher account. Hash locks and the pinned map tool narrow that window for code.
- **The macOS quarantine flag is removed** from the bundled Python and AI engine, only after their checksums are verified, so they can run from the drive without prompts.
- **The AI can be wrong.** That's a safety problem more than a security one, and it's handled the same way: citations on every answer, quick cards that work with no AI, and plain-text fallbacks on the drive.

## Check it yourself

```bash
python -m pytest -q          # 78 tests; the AI engine, internet, Bonjour and radio are faked
```

On a Mac running Beacon:

```bash
# Only 127.0.0.1 should appear for 8642 (Beacon) and 11435 (AI engine).
# *:80 or *:8643 appears only while Wi-Fi sharing is on.
lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(80|8642|8643|11435) '

# DNS rebinding: an unknown host name is refused (403), and the Mac shows an alert.
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: evil.example" http://127.0.0.1:8642/api/status

# CSRF: an action without Beacon's header is refused (403) and logged in Connections.
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8642/api/quit
```

From another computer on the same Wi-Fi, `nmap -p 80,8642,8643,11435 <the Mac's address>` should show 8642 and 11435 closed; 80 or 8643 is open only while sharing. From a phone, enter five wrong codes: the phone is locked out for five minutes and the Mac shows a notification.

## Reporting a problem

Please use GitHub's private vulnerability reporting for this repository (the **Security** tab, then **Report a vulnerability**) rather than a public issue. Include what you did, what happened, and the Beacon version or commit. Reports about the controls above, the drive builder, or anything that exposes household data are especially welcome.
