"""Typed contracts for tool arguments, results, cache payloads, and reports."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    customer_id: str
    report_type: Literal["account_summary"] = "account_summary"


class LookupArgs(BaseModel):
    """Arguments for the PostgreSQL customer lookup tool."""
    customer_id: str = Field(..., min_length=3)


class FormatArgs(BaseModel):
    """Arguments for the report formatting tool.

    `customer` is the NORMALIZED record produced by the lookup tool,
    not a raw database row.
    """
    customer: Dict[str, Any]
    report_type: Literal["account_summary"] = "account_summary"


class NormalizedCustomer(BaseModel):
    """LLM-safe, minimal customer record. No internal notes / raw PII dumps."""
    customer_id: str
    full_name: str
    plan_tier: str
    account_status: str
    support_tier: str
    region: str
    risk_flag: bool
    total_orders: int
    last_delivery_at: Optional[str] = None


class ReportPayload(BaseModel):
    """Final report-ready payload produced by the formatting tool."""
    customer_id: str
    headline: str
    status_line: str
    activity_line: str
    risk_line: str
    report_type: str = "account_summary"


class ToolError(BaseModel):
    """Machine-readable structured tool error."""
    code: Literal[
        "invalid_arguments",
        "customer_not_found",
        "customer_inactive",
        "cache_unavailable",
        "lookup_failed",
        "format_failed",
    ]
    message: str
    retryable: bool = False


class ToolResult(BaseModel):
    """Uniform tool result envelope. Exactly one of data/error is set."""
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[ToolError] = None

    @classmethod
    def success(cls, data: Dict[str, Any]) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, code: str, message: str, retryable: bool = False) -> "ToolResult":
        return cls(ok=False, error=ToolError(code=code, message=message, retryable=retryable))


class CachePayload(BaseModel):
    """What gets stored in Redis for a normalized report plan.

    `schema_version` must match config.CACHE_SCHEMA_VERSION to be reusable.
    """
    schema_version: int
    customer_id: str
    report: ReportPayload

