"""CLI: key-free selfcheck and an optional end-to-end run."""
import argparse
import sys

from .config import config
from .schemas import ReportRequest
from .tools import TOOL_SPECS, ALLOWED_TOOL_NAMES, RedisCacheTool


def selfcheck() -> int:
    """Key-free readiness: imports, tool specs, config, datastore reachability.

    Does NOT call candidate stubs, the model, or the full agent loop.
    """
    print("[selfcheck] config loaded:", config.AGENT_MODEL, "test_mode=", config.AGENT_TEST_MODE)
    names = {t["function"]["name"] for t in TOOL_SPECS}
    assert names == ALLOWED_TOOL_NAMES, f"tool spec / allowed names mismatch: {names}"
    print("[selfcheck] tool specs OK:", sorted(names))

    cache = RedisCacheTool()
    print("[selfcheck] redis ping:", cache.ping())

    # Light DB connectivity check (no candidate logic).
    try:
        import psycopg
        with psycopg.connect(config.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM customers")
                n = cur.fetchone()[0]
        print("[selfcheck] customers rows:", n)
    except Exception as exc:  # noqa: BLE001
        print("[selfcheck] WARN db check skipped:", exc)

    print("[selfcheck] OK")
    return 0


def run_end_to_end(customer_id: str) -> int:
    from .orchestrator import ReportAgent
    agent = ReportAgent()
    out = agent.run_with_model(ReportRequest(customer_id=customer_id))
    print(out)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--customer", default="CUST-1002")
    args = parser.parse_args()
    if args.selfcheck:
        return selfcheck()
    return run_end_to_end(args.customer)


if __name__ == "__main__":
    sys.exit(main())

