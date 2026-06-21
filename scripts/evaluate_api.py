import argparse
import json
import re
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.services.auth_service import create_access_token


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


def normalize_match_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").lower()).strip()
    # "5 MB" và "5MB" là cùng một giá trị trong câu trả lời kỹ thuật.
    return re.sub(r"(?<=\d)\s+(?=(?:kb|mb|gb)\b)", "", normalized)


def contains_all(answer: str, phrases: list[str]) -> tuple[bool, list[str]]:
    folded = normalize_match_text(answer)
    missing = [phrase for phrase in phrases if normalize_match_text(phrase) not in folded]
    return not missing, missing


def contains_none(answer: str, phrases: list[str]) -> tuple[bool, list[str]]:
    folded = normalize_match_text(answer)
    hits = [phrase for phrase in phrases if normalize_match_text(phrase) in folded]
    return not hits, hits


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def source_type_hits(citations: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("source_type")) for item in citations if item.get("source_type")}


def check_case(case: dict[str, Any], response: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    missing: list[str] = []
    forbidden_hits: list[str] = []

    if error:
        checks["request_ok"] = False
        return {"passed": False, "checks": checks, "missing_phrases": missing, "forbidden_hits": forbidden_hits}

    response = response or {}
    answer = response.get("answer") or ""
    citations = response.get("citations") or []
    metrics = response.get("metrics") or {}

    checks["request_ok"] = True
    checks["answer_not_empty"] = bool(answer.strip())
    checks["no_llm_error"] = "[LLM error]" not in answer and "Không gọi được model local" not in answer

    if case.get("expected_route"):
        checks["route"] = response.get("route") == case["expected_route"]
    if "min_confidence" in case:
        checks["min_confidence"] = float(response.get("confidence") or 0.0) >= float(case["min_confidence"])
    if "min_citations" in case:
        checks["min_citations"] = len(citations) >= int(case["min_citations"])
    if case.get("expected_source_types"):
        checks["expected_source_types"] = set(case["expected_source_types"]).issubset(source_type_hits(citations))
    if case.get("guard_problems_empty", False):
        checks["guard_problems_empty"] = not metrics.get("guard_problems")
    if case.get("must_include"):
        ok, missing = contains_all(answer, case["must_include"])
        checks["must_include"] = ok
    if case.get("must_include_any"):
        folded = normalize_match_text(answer)
        alternatives = case["must_include_any"]
        hits = [phrase for phrase in alternatives if normalize_match_text(phrase) in folded]
        checks["must_include_any"] = bool(hits)
        if not hits:
            missing.extend(alternatives)
    if case.get("must_not_include"):
        ok, forbidden_hits = contains_none(answer, case["must_not_include"])
        checks["must_not_include"] = ok
    if case.get("require_vietnamese", False):
        checks["no_foreign_script"] = not bool(
            re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\u0400-\u04ff]", answer)
        )

    return {
        "passed": all(checks.values()),
        "checks": checks,
        "missing_phrases": missing,
        "forbidden_hits": forbidden_hits,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    latencies = [float(item.get("elapsed_seconds") or 0.0) for item in results]
    confidences = [float(item.get("confidence") or 0.0) for item in results if item.get("confidence") is not None]
    citation_counts = [int(item.get("citation_count") or 0) for item in results]

    by_category: dict[str, dict[str, Any]] = {}
    for item in results:
        category = item.get("category") or "unknown"
        bucket = by_category.setdefault(
            category,
            {"total": 0, "passed": 0, "failed": 0, "avg_latency_seconds": 0.0, "latencies": []},
        )
        bucket["total"] += 1
        bucket["passed"] += 1 if item.get("passed") else 0
        bucket["failed"] += 0 if item.get("passed") else 1
        bucket["latencies"].append(float(item.get("elapsed_seconds") or 0.0))

    for bucket in by_category.values():
        bucket["avg_latency_seconds"] = round(statistics.mean(bucket["latencies"]), 3) if bucket["latencies"] else 0.0
        bucket["p95_latency_seconds"] = round(percentile(bucket["latencies"], 0.95), 3)
        del bucket["latencies"]

    routes: dict[str, int] = {}
    for item in results:
        route = item.get("route") or "unknown"
        routes[route] = routes.get(route, 0) + 1

    expected_route_cases = [item for item in results if item.get("expected_route")]
    route_correct = sum(
        1 for item in expected_route_cases if item.get("route") == item.get("expected_route")
    )

    check_stats: dict[str, dict[str, Any]] = {}
    for item in results:
        for check_name, ok in (item.get("checks") or {}).items():
            bucket = check_stats.setdefault(check_name, {"total": 0, "passed": 0})
            bucket["total"] += 1
            bucket["passed"] += int(bool(ok))
    for bucket in check_stats.values():
        bucket["rate"] = round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0

    node_values: dict[str, list[float]] = {}
    server_latencies_ms: list[float] = []
    overhead_ms: list[float] = []
    for item in results:
        metrics = item.get("metrics") or {}
        for node, value in (metrics.get("node_latency_ms") or {}).items():
            node_values.setdefault(node, []).append(float(value or 0.0))
        if metrics.get("total_latency_ms") is not None:
            server_ms = float(metrics["total_latency_ms"])
            server_latencies_ms.append(server_ms)
            overhead_ms.append(max(0.0, float(item.get("elapsed_seconds") or 0.0) * 1000 - server_ms))

    node_latency_ms = {
        node: {
            "count": len(values),
            "min": round(min(values), 2),
            "avg": round(statistics.mean(values), 2),
            "p50": round(percentile(values, 0.50), 2),
            "p95": round(percentile(values, 0.95), 2),
            "max": round(max(values), 2),
        }
        for node, values in sorted(node_values.items())
    }

    context_followups = [
        item
        for item in results
        if item.get("context_required") is True
        or (
            "context_required" not in item
            and item.get("context_chain")
            and int(item.get("turn") or 0) > 1
        )
    ]
    context_passed = sum(1 for item in context_followups if item.get("passed"))
    context_content_hits = 0
    for item in context_followups:
        checks = item.get("checks") or {}
        content_checks = [
            checks[name]
            for name in ("must_include", "must_include_any")
            if name in checks
        ]
        if content_checks and all(content_checks):
            context_content_hits += 1
    context_route_hits = sum(
        1 for item in context_followups if (item.get("checks") or {}).get("route", False)
    )

    by_user: dict[str, dict[str, Any]] = {}
    for item in results:
        user_id = item.get("user_id") or "unknown"
        bucket = by_user.setdefault(user_id, {"total": 0, "passed": 0, "latencies": []})
        bucket["total"] += 1
        bucket["passed"] += int(bool(item.get("passed")))
        bucket["latencies"].append(float(item.get("elapsed_seconds") or 0.0))
    for bucket in by_user.values():
        bucket["pass_rate"] = round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0
        bucket["avg_latency_seconds"] = round(statistics.mean(bucket["latencies"]), 3)
        del bucket["latencies"]

    by_subcategory: dict[str, dict[str, Any]] = {}
    for item in results:
        if not item.get("subcategory"):
            continue
        bucket = by_subcategory.setdefault(item["subcategory"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += int(bool(item.get("passed")))
    for bucket in by_subcategory.values():
        bucket["pass_rate"] = round(bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0

    status_codes: dict[str, int] = {}
    for item in results:
        code = str(item.get("status_code") or "error")
        status_codes[code] = status_codes.get(code, 0) + 1

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "latency_seconds": {
            "min": round(min(latencies), 3) if latencies else 0.0,
            "avg": round(statistics.mean(latencies), 3) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 3),
            "p90": round(percentile(latencies, 0.90), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "confidence": {
            "avg": round(statistics.mean(confidences), 4) if confidences else 0.0,
            "min": round(min(confidences), 4) if confidences else 0.0,
            "max": round(max(confidences), 4) if confidences else 0.0,
        },
        "citations": {
            "avg_count": round(statistics.mean(citation_counts), 3) if citation_counts else 0.0,
            "min_count": min(citation_counts) if citation_counts else 0,
            "max_count": max(citation_counts) if citation_counts else 0,
        },
        "routes": routes,
        "route_accuracy": {
            "correct": route_correct,
            "total": len(expected_route_cases),
            "rate": round(route_correct / len(expected_route_cases), 4) if expected_route_cases else 0.0,
        },
        "check_pass_rates": check_stats,
        "status_codes": status_codes,
        "server_latency_ms": {
            "avg": round(statistics.mean(server_latencies_ms), 2) if server_latencies_ms else 0.0,
            "p95": round(percentile(server_latencies_ms, 0.95), 2),
            "max": round(max(server_latencies_ms), 2) if server_latencies_ms else 0.0,
        },
        "client_overhead_ms": {
            "avg": round(statistics.mean(overhead_ms), 2) if overhead_ms else 0.0,
            "p95": round(percentile(overhead_ms, 0.95), 2),
        },
        "node_latency_ms": node_latency_ms,
        "context_followups": {
            "total": len(context_followups),
            "full_case_passed": context_passed,
            "full_case_pass_rate": round(context_passed / len(context_followups), 4) if context_followups else 0.0,
            "content_recall_passed": context_content_hits,
            "content_recall_rate": round(context_content_hits / len(context_followups), 4) if context_followups else 0.0,
            "route_correct": context_route_hits,
            "route_accuracy": round(context_route_hits / len(context_followups), 4) if context_followups else 0.0,
            "failed_ids": [item.get("id") for item in context_followups if not item.get("passed")],
        },
        "by_user": by_user,
        "by_subcategory": by_subcategory,
        "by_category": by_category,
        "llm_error_count": sum(1 for item in results if "[LLM error]" in (item.get("answer") or "")),
        "failed_ids": [item.get("id") for item in results if not item.get("passed")],
        "top_slowest": sorted(
            [
                {"id": item.get("id"), "category": item.get("category"), "elapsed_seconds": item.get("elapsed_seconds")}
                for item in results
            ],
            key=lambda item: item["elapsed_seconds"] or 0,
            reverse=True,
        )[:10],
    }


def run_case(
    client: httpx.Client,
    url: str,
    case: dict[str, Any],
    index: int,
    token: str | None = None,
) -> dict[str, Any]:
    payload = {
        "request_id": f"eval-{case.get('id')}-{uuid.uuid4()}",
        "user_id": case.get("user_id", "docker-api-eval-user"),
        "session_id": case.get("session_id", f"docker-api-eval-session-{index}"),
        "message": case["query"],
        "language": case.get("language", "vi"),
        "stream": False,
    }

    start = time.perf_counter()
    response_json = None
    error = None
    status_code = None
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        response = client.post(url, json=payload, headers=headers)
        status_code = response.status_code
        response.raise_for_status()
        response_json = response.json()
    except Exception as exc:
        error = repr(exc)
    elapsed = round(time.perf_counter() - start, 3)

    verdict = check_case(case, response_json, error)
    response_json = response_json or {}
    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "subcategory": case.get("subcategory"),
        "user_id": payload["user_id"],
        "session_id": payload["session_id"],
        "context_chain": case.get("context_chain"),
        "context_required": case.get("context_required"),
        "turn": case.get("turn"),
        "query": case.get("query"),
        "expected_route": case.get("expected_route"),
        "passed": verdict["passed"],
        "checks": verdict["checks"],
        "missing_phrases": verdict["missing_phrases"],
        "forbidden_hits": verdict["forbidden_hits"],
        "status_code": status_code,
        "route": response_json.get("route"),
        "confidence": response_json.get("confidence"),
        "citation_count": len(response_json.get("citations") or []),
        "citations": (response_json.get("citations") or [])[:5],
        "metrics": response_json.get("metrics") or {},
        "answer": response_json.get("answer") or "",
        "elapsed_seconds": elapsed,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the running Docker API via HTTP.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--url", default="http://localhost:8000/v1/chat")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--run-id", default="", help="Hậu tố session để mỗi lần chạy không dính lịch sử cũ.")
    parser.add_argument("--token", default="", help="Một Bearer token dùng cho mọi case (không phù hợp test multi-user).")
    parser.add_argument(
        "--no-auto-auth",
        action="store_true",
        help="Không tự tạo Bearer token riêng từ user_id của từng case.",
    )
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if args.limit:
        cases = cases[: args.limit]

    results = []
    user_tokens: dict[str, str] = {}
    suite_started = time.perf_counter()
    with httpx.Client(timeout=args.timeout) as client:
        for index, case in enumerate(cases, start=1):
            if args.run_id:
                case = {**case, "session_id": f"{case.get('session_id', f'eval-session-{index}')}-{args.run_id}"}
            token = args.token or None
            if not token and not args.no_auto_auth and settings.AUTH_REQUIRED:
                user_id = case.get("user_id", "docker-api-eval-user")
                token = user_tokens.setdefault(user_id, create_access_token(user_id, 120))
            result = run_case(client, args.url, case, index, token=token)
            results.append(result)
            print(
                f"[{index}/{len(cases)}] {result['id']} "
                f"passed={result['passed']} route={result.get('route')} "
                f"elapsed={result['elapsed_seconds']}s"
            )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        for result in results:
            output.write(json.dumps(result, ensure_ascii=False) + "\n")

    summary = summarize(results)
    execution_seconds = round(time.perf_counter() - suite_started, 3)
    summary["execution"] = {
        "seconds": execution_seconds,
        "requests_per_second": round(len(results) / execution_seconds, 4) if execution_seconds else 0.0,
        "sequential": True,
    }
    summary_path = Path(args.summary_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
