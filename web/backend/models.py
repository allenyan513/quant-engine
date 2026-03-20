"""Pydantic models for the web API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str


class UpdateCodeRequest(BaseModel):
    code: str


class UpdateParamsRequest(BaseModel):
    symbols: list[str] = Field(default=["AAPL"])
    start: str = Field(default="2023-01-01")
    end: str = Field(default="2025-12-31")
    initial_cash: float = Field(default=100_000.0)
    fee_model: str = Field(default="per_share")  # per_share | percentage | zero
    slippage_rate: float = Field(default=0.0005)


class CreateSessionRequest(BaseModel):
    title: str = ""


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    id: int
    role: str  # user | assistant
    content: str
    created_at: str


class SessionResponse(BaseModel):
    id: str
    title: str
    strategy_code: str
    params: UpdateParamsRequest
    messages: list[MessageResponse]
    created_at: str
    updated_at: str


class SessionListItem(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class TradeResponse(BaseModel):
    symbol: str
    direction: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    quantity: int
    net_pnl: float
    return_pct: float
    holding_days: int


class BacktestResultResponse(BaseModel):
    id: int
    session_id: str
    status: str  # running | completed | failed
    error: str | None = None
    metrics: dict[str, Any] = {}
    trade_summary: dict[str, Any] = {}
    trades: list[TradeResponse] = []
    equity_curve: list[list[Any]] = []  # [[timestamp_ms, value], ...]
    benchmark_curve: list[list[Any]] = []
    drawdown_curve: list[list[Any]] = []
    created_at: str
