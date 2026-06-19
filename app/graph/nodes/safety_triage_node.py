import re
import unicodedata

from app.policies.safety_policy import policy_citation
from app.services.safety_gate import safety_gate


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", (text or "").lower())
    folded = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return folded.replace("đ", "d")


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _set_safety(
    state,
    *,
    action: str,
    condition: str,
    kind: str,
    suffix: str = "",
    preferred_conditions: list[str] | None = None,
):
    state["safety_action"] = action
    state["safety_condition"] = condition
    state["safety_response_kind"] = kind
    state["risk_level"] = "blocked" if action == "respond" else "sensitive"

    plan = dict(state.get("search_plan", {}))
    plan["need_kb"] = True
    plan["need_user_memory"] = True
    plan["preferred_source_types"] = [
        "safety_guardrail",
        "clinical_nutrition_guideline",
        "clinical_patient_guidance",
    ]
    if preferred_conditions:
        plan["condition"] = preferred_conditions
    plan["top_k_vector"] = max(int(plan.get("top_k_vector", 8)), 10)
    state["search_plan"] = plan

    if suffix:
        state["rewritten_question"] = f"{state.get('rewritten_question') or state['original_question']} {suffix}"
    return state


async def safety_triage_node(state):
    text = _fold(state.get("original_question", ""))
    gate = safety_gate(state.get("original_question", ""))

    if gate:
        _set_safety(
            state,
            action=gate["action"],
            condition=gate["condition"],
            kind=gate["kind"],
            suffix=gate["suffix"],
            preferred_conditions=gate["preferred_conditions"],
        )
        if gate.get("fast_path"):
            state["safety_fast_path"] = True
            state["citations"] = [policy_citation(gate["condition"])]
            state.setdefault("metrics", {})["safety_fast_path"] = True
    elif _has_any(text, ["bo qua moi quy tac", "ignore previous", "ignore all rules", "bo qua quy tac an toan"]):
        _set_safety(
            state,
            action="respond",
            condition="prompt_injection",
            kind="prompt_injection",
            suffix="prompt injection khong bo qua quy tac an toan khong khuyen bo thuoc",
            preferred_conditions=["general"],
        )
    elif _has_any(text, ["duong huyet 45", "duong huyet 50", "ha duong huyet", "run tay", "va mo hoi", "lu lan"]) and _has_any(text, ["insulin", "gliclazide", "sulfonylurea", "thuoc tieu duong"]):
        _set_safety(
            state,
            action="respond",
            condition="diabetes_hypoglycemia",
            kind="acute_hypoglycemia",
            suffix="ha duong huyet insulin sulfonylurea can xu tri an toan khan cap",
            preferred_conditions=["diabetes"],
        )
    elif _has_any(text, ["insulin", "gliclazide", "sulfonylurea"]) and _has_any(text, ["detox", "nhin an", "bo bua", "nuoc gao lut", "cat carb", "giam carb dot ngot"]):
        _set_safety(
            state,
            action="respond",
            condition="diabetes_insulin_or_secretagogue",
            kind="insulin_detox",
            suffix="dai thao duong insulin sulfonylurea detox nhin an bo bua ha duong huyet khong tu bo thuoc",
            preferred_conditions=["diabetes"],
        )
    elif _has_any(text, ["ung thu", "hoa tri", "xa tri"]) and _has_any(text, ["thay", "chua", "phac do", "bo dieu tri", "ngung dieu tri", "khoi benh"]):
        _set_safety(
            state,
            action="respond",
            condition="cancer_safety",
            kind="cancer_treatment_replacement",
            suffix="ung thu thuc duong khong thay hoa tri xa tri dieu tri chuan",
            preferred_conditions=["cancer_safety"],
        )
    elif _has_any(text, ["ung thu", "hoa tri", "xa tri"]) and _has_any(text, ["sut can", "an kem", "met moi", "raw", "vegan", "thanh loc", "detox", "nhin an"]):
        _set_safety(
            state,
            action="respond",
            condition="cancer_cachexia",
            kind="cancer_cachexia_restrictive",
            suffix="ung thu hoa tri sut can an kem khong an kieng cuc doan can nang luong protein",
            preferred_conditions=["cancer_safety"],
        )
    elif _has_any(text, ["suy than", "benh than", "ckd", "kali cao", "loc mau"]) and _has_any(text, ["muoi kali", "muoi thay the", "detox", "nhin an", "giam phu", "bo loc mau"]):
        _set_safety(
            state,
            action="respond",
            condition="ckd_safety",
            kind="ckd_potassium_or_fasting",
            suffix="suy than kali cao muoi thay the nhin an detox can bac si",
            preferred_conditions=["ckd"],
        )
    elif _has_any(text, ["tang huyet ap", "cao huyet ap", "huyet ap cao"]) and _has_any(text, ["muoi me", "miso", "tamari", "nuoc tuong", "dua muoi", "do muoi", "muoi"]):
        _set_safety(
            state,
            action="respond",
            condition="hypertension_sodium",
            kind="hypertension_sodium",
            suffix="tang huyet ap can than natri muoi me miso nuoc tuong dua muoi",
            preferred_conditions=["hypertension"],
        )
    elif _has_any(text, ["di ung", "soc phan ve", "kho tho", "sung moi", "sung mat", "noi me day"]) and _has_any(text, ["me", "dau phong", "lac", "dau nanh", "thuc pham"]):
        _set_safety(
            state,
            action="respond",
            condition="severe_allergy",
            kind="severe_allergy",
            suffix="di ung thuc pham kho tho sung moi noi me day khong thu tai nha",
            preferred_conditions=["general"],
        )
    elif _has_any(text, ["mang thai", "thai ky", "co bau", "tre em", "be ", "con toi", "nguoi gia", "thieu can", "sut can", "roi loan an uong"]) and _has_any(text, ["thuc duong nghiem", "gao lut muoi me", "bo sua", "bo trung", "bo thit", "giam can", "an kieng", "an rat it"]):
        _set_safety(
            state,
            action="respond",
            condition="vulnerable_group_restrictive",
            kind="restrictive_diet_vulnerable_group",
            suffix="thai ky tre em nguoi gia thieu can an kieng nghiem can du nang luong protein vi chat",
            preferred_conditions=["pregnancy", "vegetarian_risk"],
        )
    elif _has_any(text, ["100 ngay het benh", "chua khoi ung thu", "chua khoi tieu duong", "gao lut muoi me chua", "cang an it cang tot"]):
        _set_safety(
            state,
            action="respond",
            condition="miracle_cure_claim",
            kind="miracle_cure_claim",
            suffix="khong co che do an chua khoi ung thu tieu duong khong dua claim tuyet doi",
            preferred_conditions=["general"],
        )
    elif _has_any(text, ["soi than", "oxalate", "soi oxalat"]) and _has_any(text, ["rau bina", "cai bo xoi", "me", "hat", "tra dac"]):
        _set_safety(
            state,
            action="respond",
            condition="kidney_stone_oxalate",
            kind="kidney_stone_oxalate",
            suffix="soi than oxalate can than rau bina me hat tra dac",
            preferred_conditions=["ckd", "general"],
        )
    elif re.search(r"(bo|ngung|dung|giam).{0,20}(thuoc|insulin|hoa tri|xa tri|loc mau|tai kham)", text):
        _set_safety(
            state,
            action="respond",
            condition="medical_treatment_stop",
            kind="stop_medication",
            suffix="khong tu bo thuoc khong thay dieu tri y khoa bang an uong",
            preferred_conditions=["general"],
        )

    state["trace"].append({
        "node": "safety_triage",
        "action": state.get("safety_action", "pass"),
        "condition": state.get("safety_condition", ""),
    })
    return state


def route_after_safety_triage(state):
    if state.get("safety_fast_path") and state.get("safety_action") == "respond":
        return "answer_generation"
    return "parallel_retrieval"
