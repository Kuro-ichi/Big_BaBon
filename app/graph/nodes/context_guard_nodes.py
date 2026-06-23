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
    "tranh",
]

EMPTY_ANSWER_FALLBACK = "Mình chưa thể tạo câu trả lời an toàn ở lượt này. Bạn vui lòng thử lại sau."
UNSAFE_ANSWER_FALLBACK = (
    "Mình không thể cung cấp nội dung có thể dẫn đến việc tự ý ngừng thuốc, "
    "thay đổi điều trị hoặc áp dụng chế độ ăn nguy hiểm. Hãy trao đổi với bác sĩ "
    "phụ trách trước khi thay đổi thuốc hoặc phác đồ điều trị."
)


def _find_unsafe_pattern(answer_folded: str) -> str | None:
    for pattern in UNSAFE_ANSWER_PATTERNS:
        start = answer_folded.find(pattern)
        while start >= 0:
            prefix = answer_folded[max(0, start - 40):start]
            if not any(negation in prefix for negation in SAFE_NEGATIONS):
                return pattern
            start = answer_folded.find(pattern, start + len(pattern))
    return None


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
    # Safety fast-path dùng câu trả lời tĩnh đã được duyệt. Không quét lại bằng
    # matcher từ khóa đơn giản vì các câu an toàn thường chứa cụm "không nên
    # nhịn ăn", dễ bị nhận nhầm thành khuyến nghị nguy hiểm.
    curated_safety_answer = bool(
        state.get("safety_fast_path") and state.get("safety_action") == "respond"
    )
    unsafe_pattern = None if curated_safety_answer else _find_unsafe_pattern(answer_folded)
    if unsafe_pattern:
        problems.append(f"unsafe_phrase:{unsafe_pattern}")
    if problems:
        state["errors"].append({"node": "lightweight_guard", "problems": problems})
        state["answer"] = (
            EMPTY_ANSWER_FALLBACK
            if "empty_answer" in problems
            else UNSAFE_ANSWER_FALLBACK
        )
        state["confidence"] = 0.0
        state["citations"] = []
    state["metrics"]["guard_problems"] = problems
    state["metrics"]["guard_replaced_answer"] = bool(problems)
    state["trace"].append({"node": "lightweight_guard", "problems": problems})
    return state
