"""SQLAlchemy models for the ClinicPilot schema.

The source datasets are preserved relationally with their original IDs. Prices
are stored as integer cents. Timestamps that are compared or ordered across
timezones (``starts_at_utc`` and the internal bookkeeping timestamps) use
:class:`UTCDateTime`, which normalizes to UTC on the way in and re-attaches the
UTC tzinfo on the way out (SQLite itself has no timezone-aware type).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetime stored as a naive UTC value in SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class Clinic(Base):
    __tablename__ = "clinics"

    clinic_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    clinic_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    operating_hours: Mapped[str] = mapped_column(String(500), nullable=False)
    cancellation_policy: Mapped[str] = mapped_column(Text, nullable=False)
    emergency_instructions: Mapped[str] = mapped_column(Text, nullable=False)


class Doctor(Base):
    __tablename__ = "doctors"

    doctor_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("clinics.clinic_id"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    specialty: Mapped[str] = mapped_column(String(120), nullable=False)
    languages_spoken: Mapped[str] = mapped_column(String(200), nullable=False)
    consultation_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    bio: Mapped[str] = mapped_column(Text, nullable=False)


class Treatment(Base):
    __tablename__ = "treatments"

    treatment_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    treatment_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    pre_treatment_instructions: Mapped[str] = mapped_column(Text, nullable=False)


class Patient(Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    known_allergies: Mapped[str] = mapped_column(Text, nullable=False)
    emergency_contact: Mapped[str] = mapped_column(String(300), nullable=False)


class PatientTreatmentHistory(Base):
    __tablename__ = "patient_treatment_history"

    record_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("patients.patient_id"), nullable=False, index=True
    )
    doctor_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("doctors.doctor_id"), nullable=False, index=True
    )
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(String(300), nullable=False)
    prescribed_medication: Mapped[str] = mapped_column(String(300), nullable=False)
    doctor_notes: Mapped[str] = mapped_column(Text, nullable=False)


class PatientBooking(Base):
    __tablename__ = "patient_bookings"

    booking_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("patients.patient_id"), nullable=False, index=True
    )
    doctor_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("doctors.doctor_id"), nullable=False, index=True
    )
    treatment_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("treatments.treatment_id"), nullable=False, index=True
    )
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    booking_time: Mapped[time] = mapped_column(Time, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class DemoSession(Base):
    __tablename__ = "demo_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    demo_session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("demo_sessions.id"), nullable=False, index=True
    )
    patient_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("patients.patient_id"), nullable=False, index=True
    )
    messages_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ChatTurn(Base):
    __tablename__ = "chat_turns"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "client_message_id", name="uq_chat_turns_conversation_message"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False, index=True
    )
    client_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class BookingDraft(Base):
    __tablename__ = "booking_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    doctor_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("doctors.doctor_id"), nullable=True
    )
    treatment_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("treatments.treatment_id"), nullable=True
    )
    local_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    local_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    starts_at_utc: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirmation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authorized_turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    booking_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("patient_bookings.booking_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
