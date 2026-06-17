import re
import unicodedata
from typing import Any, Iterable

from app.policies.safety_policy import get_safety_policy



def fold_text(text: str | None) -> str:
    """Lowercase, remove Vietnamese accents, and normalize Vietnamese 'đ'."""
    normalized = unicodedata.normalize("NFD", (text or "").lower())
    folded = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return folded.replace("đ", "d")


def has_any(text: str, terms: Iterable[str]) -> bool:
    """Return True when normalized text contains any normalized term."""
    return any(fold_text(term) in text for term in terms if term)


def has_regex(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns if pattern)


def _gate(
    *,
    condition: str,
    kind: str,
    suffix: str,
    preferred_conditions: list[str] | None = None,
    action: str = "respond",
) -> dict[str, Any]:
    policy = get_safety_policy(condition)
    return {
        "action": action,
        "condition": condition,
        "kind": kind,
        "suffix": suffix,
        "fast_path": policy["fast_path"],
        "preferred_conditions": preferred_conditions or policy["preferred_conditions"],
        "preferred_source_types": policy["preferred_source_types"],
    }


def safety_gate(question: str | None) -> dict[str, Any] | None:
    """Deterministic high-risk gate.

    This gate intentionally covers only high-risk health/safety combinations.
    General routing still belongs to the LLM precheck. The goal is to prevent
    dangerous requests from bypassing safety triage when the LLM router chooses
    direct_answer or clarify.
    """
    text = fold_text(question)
    if not text.strip():
        return None

    if has_any(
        text,
        [
            "bo qua moi quy tac",
            "bo qua quy tac an toan",
            "bo qua huong dan an toan",
            "ignore previous",
            "ignore all rules",
            "ignore safety rules",
            "developer mode",
            "jailbreak",
        ],
    ):
        return _gate(
            condition="prompt_injection",
            kind="prompt_injection",
            suffix="prompt injection khong bo qua quy tac an toan khong khuyen bo thuoc",
            preferred_conditions=["general"],
        )

    low_glucose_signal = has_any(
        text,
        [
            "duong huyet 45",
            "duong huyet 50",
            "duong mau 45",
            "duong mau 50",
            "duong huyet thap",
            "duong mau thap",
            "ha duong huyet",
            "hypoglycemia",
            "low blood sugar",
            "run tay",
            "ra mo hoi",
            "toat mo hoi",
            "vo mo hoi",
            "doi con cao",
            "doi run",
            "choang",
            "xay xam",
            "lu lan",
        ],
    )
    risky_low_glucose_action = has_any(
        text,
        [
            "nhin an",
            "detox",
            "tap the duc",
            "tap luyen",
            "ha duong",
            "bo bua",
            "fasting",
            "exercise",
            "skip meal",
        ],
    )
    explicit_low_glucose_number = has_regex(
        text,
        [
            r"(?:duong\s*(?:huyet|mau)|blood\s*sugar|glucose)\D{0,8}(45|50)\b",
            r"\b(45|50)\D{0,8}(?:mg/dl|mgdl)\b",
        ],
    )
    if low_glucose_signal and (risky_low_glucose_action or explicit_low_glucose_number):
        return _gate(
            condition="diabetes_hypoglycemia",
            kind="acute_hypoglycemia",
            suffix="ha duong huyet can xu tri an toan khan cap khong nhin an detox tap luyen",
            preferred_conditions=["diabetes"],
        )

    diabetes_medication = has_any(
        text,
        [
            "insulin",
            "gliclazide",
            "glibenclamide",
            "glimepiride",
            "sulfonylurea",
            "thuoc tieu duong",
            "thuoc dai thao duong",
            "thuoc ha duong huyet",
            "diabetes medication",
        ],
    )
    fasting_or_detox = has_any(
        text,
        [
            "detox",
            "nhin an",
            "bo bua",
            "nuoc gao lut",
            "cat carb",
            "giam carb dot ngot",
            "fasting",
            "skip meal",
            "low carb suddenly",
        ],
    )
    medication_change = has_regex(
        text,
        [
            r"(tu\s*)?(giam|bo|ngung|dung|doi).{0,24}(lieu|thuoc|insulin)",
            r"(thuoc|insulin).{0,24}(tu\s*)?(giam|bo|ngung|dung|doi)",
            r"(stop|quit|reduce|change).{0,24}(medicine|medication|insulin|dose)",
            r"(medicine|medication|insulin|dose).{0,24}(stop|quit|reduce|change)",
        ],
    )
    if diabetes_medication and fasting_or_detox:
        return _gate(
            condition="diabetes_insulin_or_secretagogue",
            kind="insulin_detox",
            suffix="dai thao duong insulin sulfonylurea detox nhin an bo bua ha duong huyet khong tu bo thuoc",
            preferred_conditions=["diabetes"],
        )
    if diabetes_medication and medication_change:
        return _gate(
            condition="medical_treatment_stop",
            kind="stop_medication",
            suffix="khong tu giam lieu thuoc tieu duong khong thay dieu tri y khoa bang an uong",
            preferred_conditions=["diabetes"],
        )

    cancer_terms = ["ung thu", "hoa tri", "xa tri", "cancer", "chemotherapy", "radiotherapy", "radiation therapy"]
    if has_any(text, cancer_terms) and has_any(
        text,
        [
            "thay",
            "thay the",
            "chua",
            "phac do",
            "bo dieu tri",
            "ngung dieu tri",
            "bo hoa tri",
            "dung hoa tri",
            "ngung hoa tri",
            "bo xa tri",
            "ngung xa tri",
            "thay hoa tri",
            "thay xa tri",
            "khoi benh",
            "100 ngay",
            "replace treatment",
            "stop treatment",
            "cure cancer",
        ],
    ):
        return _gate(
            condition="cancer_safety",
            kind="cancer_treatment_replacement",
            suffix="ung thu thuc duong khong thay hoa tri xa tri dieu tri chuan",
            preferred_conditions=["cancer_safety"],
        )

    if has_any(text, cancer_terms) and has_any(
        text,
        [
            "sut can",
            "an kem",
            "met moi",
            "raw",
            "vegan",
            "thanh loc",
            "detox",
            "nhin an",
            "it dam",
            "weight loss",
            "poor appetite",
            "low protein",
            "fasting",
        ],
    ):
        return _gate(
            condition="cancer_cachexia",
            kind="cancer_cachexia_restrictive",
            suffix="ung thu hoa tri sut can an kem khong an kieng cuc doan can nang luong protein",
            preferred_conditions=["cancer_safety"],
        )

    kidney_terms = ["suy than", "benh than man", "benh than", "ckd", "kali cao", "loc mau", "kidney disease", "dialysis"]
    if has_any(text, kidney_terms) and has_any(
        text,
        [
            "muoi kali",
            "muoi thay the",
            "detox",
            "nhin an",
            "giam phu",
            "bo loc mau",
            "bo buoi loc mau",
            "bo qua loc mau",
            "han che dich",
            "chao loang",
            "nuoc gao lut",
            "potassium salt",
            "salt substitute",
            "skip dialysis",
            "fasting",
        ],
    ):
        return _gate(
            condition="ckd_safety",
            kind="ckd_potassium_or_fasting",
            suffix="suy than kali cao loc mau muoi thay the nhin an detox can bac si",
            preferred_conditions=["ckd"],
        )

    if has_any(text, kidney_terms) and has_any(
        text,
        [
            "ca nhan hoa",
            "yeu to nao",
            "an thuc duong",
            "che do an",
            "can luu y",
            "personalize",
            "diet plan",
            "what should i eat",
        ],
    ):
        return _gate(
            condition="ckd_safety",
            kind="ckd_personalize",
            suffix="benh than man che do an can ca nhan hoa theo egfr kali phospho huyet ap dich thuoc",
            preferred_conditions=["ckd"],
        )

    if has_any(text, ["soi than", "oxalate", "oxalat", "kidney stone"]) and has_any(
        text,
        ["rau bina", "cai bo xoi", "me", "hat", "tra dac", "spinach", "sesame", "nuts", "strong tea"],
    ):
        return _gate(
            condition="kidney_stone_oxalate",
            kind="kidney_stone_oxalate",
            suffix="soi than oxalate can than rau bina me hat tra dac",
            preferred_conditions=["ckd", "general"],
        )

    if has_any(text, ["tang huyet ap", "cao huyet ap", "huyet ap cao", "hypertension", "high blood pressure"]) and has_any(
        text,
        [
            "muoi me",
            "miso",
            "tamari",
            "nuoc tuong",
            "dua muoi",
            "do muoi",
            "muoi",
            "natri",
            "tu ngung thuoc",
            "salt",
            "sodium",
            "soy sauce",
            "stop medication",
        ],
    ):
        return _gate(
            condition="hypertension_sodium",
            kind="hypertension_sodium",
            suffix="tang huyet ap can than natri muoi me miso nuoc tuong dua muoi",
            preferred_conditions=["hypertension"],
        )

    if has_any(text, ["di ung", "soc phan ve", "kho tho", "sung moi", "sung mat", "noi me day", "allergy", "anaphylaxis", "hives"]) and has_any(
        text,
        [
            "me",
            "dau phong",
            "lac",
            "dau nanh",
            "thuc pham",
            "thu lai",
            "an lai",
            "luong nho",
            "sesame",
            "peanut",
            "soy",
            "try again",
            "small amount",
        ],
    ):
        return _gate(
            condition="severe_allergy",
            kind="severe_allergy",
            suffix="di ung thuc pham kho tho sung moi noi me day khong thu tai nha",
            preferred_conditions=["general"],
        )

    vulnerable_group = has_any(
        text,
        [
            "mang thai",
            "thai ky",
            "co bau",
            "tre em",
            "tre 8 tuoi",
            "be ",
            "con toi",
            "nguoi gia",
            "nguoi cao tuoi",
            "thieu can",
            "sut can",
            "sut can nhanh",
            "roi loan an uong",
            "pregnant",
            "pregnancy",
            "child",
            "children",
            "elderly",
            "underweight",
            "eating disorder",
        ],
    )
    restrictive_action = has_any(
        text,
        [
            "thuc duong nghiem",
            "gao lut muoi me",
            "gao lut va muoi me",
            "chi gao lut",
            "bo sua",
            "bo trung",
            "bo thit",
            "giam can",
            "an kieng",
            "an rat it",
            "an don dieu",
            "don dieu",
            "detox",
            "chao gao lut",
            "chao loang",
            "strict diet",
            "only brown rice",
            "restrictive diet",
            "very low calorie",
            "fasting",
        ],
    )
    if vulnerable_group and restrictive_action:
        return _gate(
            condition="vulnerable_group_restrictive",
            kind="restrictive_diet_vulnerable_group",
            suffix="thai ky tre em nguoi cao tuoi thieu can sut can an kieng nghiem can du nang luong protein vi chat",
            preferred_conditions=["pregnancy", "vegetarian_risk"],
        )

    if has_any(
        text,
        [
            "100 ngay het benh",
            "chua khoi ung thu",
            "chua khoi tieu duong",
            "gao lut muoi me chua",
            "cang an it cang tot",
            "cure cancer",
            "cure diabetes",
            "miracle cure",
            "eat less is always better",
        ],
    ):
        return _gate(
            condition="miracle_cure_claim",
            kind="miracle_cure_claim",
            suffix="khong co che do an chua khoi ung thu tieu duong khong dua claim tuyet doi",
            preferred_conditions=["general"],
        )

    if has_regex(
        text,
        [
            r"(bo|ngung|dung|giam|doi).{0,24}(thuoc|insulin|hoa tri|xa tri|loc mau|tai kham)",
            r"(stop|quit|reduce|change).{0,24}(medicine|medication|insulin|chemotherapy|radiotherapy|dialysis|follow\s*up)",
        ],
    ):
        return _gate(
            condition="medical_treatment_stop",
            kind="stop_medication",
            suffix="khong tu bo thuoc khong thay dieu tri y khoa bang an uong",
            preferred_conditions=["general"],
        )

    return None


def is_direct_knowledge_question(question: str | None) -> bool:
    text = fold_text(question)
    if not text.strip():
        return False

    knowledge_terms = (
        "api|http|json|cache|redis|database|co so du lieu|postgres|postgresql|"
        "pgadmin|qdrant|vector database|embedding|docker|docker compose|env|env example"
    )
    direct_patterns = [
        rf"\b({knowledge_terms})\b.{{0,50}}\bla gi\b",
        rf"\bla gi\b.{{0,50}}\b({knowledge_terms})\b",
        rf"\b({knowledge_terms})\b.{{0,50}}\bkhac gi\b",
        rf"\bkhac gi\b.{{0,50}}\b({knowledge_terms})\b",
        rf"\b({knowledge_terms})\b.{{0,50}}\bco anh huong\b",
    ]
    return has_regex(text, direct_patterns)
