"""initial_schema_personal

Revision ID: 20260401_001
Revises:
Create Date: 2026-04-01 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260401_001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ─── investor_profiles ─────────────────────────────────────────────
    # Profilo investitore — UNA sola fonte di verità per filtrare
    # tutti i suggerimenti (Regola 22).
    op.create_table(
        "investor_profiles",
        sa.Column("profile_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("risk_tolerance", sa.String(), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("investment_horizon", sa.String(), nullable=False),
        sa.Column("horizon_years", sa.Integer(), nullable=False),
        sa.Column("liquidity_reserve_months", sa.Integer(), nullable=False),
        sa.Column("financial_knowledge", sa.Integer(), nullable=False),
        sa.Column("allowed_asset_classes", sa.String(), nullable=False),  # JSON
        sa.Column("excluded_sectors", sa.String(), nullable=False, server_default="[]"),
        sa.Column("excluded_countries", sa.String(), nullable=False, server_default="[]"),
        sa.Column("base_currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── positions (eToro import) ──────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("position_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("investor_profiles.profile_id"),
                  nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("source", sa.String(), nullable=False, server_default="etoro"),
        sa.Column("imported_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_positions_profile", "positions", ["profile_id"])
    op.create_index("idx_positions_ticker", "positions", ["ticker"])
    op.create_index("idx_positions_open", "positions", ["is_open"])

    # ─── cash_flow_entries ─────────────────────────────────────────────
    op.create_table(
        "cash_flow_entries",
        sa.Column("entry_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("investor_profiles.profile_id"),
                  nullable=False),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),   # 'in' | 'out'
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("subcategory", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_cashflow_profile_date", "cash_flow_entries",
                    ["profile_id", "occurred_at"])

    # ─── financial_goals (SMART) ───────────────────────────────────────
    op.create_table(
        "financial_goals",
        sa.Column("goal_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("investor_profiles.profile_id"),
                  nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("target_amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("current_amount", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_goals_profile", "financial_goals", ["profile_id"])

    # ─── wealth_snapshots ──────────────────────────────────────────────
    op.create_table(
        "wealth_snapshots",
        sa.Column("snapshot_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("investor_profiles.profile_id"),
                  nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("total_assets", sa.Float(), nullable=False),
        sa.Column("total_liabilities", sa.Float(), nullable=False),
        sa.Column("net_worth", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("breakdown_json", sa.String(), nullable=False),  # asset/liability breakdown
    )
    op.create_index("idx_wealth_profile_time", "wealth_snapshots",
                    ["profile_id", "captured_at"])

    # ─── assets / liabilities (net worth components) ──────────────────
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("investor_profiles.profile_id"),
                  nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),  # cash/equity/real_estate/crypto
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata_json", sa.String(), nullable=True),
    )
    op.create_table(
        "liabilities",
        sa.Column("liability_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), sa.ForeignKey("investor_profiles.profile_id"),
                  nullable=False),
        sa.Column("liability_type", sa.String(), nullable=False),   # mortgage/loan/credit_card
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("outstanding_amount", sa.Float(), nullable=False),
        sa.Column("interest_rate", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("last_updated", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ─── alert_history ─────────────────────────────────────────────────
    op.create_table(
        "alert_history",
        sa.Column("alert_id", sa.String(), primary_key=True),
        sa.Column("profile_id", sa.String(), nullable=True),  # NULL = market-wide alert
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),   # info | warning | critical
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("idx_alert_triggered", "alert_history", ["triggered_at"])
    op.create_index("idx_alert_type_severity", "alert_history", ["alert_type", "severity"])


def downgrade() -> None:
    # Ordine inverso per rispettare le foreign key
    op.drop_index("idx_alert_type_severity", table_name="alert_history")
    op.drop_index("idx_alert_triggered", table_name="alert_history")
    op.drop_table("alert_history")
    op.drop_table("liabilities")
    op.drop_table("assets")
    op.drop_index("idx_wealth_profile_time", table_name="wealth_snapshots")
    op.drop_table("wealth_snapshots")
    op.drop_index("idx_goals_profile", table_name="financial_goals")
    op.drop_table("financial_goals")
    op.drop_index("idx_cashflow_profile_date", table_name="cash_flow_entries")
    op.drop_table("cash_flow_entries")
    op.drop_index("idx_positions_open", table_name="positions")
    op.drop_index("idx_positions_ticker", table_name="positions")
    op.drop_index("idx_positions_profile", table_name="positions")
    op.drop_table("positions")
    op.drop_table("investor_profiles")
