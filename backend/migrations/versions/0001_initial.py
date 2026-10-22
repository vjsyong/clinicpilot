"""Initial ClinicPilot schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clinics",
        sa.Column("clinic_id", sa.String(length=16), primary_key=True),
        sa.Column("clinic_name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("operating_hours", sa.String(length=500), nullable=False),
        sa.Column("cancellation_policy", sa.Text(), nullable=False),
        sa.Column("emergency_instructions", sa.Text(), nullable=False),
    )

    op.create_table(
        "doctors",
        sa.Column("doctor_id", sa.String(length=16), primary_key=True),
        sa.Column(
            "clinic_id",
            sa.String(length=16),
            sa.ForeignKey("clinics.clinic_id"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("specialty", sa.String(length=120), nullable=False),
        sa.Column("languages_spoken", sa.String(length=200), nullable=False),
        sa.Column("consultation_fee_cents", sa.Integer(), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
    )
    op.create_index("ix_doctors_clinic_id", "doctors", ["clinic_id"])

    op.create_table(
        "treatments",
        sa.Column("treatment_id", sa.String(length=16), primary_key=True),
        sa.Column("treatment_name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("pre_treatment_instructions", sa.Text(), nullable=False),
    )

    op.create_table(
        "patients",
        sa.Column("patient_id", sa.String(length=16), primary_key=True),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("dob", sa.Date(), nullable=False),
        sa.Column("gender", sa.String(length=32), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("known_allergies", sa.Text(), nullable=False),
        sa.Column("emergency_contact", sa.String(length=300), nullable=False),
    )

    op.create_table(
        "patient_treatment_history",
        sa.Column("record_id", sa.String(length=16), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(length=16),
            sa.ForeignKey("patients.patient_id"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            sa.String(length=16),
            sa.ForeignKey("doctors.doctor_id"),
            nullable=False,
        ),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("chief_complaint", sa.Text(), nullable=False),
        sa.Column("diagnosis", sa.String(length=300), nullable=False),
        sa.Column("prescribed_medication", sa.String(length=300), nullable=False),
        sa.Column("doctor_notes", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_patient_treatment_history_patient_id",
        "patient_treatment_history",
        ["patient_id"],
    )
    op.create_index(
        "ix_patient_treatment_history_doctor_id",
        "patient_treatment_history",
        ["doctor_id"],
    )

    op.create_table(
        "patient_bookings",
        sa.Column("booking_id", sa.String(length=16), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(length=16),
            sa.ForeignKey("patients.patient_id"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            sa.String(length=16),
            sa.ForeignKey("doctors.doctor_id"),
            nullable=False,
        ),
        sa.Column(
            "treatment_id",
            sa.String(length=16),
            sa.ForeignKey("treatments.treatment_id"),
            nullable=False,
        ),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("booking_time", sa.Time(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_patient_bookings_patient_id", "patient_bookings", ["patient_id"])
    op.create_index("ix_patient_bookings_doctor_id", "patient_bookings", ["doctor_id"])
    op.create_index("ix_patient_bookings_treatment_id", "patient_bookings", ["treatment_id"])
    op.create_index(
        "ux_patient_bookings_idempotency_key",
        "patient_bookings",
        ["idempotency_key"],
        unique=True,
    )

    op.create_table(
        "demo_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ux_demo_sessions_token_hash", "demo_sessions", ["token_hash"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "demo_session_id",
            sa.Integer(),
            sa.ForeignKey("demo_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.String(length=16),
            sa.ForeignKey("patients.patient_id"),
            nullable=False,
        ),
        sa.Column("messages_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversations_demo_session_id", "conversations", ["demo_session_id"])
    op.create_index("ix_conversations_patient_id", "conversations", ["patient_id"])

    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("client_message_id", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_chat_turns_conversation_message",
        ),
    )
    op.create_index("ix_chat_turns_conversation_id", "chat_turns", ["conversation_id"])

    op.create_table(
        "booking_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "doctor_id",
            sa.String(length=16),
            sa.ForeignKey("doctors.doctor_id"),
            nullable=True,
        ),
        sa.Column(
            "treatment_id",
            sa.String(length=16),
            sa.ForeignKey("treatments.treatment_id"),
            nullable=True,
        ),
        sa.Column("local_date", sa.String(length=10), nullable=True),
        sa.Column("local_time", sa.String(length=5), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("confirmation_message_id", sa.String(length=200), nullable=True),
        sa.Column("confirmation_version", sa.Integer(), nullable=True),
        sa.Column("authorized_turn_id", sa.String(length=36), nullable=True),
        sa.Column(
            "booking_id",
            sa.String(length=16),
            sa.ForeignKey("patient_bookings.booking_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_booking_drafts_conversation_id", "booking_drafts", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("booking_drafts")
    op.drop_table("chat_turns")
    op.drop_table("conversations")
    op.drop_table("demo_sessions")
    op.drop_table("patient_bookings")
    op.drop_table("patient_treatment_history")
    op.drop_table("patients")
    op.drop_table("treatments")
    op.drop_table("doctors")
    op.drop_table("clinics")
