"""SaaS foundation schema.

Revision ID: 0001_saas_foundation
Revises: None
"""
from alembic import op

from gateway.opensms_gateway.saas.models import Base

revision = "0001_saas_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    raise RuntimeError("destructive downgrade is intentionally disabled for SaaS foundation")
