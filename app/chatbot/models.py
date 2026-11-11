"""SQLAlchemy database models and connection for Chatbot package."""
from datetime import datetime, timezone
import json
from typing import List, Optional, Any
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Integer,
    Index,
    create_engine,
    TypeDecorator
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from .config import cfg

Base = declarative_base()


class JSONEncodedList(TypeDecorator):
    """Enables portable JSON/FloatArray storage across SQLite and PostgreSQL."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                return json.loads(value)
            except Exception:
                return None
        return None


class ChatKbChunk(Base):
    """Knowledge base chunk table for RAG."""
    __tablename__ = "chat_kb_chunks"

    id = Column(String(255), primary_key=True)  # file_id:heading_slug
    file_id = Column(String(100), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # glossary, mistake, platform, education
    title = Column(String(255), nullable=False)
    heading = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)  # sha256 of title, heading, content
    source_title = Column(String(255), nullable=True)
    source_url = Column(String(500), nullable=True)
    evidence = Column(String(50), nullable=True)
    embedding = Column(JSONEncodedList, nullable=True)
    embedding_model = Column(String(100), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )


class ChatMessage(Base):
    """Chat message history."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    route = Column(String(50), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    __table_args__ = (
        Index("ix_chat_messages_user_created", "user_id", "created_at"),
    )


class ChatNote(Base):
    """User notes and reflections."""
    __tablename__ = "chat_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    text = Column(Text, nullable=False)
    embedding = Column(JSONEncodedList, nullable=True)
    embedding_model = Column(String(100), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    __table_args__ = (
        Index("ix_chat_notes_user_created", "user_id", "created_at"),
    )


# Database Engine and Session creation
_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        db_url = cfg.effective_database_url
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        _engine = create_engine(db_url, connect_args=connect_args)
    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionFactory


def init_db(engine_override=None):
    """Idempotently creates chatbot tables if they do not exist."""
    target_engine = engine_override or get_engine()
    Base.metadata.create_all(bind=target_engine)


def get_db_session() -> Session:
    """Creates a new Session instance."""
    factory = get_session_factory()
    return factory()
