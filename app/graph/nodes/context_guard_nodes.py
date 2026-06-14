def _safe_score(value, default=0.5):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def rule_context_check_node(state):
    docs = state.get("documents", [])
    selected_count = state.get("metrics", {}).get("context", {}).get("selected_count", 0)
    if not docs:
        state["confidence"] = 0.0
    else:
        best_score = max([_safe_score(doc.get("rerank_score", doc.get("score", 0.5))) for doc in docs])
        coverage_bonus = min(selected_count * 0.04, 0.2)
        state["confidence"] = round(min(max(best_score + coverage_bonus, 0.05), 0.95), 4)
    state["metrics"]["context_guard"] = {
        "has_context": bool(state.get("selected_context")),
        "citation_count": len(state.get("citations", [])),
    }
    state["trace"].append({"node": "rule_context_check", "confidence": state["confidence"]})
    return state

def lightweight_guard_node(state):
    problems = []
    if not state.get("answer"):
        problems.append("empty_answer")
    if state.get("selected_context") and not state.get("citations"):
        problems.append("missing_citations")
    answer_lower = state.get("answer", "").lower()
    if "system prompt" in answer_lower or "chain-of-thought" in answer_lower or "developer message" in answer_lower:
        problems.append("internal_prompt_leak_risk")
    if state.get("route") == "rag" and not state.get("selected_context"):
        problems.append("insufficient_context")
    state["metrics"]["guard_problems"] = problems
    state["trace"].append({"node": "lightweight_guard", "problems": problems})
    return state
