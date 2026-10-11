import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    license_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    subscription_status: Mapped[str] = mapped_column(String(32), default="active")
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    runs_quota: Mapped[int] = mapped_column(Integer, default=500)
    device_limit: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    activations: Mapped[list["Activation"]] = relationship(back_populates="license", cascade="all, delete-orphan")
    runs: Mapped[list["Run"]] = relationship(back_populates="license", cascade="all, delete-orphan")


class Activation(Base):
    __tablename__ = "activations"
    __table_args__ = (UniqueConstraint("license_id", "device_fingerprint", name="uq_license_device"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id", ondelete="CASCADE"), index=True)
    device_fingerprint: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    license: Mapped[License] = relationship(back_populates="activations")

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    license_id: Mapped[int] = mapped_column(ForeignKey("licenses.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    license: Mapped[License] = relationship(back_populates="runs")


def generate_license_key() -> str:
    raw = secrets.token_hex(12).upper()
    return f"TIA-{raw[:8]}-{raw[8:16]}-{raw[16:24]}"


def seed_license(settings: Settings) -> License:
    return License(
        license_key=generate_license_key(),
        subscription_status="active",
        runs_quota=settings.default_runs_per_period,
        device_limit=settings.default_device_limit,
        current_period_start=utcnow(),
        current_period_end=None,
    )
