from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Role(str, enum.Enum):
    caregiver = "caregiver"
    asha = "asha"
    manager = "manager"
    admin = "admin"


class Sex(str, enum.Enum):
    female = "female"
    male = "male"
    other = "other"


class DoseSource(str, enum.Enum):
    app = "app"
    paper = "paper"
    register = "register"


class NotificationChannel(str, enum.Enum):
    sms = "sms"
    ivr = "ivr"


class EntityType(str, enum.Enum):
    child = "child"
    caregiver = "caregiver"
    asha = "asha"
    manager = "manager"
    village = "village"
    team = "team"


class JobStatus(str, enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class EventStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    village_id: Mapped[Optional[int]] = mapped_column(ForeignKey("villages.id"), nullable=True, index=True)
    pw_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    preferred_language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    village: Mapped[Optional["Village"]] = relationship(back_populates="users")
    guardian_children: Mapped[list["Child"]] = relationship(
        back_populates="guardian",
        foreign_keys="Child.guardian_id",
    )
    asha_children: Mapped[list["Child"]] = relationship(
        back_populates="asha",
        foreign_keys="Child.asha_id",
    )


class Village(Base):
    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    users: Mapped[list[User]] = relationship(back_populates="village")
    children: Mapped[list["Child"]] = relationship(back_populates="village")
    sessions: Mapped[list["ImmunizationSession"]] = relationship(back_populates="village")


class Child(Base):
    __tablename__ = "children"
    __table_args__ = (
        Index("ix_children_village_id_active", "village_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dob: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sex: Mapped[Sex] = mapped_column(Enum(Sex), nullable=False)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"), nullable=False, index=True)
    guardian_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    asha_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    opt_in_sms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opt_in_ivr: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opt_in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    client_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    village: Mapped[Village] = relationship(back_populates="children")
    guardian: Mapped[User] = relationship(back_populates="guardian_children", foreign_keys=[guardian_id])
    asha: Mapped[User] = relationship(back_populates="asha_children", foreign_keys=[asha_id])
    doses: Mapped[list["Dose"]] = relationship(back_populates="child", cascade="all, delete-orphan")


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guardian_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint(
            "guardian_id",
            "child_id",
            "channel",
            "reminder_type",
            "vaccine_code",
            "scheduled_for",
            name="uq_notification_once_per_reminder",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guardian_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    child_id: Mapped[Optional[int]] = mapped_column(ForeignKey("children.id"), nullable=True, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel), nullable=False, index=True)
    reminder_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    vaccine_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="logged")
    scheduled_for: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationOptOut(Base):
    __tablename__ = "notification_opt_outs"
    __table_args__ = (UniqueConstraint("guardian_id", "channel", name="uq_notification_opt_out_guardian_channel"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guardian_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    opted_out_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Grievance(Base):
    __tablename__ = "grievances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guardian_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    child_id: Mapped[Optional[int]] = mapped_column(ForeignKey("children.id"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    contact_preference: Mapped[str] = mapped_column(String(40), nullable=False, default="asha")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VaccineSchedule(Base):
    __tablename__ = "vaccine_schedules"
    __table_args__ = (UniqueConstraint("vaccine_code", name="uq_vaccine_schedules_vaccine_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vaccine_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    age_due_days: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    endemic_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Dose(Base):
    __tablename__ = "doses"
    __table_args__ = (
        UniqueConstraint("child_id", "vaccine_code", name="uq_doses_child_vaccine"),
        Index("ix_doses_child_id_vaccine_code", "child_id", "vaccine_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id"), nullable=False, index=True)
    vaccine_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    given_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    batch_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"), nullable=True, index=True)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source: Mapped[DoseSource] = mapped_column(Enum(DoseSource), nullable=False)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    client_uuid: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, unique=True, index=True)
    client_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    child: Mapped[Child] = relationship(back_populates="doses")
    session: Mapped[Optional["ImmunizationSession"]] = relationship(back_populates="doses")


class ImmunizationSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    village: Mapped[Village] = relationship(back_populates="sessions")
    doses: Mapped[list[Dose]] = relationship(back_populates="session")
    stock_logs: Mapped[list["StockLog"]] = relationship(back_populates="session")


class StockLog(Base):
    __tablename__ = "stock_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vaccine_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"), nullable=False, index=True)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sessions.id"), nullable=True, index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped[Optional[ImmunizationSession]] = relationship(back_populates="stock_logs")


class Points(Base):
    __tablename__ = "points"
    __table_args__ = (Index("ix_points_entity_id", "entity_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(140), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(140), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetterLog(Base):
    __tablename__ = "dead_letter_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExternalRegisterRow(Base):
    __tablename__ = "external_register_rows"
    __table_args__ = (
        UniqueConstraint("source_name", "block", "vaccine_code", name="uq_external_register_source_block_vaccine"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    block: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    vaccine_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), nullable=False, default=EventStatus.pending, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class EventDelivery(Base):
    __tablename__ = "event_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "subscriber", name="uq_event_delivery_event_subscriber"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("outbox_events.id"), nullable=False, index=True)
    subscriber: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), nullable=False, default=EventStatus.pending, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
