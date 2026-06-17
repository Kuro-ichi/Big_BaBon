import json
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).with_name("safety_taxonomy.json")
DEFAULT_SOURCE_TYPES = [
    "safety_guardrail",
    "clinical_nutrition_guideline",
    "clinical_patient_guidance",
]


@lru_cache(maxsize=1)
def load_safety_taxonomy() -> dict[str, dict[str, Any]]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def get_safety_policy(condition: str) -> dict[str, Any]:
    configured = load_safety_taxonomy().get(condition, {})
    return {
        "fast_path": bool(configured.get("fast_path", False)),
        "preferred_conditions": configured.get("preferred_conditions") or ["general"],
        "preferred_source_types": configured.get("preferred_source_types") or DEFAULT_SOURCE_TYPES,
    }


def policy_citation(condition: str) -> dict[str, Any]:
    return {
        "id": f"safety-policy:{condition}",
        "source": "internal:safety_taxonomy",
        "title": f"Chính sách an toàn - {condition}",
        "source_type": "safety_guardrail",
        "score": 1.0,
    }
