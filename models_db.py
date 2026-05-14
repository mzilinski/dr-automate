"""
SQLAlchemy-ORM-Modelle fuer dr-automate.

Trennung von Pydantic (``models.py``):
- ``models.py``    — Request/Response-Validation
- ``models_db.py`` — Persistenz

Encryption-Boundary (siehe ``crypto.py``):
- Plain  → alle Spalten, die in WHERE/ORDER BY landen
           (user_id, status, datum, zielort fuer Listenfilter, …).
- Encrypted → personenbezogen-sensible Felder
           (Adresse, IBAN/BIC, voll-serialisierte Reise-JSONs).
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from crypto import EncryptedJSON, EncryptedString
from db import Base


class DienstreiseStatus(str, enum.Enum):
    entwurf = "entwurf"
    eingereicht = "eingereicht"
    genehmigt = "genehmigt"
    abgerechnet = "abgerechnet"
    verworfen = "verworfen"


class AbrechnungStatus(str, enum.Enum):
    entwurf = "entwurf"
    eingereicht = "eingereicht"
    abgeschlossen = "abgeschlossen"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # remote_user kommt aus Authelias `Remote-User`-Header und ist die eindeutige
    # Identitaet ueber Sessions hinweg. Nicht verschluesselt, weil es als
    # Login-Key fuer Upsert/Lookup gebraucht wird.
    remote_user: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(254))
    display_name: Mapped[str | None] = mapped_column(String(200))
    tour_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[UserProfile | None] = relationship(
        "UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    dienstreisen: Mapped[list[Dienstreise]] = relationship(
        "Dienstreise", back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    vorname: Mapped[str | None] = mapped_column(String(100))
    nachname: Mapped[str | None] = mapped_column(String(100))
    abteilung: Mapped[str | None] = mapped_column(String(100))
    telefon: Mapped[str | None] = mapped_column(String(50))
    # Encrypted (DSGVO): Adresse, IBAN, BIC sind personenbezogene Finanz-/Wohndaten.
    adresse_privat: Mapped[str | None] = mapped_column(EncryptedString(2048))
    iban: Mapped[str | None] = mapped_column(EncryptedString(512))
    bic: Mapped[str | None] = mapped_column(EncryptedString(512))
    mitreisender_name_default: Mapped[str | None] = mapped_column(String(200))
    rkr_default: Mapped[str | None] = mapped_column(String(20))
    abrechnende_dienststelle: Mapped[str | None] = mapped_column(String(200))
    # BahnCards: JSON-Blob fuer flexible Struktur (Type, Klasse, etc.).
    bahncards: Mapped[dict | None] = mapped_column(EncryptedJSON(4096))
    ai_provider_default: Mapped[str | None] = mapped_column(String(50))
    # DeepSeek-API-Key: verschluesselt, weil API-Credentials wie Finanz-Daten
    # behandelt werden. Fallback in /extract, wenn kein X-DeepSeek-Key-Header
    # mitkommt. Multi-Device-Support: einmal eintragen, ueberall verfuegbar.
    deepseek_api_key: Mapped[str | None] = mapped_column(EncryptedString(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="profile")


class Dienstreise(Base):
    __tablename__ = "dienstreisen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    titel: Mapped[str] = mapped_column(String(200), nullable=False)
    zielort: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[DienstreiseStatus] = mapped_column(
        Enum(DienstreiseStatus, name="dienstreise_status"),
        default=DienstreiseStatus.entwurf,
        nullable=False,
        index=True,
    )
    # Volles Antrag-JSON (Pydantic-serialisiert) — enthaelt Reisedaten,
    # Befoerderung, Konfiguration, ggf. Bemerkungen. Verschluesselt, weil
    # Reise-Details inkl. Mitreisende/Adressen personenbezogen sind.
    antrag_json: Mapped[dict | None] = mapped_column(EncryptedJSON(65536))
    antrag_pdf_path: Mapped[str | None] = mapped_column(String(512))

    # DR-Genehmigung (vom Vorgesetzten/Personalstelle erteilt).
    genehmigung_datum: Mapped[date | None] = mapped_column(Date)
    genehmigung_aktenzeichen: Mapped[str | None] = mapped_column(String(100))

    start_datum: Mapped[date | None] = mapped_column(Date, index=True)
    ende_datum: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="dienstreisen")
    abrechnung: Mapped[Abrechnung | None] = relationship(
        "Abrechnung", back_populates="dienstreise", uselist=False, cascade="all, delete-orphan"
    )


class Abrechnung(Base):
    __tablename__ = "abrechnungen"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dienstreise_id: Mapped[int] = mapped_column(
        ForeignKey("dienstreisen.id", ondelete="CASCADE"), nullable=False, index=True, unique=True
    )
    status: Mapped[AbrechnungStatus] = mapped_column(
        Enum(AbrechnungStatus, name="abrechnung_status"), default=AbrechnungStatus.entwurf, nullable=False
    )
    abrechnung_json: Mapped[dict | None] = mapped_column(EncryptedJSON(65536))
    abrechnung_pdf_path: Mapped[str | None] = mapped_column(String(512))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    dienstreise: Mapped[Dienstreise] = relationship("Dienstreise", back_populates="abrechnung")


class AccountRequest(Base):
    """Account-Anfragen aus dem oeffentlichen Formular — nur als Audit-Trail."""

    __tablename__ = "account_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    begruendung: Mapped[str | None] = mapped_column(Text)
    remote_addr: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Wird true, sobald Admin den User in users_database.yml eintraegt.
    fulfilled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("idx_dienstreisen_user_status", Dienstreise.user_id, Dienstreise.status)
UniqueConstraint("user_id", name="uq_user_profiles_user")
