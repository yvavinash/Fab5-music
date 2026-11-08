"""Database layer and ORM models for the music-sharing MVP.

Uses SQLite by default (zero setup). Point [database].url in secrets.toml at a
Postgres instance (Neon/Supabase) to persist across deploys.
"""
from __future__ import annotations

import datetime as _dt
import os

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker


def _database_url() -> str:
    """Resolve the DB URL from Streamlit secrets, env var, or SQLite fallback."""
    try:
        import streamlit as st  # imported lazily so models stay usable outside Streamlit

        url = st.secrets.get("database", {}).get("url", "")
    except Exception:
        url = ""
    url = url or os.environ.get("DATABASE_URL", "")
    if not url:
        here = os.path.dirname(os.path.abspath(__file__))
        url = f"sqlite:///{os.path.join(here, 'music_app.db')}"
    return url


class Base(DeclarativeBase):
    pass


class SuggestionRequest(Base):
    """A 'please suggest me 5 songs' request created by the app owner."""

    __tablename__ = "suggestion_requests"

    id = Column(Integer, primary_key=True)
    public_id = Column(String(32), unique=True, nullable=False, index=True)
    owner_name = Column(String(120), nullable=False)
    prompt = Column(Text, default="")  # e.g. "Best 5 Bengali songs you love"
    target_language = Column(String(60), default="")
    max_songs = Column(Integer, default=5)
    created_at = Column(DateTime, default=_dt.datetime.utcnow)

    suggestions = relationship("Suggestion", back_populates="request")


class Suggester(Base):
    """A named friend who makes suggestions. Named (not anonymous) so credibility
    can accrue, but no password/login required."""

    __tablename__ = "suggesters"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    handle = Column(String(120), default="")  # optional email/phone to merge identities
    created_at = Column(DateTime, default=_dt.datetime.utcnow)

    suggestions = relationship("Suggestion", back_populates="suggester")

    __table_args__ = (UniqueConstraint("name", "handle", name="uq_suggester_identity"),)


class Song(Base):
    """A platform-neutral song identity, keyed on ISRC where available.
    Caches cross-platform deep-links resolved via Odesli."""

    __tablename__ = "songs"

    id = Column(Integer, primary_key=True)
    isrc = Column(String(32), index=True, default="")
    title = Column(String(300), nullable=False)
    artist = Column(String(300), default="")
    album = Column(String(300), default="")
    cover_url = Column(Text, default="")
    spotify_url = Column(Text, default="")
    amazon_url = Column(Text, default="")
    ytmusic_url = Column(Text, default="")
    apple_url = Column(Text, default="")
    links_resolved = Column(Integer, default=0)  # 0 = not yet fanned out via Odesli
    created_at = Column(DateTime, default=_dt.datetime.utcnow)


class Suggestion(Base):
    """One song suggested by one suggester for one request (max_songs enforced)."""

    __tablename__ = "suggestions"

    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, ForeignKey("suggestion_requests.id"), nullable=False)
    suggester_id = Column(Integer, ForeignKey("suggesters.id"), nullable=False)
    song_id = Column(Integer, ForeignKey("songs.id"), nullable=False)
    note = Column(Text, default="")  # why they picked it
    created_at = Column(DateTime, default=_dt.datetime.utcnow)

    request = relationship("SuggestionRequest", back_populates="suggestions")
    suggester = relationship("Suggester", back_populates="suggestions")
    song = relationship("Song")


class Feedback(Base):
    """Owner's reaction to a suggestion -> feeds the future credibility score."""

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    suggestion_id = Column(Integer, ForeignKey("suggestions.id"), nullable=False)
    saved = Column(Integer, default=0)  # added to my playlist
    rating = Column(Float, default=0.0)  # 0-5
    created_at = Column(DateTime, default=_dt.datetime.utcnow)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = _database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
    return _engine


def init_db():
    Base.metadata.create_all(get_engine())


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal()
