from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CHAR, BigInteger, Date, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str, pool_size: int = 10, max_overflow: int = 20) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class TrustedFlaggerORM(Base):
    __tablename__ = "trusted_flaggers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_form: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    email_domain: Mapped[str | None] = mapped_column(Text)
    address_raw: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    city: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    dsc_name: Mapped[str | None] = mapped_column(Text)
    dsc_country_code: Mapped[str | None] = mapped_column(CHAR(2))
    areas_of_expertise_raw: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    areas_of_expertise: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    designation_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_snapshot_url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_tf_country", "country_code"),
        Index("idx_tf_email_domain", "email_domain"),
        Index("idx_tf_status", "status"),
        Index("idx_tf_areas_gin", "areas_of_expertise", postgresql_using="gin"),
    )


class TrustedFlaggerEventORM(Base):
    __tablename__ = "trusted_flagger_events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tf_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[dict | None] = mapped_column(JSONB)
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    scrape_run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_tfe_tf", "tf_id", "occurred_at"),
        Index("idx_tfe_time", "occurred_at"),
    )


class ScrapeRunORM(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_response_status: Mapped[int | None] = mapped_column(Integer)
    source_content_hash: Mapped[str | None] = mapped_column(Text)
    rows_seen: Mapped[int | None] = mapped_column(Integer)
    rows_created: Mapped[int | None] = mapped_column(Integer)
    rows_updated: Mapped[int | None] = mapped_column(Integer)
    rows_removed: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    raw_html_snapshot_url: Mapped[str | None] = mapped_column(Text)
