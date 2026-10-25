"""SaaS foundation schema.

Revision ID: 0001_saas_foundation
Revises: None
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_saas_foundation"
down_revision = None
branch_labels = None
depends_on = None


tenant_type = sa.Enum("PF", "PJ", name="tenant_type")
plan_tenant_type = sa.Enum("PF", "PJ", name="plan_tenant_type")
document_type = sa.Enum("CPF", "CNPJ", name="document_type")
tenant_role = sa.Enum("Owner", "Admin", "Operator", name="tenant_role")
tenant_status = sa.Enum("active", "suspended", name="tenant_status")
overage_policy = sa.Enum("block", "bill", name="overage_policy")


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False, unique=True),
        sa.Column("tenant_type", plan_tenant_type, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("included_users", sa.Integer(), nullable=False),
        sa.Column("included_devices", sa.Integer(), nullable=False),
        sa.Column("included_api_keys", sa.Integer(), nullable=False),
        sa.Column("included_messages", sa.Integer(), nullable=False),
        sa.Column("external_api_enabled", sa.Boolean(), nullable=False),
        sa.Column("bulk_campaigns_enabled", sa.Boolean(), nullable=False),
        sa.Column("overage_policy", overage_policy, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plans_tenant_type", "plans", ["tenant_type"])

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_type", tenant_type, nullable=False),
        sa.Column("document_type", document_type, nullable=False),
        sa.Column("document_number", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column("status", tenant_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_number", name="uq_tenants_document_number"),
    )
    op.create_index("ix_tenants_document_number", "tenants", ["document_number"], unique=True)
    op.create_index("ix_tenants_plan_id", "tenants", ["plan_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", tenant_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "tenant_entitlements",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capability", sa.String(length=80), nullable=False),
        sa.Column("int_value", sa.Integer()),
        sa.Column("bool_value", sa.Boolean()),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "capability", name="uq_tenant_entitlement_capability"),
    )
    op.create_index("ix_tenant_entitlements_tenant_id", "tenant_entitlements", ["tenant_id"])

    op.create_table(
        "trials",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_number", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", name="uq_trials_tenant_id"),
        sa.UniqueConstraint("document_number", name="uq_trials_document_number"),
    )
    op.create_index("ix_trials_tenant_id", "trials", ["tenant_id"], unique=True)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        sa.UniqueConstraint("tenant_id", "label", name="uq_api_key_tenant_label"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])

    op.create_table(
        "tenant_devices",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("device_id", name="uq_tenant_devices_device_id"),
        sa.UniqueConstraint("tenant_id", "device_id", name="uq_tenant_device"),
    )
    op.create_index("ix_tenant_devices_tenant_id", "tenant_devices", ["tenant_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=255)),
        sa.Column("metadata_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    op.create_table(
        "session_records",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE")),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_session_records_token_hash"),
    )
    op.create_index("ix_session_records_user_id", "session_records", ["user_id"])
    op.create_index("ix_session_records_tenant_id", "session_records", ["tenant_id"])

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_tokens_token_hash"),
    )
    op.create_index("ix_email_verification_tokens_user_id", "email_verification_tokens", ["user_id"])


def downgrade() -> None:
    raise RuntimeError("destructive downgrade is intentionally disabled for SaaS foundation")
