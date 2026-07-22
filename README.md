# Deck Dupes & Combos

Paste multiple Magic: The Gathering decklists (or import public Deckstats decks) to see:

1. **Shared cards** across decks and which deck holds each physical copy
2. **Combos in each deck** via [Commander Spellbook](https://commanderspellbook.com/)
3. **Owned vs missing** via ManaBox / Deckstats CSV (or public Deckstats collection pull)
4. **Collection search** for cards you already own

## App tabs

| Tab | What it’s for |
| --- | --- |
| **Imports & Decks** | Upload CSVs, Deckstats collection/deck import, paste decklists, Quick assign, Analyze |
| **Shared & Locations** | Choose which decks to compare, view shared staples, and set “your copy is in” locations |
| **Lands** | Track basic land pools by count (owned vs each deck’s need / sleeved) |
| **Play a Deck** | Pick a deck to see which shared cards and basics to pull, plus other decks that share non-staple cards |
| **Combos** | Commander Spellbook results (after Analyze) |
| **Owned / Missing** | Cards you still need vs what’s in your collection |
| **Collection** | Search your imported collection by card name |

## Run locally

```bash
pip install -r requirements.txt
python server.py
```

Or double-click `start.bat`, then open [http://localhost:8080](http://localhost:8080).

Use `server.py` (not plain `http.server`) so Deckstats import works.

## Deploy on Render (free)

This repo includes `render.yaml` for a free web service.

1. Push this project to a **GitHub** repository (public is fine).
2. Go to [https://dashboard.render.com](https://dashboard.render.com) → sign up with GitHub.
3. **New** → **Blueprint** → select this repo  
   *or* **New** → **Web Service** → connect the repo and use:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `python server.py`
   - **Instance type:** Free
4. Deploy. Open the `https://….onrender.com` URL Render gives you.

Notes:

- Free tier **sleeps after ~15 minutes** idle; first load can take ~30–60s.
- Uploaded collection files live on the server disk and may reset on redeploy (no persistent disk on free).
- **Browser storage:** Decks, collection CSV data, mark-owned overrides, and staple assignments are also saved in **localStorage** on your device — they survive refresh and Render redeploys (but not a different browser/device).
- **Phone / quick assign:** Open the same Render URL on your phone. Use **Quick assign** (or the bottom bar on small screens) to update “your copy is in” without waiting for combo lookup. Deck lists and assignments sync via `/api/decks/session` and `/api/assignments` while the server instance is up. Add to home screen (`/#assign`) for a shortcut — PWA manifest included.
- Anyone with the URL can use the app and see whatever is stored in that instance’s `data/` folder.
- **Deckstats “Load decks”** calls Deckstats from the Render server. Cloudflare sometimes blocks that; if it fails, paste decklists manually (or load decks on your PC). Combos still work either way.

## Typical workflow

1. **Imports & Decks** → upload ManaBox/Deckstats CSV (and/or pull Deckstats collection)
2. Import Deckstats decks or paste lists
3. Click **Analyze decks** (or **Quick assign** on phone to skip combo lookup)
4. **Shared & Locations** → select the decks to compare, then set which deck has each shared staple
5. **Lands** → set owned basic counts and optional sleeved counts for the shared land pool
6. **Play a Deck** → pick the deck you want to play to see staples/basics to pull, and which other decks share interesting (non-staple) cards with it
7. Check **Combos** / **Owned / Missing** as needed
8. **Collection** → search any owned card by name

## Deckstats import

1. On **Imports & Decks**, paste your public profile URL, e.g. `https://deckstats.net/users/123456-YourName`
2. Click **Load decks**
3. Select decks → **Import selected**
4. Click **Analyze decks**

## Ownership (ManaBox + Deckstats)

1. **CSV:** Export from ManaBox or Deckstats → **Upload CSV** (saved in this browser + server `data/` when running locally)
2. **Deckstats live pull:** Needs a collection **number** (`…/collections/12345`), not plain `/collections`
3. Analyze (or Quick assign) → **Owned / Missing** tab
4. Cards already listed in another imported deck count as owned (shown under “sleeve for this deck,” not missing) — helpful when Deckstats collection export only has unbound cards
5. **Mark owned**, **Mark proxy**, or **Mark not owned** when your CSV is wrong / you don’t have the card
6. On **Imports**, use deck checkboxes + **Remove selected**, or each deck’s **Remove**, to drop lists you no longer need
7. **Shared & Locations** → pick which deck holds your **only copy** of each staple
8. **Collection** tab → search the merged inventory (ManaBox + Deckstats + overrides)

Private Deckstats collections can’t be pulled without login — use CSV export for those.

## Help, feedback, and support

- New visitors see a short tutorial; completion is remembered for one year in a browser cookie.
- Reopen the tutorial anytime from **How to use Card Checker** in the footer.
- Feedback: [isaacl.balogh@gmail.com](mailto:isaacl.balogh@gmail.com?subject=Card%20Checker%20Feedback)
- Optional support: [Ko-fi](https://ko-fi.com/gearsteak)
