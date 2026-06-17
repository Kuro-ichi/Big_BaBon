from typing import TypedDict, List, Dict, Any

class ChatState(TypedDict):
    request_id: str
    user_id: str
    session_id: str
    original_question: str
    rewritten_question: str
    route: str
    intent: str
    risk_level: str
    safety_action: str
    safety_condition: str
    safety_response_kind: str
    safety_fast_path: bool
    runtime_context: Dict[str, Any]
    search_plan: Dict[str, Any]
    documents: List[Dict[str, Any]]
    selected_context: str
    citations: List[Dict[str, Any]]
    answer: str
    confidence: float
    web_fallback_used: bool
    errors: List[Dict[str, Any]]
    trace: List[Dict[str, Any]]
    metrics: Dict[str, Any]
