"""Fab 5 — a curated-scarcity music sharing app.

Ask a friend for their BEST 5 songs (not a random dump). Each suggestion is tied
to a named person, so good curators build credibility over time. Great for
discovering songs across languages you don't speak.

Run locally:
    streamlit run App.py
"""
from __future__ import annotations

import secrets as _secrets

import streamlit as st

from db import (
    Feedback,
    Song,
    Suggester,
    Suggestion,
    SuggestionRequest,
    get_session,
    init_db,
)
from services import resolve_links, search_tracks, spotify_enabled

st.set_page_config(page_title="Fab 5 — Music Sharing", page_icon="🎵", layout="centered")
init_db()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_or_create_song(session, track: dict) -> Song:
    """Find an existing Song by ISRC/title+artist, else create it."""
    song = None
    if track.get("isrc"):
        song = session.query(Song).filter(Song.isrc == track["isrc"]).first()
    if not song:
        song = (
            session.query(Song)
            .filter(Song.title == track.get("title", ""), Song.artist == track.get("artist", ""))
            .first()
        )
    if not song:
        song = Song(
            isrc=track.get("isrc", ""),
            title=track.get("title", ""),
            artist=track.get("artist", ""),
            album=track.get("album", ""),
            cover_url=track.get("cover_url", ""),
            spotify_url=track.get("spotify_url", ""),
            ytmusic_url=track.get("ytmusic_url", ""),
        )
        session.add(song)
        session.flush()
    return song


def _ensure_links(session, song: Song) -> Song:
    """Lazily fan out cross-platform links via Odesli and cache them."""
    if song.links_resolved:
        return song
    links = resolve_links(spotify_url=song.spotify_url, ytmusic_url=song.ytmusic_url)
    song.spotify_url = links.get("spotify_url") or song.spotify_url
    song.ytmusic_url = links.get("ytmusic_url") or song.ytmusic_url
    song.amazon_url = links.get("amazon_url") or song.amazon_url
    song.apple_url = links.get("apple_url") or song.apple_url
    song.links_resolved = 1
    session.add(song)
    session.commit()
    return song


def _nav():
    pages = ["Home", "Create request", "Suggest songs", "Inbox"]
    # Deep-link: if a request id is in the URL, jump straight to the suggest page.
    qp = st.query_params
    default = "Suggest songs" if qp.get("r") else "Home"
    choice = st.sidebar.radio("Navigate", pages, index=pages.index(default))
    return choice


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_home():
    st.title("🎵 Fab 5")
    st.subheader("Get the 5 *best* songs from a friend — not a random dump.")
    st.markdown(
        """
        **How it works**
        1. **Create a request** — e.g. *"Your 5 best Bengali songs."*
        2. **Share the link** with a friend.
        3. They **enter their name** and pick **exactly 5 songs**.
        4. You get them in your **Inbox** with Spotify, Amazon Music & YouTube Music links.

        Because the choices are scarce *and named*, every pick counts — and good
        curators build **credibility** over time.
        """
    )
    if not spotify_enabled():
        st.info(
            "Spotify credentials not set — search falls back to YouTube Music, and "
            "manual entry always works. Add keys in `.streamlit/secrets.toml` for the "
            "best search experience."
        )


def page_create_request():
    st.title("Create a Suggest-5 request")
    with st.form("create_request"):
        owner_name = st.text_input("Your name", placeholder="e.g. Avinash")
        prompt = st.text_input(
            "What do you want?", placeholder="e.g. Your 5 best Bengali songs right now"
        )
        target_language = st.text_input("Target language (optional)", placeholder="Bengali")
        max_songs = st.number_input("Number of songs", min_value=1, max_value=10, value=5)
        submitted = st.form_submit_button("Create request & get link")

    if submitted:
        if not owner_name.strip():
            st.error("Please enter your name.")
            return
        session = get_session()
        try:
            req = SuggestionRequest(
                public_id=_secrets.token_urlsafe(8),
                owner_name=owner_name.strip(),
                prompt=prompt.strip(),
                target_language=target_language.strip(),
                max_songs=int(max_songs),
            )
            session.add(req)
            session.commit()
            public_id = req.public_id
        finally:
            session.close()

        st.success("Request created! Share this link with your friend:")
        st.code(f"?r={public_id}", language="text")
        st.caption(
            "On a deployed app this becomes a full URL like "
            f"`https://your-app.streamlit.app/?r={public_id}`. "
            "Open it (or paste the `?r=...` into the address bar) to try the suggest flow."
        )


def _render_search_and_pick(key_prefix: str) -> list:
    """Reusable search + 5-slot picker. Returns the current picked tracks list."""
    picks_key = f"{key_prefix}_picks"
    if picks_key not in st.session_state:
        st.session_state[picks_key] = []

    picks = st.session_state[picks_key]
    max_songs = st.session_state.get(f"{key_prefix}_max", 5)

    st.markdown(f"**Your picks ({len(picks)}/{max_songs})**")
    if picks:
        for i, p in enumerate(picks):
            cols = st.columns([5, 1])
            cols[0].write(f"🎵 **{p['title']}** — {p['artist']}")
            if cols[1].button("Remove", key=f"{key_prefix}_rm_{i}"):
                picks.pop(i)
                st.rerun()
    else:
        st.caption("No songs picked yet.")

    slots_left = max_songs - len(picks)
    if slots_left <= 0:
        st.success("All slots filled! You can remove one to swap.")
        return picks

    st.divider()
    tab_search, tab_manual = st.tabs(["🔎 Search", "✍️ Type it in"])

    with tab_search:
        query = st.text_input("Search a song or artist", key=f"{key_prefix}_q")
        if query:
            results = search_tracks(query, limit=8)
            if not results:
                st.caption("No results — try the 'Type it in' tab.")
            for j, r in enumerate(results):
                cols = st.columns([1, 4, 1])
                if r.get("cover_url"):
                    cols[0].image(r["cover_url"], width=48)
                cols[1].write(f"**{r['title']}** — {r['artist']}  \n*{r.get('album','')}*")
                if cols[2].button("Add", key=f"{key_prefix}_add_{j}"):
                    picks.append(r)
                    st.rerun()

    with tab_manual:
        with st.form(f"{key_prefix}_manual"):
            m_title = st.text_input("Song title")
            m_artist = st.text_input("Artist")
            m_album = st.text_input("Album (optional)")
            add_manual = st.form_submit_button("Add this song")
        if add_manual and m_title.strip():
            picks.append(
                {
                    "title": m_title.strip(),
                    "artist": m_artist.strip(),
                    "album": m_album.strip(),
                    "isrc": "",
                    "cover_url": "",
                    "spotify_url": "",
                    "ytmusic_url": "",
                    "source": "manual",
                }
            )
            st.rerun()

    return picks


