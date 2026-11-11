"""Day 3 real-LLM smoke test: 5 representative requests.

This is intentionally not part of pytest: it calls a paid LLM provider.
Run manually from backend/:

    python -m app.eval.smoke_llm
"""

from __future__ import annotations

from datetime import date, timedelta

from ..agents.planner import PlannerAgent
from ..dag.llm_pipeline import run_llm_pipeline
from ..domain.models import TripRequest
from ..llm.client import create_llm_client

CASES = [
    {
        "name": "2d-history-800",
        "start": "2026-11-14",
        "days": 2,
        "budget": 800,
        "preferences": ["历史文化"],
        "party": "solo",
        "accommodation": "经济型酒店",
        "transportation": "公共交通",
    },
    {
        "name": "1d-food-600",
        "start": "2026-11-15",
        "days": 1,
        "budget": 600,
        "preferences": ["美食"],
        "party": "solo",
        "accommodation": "经济型酒店",
        "transportation": "公共交通",
    },
    {
        "name": "3d-nature-1500",
        "start": "2026-11-17",
        "days": 3,
        "budget": 1500,
        "preferences": ["自然风光"],
        "party": "couple",
        "accommodation": "舒适型酒店",
        "transportation": "公共交通",
    },
    {
        "name": "2d-family-1000",
        "start": "2026-11-21",
        "days": 2,
        "budget": 1000,
        "preferences": ["亲子", "历史文化"],
        "party": "family",
        "accommodation": "舒适型酒店",
        "transportation": "打车",
    },
    {
        "name": "2d-elderly-1200",
        "start": "2026-11-24",
        "days": 2,
        "budget": 1200,
        "preferences": ["历史文化", "休闲"],
        "party": "elderly",
        "accommodation": "舒适型酒店",
        "transportation": "打车",
    },
]


def build_request(case: dict) -> TripRequest:
    start = date.fromisoformat(case["start"])
    end = start + timedelta(days=case["days"] - 1)
    return TripRequest(
        city="镇江",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        travel_days=case["days"],
        transportation=case["transportation"],
        accommodation=case["accommodation"],
        preferences=case["preferences"],
        budget_limit=case["budget"],
        party=case["party"],
        pace="normal",
    )


def main() -> int:
    planner = PlannerAgent(create_llm_client())
    failures = 0

    for case in CASES:
        request = build_request(case)
        try:
            result = run_llm_pipeline(request, planner)
            identity_ok = result.budget.total == sum(
                line.amount for line in result.budget.lines
            )
            plan_event = next(
                (event for event in result.trace if event.node_id == "plan"),
                None,
            )
            tokens = plan_event.meta.get("total_tokens", 0) if plan_event else 0
            attempts = (
                plan_event.meta.get("planner_attempts", 0) if plan_event else 0
            )
            ok = result.validation.passed and identity_ok
            status = "OK" if ok else "FAIL"
            if not ok:
                failures += 1
            print(
                f"[{status}] {case['name']}: "
                f"{len(result.days)}d, "
                f"budget={result.budget.total}, "
                f"over={result.budget.over_budget}, "
                f"tokens={tokens}, "
                f"attempts={attempts}, "
                f"validation={result.validation.passed}"
            )
        except Exception as exc:  # noqa: BLE001 - smoke test reports all failures
            failures += 1
            print(f"[FAIL] {case['name']}: {exc}")

    print(f"\nsummary: {len(CASES) - failures}/{len(CASES)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
