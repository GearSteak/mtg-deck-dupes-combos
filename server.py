#!/usr/bin/env python3
"""Local server for Deck Dupes & Combos + Deckstats + ManaBox collection."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
COLLECTION_PATH = DATA_DIR / "collection.json"  # ManaBox / CSV upload
DECKSTATS_COLLECTION_PATH = DATA_DIR / "deckstats_collection.json"
OVERRIDES_PATH = DATA_DIR / "owned_overrides.json"
ASSIGNMENTS_PATH = DATA_DIR / "assignments.json"
DECKS_SESSION_PATH = DATA_DIR / "decks_session.json"
SPELLBOOK_FIND_COMBOS = "https://backend.commanderspellbook.com/find-my-combos"

def _pip_install(package: str) -> None:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])


try:
    from curl_cffi import requests as curl_requests
except ImportError:
    try:
        _pip_install("curl_cffi")
        from curl_cffi import requests as curl_requests
    except Exception:
        curl_requests = None  # type: ignore

try:
    import cloudscraper
except ImportError:
    _pip_install("cloudscraper")
    import cloudscraper


SCRAPER = None
USE_CURL_CFFI = curl_requests is not None


def get_scraper():
    global SCRAPER
    if SCRAPER is None:
        SCRAPER = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
    return SCRAPER


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _response_has_inertia(resp) -> bool:
    text = getattr(resp, "text", None) or ""
    return 'data-page="app"' in text or "data-page='app'" in text


def fetch(url: str, params: dict | None = None):
    """Fetch URL, preferring curl_cffi (better against Cloudflare on cloud hosts)."""
    params = params or {}
    errors: list[str] = []
    if USE_CURL_CFFI:
        try:
            resp = curl_requests.get(
                url,
                params=params,
                impersonate="chrome",
                timeout=45,
            )
            if resp.status_code < 400 and (
                _response_has_inertia(resp) or not looks_like_cloudflare_challenge(resp.text)
            ):
                return resp
            errors.append(f"curl_cffi HTTP {resp.status_code}")
        except Exception as e:
            errors.append(f"curl_cffi: {e}")
    resp = get_scraper().get(url, params=params, timeout=45)
    if errors and resp.status_code >= 400:
        raise ValueError("; ".join(errors + [f"cloudscraper HTTP {resp.status_code}"]))
    return resp


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("\u200b", "").strip())


def name_key(name: str) -> str:
    return normalize_name(name).lower()


def parse_owner_from_input(raw: str) -> str:
    return parse_profile_input(raw)["owner_id"]


def parse_profile_input(raw: str) -> dict:
    """Extract owner id and preferred profile URLs from pasted text."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Paste a Deckstats profile URL or user id.")

    preferred: list[str] = []

    m = re.search(
        r"(https?://(?:www\.)?deckstats\.net/users/(\d+)(?:-[A-Za-z0-9_]+)?)",
        text,
        re.I,
    )
    if m:
        preferred.append(m.group(1).split("?")[0].rstrip("/"))
        owner_id = m.group(2)
        return {"owner_id": owner_id, "preferred_urls": preferred}

    m = re.search(
        r"(https?://(?:www\.)?deckstats\.net/decks/(\d+)(?:-[A-Za-z0-9_]+)?/?)",
        text,
        re.I,
    )
    if m:
        preferred.append(m.group(1).split("?")[0])
        owner_id = m.group(2)
        return {"owner_id": owner_id, "preferred_urls": preferred}

    m = re.search(r"deckstats\.net/users/(\d+)(?:-([A-Za-z0-9_]+))?", text, re.I)
    if m:
        owner_id = m.group(1)
        if m.group(2):
            preferred.append(f"https://deckstats.net/users/{owner_id}-{m.group(2)}")
        return {"owner_id": owner_id, "preferred_urls": preferred}

    m = re.search(r"deckstats\.net/decks/(\d+)", text, re.I)
    if m:
        return {"owner_id": m.group(1), "preferred_urls": preferred}

    if re.fullmatch(r"\d+", text):
        return {"owner_id": text, "preferred_urls": preferred}

    raise ValueError(
        "Could not find a user id. Paste something like "
        "https://deckstats.net/users/123456-YourName"
    )


