from sqlalchemy import Column, Integer, String, Float, DateTime, BigInteger, ForeignKey, JSON, Text
from sqlalchemy.sql import func
from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    broker = Column(String(100))
    account_number = Column(String(100))
    platform = Column(String(20))
    currency = Column(String(10))
    created_at = Column(DateTime, server_default=func.now())


class TradeHistory(Base):
    __tablename__ = "trade_history"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    ticket = Column(String(50))
    symbol = Column(String(20))
    type = Column(String(10))
    lots = Column(Float)
    open_price = Column(Float)
    close_price = Column(Float)
    profit = Column(Float)
    commission = Column(Float)
    swap = Column(Float)
    open_time = Column(DateTime)
    close_time = Column(DateTime)


class Position(Base):
    __tablename__ = "positions"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))
    ticket = Column(String(50))
    symbol = Column(String(20))
    type = Column(String(10))
    lots = Column(Float)
    open_price = Column(Float)
    current_price = Column(Float)
    floating_profit = Column(Float)
    open_time = Column(DateTime)


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer)
    event_type = Column(String(50))
    severity = Column(String(20))
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class RadarSignal(Base):
    __tablename__ = "radar_signals"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer)
    signal_type = Column(String(50))
    score = Column(Float)
    meta_data = Column("metadata", JSON)
    created_at = Column(DateTime, server_default=func.now())


class StrategyMetric(Base):
    __tablename__ = "strategy_metrics"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer)
    winrate = Column(Float)
    profit_factor = Column(Float)
    max_drawdown = Column(Float)
    sharpe_ratio = Column(Float)
    calculated_at = Column(DateTime)