import unicodedata

from app.core.config import settings
from app.services.llm_service import llm_service
from app.services.safety_gate import is_direct_knowledge_question, safety_gate


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", (text or "").lower())
    folded = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return folded.replace("đ", "d")


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _merge_search_plan(state, precheck: dict, updates: dict):
    precheck["search_plan"] = {
        **precheck.get("search_plan", {}),
        **updates,
    }
    state["search_plan"] = precheck["search_plan"]


RAG_HINT_TERMS = [
    "tai lieu",
    "knowledge base",
    "citation",
    "nguon",
    "context",
    "du lieu",
    "bang",
    "dinh duong",
    "thuc pham",
    "tieu duong",
    "dai thao duong",
    "di ung",
    "benh",
    "suc khoe",
    "theo who",
    "moi nhat",
]

SAFETY_HINT_TERMS = [
    "insulin",
    "detox",
    "nhin an",
    "bo bua",
    "bo thuoc",
    "ngung thuoc",
    "ung thu",
    "hoa tri",
    "xa tri",
    "suy than",
    "benh than",
    "kali cao",
    "muoi kali",
    "mang thai",
    "tre em",
    "gao lut muoi me",
    "duong huyet",
    "ha duong huyet",
    "di ung",
    "kho tho",
    "sung moi",
]

FOOD_HINT_TERMS = [
    "bao nhieu calo",
    "bao nhieu kcal",
    "calo",
    "kcal",
    "protein",
    "lipid",
    "glucid",
    "natri",
    "sat",
    "kem",
    "bang dinh duong",
    "mon an",
    "nguyen lieu",
    "cong thuc",
]

DIABETES_HINT_TERMS = [
    "tieu duong",
    "dai thao duong",
    "duong huyet",
    "insulin",
    "gliclazide",
    "metformin",
]

TECHNICAL_DIRECT_TERMS = [
    "api",
    "endpoint",
    "http",
    "json",
    "schema",
    "timeout",
    "request",
    "response",
    "webhook",
    "header",
    "method",
    "status",
    "multipart",
    "rate limit",
    "test case",
    "negative test",
    "boundary test",
    "assertion",
    "field",
    "phan trang",
    "page",
    "limit",
    "idempotency",
]

CONTEXT_FOLLOWUP_TERMS = [
    "vua noi",
    "luc nay",
    "cua no",
    "api do",
    "endpoint do",
    "header do",
    "gioi han do",
    "da thong nhat",
    "test nay",
    "tai lieu do",
    "guardrail do",
    "nguoi do",
    "benh nhan do",
    "truong hop do",
    "truong hop cua toi",
    "nhac lai",
    "tom tat",
]


def _is_direct_technical_question(question: str, runtime_context: dict) -> bool:
    question_folded = _fold(question)
    if _has_any(question_folded, TECHNICAL_DIRECT_TERMS):
        return True

    recent = " ".join(
        str(item.get("content") or "")
        for item in (runtime_context or {}).get("recent_messages", [])[-4:]
    )
    recent_folded = _fold(recent)
    return bool(
        recent_folded
        and _has_any(recent_folded, TECHNICAL_DIRECT_TERMS)
        and _has_any(question_folded, CONTEXT_FOLLOWUP_TERMS)
    )


def _prior_source_types(runtime_context: dict) -> set[str]:
    source_types: set[str] = set()
    for item in reversed((runtime_context or {}).get("recent_messages", [])):
        metadata = item.get("metadata") or {}
        for citation in metadata.get("citations") or []:
            source_type = str(citation.get("source_type") or "").strip()
            if source_type:
                source_types.add(source_type)
        if source_types:
            break
    return source_types


