"""Knowledge Nexus reskin: model catalog, usage/cost ledger, audit log,
tenant policies, tenant settings JSONB

Backs the Super Admin dashboard (platform overview KPIs, requests-per-day
chart, cost-by-tenant, model catalog + onboarding gates, platform health,
audit log) and the Tenant Admin Norms tab (named access policies, rate
limits + guardrails) added in this pass. See the class docstrings on
app/models/model_route.py, usage_event.py, audit_log.py, policy.py, and
the DEFAULT_TENANT_SETTINGS comment in app/models/tenant.py for exactly
what each new column means and the scaffold-vs-real boundary it sits on.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Tenant settings (rate limits + guardrails) -------------------------
    op.add_column(
        "tenants",
        sa.Column(
            "settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text(
                "'{\"rate_limits\": {\"per_user_rpm\": 60, \"per_tenant_rpm\": 1200, "
                "\"tokens_per_day\": 250000}, \"guardrails\": {\"pii_redaction\": true, "
                "\"prompt_injection_screening\": true, \"groundedness_check\": true, "
                "\"topic_blocklist\": false}}'::jsonb"
            ),
        ),
    )

    # --- Model catalog (Super Admin-managed MLflow Gateway routes) ----------
    op.create_table(
        "model_routes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("route", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="chat"),
        sa.Column("input_cost_per_1m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("output_cost_per_1m", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="eval"),
        sa.Column("gateway_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_meter_registered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("eval_faithfulness", sa.Float(), nullable=True),
        sa.Column("eval_faithfulness_threshold", sa.Float(), nullable=False, server_default="0.92"),
        sa.Column("eval_task_completion", sa.Float(), nullable=True),
        sa.Column("eval_task_completion_threshold", sa.Float(), nullable=False, server_default="0.85"),
        sa.Column("eval_security_redteam_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_model_routes_route", "model_routes", ["route"], unique=True)

    # --- Usage / cost ledger --------------------------------------------------
    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("model_route_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_routes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=20), nullable=False, server_default="chat_turn"),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_usage_events_tenant_created", "usage_events", ["tenant_id", "created_at"])

    # --- Audit log -------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_logs_created", "audit_logs", ["created_at"])

    # --- Tenant policies (Norms tab) --------------------------------------------
    op.create_table(
        "policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("rule_expression", sa.String(length=500), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="dry_run"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # --- Seed the platform model catalog with the routes referenced by the
    # Admin Expertise tab's default Planner/Executor/Critic selects, so a
    # fresh install's dropdowns aren't empty. Matches Agent.model_name
    # defaults already used elsewhere in this app (e.g. "stub-echo" stays
    # unmatched on purpose — see pricing.py's default-rate fallback).
    conn = op.get_bind()
    import uuid as _uuid

    seed_rows = [
        {
            "id": str(_uuid.uuid4()),
            "name": "gpt-4o",
            "provider": "Azure OpenAI",
            "route": "chat/primary",
            "kind": "chat",
            "input_cost_per_1m": 2.50,
            "output_cost_per_1m": 10.00,
            "status": "live",
            "gateway_configured": True,
            "cost_meter_registered": True,
            "eval_faithfulness": 0.95,
            "eval_task_completion": 0.91,
            "eval_security_redteam_passed": True,
        },
        {
            "id": str(_uuid.uuid4()),
            "name": "gpt-4o-mini",
            "provider": "Azure OpenAI",
            "route": "chat/fast",
            "kind": "chat",
            "input_cost_per_1m": 0.15,
            "output_cost_per_1m": 0.60,
            "status": "live",
            "gateway_configured": True,
            "cost_meter_registered": True,
            "eval_faithfulness": 0.93,
            "eval_task_completion": 0.88,
            "eval_security_redteam_passed": True,
        },
        {
            "id": str(_uuid.uuid4()),
            "name": "text-embedding-3-large",
            "provider": "Azure OpenAI",
            "route": "embed/default",
            "kind": "embed",
            "input_cost_per_1m": 0.13,
            "output_cost_per_1m": None,
            "status": "live",
            "gateway_configured": True,
            "cost_meter_registered": True,
            "eval_faithfulness": None,
            "eval_task_completion": None,
            "eval_security_redteam_passed": True,
        },
        {
            "id": str(_uuid.uuid4()),
            "name": "claude-sonnet-4-6",
            "provider": "Anthropic",
            "route": "chat/eval-canary",
            "kind": "chat",
            "input_cost_per_1m": 3.00,
            "output_cost_per_1m": 15.00,
            "status": "eval",
            "gateway_configured": True,
            "cost_meter_registered": True,
            "eval_faithfulness": 0.89,
            "eval_task_completion": 0.83,
            "eval_security_redteam_passed": False,
        },
    ]
    for row in seed_rows:
        conn.execute(
            sa.text(
                "INSERT INTO model_routes (id, name, provider, route, kind, input_cost_per_1m, "
                "output_cost_per_1m, status, gateway_configured, cost_meter_registered, "
                "eval_faithfulness, eval_task_completion, eval_security_redteam_passed, "
                "eval_faithfulness_threshold, eval_task_completion_threshold, is_active, created_at, updated_at) "
                "VALUES (:id, :name, :provider, :route, :kind, :input_cost_per_1m, :output_cost_per_1m, "
                ":status, :gateway_configured, :cost_meter_registered, :eval_faithfulness, "
                ":eval_task_completion, :eval_security_redteam_passed, 0.92, 0.85, true, now(), now())"
            ),
            row,
        )


def downgrade() -> None:
    op.drop_table("policies")
    op.drop_index("ix_audit_logs_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_usage_events_tenant_created", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index("ix_model_routes_route", table_name="model_routes")
    op.drop_table("model_routes")
    op.drop_column("tenants", "settings")
