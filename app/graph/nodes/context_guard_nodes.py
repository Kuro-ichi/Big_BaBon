import unicodedata

from app.core.config import settings


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", (text or "").lower())
    folded = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return folded.replace("đ", "d")


UNSAFE_ANSWER_PATTERNS = [
    "bo thuoc",
    "ngung thuoc",
    "tu giam lieu",
    "bo insulin",
    "ngung insulin",
    "thay hoa tri",
    "thay xa tri",
    "bo loc mau",
    "chua khoi ung thu",
    "chua khoi tieu duong",
    "detox 3 ngay",
    "nhin an",
    "cang an it cang tot",
]

SAFE_NEGATIONS = [
    "khong",
    "khong nen",
    "khong the",
    "khong khuyen nghi",
    "dung",
    "tranh",
]


def rule_context_check_node(state):
    docs = state.get("documents", [])
    if not docs:
        state["confidence"] = 0.0
    else:
        state["confidence"] = min(max([doc.get("score", 0.5) for doc in docs]), 0.95)
    state["trace"].append({"node": "rule_context_check", "confidence": state["confidence"]})
    return state


def route_after_context_check(state):
    if state.get("safety_action") == "respond":
        return "answer_generation"
    if not settings.WEB_FALLBACK_ENABLED:
        return "answer_generation"
    if state.get("web_fallback_used"):
        return "answer_generation"

    plan = state.get("search_plan", {})
    needs_web = bool(plan.get("need_web", False))
    low_confidence = state.get("confidence", 0.0) < settings.WEB_FALLBACK_CONFIDENCE_THRESHOLD
    no_context = not state.get("selected_context")
    if needs_web or low_confidence or no_context:
        return "web_fallback"
    return "answer_generation"


def lightweight_guard_node(state):
    problems = []
    if not state.get("answer"):
        problems.append("empty_answer")
    answer_folded = _fold(state.get("answer") or "")
    if state.get("risk_level") in {"sensitive", "blocked"}:
        for pattern in UNSAFE_ANSWER_PATTERNS:
            if pattern in answer_folded and not any(negation in answer_folded for negation in SAFE_NEGATIONS):
                problems.append(f"unsafe_phrase:{pattern}")
                break
    if problems:
        state["errors"].append({"node": "lightweight_guard", "problems": problems})
    state["metrics"]["guard_problems"] = problems
    state["trace"].append({"node": "lightweight_guard", "problems": problems})
    return state