def looks_like_cloudflare_challenge(html: str) -> bool:
    """True only for actual interstitial pages, not normal Deckstats HTML that mentions Cloudflare."""
    low = (html or "").lower()
    if 'data-page="app"' in low or "data-page='app'" in low:
        return False
    return (
        "just a moment" in low
        or "cf-browser-verification" in low
        or "cdn-cgi/challenge-platform" in low
        or ("attention required" in low and "cloudflare" in low)
    )


def extract_inertia_props(html: str) -> dict:
    patterns = [
        r'<script[^>]*data-page=["\']app["\'][^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        r'<script[^>]*type=["\']application/json["\'][^>]*data-page=["\']app["\'][^>]*>(.*?)</script>',
        r'<script[^>]*data-page=["\']app["\'][^>]*>(.*?)</script>',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.S | re.I)
        if m:
            data = json.loads(m.group(1))
            return data.get("props") or data
    if looks_like_cloudflare_challenge(html):
        raise ValueError(
            "Deckstats blocked this server behind Cloudflare. "
            "Paste decklists manually, or use Load decks from your local copy of the app."
        )
    raise ValueError(
        "Could not read Deckstats profile page (layout may have changed, or the host is blocked)."
    )


def profile_candidate_urls(owner_id: str, preferred_urls: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    for url in preferred_urls or []:
        u = (url or "").strip()
        if u and u not in candidates:
            candidates.append(u)
    for url in (
        f"https://deckstats.net/users/{owner_id}",
        f"https://deckstats.net/decks/{owner_id}/",
    ):
        if url not in candidates:
            candidates.append(url)
    return candidates


def decks_from_props(props: dict) -> list[dict]:
    folders = {
        f.get("id"): f.get("name")
        for f in (props.get("folders") or [])
        if isinstance(f, dict)
    }
    decks = []
    for d in props.get("decks") or []:
        if not isinstance(d, dict):
            continue
        deck_id = d.get("idsdeck") or d.get("id") or d.get("saved_id")
        if not deck_id:
            continue
        folder_id = d.get("folder_id") or 0
        decks.append(
            {
                "id": int(deck_id),
                "name": d.get("name") or f"Deck {deck_id}",
                "format": d.get("format_name") or "",
                "cards": d.get("number_cards_main") or d.get("number_main") or None,
                "folder": folders.get(folder_id)
                or ("Unfiled" if not folder_id else f"Folder {folder_id}"),
                "folder_id": folder_id,
            }
        )
    decks.sort(key=lambda x: (x["folder"].lower(), x["name"].lower()))
    return decks


def load_profile(owner_id: str, preferred_urls: list[str] | None = None) -> dict:
    candidates = profile_candidate_urls(owner_id, preferred_urls)
    errors: list[str] = []
    best: tuple[dict, list[dict], str] | None = None

    for url in candidates:
        try:
            r = fetch(url)
            if r.status_code >= 400:
                errors.append(f"HTTP {r.status_code} for {url}")
                continue
            props = extract_inertia_props(r.text)
            decks = decks_from_props(props)
            # Prefer a page that actually lists decks (user profile), not a single-deck editor
            if decks:
                best = (props, decks, url)
                break
            if best is None:
                best = (props, decks, url)
                errors.append(f"No deck list in page data for {url}")
        except Exception as e:
            errors.append(f"{url}: {e}")

    if best is None:
        detail = "; ".join(errors) if errors else "Failed to load profile."
        raise ValueError(
            detail
            + " Tip: paste the full profile URL (…/users/ID-Name). "
            "If this host is blocked by Deckstats, paste decklists manually."
        )

    props, decks, used = best
    if not decks and errors:
        # Loaded something but never found a decks array — surface why
        raise ValueError(
            "Could not find public decks. "
            + "; ".join(errors)
            + " Paste decklists manually if Deckstats is blocking this host."
        )

    profile = props.get("profile") or {}
    return {
        "owner_id": int(owner_id),
        "username": profile.get("username") or profile.get("name") or str(owner_id),
        "deck_count": profile.get("deck_count") or len(decks),
        "decks": decks,
        "source": used,
    }


def deck_to_list_text(deck: dict) -> str:
    commanders: list[tuple[int, str]] = []
    main: list[tuple[int, str]] = []

    for section in deck.get("sections") or []:
        for card in section.get("cards") or []:
            name = (card.get("name") or "").strip()
            if not name:
                continue
            amount = int(card.get("amount") or 1)
            if card.get("isCommander"):
                commanders.append((amount, name))
            else:
                main.append((amount, name))

    lines: list[str] = []
    if commanders:
        lines.append("Commander")
        for amount, name in commanders:
            lines.append(f"{amount} {name}")
        lines.append("")
    lines.append("Deck")
    for amount, name in main:
        lines.append(f"{amount} {name}")
    return "\n".join(lines).strip() + "\n"


def load_deck(owner_id: str, deck_id: str) -> dict:
    r = fetch(
        "https://deckstats.net/api.php",
        params={
            "action": "get_deck",
            "id_type": "saved",
            "owner_id": owner_id,
            "id": deck_id,
            "response_type": "json",
        },
    )
    if r.status_code >= 400:
        raise ValueError(f"Deckstats API HTTP {r.status_code}")
    try:
        deck = r.json()
    except Exception as e:
        raise ValueError(f"Invalid deck JSON: {e}") from e
    if not isinstance(deck, dict) or "sections" not in deck:
        raise ValueError("Unexpected deck response (deck may be private).")
    return {
        "id": int(deck_id),
        "owner_id": int(owner_id),
        "name": deck.get("name") or f"Deck {deck_id}",
        "list": deck_to_list_text(deck),
        "public": bool(deck.get("is_public", True)),
    }


# --- ownership collections ---

NAME_HEADERS = {
    "name",
    "card name",
    "card",
    "card_name",
    "cardname",
}
QTY_HEADERS = {
    "quantity",
    "qty",
    "count",
    "amount",
    "copies",
    "total quantity",
    "total qty",
}


def _pick_header(fieldnames: list[str], wanted: set[str]) -> str | None:
    lower_map = {h.lower().strip(): h for h in fieldnames if h}
    for key in wanted:
        if key in lower_map:
            return lower_map[key]
    return None


def add_card_qty(cards: dict[str, dict], raw_name: str, qty: int) -> None:
    display = normalize_name(raw_name)
    if not display:
        return
    key = name_key(display)
    if key not in cards:
        cards[key] = {"name": display, "quantity": 0}
    cards[key]["quantity"] += qty

    if " // " in display:
        for face in display.split(" // "):
            face = normalize_name(face)
            if not face:
                continue
            fk = name_key(face)
            if fk not in cards:
                cards[fk] = {"name": face, "quantity": 0, "face_of": display}
            cards[fk]["quantity"] = max(cards[fk]["quantity"], cards[key]["quantity"])
            cards[fk]["face_of"] = display


def cards_from_rows(rows: list[dict]) -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            qty = max(0, int(row.get("amount") or row.get("quantity") or 1))
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            continue
        add_card_qty(cards, name, qty)
    if not cards:
        raise ValueError("No cards found.")
    return cards


def parse_collection_csv(text: str) -> dict[str, dict]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")

    name_col = _pick_header(list(reader.fieldnames), NAME_HEADERS)
    qty_col = _pick_header(list(reader.fieldnames), QTY_HEADERS)
    if not name_col:
        raise ValueError(
            "Could not find a Name / card_name column (ManaBox or Deckstats CSV)."
        )

    cards: dict[str, dict] = {}
    for row in reader:
        raw_name = (row.get(name_col) or "").strip()
        if not raw_name:
            continue
        if raw_name.lower() in {"name", "card name", "card_name"}:
            continue
        qty = 1
        if qty_col:
            qraw = (row.get(qty_col) or "1").strip()
            try:
                qty = max(0, int(float(qraw)))
            except ValueError:
                qty = 1
        if qty <= 0:
            continue
        add_card_qty(cards, raw_name, qty)

    if not cards:
        raise ValueError("No cards found in CSV.")
    return cards


def summarize_cards(cards: dict[str, dict]) -> tuple[int, int]:
    unique = {k: v for k, v in cards.items() if not v.get("face_of")}
    return len(unique), sum(v["quantity"] for v in unique.values())


def save_source_collection(path: Path, cards: dict[str, dict], meta: dict) -> dict:
    ensure_data_dir()
    unique_n, total_n = summarize_cards(cards)
    payload = {
        "updated_at": utc_now(),
        "unique_cards": unique_n,
        "total_copies": total_n,
        "cards": {
            k: {
                "name": v["name"],
                "quantity": v["quantity"],
                **({"face_of": v["face_of"]} if v.get("face_of") else {}),
            }
            for k, v in cards.items()
        },
        **meta,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def parse_deckstats_collection_id(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Paste a public Deckstats collection URL or numeric id.")

    # Common logged-in URL with no collection id — fail early with guidance
    bare = re.sub(r"[?#].*$", "", text).rstrip("/")
    if re.search(r"deckstats\.net/collections?$", bare, re.I) or bare.lower().endswith(
        "/collections"
    ) or bare.lower().endswith("/collection"):
        raise ValueError(
            "That link is just the Collection page (no id). "
            "While logged into Deckstats, either: (1) Export CSV and Upload CSV here, or "
            "(2) open Network tab → filter collection_get → copy the idcollections number, "
            "or use a public share link like https://deckstats.net/collections/12345"
        )

    m = re.search(r"deckstats\.net/collections?/(\d+)", text, re.I)
    if m:
        return m.group(1)

    m = re.search(r"[?&]idcollections=(\d+)", text, re.I)
    if m:
        return m.group(1)

    m = re.search(r"[?&]id=(\d+)", text, re.I)
    if m and "deckstats" in text.lower():
        return m.group(1)

    # idcollections: 12345 or "idcollections":12345 from pasted network JSON
    m = re.search(r"idcollections[\"'\s:=]+(\d+)", text, re.I)
    if m:
        return m.group(1)

    # Deckstats CSV filenames sometimes contain ids
    m = re.search(r"collection[_\-]?(\d+)[_\-](\d+)", text, re.I)
    if m:
        # prefer the larger/latter group often used as collection id
        return m.group(2) if int(m.group(2)) > 0 else m.group(1)

    if re.fullmatch(r"\d+", text):
        return text

    # Profile / decks URL mistaken for collection (user id ≠ collection id)
    m = re.search(r"deckstats\.net/(?:users|decks)/(\d+)", text, re.I)
    if m:
        raise ValueError(
            f"That is your Deckstats profile (user id {m.group(1)}), not a collection. "
            "For ownership use Collection → Export CSV → Upload CSV here. "
            "Live pull needs a separate idcollections number from Network → collection_get "
            "(it is usually different from your user id)."
        )

    raise ValueError(
        "Could not find a collection id. Paste a number, a link like "
        "https://deckstats.net/collections/12345, or Upload CSV from Deckstats instead."
    )


def looks_like_deckstats_user_id(maybe_id: str) -> bool:
    """True if Deckstats has a public profile for this numeric id (not a collection)."""
    try:
        r = fetch(f"https://deckstats.net/users/{maybe_id}")
        if r.status_code != 200:
            return False
        # Profile URLs rewrite to /users/123-Name when the user exists
        return bool(re.search(rf"/users/{re.escape(maybe_id)}-", r.url or "", re.I))
    except Exception:
        return False


def collection_not_found_message(collection_id: str) -> str:
    if looks_like_deckstats_user_id(collection_id):
        return (
            f"{collection_id} is your Deckstats user id, not a collection id. "
            "Live pull needs the numeric idcollections value. "
            "Easiest: on Deckstats open Collection → Export CSV → Upload CSV here. "
            "Or while on Collection, DevTools → Network → filter collection_get → "
            "copy idcollections=… (it is usually not the same as your user id)."
        )
    return (
        f"Deckstats has no public collection with id {collection_id}. "
        "Use Collection → Export CSV → Upload CSV, or paste the real "
        "idcollections number from Network → collection_get."
    )


def fetch_deckstats_collection(collection_id: str) -> dict:
    all_rows: list[dict] = []
    meta = None
    chunk = 0
    while chunk < 500:
        r = fetch(
            "https://deckstats.net/api.php",
            params={
                "action": "collection_get",
                "idcollections": collection_id,
                "cards_type": "basic",
                "chunk_index": chunk,
            },
        )
        body = (r.text or "").strip()
        if r.status_code == 401 or "only available to registered users" in body.lower():
            raise ValueError(
                "That Deckstats collection requires login (it is probably private). "
                "Make it public, or export CSV from Deckstats and upload it."
            )
        if r.status_code >= 400:
            if "could not be found" in body.lower() or "not found" in body.lower():
                raise ValueError(collection_not_found_message(collection_id))
            raise ValueError(f"Deckstats collection HTTP {r.status_code}: {body[:180]}")
        try:
            data = r.json()
        except Exception as e:
            if "could not be found" in body.lower():
                raise ValueError(collection_not_found_message(collection_id)) from e
            raise ValueError(f"Invalid Deckstats JSON: {e}") from e
        if not data.get("success"):
            err = str(data.get("error") or data.get("message") or "collection_get failed")
            if "could not be found" in err.lower() or "not found" in err.lower():
                raise ValueError(collection_not_found_message(collection_id))
            raise ValueError(err)
        coll = data.get("collection")
        if not coll:
            raise ValueError(collection_not_found_message(collection_id))
        if meta is None:
            meta = coll
        rows = coll.get("cards") or []
        all_rows.extend(rows)
        if not coll.get("cards_more"):
            break
        chunk += 1

    cards = cards_from_rows(all_rows)
    title = (meta or {}).get("title") or f"Collection {collection_id}"
    return save_source_collection(
        DECKSTATS_COLLECTION_PATH,
        cards,
        {
            "source": "deckstats",
            "collection_id": int(collection_id),
            "title": title,
            "owner_id": (meta or {}).get("owner_id"),
            "is_public": bool((meta or {}).get("is_public", True)),
            "source_filename": f"deckstats:{collection_id}",
        },
    )


def load_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_collection_raw() -> dict | None:
    return load_json_file(COLLECTION_PATH)


def load_deckstats_collection_raw() -> dict | None:
    return load_json_file(DECKSTATS_COLLECTION_PATH)


def merge_card_maps(*maps: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cards in maps:
        for k, v in (cards or {}).items():
            if k not in out:
                out[k] = {
                    "name": v.get("name") or k,
                    "quantity": int(v.get("quantity") or 0),
                    **({"face_of": v["face_of"]} if v.get("face_of") else {}),
                }
            else:
                out[k]["quantity"] = max(out[k]["quantity"], int(v.get("quantity") or 0))
                if v.get("face_of") and not out[k].get("face_of"):
                    out[k]["face_of"] = v["face_of"]
                if not v.get("face_of") and out[k].get("face_of"):
                    out[k]["name"] = v.get("name") or out[k]["name"]
                    out[k].pop("face_of", None)
    return out


def load_overrides() -> dict:
    ensure_data_dir()
    data = load_json_file(OVERRIDES_PATH) or {}
    owned = data.get("owned") or []
    clean = []
    seen = set()
    for n in owned:
        disp = normalize_name(str(n))
        k = name_key(disp)
        if disp and k not in seen:
            seen.add(k)
            clean.append(disp)
    return {"owned": clean}


def save_overrides(owned_names: list[str]) -> dict:
    ensure_data_dir()
    clean = []
    seen = set()
    for n in owned_names:
        disp = normalize_name(str(n))
        k = name_key(disp)
        if disp and k not in seen:
            seen.add(k)
            clean.append(disp)
    payload = {"owned": clean, "updated_at": utc_now()}
    OVERRIDES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def collection_summary() -> dict:
    manabox = load_collection_raw()
    deckstats = load_deckstats_collection_raw()
    overrides = load_overrides()
    merged = merge_card_maps(
        (manabox or {}).get("cards") or {},
        (deckstats or {}).get("cards") or {},
    )
    unique_n, total_n = summarize_cards(merged) if merged else (0, 0)
    return {
        "ok": True,
        "has_collection": bool(manabox or deckstats),
        "unique_cards": unique_n,
        "total_copies": total_n,
        "overrides": overrides["owned"],
        "override_count": len(overrides["owned"]),
        "sources": {
            "manabox": {
                "present": bool(manabox),
                "updated_at": (manabox or {}).get("updated_at"),
                "source_filename": (manabox or {}).get("source_filename"),
                "unique_cards": (manabox or {}).get("unique_cards"),
                "total_copies": (manabox or {}).get("total_copies"),
            },
            "deckstats": {
                "present": bool(deckstats),
                "updated_at": (deckstats or {}).get("updated_at"),
                "title": (deckstats or {}).get("title"),
                "collection_id": (deckstats or {}).get("collection_id"),
                "unique_cards": (deckstats or {}).get("unique_cards"),
                "total_copies": (deckstats or {}).get("total_copies"),
            },
        },
    }


def find_combos(payload: dict) -> dict:
    """Proxy Commander Spellbook find-my-combos (browser CORS only allows localhost)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SPELLBOOK_FIND_COMBOS,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mtg-deck-dupes-combos/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise ValueError(f"Spellbook HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Spellbook unreachable: {e.reason}") from e


def collection_lookup_payload() -> dict:
    manabox = load_collection_raw()
    deckstats = load_deckstats_collection_raw()
    overrides = load_overrides()
    manabox_cards = (manabox or {}).get("cards") or {}
    deckstats_cards = (deckstats or {}).get("cards") or {}
    cards = merge_card_maps(manabox_cards, deckstats_cards)
    return {
        **collection_summary(),
        "cards": cards,
        "cards_by_source": {
            "manabox": manabox_cards,
            "deckstats": deckstats_cards,
        },
        "override_keys": [name_key(n) for n in overrides["owned"]],
    }


def load_assignments() -> dict:
    if not ASSIGNMENTS_PATH.exists():
        return {"assignments": {}, "updated_at": None}
    try:
        data = json.loads(ASSIGNMENTS_PATH.read_text(encoding="utf-8"))
        assignments = data.get("assignments") or {}
        if not isinstance(assignments, dict):
            assignments = {}
        return {
            "assignments": assignments,
            "updated_at": data.get("updated_at"),
        }
    except (json.JSONDecodeError, OSError):
        return {"assignments": {}, "updated_at": None}


def save_assignments(assignments: dict) -> dict:
    ensure_data_dir()
    clean = {}
    for key, deck_id in (assignments or {}).items():
        if not key:
            continue
        try:
            clean[str(key)] = int(deck_id)
        except (TypeError, ValueError):
            continue
    payload = {"assignments": clean, "updated_at": utc_now()}
    ASSIGNMENTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_decks_session() -> dict:
    if not DECKS_SESSION_PATH.exists():
        return {"decks": [], "updated_at": None}
    try:
        data = json.loads(DECKS_SESSION_PATH.read_text(encoding="utf-8"))
        decks = data.get("decks") or []
        if not isinstance(decks, list):
            decks = []
        clean = []
        for deck in decks:
            if not isinstance(deck, dict):
                continue
            try:
                deck_id = int(deck.get("id"))
            except (TypeError, ValueError):
                continue
            name = str(deck.get("name") or "").strip() or f"Deck {deck_id}"
            text = str(deck.get("text") or "")
            clean.append({"id": deck_id, "name": name, "text": text})
        return {"decks": clean, "updated_at": data.get("updated_at")}
    except (json.JSONDecodeError, OSError):
        return {"decks": [], "updated_at": None}


def save_decks_session(decks: list) -> dict:
    ensure_data_dir()
    clean = []
    seen_ids = set()
    for deck in decks or []:
        if not isinstance(deck, dict):
            continue
        try:
            deck_id = int(deck.get("id"))
        except (TypeError, ValueError):
            continue
        if deck_id in seen_ids:
            continue
        seen_ids.add(deck_id)
        name = str(deck.get("name") or "").strip() or f"Deck {deck_id}"
        text = str(deck.get("text") or "")
        clean.append({"id": deck_id, "name": name, "text": text})
    payload = {"decks": clean, "updated_at": utc_now()}
    DECKS_SESSION_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/deckstats/profile":
            try:
                qs = parse_qs(parsed.query)
                raw = (qs.get("url") or qs.get("q") or [""])[0]
                parsed_in = parse_profile_input(raw)
                self._json(
                    200,
                    {
                        "ok": True,
                        **load_profile(
                            parsed_in["owner_id"],
                            preferred_urls=parsed_in.get("preferred_urls"),
                        ),
                    },
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/deckstats/deck":
            try:
                qs = parse_qs(parsed.query)
                owner_id = (qs.get("owner_id") or [""])[0].strip()
                deck_id = (qs.get("deck_id") or [""])[0].strip()
                if not owner_id or not deck_id:
                    raise ValueError("owner_id and deck_id are required.")
                self._json(200, {"ok": True, **load_deck(owner_id, deck_id)})
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/collection":
            try:
                qs = parse_qs(parsed.query)
                full = (qs.get("full") or ["0"])[0] in ("1", "true", "yes")
                self._json(
                    200,
                    collection_lookup_payload() if full else collection_summary(),
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/assignments":
            try:
                data = load_assignments()
                self._json(
                    200,
                    {"ok": True, "assignments": data["assignments"], "updated_at": data["updated_at"]},
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/decks/session":
            try:
                data = load_decks_session()
                self._json(
                    200,
                    {"ok": True, "decks": data["decks"], "updated_at": data["updated_at"]},
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/combos":
            try:
                body = self._read_json_body()
                if not isinstance(body, dict):
                    raise ValueError("Expected JSON object with commanders/main.")
                data = find_combos(body)
                # Pass through Spellbook payload so the frontend can keep parsing it
                if isinstance(data, dict):
                    data = {**data, "ok": True}
                self._json(200, data if isinstance(data, dict) else {"ok": True, "results": data})
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/collection":
            try:
                body = self._read_json_body()
                csv_text = body.get("csv")
                if not csv_text or not str(csv_text).strip():
                    raise ValueError("No CSV content received.")
                filename = body.get("filename") or "collection.csv"
                cards = parse_collection_csv(str(csv_text))
                # Route Deckstats-style CSVs to the deckstats slot for clearer status
                lower_name = filename.lower()
                field_hint = str(csv_text).splitlines()[0].lower() if csv_text else ""
                is_deckstats_csv = (
                    "card_name" in field_hint
                    or "deckstats" in lower_name
                    or lower_name.startswith("collection_")
                )
                path = DECKSTATS_COLLECTION_PATH if is_deckstats_csv else COLLECTION_PATH
                source = "deckstats_csv" if is_deckstats_csv else "csv"
                meta = {"source": source, "source_filename": filename}
                if is_deckstats_csv:
                    meta["title"] = filename
                save_source_collection(path, cards, meta)
                self._json(
                    200,
                    {
                        "ok": True,
                        **collection_summary(),
                        "message": (
                            "Deckstats CSV saved locally."
                            if is_deckstats_csv
                            else "CSV collection saved locally."
                        ),
                    },
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/collection/deckstats":
            try:
                body = self._read_json_body()
                raw = (body.get("url") or body.get("id") or "").strip()
                collection_id = parse_deckstats_collection_id(raw)
                fetch_deckstats_collection(collection_id)
                self._json(
                    200,
                    {
                        "ok": True,
                        **collection_summary(),
                        "message": "Deckstats collection saved locally.",
                    },
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/collection/owned":
            try:
                body = self._read_json_body()
                overrides = load_overrides()
                owned = list(overrides["owned"])
                owned_keys = {name_key(n) for n in owned}

                for n in body.get("add") or []:
                    disp = normalize_name(str(n))
                    k = name_key(disp)
                    if disp and k not in owned_keys:
                        owned.append(disp)
                        owned_keys.add(k)

                remove_keys = {name_key(str(n)) for n in (body.get("remove") or [])}
                if remove_keys:
                    owned = [n for n in owned if name_key(n) not in remove_keys]

                saved = save_overrides(owned)
                self._json(
                    200,
                    {
                        "ok": True,
                        "overrides": saved["owned"],
                        "override_count": len(saved["owned"]),
                    },
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/assignments":
            try:
                body = self._read_json_body()
                assignments = body.get("assignments")
                if not isinstance(assignments, dict):
                    raise ValueError("Expected JSON object with assignments map.")
                saved = save_assignments(assignments)
                self._json(
                    200,
                    {
                        "ok": True,
                        "assignments": saved["assignments"],
                        "updated_at": saved["updated_at"],
                    },
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        if parsed.path == "/api/decks/session":
            try:
                body = self._read_json_body()
                decks = body.get("decks")
                if not isinstance(decks, list):
                    raise ValueError("Expected JSON object with decks array.")
                saved = save_decks_session(decks)
                self._json(
                    200,
                    {
                        "ok": True,
                        "decks": saved["decks"],
                        "updated_at": saved["updated_at"],
                    },
                )
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return

        self.send_error(404, "Not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/collection":
            try:
                qs = parse_qs(parsed.query)
                clear_overrides = (qs.get("overrides") or ["0"])[0] in (
                    "1",
                    "true",
                    "yes",
                )
                source = (qs.get("source") or ["all"])[0].lower()
                if source in ("all", "csv", "manabox") and COLLECTION_PATH.exists():
                    COLLECTION_PATH.unlink()
                if source in ("all", "deckstats") and DECKSTATS_COLLECTION_PATH.exists():
                    DECKSTATS_COLLECTION_PATH.unlink()
                if clear_overrides and OVERRIDES_PATH.exists():
                    OVERRIDES_PATH.unlink()
                self._json(200, {"ok": True, **collection_summary()})
            except Exception as e:
                traceback.print_exc()
                self._json(400, {"ok": False, "error": str(e)})
            return
        self.send_error(404, "Not found")


def main():
    ensure_data_dir()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving http://{HOST}:{PORT}")
    print("Deckstats decks/collection + ManaBox CSV (./data/). Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
