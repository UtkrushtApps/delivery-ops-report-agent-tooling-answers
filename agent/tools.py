"""Tool catalogue and deterministic tool implementations.

The Redis cache tool, PostgreSQL lookup tool, and formatting tool live here.
The orchestrator (orchestrator.py) is responsible for chaining them and for
cache reuse decisions; some glue is intentionally incomplete there.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any, Dict, List, Optional

import psycopg
import redis

from .config import config
from .schemas import (
    CachePayload,
    FormatArgs,
    LookupArgs,
    NormalizedCustomer,
    ReportPayload,
    ToolResult,
)

# ---------------------------------------------------------------------------
# Tool specs advertised to the model (OpenAI/LiteLLM tool-calling format).
# ---------------------------------------------------------------------------
TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": "Look up a delivery customer's account record by customer_id from the system of record. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "Customer id like CUST-1002"}
                },
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "format_report",
            "description": "Format a normalized customer record into an account_summary report payload. Pass the normalized record returned by lookup_customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "object", "description": "Normalized customer record from lookup_customer"},
                    "report_type": {"type": "string", "enum": ["account_summary"]},
                },
                "required": ["customer"],
            },
        },
    },
]

ALLOWED_TOOL_NAMES = {"lookup_customer", "format_report"}


class RedisCacheTool:
    """Stores and retrieves normalized report plans as JSON in Redis."""

    def __init__(self, url: Optional[str] = None):
        self._url = url or config.REDIS_URL
        self._client = redis.Redis.from_url(self._url, decode_responses=True)

    @staticmethod
    def cache_key(customer_id: str, report_type: str) -> str:
        return f"report:{report_type}:{customer_id}"

    def get_raw(self, key: str) -> Optional[str]:
        try:
            return self._client.get(key)
        except redis.RedisError:
            return None

    def set_payload(self, key: str, payload: CachePayload) -> None:
        try:
            self._client.set(key, payload.model_dump_json(), ex=config.REPORT_CACHE_TTL_SECONDS)
        except redis.RedisError:
            pass

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except redis.RedisError:
            return False


class CustomerLookupTool:
    """PostgreSQL-backed read-only customer lookup."""

    def __init__(self, dsn: Optional[str] = None):
        self._dsn = dsn or config.DATABASE_URL

    def lookup(self, args: Dict[str, Any]) -> ToolResult:
        """Validate args, run parameterized SQL, return a NORMALIZED record.

        Returns ToolResult.success({...normalized...}) or a structured failure
        (invalid_arguments / customer_not_found / customer_inactive / lookup_failed).
        """
        try:
            valid = LookupArgs(**args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure("invalid_arguments", f"Bad lookup args: {exc}")

        try:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT customer_id, full_name, plan_tier, account_status, "
                        "support_tier, region, risk_flag, total_orders, last_delivery_at "
                        "FROM customers WHERE customer_id = %s",
                        (valid.customer_id,),
                    )
                    row = cur.fetchone()
        except psycopg.Error as exc:
            return ToolResult.failure("lookup_failed", f"DB error: {exc}", retryable=True)

        if row is None:
            return ToolResult.failure(
                "customer_not_found", f"No customer {valid.customer_id}"
            )

        try:
            normalized = self.normalize_row(row)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(
                "lookup_failed",
                f"Customer record could not be normalized: {exc}",
                retryable=False,
            )

        # Business rule: inactive/suspended customers are a structured condition.
        if normalized.account_status in ("inactive", "suspended"):
            return ToolResult.failure(
                "customer_inactive",
                f"Customer {normalized.customer_id} is {normalized.account_status}",
            )
        return ToolResult.success(normalized.model_dump())

    @staticmethod
    def normalize_row(row: tuple) -> NormalizedCustomer:
        """Convert a raw DB row tuple into an LLM-safe NormalizedCustomer.

        Column order: customer_id, full_name, plan_tier, account_status,
        support_tier, region, risk_flag, total_orders, last_delivery_at.
        Do NOT include internal_notes or other sensitive fields.
        """
        (
            customer_id,
            full_name,
            plan_tier,
            account_status,
            support_tier,
            region,
            risk_flag,
            total_orders,
            last_delivery_at,
        ) = row

        if isinstance(last_delivery_at, datetime):
            last_delivery_value: Optional[str] = last_delivery_at.isoformat(sep=" ", timespec="seconds")
        elif isinstance(last_delivery_at, date):
            last_delivery_value = last_delivery_at.isoformat()
        elif last_delivery_at is None:
            last_delivery_value = None
        else:
            last_delivery_value = str(last_delivery_at)

        return NormalizedCustomer(
            customer_id=str(customer_id),
            full_name=str(full_name),
            plan_tier=str(plan_tier),
            account_status=str(account_status),
            support_tier=str(support_tier),
            region=str(region),
            risk_flag=bool(risk_flag),
            total_orders=int(total_orders),
            last_delivery_at=last_delivery_value,
        )


class ReportFormatTool:
    """Turns a normalized customer record into a ReportPayload."""

    def format(self, args: Dict[str, Any]) -> ToolResult:
        """Validate FormatArgs and build a ReportPayload.

        On invalid args return ToolResult.failure('invalid_arguments', ...).
        On success return ToolResult.success(ReportPayload(...).model_dump()).
        """
        try:
            valid = FormatArgs(**args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure("invalid_arguments", f"Bad format args: {exc}")
        try:
            c = NormalizedCustomer(**valid.customer)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure("format_failed", f"Bad customer record: {exc}")

        payload = ReportPayload(
            customer_id=c.customer_id,
            headline=f"Account summary for {c.full_name} ({c.customer_id})",
            status_line=f"Plan: {c.plan_tier} | Status: {c.account_status} | Support: {c.support_tier} | Region: {c.region}",
            activity_line=(
                f"Total orders: {c.total_orders} | Last delivery: "
                f"{c.last_delivery_at or 'none on record'}"
            ),
            risk_line="Risk flag: RAISED" if c.risk_flag else "Risk flag: clear",
        )
        return ToolResult.success(payload.model_dump())

