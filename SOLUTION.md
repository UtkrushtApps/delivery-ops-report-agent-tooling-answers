# Solution Steps

1. Implement `CustomerLookupTool.normalize_row` so the PostgreSQL row tuple is converted into a `NormalizedCustomer` pydantic model using only safe report fields. Convert timestamps/dates to strings, coerce booleans and integers, and never include `internal_notes`.

2. Keep the customer lookup SQL parameterized and have `lookup` return structured `ToolResult` failures for invalid arguments, not found customers, inactive/suspended customers, and database/normalization failures.

3. Implement `ReportAgent.load_cached_report` to build the Redis key, read the raw JSON, validate it with `CachePayload.model_validate_json`, verify the schema version, customer id, report customer id, and report type, and return `None` for any absent/invalid/stale/mismatched value.

4. Emit clear trace records from the cache layer: `cache_hit` for reusable payloads and `cache_miss` with a reason for absent, invalid JSON/schema, stale schema, customer mismatch, or report-type mismatch.

5. Implement `ReportAgent.run_tool_chain` to call `lookup_customer` first, immediately return any structured lookup failure, then pass `lookup_result.data` as the `customer` argument to `format_report` together with the requested report type.

6. Emit trace records around each tool call and tool result so cache behavior and lookup/format behavior can be inspected during debugging.

7. Implement `ReportAgent.error_to_message` to map `customer_not_found`, `customer_inactive`, `invalid_arguments`, `lookup_failed`, `format_failed`, and `cache_unavailable` to safe user-facing messages that do not leak stack traces or internal database details.

8. In `build_report`, reuse valid cached reports without running lookup, recompute and refresh Redis on cache misses, and include a structured `error_code` alongside the safe error string for failure responses.

9. Run `AGENT_TEST_MODE=1 python -m agent --selfcheck` after starting Docker services to verify configuration and datastore reachability.

10. Run `pytest -q` to confirm cache hit/miss behavior, invalid/stale cache fallback, lookup normalization, lookup-to-formatter handoff, and structured missing/inactive customer responses.

