# Lantern 🏮

**An offline emergency knowledge base on a USB stick.** Plug it into any MacBook, double-click, and ask questions: water, first aid, power outages, food, radio, repairs. A local AI answers from a library of survival manuals, offline encyclopedias and quick-reference cards, and cites the exact page or article it used. No internet, no installs, no accounts.

![Lantern answering a question with cited sources](docs/screenshot.png)

## What's on the drive

| Part | What it is |
|---|---|
| **AI engine** | [Ollama](https://ollama.com), bundled. Runs on Apple Silicon (fast, uses the GPU) and Intel Macs (slower, CPU only). |
| **Models** | Picks the **strongest model your Mac's memory can run**, automatically: `qwen3:4b` on 8 GB Macs, `qwen3:14b` on 16 GB+, optionally `qwen3.6:27b` on 32 GB+. You can switch in the sidebar. |
| **Offline libraries** | [Kiwix](https://kiwix.org) archives: post-disaster survival guides, field medicine, water, food preparation, knots, WikiMed, amateur radio and outdoors Q&A. Larger tiers add iFixit, home repair, off-grid energy, WikiHow and all of Wikipedia. Full list: [`catalog.json`](catalog.json). |
| **Manuals** | Public-domain US Army survival (ATP 3-50.21) and first aid (TC 4-02.1), FEMA *Are You Ready?*, plus any PDFs you add. |
| **Quick cards** | Plain-text cards that work even if the AI never starts: [emergency radio frequencies](library/manuals/cards/emergency-radio.md), [safe drinking water](library/manuals/cards/water.md), [power outage](library/manuals/cards/power-outage.md). |
| **Portable Python** | Its own Python for both chip types, so the Mac needs nothing installed. |

## Build the drive (once, on a Mac with internet)

1. **Get a USB drive.** 64 GB minimum for the essential tier; 128 GB for recommended; **256 GB** if you want all of Wikipedia. A USB 3 / USB-C drive makes models load much faster.
2. **Format it** in Disk Utility as **exFAT** (works on Mac and Windows) or **APFS** (Mac only). Name it `LANTERN`. FAT32 won't work: it can't hold files over 4 GB.
3. **Run the builder:**
   ```bash
   git clone https://github.com/<you>/lantern.git
   cd lantern
   ./scripts/build_usb.sh /Volumes/LANTERN                    # essential library + 2 models
   ./scripts/build_usb.sh /Volumes/LANTERN --tier recommended # + repair, energy, cooking, gardening
   ./scripts/build_usb.sh /Volumes/LANTERN --tier full        # + WikiHow and all of Wikipedia
   # add the 32 GB-Mac model:
   ./scripts/build_usb.sh /Volumes/LANTERN --models "qwen3:4b qwen3:14b qwen3.6:27b"
   ```
   It's safe to re-run: finished files are skipped and interrupted downloads resume. Re-run it every few months to refresh libraries.
4. **Add your own PDFs** to `Lantern/library/manuals/` (generator and inverter manuals, radio manual, medical records, house info, maps). Then click **Index manuals folder** in the app. Worth adding by hand: *Where There Is No Doctor* (free from Hesperian) and the USDA *Complete Guide to Home Canning*.

## Use it (any Mac, no internet)

1. Plug in the drive, open **LANTERN → Lantern**.
2. **First time on a Mac:** right-click `Lantern.command` → **Open** → **Open**. (macOS asks once for files from a USB stick.) After that, just double-click.
3. Your browser opens to Lantern. Keep the Terminal window open; closing it shuts Lantern down.

Click any citation like **[2]** to read the original page or article.

## Honest limits

- **The AI can be wrong.** It's told to answer from your library and cite it, and to say when it's guessing, but small models still make mistakes. For anything medical, electrical, or structural, **click the citation and read the source**. Call 911 if there is any way to reach them.
- **Speed.** On Apple Silicon expect a few seconds to start answering. Intel Macs and 8 GB machines are noticeably slower; the light model keeps it usable.
- **Power.** A laptop draws roughly 30–60 W while the AI is generating. Close Lantern when you don't need it to save battery.
- **Requires a reasonably recent macOS** (the version the current Ollama release supports).

## Develop on your own machine

```bash
pip install -r requirements.txt        # Python 3.10+
ollama pull qwen3:4b && ollama pull nomic-embed-text
python -m lantern                      # opens http://127.0.0.1:8642
python -m pytest -q                    # tests use a fake AI engine, no Ollama needed
```
Put `.zim` files in `library/zim/` and PDFs in `library/manuals/`. Settings live in `config.json` (created on first run). Model tiers are in [`lantern/models.py`](lantern/models.py).

## How it works

```
question ─▶ search Kiwix archives (full text) ─┐
         └▶ search your manuals (embeddings)  ─┴▶ numbered sources ─▶ local model ─▶ answer with [1][2] citations
```
Everything runs on `127.0.0.1`. Nothing is sent anywhere.

## License

MIT for the code. Downloaded libraries and manuals keep their own licenses: Kiwix archives are mostly CC BY-SA; US Army and FEMA publications are public domain. They're downloaded by the builder, not stored in this repo.
