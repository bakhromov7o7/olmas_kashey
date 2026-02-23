from datetime import datetime, timezone
from enum import Enum as PyEnum
from typing import Optional, Any, Dict, List
from sqlalchemy import BigInteger, String, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class EntityKind(str, PyEnum):
    USER = "user"
    GROUP = "group"
    CHANNEL = "channel"
    BOT = "bot"
    UNKNOWN = "unknown"

class MembershipState(str, PyEnum):
    NOT_JOINED = "not_joined"
    JOINED = "joined"
    LEFT = "left"
    REMOVED = "removed"  # Kicked/Banned

class KeywordUsage(Base):
    __tablename__ = "keyword_usage"

    keyword: Mapped[str] = mapped_column(String, primary_key=True)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
    use_count: Mapped[int] = mapped_column(default=1)

    def __repr__(self) -> str:
        return f"<KeywordUsage(keyword='{self.keyword}', count={self.use_count})>"

class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True) # Internal ID
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    kind: Mapped[EntityKind] = mapped_column(SqlEnum(EntityKind), index=True)
    
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    memberships: Mapped["Membership"] = relationship(back_populates="entity", uselist=False)
    events: Mapped[List["Event"]] = relationship(back_populates="entity")

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, tg_id={self.tg_id}, username='{self.username}', kind='{self.kind}')>"

class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    new_results_count: Mapped[int] = mapped_column(Integer, default=0) # Groups not previously in DB
    success: Mapped[bool] = mapped_column(default=False)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<SearchRun(id={self.id}, keyword='{self.keyword}', success={self.success})>"

class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), unique=True)
    state: Mapped[MembershipState] = mapped_column(SqlEnum(MembershipState), default=MembershipState.NOT_JOINED, index=True)
    
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    entity: Mapped["Entity"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:
        return f"<Membership(entity_id={self.entity_id}, state='{self.state}')>"

class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("entities.id"), nullable=True)
    type: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default={})
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    entity: Mapped[Optional["Entity"]] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return f"<Event(type='{self.type}', entity_id={self.entity_id})>"

class AllowlistItem(Base):
    __tablename__ = "allowlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String, unique=True, index=True) # username or stringified ID
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<AllowlistItem(target='{self.target}')>"
