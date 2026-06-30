"""Offline invariant tests. No provider key needed (AGENT_TEST_MODE).

These exercise the deterministic tool-use behavior the candidate completes:
cache hit/miss/invalid-cache fallback, lookup normalization, lookup->format
chaining, and structured errors. They do NOT call the real model.
"""
import os

os.environ.setdefault("AGENT_TEST_MODE", "1")

from agent.config import config  # noqa: E402
from agent.schemas import (  # noqa: E402
    CachePayload,
    NormalizedCustomer,
    ReportPayload,
    ReportRequest,
    ToolResult,
)
from agent.orchestrator import ReportAgent  # noqa: E402
from agent.tools import CustomerLookupTool, ReportFormatTool  # noqa: E402


NORMAL_ROW = (
    "CUST-1002", "Diego Ramos", "standard", "active", "silver",
    "west", False, 37, "2024-05-28 12:05:00",
)


class FakeCache:
    """In-memory cache double for offline tests (NOT a model stand-in)."""
    def __init__(self):
        self.store = {}
    @staticmethod
    def cache_key(customer_id, report_type):
        return f"report:{report_type}:{customer_id}"
    def get_raw(self, key):
        return self.store.get(key)
    def set_payload(self, key, payload):
        self.store[key] = payload.model_dump_json()
    def ping(self):
        return True


class FakeLookup:
    def __init__(self, result):
        self.result = result
        self.calls = 0
    def lookup(self, args):
        self.calls += 1
        return self.result


def _agent(cache, lookup):
    return ReportAgent(llm=None, cache=cache, lookup=lookup, formatter=ReportFormatTool())


def test_normalize_row_drops_sensitive_and_keeps_required():
    norm = CustomerLookupTool.normalize_row(NORMAL_ROW)
    assert isinstance(norm, NormalizedCustomer)
    assert norm.customer_id == "CUST-1002"
    assert norm.plan_tier == "standard"
    assert norm.total_orders == 37
    # internal_notes must not be present in the normalized model
    assert "internal_notes" not in norm.model_dump()


def test_chain_lookup_to_format_produces_report():
    lookup = FakeLookup(ToolResult.success(NormalizedCustomer(
        customer_id="CUST-1002", full_name="Diego Ramos", plan_tier="standard",
        account_status="active", support_tier="silver", region="west",
        risk_flag=False, total_orders=37, last_delivery_at="2024-05-28 12:05:00",
    ).model_dump()))
    agent = _agent(FakeCache(), lookup)
    result = agent.run_tool_chain("CUST-1002", "account_summary")
    assert result.ok
    report = ReportPayload(**result.data)
    assert report.customer_id == "CUST-1002"
    assert "standard" in report.status_line
    assert "37" in report.activity_line


def test_cache_miss_then_hit():
    lookup = FakeLookup(ToolResult.success(NormalizedCustomer(
        customer_id="CUST-1002", full_name="Diego Ramos", plan_tier="standard",
        account_status="active", support_tier="silver", region="west",
        risk_flag=False, total_orders=37, last_delivery_at="2024-05-28 12:05:00",
    ).model_dump()))
    agent = _agent(FakeCache(), lookup)
    req = ReportRequest(customer_id="CUST-1002")
    first = agent.build_report(req)
    assert first["from_cache"] is False
    assert lookup.calls == 1
    second = agent.build_report(req)
    assert second["from_cache"] is True
    # second resolution must not have hit the lookup tool again
    assert lookup.calls == 1
    assert second["report"]["customer_id"] == "CUST-1002"


def test_invalid_cache_value_is_treated_as_miss():
    cache = FakeCache()
    key = cache.cache_key("CUST-1002", "account_summary")
    cache.store[key] = "{not valid json"
    lookup = FakeLookup(ToolResult.success(NormalizedCustomer(
        customer_id="CUST-1002", full_name="Diego Ramos", plan_tier="standard",
        account_status="active", support_tier="silver", region="west",
        risk_flag=False, total_orders=37, last_delivery_at="2024-05-28 12:05:00",
    ).model_dump()))
    agent = _agent(cache, lookup)
    out = agent.build_report(ReportRequest(customer_id="CUST-1002"))
    assert out["from_cache"] is False
    assert lookup.calls == 1


def test_stale_schema_version_is_treated_as_miss():
    cache = FakeCache()
    key = cache.cache_key("CUST-1002", "account_summary")
    stale = CachePayload(
        schema_version=config.CACHE_SCHEMA_VERSION - 1,
        customer_id="CUST-1002",
        report=ReportPayload(
            customer_id="CUST-1002", headline="old", status_line="old",
            activity_line="old", risk_line="old",
        ),
    )
    cache.store[key] = stale.model_dump_json()
    lookup = FakeLookup(ToolResult.success(NormalizedCustomer(
        customer_id="CUST-1002", full_name="Diego Ramos", plan_tier="standard",
        account_status="active", support_tier="silver", region="west",
        risk_flag=False, total_orders=37, last_delivery_at="2024-05-28 12:05:00",
    ).model_dump()))
    agent = _agent(cache, lookup)
    out = agent.build_report(ReportRequest(customer_id="CUST-1002"))
    assert out["from_cache"] is False


def test_missing_customer_returns_structured_safe_message():
    lookup = FakeLookup(ToolResult.failure("customer_not_found", "No customer CUST-9999"))
    agent = _agent(FakeCache(), lookup)
    out = agent.build_report(ReportRequest(customer_id="CUST-9999"))
    assert "report" not in out
    assert "error" in out
    assert out["error_code"] == "customer_not_found"
    msg = out["error"].lower()
    assert "traceback" not in msg and "exception" not in msg
    assert "not found" in msg or "could not" in msg or "no" in msg


def test_inactive_customer_returns_structured_message():
    lookup = FakeLookup(ToolResult.failure("customer_inactive", "Customer CUST-1004 is inactive"))
    agent = _agent(FakeCache(), lookup)
    out = agent.build_report(ReportRequest(customer_id="CUST-1004"))
    assert "error" in out
    assert out["error_code"] == "customer_inactive"
    assert "inactive" in out["error"].lower() or "not active" in out["error"].lower()

