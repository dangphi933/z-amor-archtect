from alembic import op
import sqlalchemy as sa

revision = "init_trading_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():

    # USERS
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(120), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ACCOUNTS
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("broker", sa.String(100)),
        sa.Column("account_number", sa.String(100)),
        sa.Column("platform", sa.String(20)),  # MT4 MT5 cTrader
        sa.Column("currency", sa.String(10)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # TRADE HISTORY
    op.create_table(
        "trade_history",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")),
        sa.Column("ticket", sa.String(50)),
        sa.Column("symbol", sa.String(20)),
        sa.Column("type", sa.String(10)),
        sa.Column("lots", sa.Float),
        sa.Column("open_price", sa.Float),
        sa.Column("close_price", sa.Float),
        sa.Column("profit", sa.Float),
        sa.Column("commission", sa.Float),
        sa.Column("swap", sa.Float),
        sa.Column("open_time", sa.DateTime),
        sa.Column("close_time", sa.DateTime),
    )

    # POSITIONS (OPEN TRADES)
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")),
        sa.Column("ticket", sa.String(50)),
        sa.Column("symbol", sa.String(20)),
        sa.Column("type", sa.String(10)),
        sa.Column("lots", sa.Float),
        sa.Column("open_price", sa.Float),
        sa.Column("current_price", sa.Float),
        sa.Column("floating_profit", sa.Float),
        sa.Column("open_time", sa.DateTime),
    )

    # RISK EVENTS
    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("event_type", sa.String(50)),
        sa.Column("severity", sa.String(20)),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # RADAR SIGNALS
    op.create_table(
        "radar_signals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("signal_type", sa.String(50)),
        sa.Column("score", sa.Float),
        sa.Column("metadata", sa.JSON),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # STRATEGY METRICS
    op.create_table(
        "strategy_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer),
        sa.Column("winrate", sa.Float),
        sa.Column("profit_factor", sa.Float),
        sa.Column("max_drawdown", sa.Float),
        sa.Column("sharpe_ratio", sa.Float),
        sa.Column("calculated_at", sa.DateTime),
    )


def downgrade():

    op.drop_table("strategy_metrics")
    op.drop_table("radar_signals")
    op.drop_table("risk_events")
    op.drop_table("positions")
    op.drop_table("trade_history")
    op.drop_table("accounts")
    op.drop_table("users")