async def smart_precheck_node(state):
    question = state["original_question"]
    gate = safety_gate(question)
    direct_knowledge = is_direct_knowledge_question(question)
    direct_technical = _is_direct_technical_question(question, state["runtime_context"])
    if gate:
        precheck = {
            "route": "rag",
            "risk_level": "blocked",
            "risk_domain": gate["condition"],
            "risk_action": gate["kind"],
            "route_confidence": 1.0,
            "rewritten_query": question,
            "search_plan": {},
        }
    elif direct_knowledge or direct_technical:
        precheck = {
            "route": "direct_answer",
            "risk_level": "normal",
            "risk_domain": "none",
            "risk_action": "none",
            "route_confidence": 1.0,
            "rewritten_query": question,
            "search_plan": {},
        }
    else:
        precheck = await llm_service.smart_precheck(
            question=question,
            runtime_context=state["runtime_context"],
        )
    route = precheck.get("route", "rag")
    question_folded = _fold(question)
    contextual_followup = _has_any(question_folded, CONTEXT_FOLLOWUP_TERMS)
    prior_source_types = _prior_source_types(state["runtime_context"])
    prior_safety_context = contextual_followup and "safety_guardrail" in prior_source_types
    prior_food_context = contextual_followup and "food_composition_table" in prior_source_types
    semantic_risk = (
        precheck.get("risk_domain") not in {None, "", "none"}
        and precheck.get("risk_action") not in {None, "", "none"}
        and float(precheck.get("route_confidence") or 0.0) >= settings.ROUTER_RISK_OVERRIDE_CONFIDENCE
    )
    food_query = _has_any(question_folded, FOOD_HINT_TERMS) and not prior_safety_context

    if gate:
        route = "rag"
        state.setdefault("metrics", {})["safety_gate_hit"] = gate["condition"]
        _merge_search_plan(
            state,
            precheck,
            {
                "need_kb": True,
                "preferred_source_types": gate["preferred_source_types"],
                "condition": gate["preferred_conditions"],
                "top_k_vector": max(int(precheck.get("search_plan", {}).get("top_k_vector", 8)), 10),
            },
        )
    elif prior_safety_context or prior_food_context:
        route = "rag"
        _merge_search_plan(state, precheck, {"need_kb": True})
    elif semantic_risk:
        route = "rag"
        _merge_search_plan(state, precheck, {"need_kb": True})
    elif food_query:
        route = "rag"
        _merge_search_plan(state, precheck, {"need_kb": True})
    elif route == "rag" and direct_knowledge:
        route = "direct_answer"
        precheck["search_plan"] = {}
        state["search_plan"] = {}
    elif route in {"direct_answer", "clarify", "safety"} and _has_any(question_folded, SAFETY_HINT_TERMS):
        route = "rag"
        _merge_search_plan(state, precheck, {"need_kb": True})
    elif (
        route == "direct_answer"
        and not direct_technical
        and _has_any(question_folded, RAG_HINT_TERMS)
    ):
        route = "rag"
        _merge_search_plan(state, precheck, {"need_kb": True})

    plan_updates = {}
    if prior_safety_context:
        plan_updates.update({
            "need_kb": True,
            "preferred_source_types": [
                "safety_guardrail",
                "clinical_nutrition_guideline",
                "clinical_patient_guidance",
            ],
            "top_k_vector": max(int(precheck.get("search_plan", {}).get("top_k_vector", 8)), 10),
        })
    elif prior_food_context:
        plan_updates.update({
            "need_kb": True,
            "preferred_source_types": ["food_composition_table"],
            "condition": ["food_data"],
            "top_k_vector": max(int(precheck.get("search_plan", {}).get("top_k_vector", 8)), 12),
            "top_k_keyword": 0,
        })
    elif _has_any(question_folded, SAFETY_HINT_TERMS):
        plan_updates.update({
            "need_kb": True,
            "preferred_source_types": [
                "safety_guardrail",
                "clinical_nutrition_guideline",
                "clinical_patient_guidance",
            ],
            "top_k_vector": max(int(precheck.get("search_plan", {}).get("top_k_vector", 8)), 10),
        })
        if _has_any(question_folded, DIABETES_HINT_TERMS):
            plan_updates["condition"] = ["diabetes"]
    elif food_query:
        plan_updates.update({
            "need_kb": True,
            "preferred_source_types": ["food_composition_table"],
            "condition": ["food_data"],
            "top_k_vector": max(int(precheck.get("search_plan", {}).get("top_k_vector", 8)), 12),
            "top_k_keyword": 0,
        })
    elif _has_any(question_folded, DIABETES_HINT_TERMS):
        plan_updates.update({
            "need_kb": True,
            "preferred_source_types": [
                "clinical_nutrition_guideline",
                "safety_guardrail",
            ],
            "condition": ["diabetes"],
            "top_k_vector": max(int(precheck.get("search_plan", {}).get("top_k_vector", 8)), 10),
        })

    if plan_updates:
        _merge_search_plan(state, precheck, plan_updates)

    state["route"] = route
    state["risk_level"] = precheck.get("risk_level", "normal")
    state["rewritten_question"] = precheck.get("rewritten_query", state["original_question"])
    state["search_plan"] = precheck.get("search_plan", {})
    state.setdefault("metrics", {})["router"] = {
        "llm_route": precheck.get("route"),
        "final_route": route,
        "risk_domain": precheck.get("risk_domain", "none"),
        "risk_action": precheck.get("risk_action", "none"),
        "confidence": float(precheck.get("route_confidence") or 0.0),
        "safety_gate_hit": gate.get("condition") if gate else None,
    }
    state["trace"].append({
        "node": "smart_precheck",
        "route": state["route"],
        "preferred_source_types": state["search_plan"].get("preferred_source_types", []),
    })
    return state


def route_after_precheck(state):
    route = state.get("route")
    if route == "smalltalk":
        return "smalltalk_answer"
    if route == "direct_answer":
        return "direct_answer"
    if route == "clarify":
        return "clarify_response"
    if route == "safety":
        return "safety_response"
    return "parallel_retrieval"
