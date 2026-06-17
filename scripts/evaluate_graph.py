import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.postgres import close_pool
from app.graph.graph_builder import build_chat_graph


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return cases


def initial_state(case: dict[str, Any]) -> dict[str, Any]:
    query = case["query"]
    case_id = case.get("id") or str(uuid.uuid4())
    return {
        "request_id": f"eval-{case_id}",
        "user_id": case.get("user_id", f"eval-user-{case_id}"),
        "session_id": case.get("session_id", f"eval-session-{case_id}"),
        "original_question": query,
        "rewritten_question": "",
        "route": "",
        "intent": "",
        "risk_level": "normal",
        "safety_action": "pass",
        "safety_condition": "",
        "safety_response_kind": "",
        "safety_fast_path": False,
        "runtime_context": {},
        "search_plan": {},
        "documents": [],
        "selected_context": "",
        "citations": [],
        "answer": "",
        "confidence": 0.0,
        "web_fallback_used": False,
        "errors": [],
        "trace": [],
        "metrics": {},
    }


def contains_all(answer: str, phrases: list[str]) -> tuple[bool, list[str]]:
    folded = answer.lower()
    missing = [phrase for phrase in phrases if phrase.lower() not in folded]
    return not missing, missing


def contains_none(answer: str, phrases: list[str]) -> tuple[bool, list[str]]:
    folded = answer.lower()
    hits = [phrase for phrase in phrases if phrase.lower() in folded]
    return not hits, hits


def source_type_hits(citations: list[dict[str, Any]], documents: list[dict[str, Any]]) -> set[str]:
    hits = {str(item.get("source_type")) for item in citations if item.get("source_type")}
    for doc in documents:
        metadata = doc.get("metadata", {}) or {}
        if metadata.get("source_type"):
            hits.add(str(metadata["source_type"]))
    return hits


def check_case(case: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    checks = {}
    answer = state.get("answer") or ""

    if case.get("expected_route"):
        checks["route"] = state.get("route") == case["expected_route"]
    if case.get("expected_safety_condition"):
        checks["safety_condition"] = state.get("safety_condition") == case["expected_safety_condition"]
    if case.get("expected_safety_action"):
        checks["safety_action"] = state.get("safety_action") == case["expected_safety_action"]
    if "min_confidence" in case:
        checks["min_confidence"] = float(state.get("confidence") or 0.0) >= float(case["min_confidence"])
    if "min_citations" in case:
        checks["min_citations"] = len(state.get("citations", [])) >= int(case["min_citations"])
    if case.get("expected_source_types"):
        found = source_type_hits(state.get("citations", []), state.get("documents", []))
        checks["expected_source_types"] = set(case["expected_source_types"]).issubset(found)
    if case.get("must_include"):
        ok, missing = contains_all(answer, case["must_include"])
        checks["must_include"] = ok
    else:
        missing = []
    if case.get("must_not_include"):
        ok, forbidden_hits = contains_none(answer, case["must_not_include"])
        checks["must_not_include"] = ok
    else:
        forbidden_hits = []
    if case.get("guard_problems_empty", False):
        checks["guard_problems_empty"] = not state.get("metrics", {}).get("guard_problems")

    passed = all(checks.values()) if checks else True
    return {
        "passed": passed,
        "checks": checks,
        "missing_phrases": missing,
        "forbidden_hits": forbidden_hits,
    }


async def run_cases(cases: list[dict[str, Any]], *, limit: int = 0, ids: set[str] | None = None) -> list[dict[str, Any]]:
    graph = build_chat_graph()
    selected_cases = cases
    if ids:
        selected_cases = [case for case in selected_cases if case.get("id") in ids]
    if limit:
        selected_cases = selected_cases[:limit]

    results = []
    for index, case in enumerate(selected_cases, start=1):
        start = time.time()
        try:
            state = await graph.ainvoke(initial_state(case))
            verdict = check_case(case, state)
            result = {
                "id": case.get("id"),
                "category": case.get("category"),
                "query": case.get("query"),
                "passed": verdict["passed"],
                "checks": verdict["checks"],
                "missing_phrases": verdict["missing_phrases"],
                "forbidden_hits": verdict["forbidden_hits"],
                "route": state.get("route"),
                "risk_level": state.get("risk_level"),
                "safety_action": state.get("safety_action"),
                "safety_condition": state.get("safety_condition"),
                "confidence": state.get("confidence"),
                "citation_count": len(state.get("citations", [])),
                "citations": state.get("citations", [])[:5],
                "top_context": state.get("metrics", {}).get("top_context", []),
                "guard_problems": state.get("metrics", {}).get("guard_problems", []),
                "trace": state.get("trace", []),
                "answer": state.get("answer", ""),
                "elapsed_seconds": round(time.time() - start, 2),
                "error": None,
            }
        except Exception as exc:
            result = {
                "id": case.get("id"),
                "category": case.get("category"),
                "query": case.get("query"),
                "passed": False,
                "error": repr(exc),
                "elapsed_seconds": round(time.time() - start, 2),
            }
        print(f"[{index}/{len(selected_cases)}] {result.get('id')} passed={result['passed']} route={result.get('route')} elapsed={result['elapsed_seconds']}s")
        results.append(result)
    return results


def write_results(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for result in results:
            output.write(json.dumps(result, ensure_ascii=False) + "\n")


def print_summary(results: list[dict[str, Any]]) -> None:
    total = len(results)
    passed = sum(1 for result in results if result.get("passed"))
    failed = total - passed
    print(json.dumps({
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "failed_ids": [result.get("id") for result in results if not result.get("passed")],
    }, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Big_BaBon graph with JSONL test cases.")
    parser.add_argument("--cases", default=str(PROJECT_ROOT / "evals" / "smoke_cases.jsonl"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "evals" / "latest_results.jsonl"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="Comma-separated case ids to run.")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    ids = {item.strip() for item in args.ids.split(",") if item.strip()} or None
    cases = load_cases(Path(args.cases))
    results = await run_cases(cases, limit=args.limit, ids=ids)
    write_results(Path(args.output), results)
    print_summary(results)
    await close_pool()


if __name__ == "__main__":
    asyncio.run(async_main())
