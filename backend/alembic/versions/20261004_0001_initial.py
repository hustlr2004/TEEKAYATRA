"""initial schema

Revision ID: 20261004_0001
Revises:
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa


revision = "20261004_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("villages", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("block", sa.String(100), nullable=False), sa.Column("district", sa.String(100), nullable=False))
    op.create_index(op.f("ix_villages_block"), "villages", ["block"])
    op.create_index(op.f("ix_villages_district"), "villages", ["district"])
    op.create_table("vaccine_schedules", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("vaccine_code", sa.String(40), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("age_due_days", sa.Integer(), nullable=False), sa.Column("window_days", sa.Integer(), nullable=False), sa.Column("endemic_only", sa.Boolean(), nullable=False), sa.UniqueConstraint("vaccine_code", name="uq_vaccine_schedules_vaccine_code"))
    op.create_index(op.f("ix_vaccine_schedules_age_due_days"), "vaccine_schedules", ["age_due_days"])
    op.create_index(op.f("ix_vaccine_schedules_vaccine_code"), "vaccine_schedules", ["vaccine_code"])
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("role", sa.Enum("caregiver", "asha", "manager", "admin", name="role"), nullable=False), sa.Column("name", sa.String(100), nullable=False), sa.Column("phone", sa.String(255), nullable=False), sa.Column("village_id", sa.Integer(), sa.ForeignKey("villages.id"), nullable=True), sa.Column("pw_hash", sa.String(255), nullable=False), sa.Column("preferred_language", sa.String(8), nullable=False))
    op.create_index(op.f("ix_users_phone"), "users", ["phone"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"])
    op.create_index(op.f("ix_users_village_id"), "users", ["village_id"])
    op.create_table("children", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("dob", sa.Date(), nullable=False), sa.Column("sex", sa.Enum("female", "male", "other", name="sex"), nullable=False), sa.Column("village_id", sa.Integer(), sa.ForeignKey("villages.id"), nullable=False), sa.Column("guardian_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("asha_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("opt_in_sms", sa.Boolean(), nullable=False), sa.Column("opt_in_ivr", sa.Boolean(), nullable=False), sa.Column("opt_in_app", sa.Boolean(), nullable=False), sa.Column("client_updated_at", sa.DateTime(timezone=True), nullable=True), sa.Column("conflict_flag", sa.Boolean(), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_children_asha_id"), "children", ["asha_id"])
    op.create_index(op.f("ix_children_dob"), "children", ["dob"])
    op.create_index(op.f("ix_children_guardian_id"), "children", ["guardian_id"])
    op.create_index(op.f("ix_children_village_id"), "children", ["village_id"])
    op.create_index("ix_children_village_id_active", "children", ["village_id", "deleted_at"])
    op.create_index(op.f("ix_children_deleted_at"), "children", ["deleted_at"])
    op.create_table("consents", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("guardian_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("purpose", sa.String(100), nullable=False), sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_consents_guardian_id"), "consents", ["guardian_id"])
    op.create_index(op.f("ix_consents_purpose"), "consents", ["purpose"])
    op.create_table("notification_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("guardian_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("child_id", sa.Integer(), sa.ForeignKey("children.id"), nullable=True), sa.Column("channel", sa.Enum("sms", "ivr", name="notificationchannel"), nullable=False), sa.Column("reminder_type", sa.String(40), nullable=False), sa.Column("vaccine_code", sa.String(40), nullable=True), sa.Column("language", sa.String(8), nullable=False), sa.Column("recipient_phone", sa.String(255), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("scheduled_for", sa.Date(), nullable=False), sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False), sa.UniqueConstraint("guardian_id", "child_id", "channel", "reminder_type", "vaccine_code", "scheduled_for", name="uq_notification_once_per_reminder"))
    op.create_index(op.f("ix_notification_logs_channel"), "notification_logs", ["channel"])
    op.create_index(op.f("ix_notification_logs_child_id"), "notification_logs", ["child_id"])
    op.create_index(op.f("ix_notification_logs_guardian_id"), "notification_logs", ["guardian_id"])
    op.create_index(op.f("ix_notification_logs_reminder_type"), "notification_logs", ["reminder_type"])
    op.create_index(op.f("ix_notification_logs_scheduled_for"), "notification_logs", ["scheduled_for"])
    op.create_index(op.f("ix_notification_logs_vaccine_code"), "notification_logs", ["vaccine_code"])
    op.create_table("notification_opt_outs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("guardian_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("channel", sa.Enum("sms", "ivr", name="notificationchannel"), nullable=False), sa.Column("reason", sa.String(80), nullable=False), sa.Column("opted_out_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False), sa.UniqueConstraint("guardian_id", "channel", name="uq_notification_opt_out_guardian_channel"))
    op.create_index(op.f("ix_notification_opt_outs_channel"), "notification_opt_outs", ["channel"])
    op.create_index(op.f("ix_notification_opt_outs_guardian_id"), "notification_opt_outs", ["guardian_id"])
    op.create_table("grievances", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("guardian_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True), sa.Column("child_id", sa.Integer(), sa.ForeignKey("children.id"), nullable=True), sa.Column("category", sa.String(80), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("contact_preference", sa.String(40), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False))
    op.create_index(op.f("ix_grievances_category"), "grievances", ["category"])
    op.create_index(op.f("ix_grievances_child_id"), "grievances", ["child_id"])
    op.create_index(op.f("ix_grievances_guardian_id"), "grievances", ["guardian_id"])
    op.create_index(op.f("ix_grievances_status"), "grievances", ["status"])
    op.create_table("sessions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("village_id", sa.Integer(), sa.ForeignKey("villages.id"), nullable=False), sa.Column("date", sa.Date(), nullable=False))
    op.create_index(op.f("ix_sessions_date"), "sessions", ["date"])
    op.create_index(op.f("ix_sessions_village_id"), "sessions", ["village_id"])
    op.create_table("audit_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True), sa.Column("action", sa.String(64), nullable=False), sa.Column("resource_type", sa.String(64), nullable=False), sa.Column("resource_id", sa.String(64), nullable=False), sa.Column("purpose", sa.String(140), nullable=False), sa.Column("details", sa.Text(), nullable=False), sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False))
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"])
    op.create_index(op.f("ix_audit_logs_resource_type"), "audit_logs", ["resource_type"])
    op.create_table("badges", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("entity_type", sa.Enum("child", "caregiver", "asha", "manager", "village", "team", name="entitytype"), nullable=False), sa.Column("entity_id", sa.Integer(), nullable=False), sa.Column("code", sa.String(60), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("awarded_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False))
    op.create_index(op.f("ix_badges_entity_id"), "badges", ["entity_id"])
    op.create_index(op.f("ix_badges_entity_type"), "badges", ["entity_type"])
    op.create_table("doses", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("child_id", sa.Integer(), sa.ForeignKey("children.id"), nullable=False), sa.Column("vaccine_code", sa.String(40), nullable=False), sa.Column("given_on", sa.Date(), nullable=False), sa.Column("batch_no", sa.String(60), nullable=True), sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True), sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("source", sa.Enum("app", "paper", "register", name="dosesource"), nullable=False), sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True), sa.Column("client_uuid", sa.String(80), nullable=True), sa.Column("client_updated_at", sa.DateTime(timezone=True), nullable=True), sa.Column("conflict_flag", sa.Boolean(), nullable=False), sa.UniqueConstraint("child_id", "vaccine_code", name="uq_doses_child_vaccine"))
    op.create_index(op.f("ix_doses_child_id"), "doses", ["child_id"])
    op.create_index("ix_doses_child_id_vaccine_code", "doses", ["child_id", "vaccine_code"])
    op.create_index(op.f("ix_doses_client_uuid"), "doses", ["client_uuid"], unique=True)
    op.create_index(op.f("ix_doses_given_on"), "doses", ["given_on"])
    op.create_index(op.f("ix_doses_recorded_by"), "doses", ["recorded_by"])
    op.create_index(op.f("ix_doses_session_id"), "doses", ["session_id"])
    op.create_index(op.f("ix_doses_vaccine_code"), "doses", ["vaccine_code"])
    op.create_table("points", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("entity_type", sa.Enum("child", "caregiver", "asha", "manager", "village", "team", name="entitytype"), nullable=False), sa.Column("entity_id", sa.Integer(), nullable=False), sa.Column("points", sa.Integer(), nullable=False), sa.Column("reason", sa.String(140), nullable=False), sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False))
    op.create_index(op.f("ix_points_entity_id"), "points", ["entity_id"])
    op.create_index(op.f("ix_points_entity_type"), "points", ["entity_type"])
    op.create_table("stock_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("vaccine_code", sa.String(40), nullable=False), sa.Column("village_id", sa.Integer(), sa.ForeignKey("villages.id"), nullable=False), sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True), sa.Column("delta", sa.Integer(), nullable=False), sa.Column("reason", sa.String(120), nullable=False), sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False))
    op.create_index(op.f("ix_stock_logs_session_id"), "stock_logs", ["session_id"])
    op.create_index(op.f("ix_stock_logs_vaccine_code"), "stock_logs", ["vaccine_code"])
    op.create_index(op.f("ix_stock_logs_village_id"), "stock_logs", ["village_id"])
    op.create_table("job_runs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("job_name", sa.String(120), nullable=False), sa.Column("status", sa.Enum("running", "succeeded", "failed", name="jobstatus"), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("payload", sa.Text(), nullable=False), sa.Column("result", sa.Text(), nullable=False), sa.Column("error", sa.Text(), nullable=True), sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_job_runs_job_name"), "job_runs", ["job_name"])
    op.create_index(op.f("ix_job_runs_status"), "job_runs", ["status"])
    op.create_table("dead_letter_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("job_name", sa.String(120), nullable=False), sa.Column("payload", sa.Text(), nullable=False), sa.Column("error", sa.Text(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False))
    op.create_index(op.f("ix_dead_letter_logs_job_name"), "dead_letter_logs", ["job_name"])
    op.create_table("external_register_rows", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_name", sa.String(120), nullable=False), sa.Column("block", sa.String(100), nullable=False), sa.Column("vaccine_code", sa.String(40), nullable=False), sa.Column("count", sa.Integer(), nullable=False), sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False), sa.UniqueConstraint("source_name", "block", "vaccine_code", name="uq_external_register_source_block_vaccine"))
    op.create_index(op.f("ix_external_register_rows_block"), "external_register_rows", ["block"])
    op.create_index(op.f("ix_external_register_rows_source_name"), "external_register_rows", ["source_name"])
    op.create_index(op.f("ix_external_register_rows_vaccine_code"), "external_register_rows", ["vaccine_code"])
    op.create_table("outbox_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_type", sa.String(120), nullable=False), sa.Column("aggregate_type", sa.String(80), nullable=False), sa.Column("aggregate_id", sa.String(80), nullable=False), sa.Column("payload", sa.Text(), nullable=False), sa.Column("status", sa.Enum("pending", "processing", "processed", "failed", name="eventstatus"), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_outbox_events_aggregate_id"), "outbox_events", ["aggregate_id"])
    op.create_index(op.f("ix_outbox_events_aggregate_type"), "outbox_events", ["aggregate_type"])
    op.create_index(op.f("ix_outbox_events_event_type"), "outbox_events", ["event_type"])
    op.create_index(op.f("ix_outbox_events_status"), "outbox_events", ["status"])
    op.create_table("event_deliveries", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_id", sa.Integer(), sa.ForeignKey("outbox_events.id"), nullable=False), sa.Column("subscriber", sa.String(120), nullable=False), sa.Column("status", sa.Enum("pending", "processing", "processed", "failed", name="eventstatus"), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error", sa.Text(), nullable=True), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True), sa.UniqueConstraint("event_id", "subscriber", name="uq_event_delivery_event_subscriber"))
    op.create_index(op.f("ix_event_deliveries_event_id"), "event_deliveries", ["event_id"])
    op.create_index(op.f("ix_event_deliveries_status"), "event_deliveries", ["status"])
    op.create_index(op.f("ix_event_deliveries_subscriber"), "event_deliveries", ["subscriber"])


def downgrade() -> None:
    for table in ["event_deliveries", "outbox_events", "external_register_rows", "dead_letter_logs", "job_runs", "stock_logs", "points", "doses", "badges", "audit_logs", "sessions", "grievances", "notification_opt_outs", "notification_logs", "consents", "children", "users", "vaccine_schedules", "villages"]:
        op.drop_table(table)
