"""Music service integrations: Spotify search, Odesli link fan-out, YT Music fallback.

All functions degrade gracefully: if Spotify credentials are missing the search
falls back to YT Music (ytmusicapi), and manual entry always works.
"""
from __future__ import annotations

import base64
import time
from typing import List, Dict, Optional

import requests

_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
_SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
_ODESLI_URL = "https://api.song.link/v1-alpha.1/links"

_token_cache: Dict[str, object] = {"value": None, "expires_at": 0.0}


def _get_secret(section: str, key: str, default: str = "") -> str:
    try:
        import streamlit as st

        return st.secrets.get(section, {}).get(key, default) or default
    except Exception:
        return default


def spotify_enabled() -> bool:
    return bool(_get_secret("spotify", "client_id") and _get_secret("spotify", "client_secret"))


def _spotify_token() -> Optional[str]:
    if not spotify_enabled():
        return None
    now = time.time()
    if _token_cache["value"] and now < float(_token_cache["expires_at"]):
        return str(_token_cache["value"])

    cid = _get_secret("spotify", "client_id")
    secret = _get_secret("spotify", "client_secret")
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    try:
        resp = requests.post(
            _SPOTIFY_TOKEN_URL,
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    _token_cache["value"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3600)) - 60
    return str(_token_cache["value"])


def search_spotify(query: str, limit: int = 8) -> List[Dict]:
    """Return a list of normalized track dicts from Spotify."""
    token = _spotify_token()
    if not token:
        return []
    market = _get_secret("spotify", "market", "IN")
    try:
        resp = requests.get(
            _SPOTIFY_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "track", "market": market, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("tracks", {}).get("items", [])
    except Exception:
        return []

    results = []
    for t in items:
        results.append(
            {
                "title": t.get("name", ""),
                "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                "album": t.get("album", {}).get("name", ""),
                "isrc": t.get("external_ids", {}).get("isrc", ""),
                "cover_url": (t.get("album", {}).get("images") or [{}])[0].get("url", ""),
                "spotify_url": t.get("external_urls", {}).get("spotify", ""),
                "source": "spotify",
            }
        )
    return results


def search_ytmusic(query: str, limit: int = 8) -> List[Dict]:
    """Fallback search using the unofficial ytmusicapi (no Spotify needed)."""
    try:
        from ytmusicapi import YTMusic

        yt = YTMusic()
        items = yt.search(query, filter="songs", limit=limit)
    except Exception:
        return []

    results = []
    for s in items[:limit]:
        vid = s.get("videoId")
        if not vid:
            continue
        results.append(
            {
                "title": s.get("title", ""),
                "artist": ", ".join(a["name"] for a in s.get("artists", [])),
                "album": (s.get("album") or {}).get("name", "") if s.get("album") else "",
                "isrc": "",
                "cover_url": (s.get("thumbnails") or [{}])[-1].get("url", ""),
                "ytmusic_url": f"https://music.youtube.com/watch?v={vid}",
                "spotify_url": "",
                "source": "ytmusic",
            }
        )
    return results


def search_tracks(query: str, limit: int = 8) -> List[Dict]:
    """Unified search: Spotify first, YT Music fallback."""
    if not query.strip():
        return []
    results = search_spotify(query, limit)
    if results:
        return results
    return search_ytmusic(query, limit)


def resolve_links(spotify_url: str = "", ytmusic_url: str = "") -> Dict[str, str]:
    """Fan out a single track URL to Amazon Music / YT Music / Apple / Spotify
    links using the free Odesli (song.link) API."""
    source = spotify_url or ytmusic_url
    out = {"spotify_url": spotify_url, "ytmusic_url": ytmusic_url, "amazon_url": "", "apple_url": ""}
    if not source:
        return out
    try:
        resp = requests.get(_ODESLI_URL, params={"url": source, "userCountry": "IN"}, timeout=12)
        resp.raise_for_status()
        links = resp.json().get("linksByPlatform", {})
    except Exception:
        return out

    def _url(platform: str) -> str:
        return links.get(platform, {}).get("url", "")

    out["spotify_url"] = out["spotify_url"] or _url("spotify")
    out["ytmusic_url"] = out["ytmusic_url"] or _url("youtubeMusic") or _url("youtube")
    out["amazon_url"] = _url("amazonMusic") or _url("amazonStore")
    out["apple_url"] = _url("appleMusic")
    return out