def page_suggest():
    st.title("Suggest your best songs")
    qp = st.query_params
    public_id = qp.get("r", "")

    if not public_id:
        public_id = st.text_input("Enter the request code you were given (the `r=...` value)")
        if not public_id:
            st.info("Ask your friend for their request link, or enter the code above.")
            return

    session = get_session()
    try:
        req = (
            session.query(SuggestionRequest)
            .filter(SuggestionRequest.public_id == public_id)
            .first()
        )
        if not req:
            st.error("That request code wasn't found.")
            return

        st.markdown(f"### {req.owner_name} asks:")
        st.markdown(f"> **{req.prompt or 'Suggest me your best songs'}**")
        if req.target_language:
            st.caption(f"Language: {req.target_language}")

        st.session_state[f"suggest_{public_id}_max"] = req.max_songs

        # --- Named suggester (required, no login) ---
        st.markdown("#### Who's suggesting? *(required)*")
        name = st.text_input("Your name", key=f"name_{public_id}")
        handle = st.text_input(
            "Email or phone (optional — helps track your great taste across requests)",
            key=f"handle_{public_id}",
        )

        picks = _render_search_and_pick(f"suggest_{public_id}")

        st.divider()
        can_submit = bool(name.strip()) and len(picks) == req.max_songs
        if not name.strip():
            st.warning("Enter your name to submit — suggestions are named, not anonymous.")
        if len(picks) != req.max_songs:
            st.caption(f"Pick exactly {req.max_songs} songs to submit.")

        if st.button("Submit my picks 🎉", disabled=not can_submit, type="primary"):
            suggester = (
                session.query(Suggester)
                .filter(Suggester.name == name.strip(), Suggester.handle == handle.strip())
                .first()
            )
            if not suggester:
                suggester = Suggester(name=name.strip(), handle=handle.strip())
                session.add(suggester)
                session.flush()

            for track in picks:
                song = _get_or_create_song(session, track)
                session.add(
                    Suggestion(
                        request_id=req.id, suggester_id=suggester.id, song_id=song.id
                    )
                )
            session.commit()
            st.success(f"Thanks {name.strip()}! Your {req.max_songs} picks were sent. 🎵")
            st.session_state.pop(f"suggest_{public_id}_picks", None)
            st.balloons()
    finally:
        session.close()


def page_inbox():
    st.title("📥 Inbox")
    session = get_session()
    try:
        requests_list = (
            session.query(SuggestionRequest)
            .order_by(SuggestionRequest.created_at.desc())
            .all()
        )
        if not requests_list:
            st.info("No requests yet. Create one first.")
            return

        labels = {
            f"{r.prompt or 'Request'} — {r.owner_name} ({r.public_id})": r.id
            for r in requests_list
        }
        choice = st.selectbox("Pick a request", list(labels.keys()))
        req_id = labels[choice]

        suggestions = (
            session.query(Suggestion)
            .filter(Suggestion.request_id == req_id)
            .order_by(Suggestion.suggester_id)
            .all()
        )
        if not suggestions:
            st.info("No suggestions received yet. Share the link!")
            return

        # Group by suggester
        by_person: dict = {}
        for s in suggestions:
            by_person.setdefault(s.suggester, []).append(s)

        for person, items in by_person.items():
            st.subheader(f"👤 {person.name}" + (f"  ·  {person.handle}" if person.handle else ""))
            for s in items:
                song = _ensure_links(session, s.song)
                cols = st.columns([1, 4])
                if song.cover_url:
                    cols[0].image(song.cover_url, width=64)
                with cols[1]:
                    st.markdown(f"**{song.title}** — {song.artist}")
                    links = []
                    if song.spotify_url:
                        links.append(f"[Spotify]({song.spotify_url})")
                    if song.amazon_url:
                        links.append(f"[Amazon Music]({song.amazon_url})")
                    if song.ytmusic_url:
                        links.append(f"[YT Music]({song.ytmusic_url})")
                    if song.apple_url:
                        links.append(f"[Apple Music]({song.apple_url})")
                    st.markdown("  ·  ".join(links) if links else "_No streaming links found_")

                    fb = (
                        session.query(Feedback)
                        .filter(Feedback.suggestion_id == s.id)
                        .first()
                    )
                    saved = bool(fb and fb.saved)
                    if st.checkbox("⭐ Saved to my playlist", value=saved, key=f"save_{s.id}"):
                        if not fb:
                            fb = Feedback(suggestion_id=s.id)
                            session.add(fb)
                        fb.saved = 1
                        session.commit()
            st.divider()
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
PAGES = {
    "Home": page_home,
    "Create request": page_create_request,
    "Suggest songs": page_suggest,
    "Inbox": page_inbox,
}

choice = _nav()
PAGES[choice]()
