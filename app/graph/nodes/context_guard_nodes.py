def rule_context_check_node(state):
    docs = state.get("documents", [])
    if not docs:
        state["confidence"] = 0.0
    else:
        state["confidence"] = min(max([doc.get("score", 0.5) for doc in docs]), 0.95)
    state["trace"].append({"node": "rule_context_check", "confidence": state["confidence"]})
    return state

def lightweight_guard_node(state):
    problems = []
    if not state.get("answer"):
        problems.append("empty_answer")
    state["metrics"]["guard_problems"] = problems
    state["trace"].append({"node": "lightweight_guard", "problems": problems})
    return state
