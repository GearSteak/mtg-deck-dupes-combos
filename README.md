# Deck Dupes & Combos

Paste multiple Magic: The Gathering decklists (or import public Deckstats decks) to see:

1. **Shared cards** across decks
2. **Combos in each deck** via [Commander Spellbook](https://commanderspellbook.com/)
3. **Owned vs missing** via ManaBox / Deckstats CSV (or public Deckstats collection pull)

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
- Anyone with the URL can use the app and see whatever is stored in that instance’s `data/` folder.

## Deckstats import

1. Paste your public profile URL, e.g. `https://deckstats.net/users/123456-YourName`
2. Click **Load decks**
3. Select decks → **Import selected**
4. Click **Analyze decks**

## Ownership (ManaBox + Deckstats)

1. **CSV:** Export from ManaBox or Deckstats → **Upload CSV** (saved under `data/`)
2. **Deckstats live pull:** Needs a collection **number** (`…/collections/12345`), not plain `/collections`
3. Analyze decks → **Owned / missing** tab (sources are merged)
4. **Mark owned** saves local overrides

Private Deckstats collections can’t be pulled without login — use CSV export for those.
