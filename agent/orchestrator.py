"""Agent orchestration: cache reuse, tool dispatch, lookup->format chaining,
and structured fallback. The model plans which tool to call; code enforces
validation, allowed tool names, the lookup->format data flow, and caching.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .config import config
from .llm_client import LLMClient
from .schemas import CachePayload, ReportPayload, ReportRequest, ToolResult
from .tools import (
    ALLOWED_TOOL_NAMES,
    TOOL_SPECS,
    CustomerLookupTool,
    RedisCacheTool,
    ReportFormatTool,
)

logger = logging.getLogger("delivery_agent")

SYSTEM_PROMPT = (
    "You are a delivery-operations support assistant. To answer an account "
    "report request you must first call lookup_customer with the customer_id, "
    "then call format_report passing the record returned by lookup_customer. "
    "Never invent fields that the tools did not return. If a tool returns an "
    "error, explain it plainly and safely."
)


class ReportAgent:
    def __init__(
        self,
        llm: Optional[LLMClient] = None,
        cache: Optional[RedisCacheTool] = None,
        lookup: Optional[CustomerLookupTool] = None,
        formatter: Optional[ReportFormatTool] = None,
    ):
        self.llm = llm or LLMClient()
        self.cache = cache or RedisCacheTool()
        self.lookup = lookup or CustomerLookupTool()
        self.formatter = formatter or ReportFormatTool()
        self.trace: List[Dict[str, Any]] = []

    def _log(self, event: str, **fields: Any) -> None:
        rec = {"event": event, **fields}
        self.trace.append(rec)
        logger.info(json.dumps(rec))

    # -- cache layer -------------------------------------------------------
    def load_cached_report(self, customer_id: str, report_type: str) -> Optional[ReportPayload]:
        """Return a reusable ReportPayload from cache, or None on a cache miss.

        A cached value is reusable only if it is present, parses as JSON, matches
        the CachePayload schema, has schema_version == config.CACHE_SCHEMA_VERSION,
        and is for the same customer_id/report_type. Anything else is a cache
        miss. Emits a trace event for cache_hit or cache_miss.
        """
        key = self.cache.cache_key(customer_id, report_type)
        raw = self.cache.get_raw(key)
        if raw is None:
            self._log("cache_miss", customer_id=customer_id, report_type=report_type, reason="absent")
            return None

        try:
            payload = CachePayload.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            self._log(
                "cache_miss",
                customer_id=customer_id,
                report_type=report_type,
                reason="invalid_json_or_schema",
                detail=exc.__class__.__name__,
            )
            return None

        if payload.schema_version != config.CACHE_SCHEMA_VERSION:
            self._log(
                "cache_miss",
                customer_id=customer_id,
                report_type=report_type,
                reason="stale_schema_version",
                cached_schema_version=payload.schema_version,
                expected_schema_version=config.CACHE_SCHEMA_VERSION,
            )
            return None

        if payload.customer_id != customer_id:
            self._log(
                "cache_miss",
                customer_id=customer_id,
                report_type=report_type,
                reason="customer_id_mismatch",
                cached_customer_id=payload.customer_id,
            )
            return None

        if payload.report.customer_id != customer_id:
            self._log(
                "cache_miss",
                customer_id=customer_id,
                report_type=report_type,
                reason="report_customer_id_mismatch",
                cached_report_customer_id=payload.report.customer_id,
            )
            return None

        if payload.report.report_type != report_type:
            self._log(
                "cache_miss",
                customer_id=customer_id,
                report_type=report_type,
                reason="report_type_mismatch",
                cached_report_type=payload.report.report_type,
            )
            return None

        self._log("cache_hit", customer_id=customer_id, report_type=report_type)
        return payload.report

    def store_cached_report(self, customer_id: str, report: ReportPayload, report_type: str) -> None:
        key = self.cache.cache_key(customer_id, report_type)
        payload = CachePayload(
            schema_version=config.CACHE_SCHEMA_VERSION,
            customer_id=customer_id,
            report=report,
        )
        self.cache.set_payload(key, payload)
        self._log("cache_store", customer_id=customer_id, report_type=report_type)

    # -- tool chaining -----------------------------------------------------
    def run_tool_chain(self, customer_id: str, report_type: str) -> ToolResult:
        """Run lookup_customer then format_report, chaining the normalized record.

        Steps:
          1. Call the lookup tool; if it returns a structured failure, return it.
          2. Pass the NORMALIZED lookup data into the formatting tool as the
             `customer` argument (this is the required tool->tool data flow).
          3. Return the formatter's ToolResult.
        Emits trace events for the lookup and format steps.
        """
        self._log("tool_call", tool="lookup_customer", customer_id=customer_id)
        lookup_result = self.lookup.lookup({"customer_id": customer_id})
        self._log(
            "tool_result",
            tool="lookup_customer",
            ok=lookup_result.ok,
            error_code=lookup_result.error.code if lookup_result.error else None,
        )
        if not lookup_result.ok:
            return lookup_result

        normalized_customer = lookup_result.data or {}
        self._log("tool_call", tool="format_report", customer_id=customer_id, report_type=report_type)
        format_result = self.formatter.format(
            {
                "customer": normalized_customer,
                "report_type": report_type,
            }
        )
        self._log(
            "tool_result",
            tool="format_report",
            ok=format_result.ok,
            error_code=format_result.error.code if format_result.error else None,
        )
        return format_result

    def error_to_message(self, result: ToolResult) -> str:
        """Convert a structured ToolResult failure into a safe, user-facing line.

        Known error codes are mapped to plain operational messages. Internal
        exception details from tool messages are intentionally not exposed.
        """
        if result.ok:
            return ""
        if result.error is None:
            return "The report could not be generated. Please try again later."

        messages = {
            "invalid_arguments": "The report request was invalid. Please check the customer ID and report type.",
            "customer_not_found": "Customer not found. Please verify the customer ID and try again.",
            "customer_inactive": "Customer is inactive or not active, so an account report cannot be generated.",
            "cache_unavailable": "The report cache is unavailable. Please try again shortly.",
            "lookup_failed": "Customer lookup is temporarily unavailable. Please try again later.",
            "format_failed": "The report could not be formatted from the customer record.",
        }
        return messages.get(
            result.error.code,
            "The report could not be generated safely. Please try again later.",
        )

    # -- public entrypoint -------------------------------------------------
    def build_report(self, request: ReportRequest) -> Dict[str, Any]:
        """Resolve a report request, reusing cache when valid and recomputing on miss.

        Returns a dict: {"customer_id", "report" or "error", "from_cache": bool}.
        For failures it also includes "error_code" for structured callers.
        """
        self.trace = []
        cid, rtype = request.customer_id, request.report_type

        cached = self.load_cached_report(cid, rtype)
        if cached is not None:
            return {"customer_id": cid, "report": cached.model_dump(), "from_cache": True}

        result = self.run_tool_chain(cid, rtype)
        if not result.ok:
            return {
                "customer_id": cid,
                "error": self.error_to_message(result),
                "error_code": result.error.code if result.error else "unknown",
                "from_cache": False,
            }

        report = ReportPayload(**result.data)
        self.store_cached_report(cid, report, rtype)
        return {"customer_id": cid, "report": report.model_dump(), "from_cache": False}

    # -- model-driven planning (end-to-end path) ---------------------------
    def run_with_model(self, request: ReportRequest) -> str:
        """End-to-end path: let the model plan tool calls, code dispatches them.

        Used when a provider key is present. Validates tool names and arguments,
        enforces the lookup->format flow, and synthesizes a final response.
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Build an {request.report_type} report for {request.customer_id}."},
        ]
        last_lookup_data: Optional[Dict[str, Any]] = None
        for _ in range(4):
            msg = self.llm.plan_tool_calls(messages, TOOL_SPECS)
            call = LLMClient.parse_tool_call(msg)
            if call is None:
                return msg.get("content") or ""
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls")})
            name, args = call["name"], call["arguments"]
            if name not in ALLOWED_TOOL_NAMES:
                tool_out = ToolResult.failure("invalid_arguments", f"Unknown tool {name}")
            elif name == "lookup_customer":
                tool_out = self.lookup.lookup(args)
                if tool_out.ok:
                    last_lookup_data = tool_out.data
            else:  # format_report
                if "customer" not in args and last_lookup_data is not None:
                    args = {**args, "customer": last_lookup_data}
                tool_out = self.formatter.format(args)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": tool_out.model_dump_json(),
            })
            if tool_out.ok and name == "format_report":
                break
        return self.llm.synthesize(messages)

