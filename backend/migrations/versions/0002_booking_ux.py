"""Booking edit/delete support.

Revision ID: 0002_booking_ux
Revises: 0001_initial
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_booking_ux"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "patient_bookings", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("patient_bookings", sa.Column("deleted_reason", sa.Text(), nullable=True))
    op.add_column(
        "booking_drafts", sa.Column("editing_booking_id", sa.String(length=16), nullable=True)
    )
    op.create_table(
        "agent_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("demo_session_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("turn_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_events_demo_session_id", "agent_events", ["demo_session_id"])
    op.create_index("ix_agent_events_conversation_id", "agent_events", ["conversation_id"])
    op.create_index("ix_agent_events_turn_id", "agent_events", ["turn_id"])
    op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_agent_events_event_type", table_name="agent_events")
    op.drop_index("ix_agent_events_turn_id", table_name="agent_events")
    op.drop_index("ix_agent_events_conversation_id", table_name="agent_events")
    op.drop_index("ix_agent_events_demo_session_id", table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_column("booking_drafts", "editing_booking_id")
    op.drop_column("patient_bookings", "deleted_reason")
    op.drop_column("patient_bookings", "deleted_at")
