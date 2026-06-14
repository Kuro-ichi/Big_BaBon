from __future__ import annotations

import json
import re
from typing import Any

from app.prompts.prompt import (
    DEFAULT_SEARCH_PLAN,
    SUPPORTED_RISK_LEVELS,
    SUPPORTED_ROUTES,
    build_answer_messages,
    build_simple_messages,
    build_smart_precheck_messages,
    compact_text,
    normalize_language,
    prompt_meta,
)


class LLMService:
    """Prompt-aware LLM facade.

    The current project does not ship a concrete provider client, so this
    service provides deterministic fallbacks that mirror the prompt contracts.
    A real model call can be added behind the same public methods later.
    """

    _SMALLTALK_EXACT = {
        "hi",
        "hello",
        "hey",
        "xin chào",
        "chào",
        "chào bạn",
        "alo",
        "cảm ơn",
        "thanks",
        "thank you",
        "tạm biệt",
        "bye",
    }
    _DIRECT_PATTERNS = [
        r"\bbạn là ai\b",
        r"\bbạn làm được gì\b",
        r"\bbạn có thể làm gì\b",
        r"\bcách dùng\b",
        r"\bhướng dẫn sử dụng\b",
        r"\bhelp\b",
    ]
    _MEMORY_HINTS = [
        "tôi",
        "mình",
        "của tôi",
        "cho tôi",
        "chúng ta",
        "trước đó",
        "vừa nãy",
        "lúc nãy",
        "hồ sơ",
        "sở thích",
        "my ",
        "me ",
        "mine",
        "previous",
        "earlier",
    ]
    _SAFETY_HINTS = [
        "hack",
        "bypass",
        "vượt quyền",
        "chiếm quyền",
        "đánh cắp",
        "mật khẩu",
        "password",
        "token",
        "api key",
        "phishing",
        "lừa đảo",
        "malware",
        "ransomware",
        "keylogger",
        "ddos",
        "exploit",
        "crack",
        "backdoor",
        "sql injection",
        "xss",
        "bom",
        "vũ khí",
    ]
    _DEFENSIVE_HINTS = [
        "phòng chống",
        "bảo vệ",
        "ngăn chặn",
        "phát hiện",
        "kiểm tra bảo mật",
        "audit",
        "defense",
        "defensive",
        "prevent",
        "secure",
        "mitigate",
    ]

    def __init__(self) -> None:
        self.last_prompt_messages: dict[str, list[dict[str, str]]] = {}

    async def smart_precheck(self, question: str, runtime_context: dict[str, Any] | None):
        runtime_context = runtime_context or {}
        language = normalize_language(runtime_context.get("language") or self._detect_language(question))
        messages = build_smart_precheck_messages(question, runtime_context, language)
        self.last_prompt_messages["smart_precheck"] = messages

        precheck = self._rule_based_precheck(question, runtime_context, language)
        precheck["prompt_meta"] = prompt_meta("smart_precheck")
        return precheck

    async def generate_simple_answer(
        self,
        route: str,
        question: str,
        runtime_context: dict[str, Any] | None,
    ) -> str:
        runtime_context = runtime_context or {}
        language = normalize_language(runtime_context.get("language") or self._detect_language(question))
        messages = build_simple_messages(route, question, runtime_context, language)
        self.last_prompt_messages[route] = messages

        if route == "smalltalk":
            return self._smalltalk_answer(question, language)
        if route == "clarify":
            return self._clarify_answer(question, language)
        if route == "safety":
            return self._safety_answer(language)
        return self._direct_answer(question, language)

    async def generate_answer(
        self,
        question: str,
        rewritten_question: str,
        runtime_context: dict[str, Any] | None,
        selected_context: str,
        citations: list[dict[str, Any]],
    ):
        runtime_context = runtime_context or {}
        language = normalize_language(runtime_context.get("language") or self._detect_language(question))
        messages = build_answer_messages(
            question=question,
            rewritten_question=rewritten_question,
            runtime_context=runtime_context,
            selected_context=selected_context,
            citations=citations,
            language=language,
        )
        self.last_prompt_messages["answer_generation"] = messages

        if not selected_context.strip():
            return self._insufficient_context_answer(language)

        snippets = self._extract_context_snippets(selected_context, max_items=5)
        if not snippets:
            return self._insufficient_context_answer(language)

        if language == "en":
            lines = ["Based on the retrieved context, here are the most relevant points:"]
        else:
            lines = ["Dựa trên context đã truy xuất, mình tìm thấy các ý chính sau:"]

        for index, snippet in enumerate(snippets):
            marker = self._citation_marker(index, citations)
            lines.append(f"- {snippet}{marker}")

        if language == "en":
            lines.append("If you need a more conclusive answer, please add more source documents or clarify the scope.")
        else:
            lines.append("Nếu cần kết luận chắc hơn, bạn nên bổ sung thêm tài liệu nguồn hoặc làm rõ phạm vi câu hỏi.")
        return "\n".join(lines)

    def _rule_based_precheck(
        self,
        question: str,
        runtime_context: dict[str, Any],
        language: str,
    ) -> dict[str, Any]:
        normalized_question = self._normalize_question(question)
        base = self._base_precheck(language)
        base["rewritten_query"] = self._rewrite_query(question)

        if not normalized_question:
            return self._with_route(
                base,
                route="clarify",
                intent="empty_question",
                risk_level="normal",
                needs_clarification=True,
                search_plan={"need_kb": False, "need_user_memory": False},
            )

        if self._is_safety_request(normalized_question):
            return self._with_route(
                base,
                route="safety",
                intent="unsafe_or_abusive_request",
                risk_level="high",
                needs_clarification=False,
                search_plan={"need_kb": False, "need_user_memory": False},
            )

        if self._is_smalltalk(normalized_question):
            return self._with_route(
                base,
                route="smalltalk",
                intent="smalltalk",
                risk_level="normal",
                needs_clarification=False,
                search_plan={"need_kb": False, "need_user_memory": False},
            )

        if self._is_direct_question(normalized_question):
            return self._with_route(
                base,
                route="direct_answer",
                intent="assistant_capability_or_usage",
                risk_level="normal",
                needs_clarification=False,
                search_plan={"need_kb": False, "need_user_memory": False},
            )

        if self._needs_clarification(normalized_question, runtime_context):
            return self._with_route(
                base,
                route="clarify",
                intent="underspecified_request",
                risk_level="normal",
                needs_clarification=True,
                search_plan={"need_kb": False, "need_user_memory": False},
            )

        plan = self._build_search_plan(normalized_question, runtime_context, language)
        return self._with_route(
            base,
            route="rag",
            intent=self._infer_intent(normalized_question),
            risk_level="normal",
            needs_clarification=False,
            search_plan=plan,
        )

    def _base_precheck(self, language: str) -> dict[str, Any]:
        plan = dict(DEFAULT_SEARCH_PLAN)
        plan["language"] = language
        return {
            "route": "rag",
            "intent": "knowledge_lookup",
            "risk_level": "normal",
            "needs_clarification": False,
            "rewritten_query": "",
            "search_plan": plan,
        }

    def _with_route(
        self,
        payload: dict[str, Any],
        *,
        route: str,
        intent: str,
        risk_level: str,
        needs_clarification: bool,
        search_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload["route"] = route if route in SUPPORTED_ROUTES else "rag"
        payload["intent"] = intent
        payload["risk_level"] = risk_level if risk_level in SUPPORTED_RISK_LEVELS else "normal"
        payload["needs_clarification"] = needs_clarification
        if search_plan:
            plan = dict(payload.get("search_plan") or DEFAULT_SEARCH_PLAN)
            plan.update(search_plan)
            payload["search_plan"] = self._normalize_search_plan(plan)
        return payload

    def _normalize_search_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(DEFAULT_SEARCH_PLAN)
        normalized.update(plan or {})
        normalized["language"] = normalize_language(normalized.get("language"))
        normalized["need_kb"] = bool(normalized.get("need_kb"))
        normalized["need_user_memory"] = bool(normalized.get("need_user_memory"))
        normalized["need_web"] = False
        normalized["top_k_vector"] = self._clamp_int(normalized.get("top_k_vector"), 1, 12, 8)
        normalized["top_k_keyword"] = self._clamp_int(normalized.get("top_k_keyword"), 1, 10, 5)
        normalized["top_k_memory"] = self._clamp_int(normalized.get("top_k_memory"), 0, 5, 3)
        return normalized

    def _build_search_plan(
        self,
        normalized_question: str,
        runtime_context: dict[str, Any],
        language: str,
    ) -> dict[str, Any]:
        plan = dict(DEFAULT_SEARCH_PLAN)
        plan["language"] = language
        plan["domain"] = self._infer_domain(normalized_question)
        plan["need_user_memory"] = self._needs_user_memory(normalized_question, runtime_context)

        if len(normalized_question) > 180:
            plan["top_k_vector"] = 10
            plan["top_k_keyword"] = 7
        if plan["need_user_memory"]:
            plan["top_k_memory"] = 5
        return self._normalize_search_plan(plan)

    def _normalize_question(self, question: str) -> str:
        return re.sub(r"\s+", " ", (question or "").strip().lower())

    def _rewrite_query(self, question: str) -> str:
        text = re.sub(r"\s+", " ", (question or "").strip())
        polite_prefixes = [
            "cho tôi hỏi",
            "mình muốn hỏi",
            "bạn ơi",
            "please",
            "can you",
            "could you",
        ]
        lowered = text.lower()
        for prefix in polite_prefixes:
            if lowered.startswith(prefix):
                text = text[len(prefix) :].strip(" ,:;-")
                break
        return text or question

    def _detect_language(self, question: str) -> str:
        text = question or ""
        vietnamese_marks = "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
        if any(char in vietnamese_marks for char in text.lower()):
            return "vi"
        return "en" if re.search(r"\b(what|how|why|when|where|please|can|could)\b", text.lower()) else "vi"

    def _is_smalltalk(self, normalized_question: str) -> bool:
        if normalized_question in self._SMALLTALK_EXACT:
            return True
        return bool(re.fullmatch(r"(xin )?chào[!. ]*(bạn|bot|anh|chị)?[!. ]*", normalized_question))

    def _is_direct_question(self, normalized_question: str) -> bool:
        return any(re.search(pattern, normalized_question) for pattern in self._DIRECT_PATTERNS)

    def _needs_clarification(self, normalized_question: str, runtime_context: dict[str, Any]) -> bool:
        if len(normalized_question) < 4:
            return True

        vague_references = ["cái này", "cái đó", "nó", "việc đó", "như trên", "đoạn này"]
        has_recent_context = bool(runtime_context.get("recent_messages") or runtime_context.get("session_summary"))
        if any(ref in normalized_question for ref in vague_references) and not has_recent_context:
            return True

        vague_commands = {"làm đi", "xử lý đi", "sửa đi", "tối ưu đi", "giải thích đi"}
        return normalized_question in vague_commands

    def _is_safety_request(self, normalized_question: str) -> bool:
        has_risky_term = any(term in normalized_question for term in self._SAFETY_HINTS)
        if not has_risky_term:
            return False
        if any(term in normalized_question for term in self._DEFENSIVE_HINTS):
            return False

        harmful_intent = [
            "cách",
            "hướng dẫn",
            "viết",
            "tạo",
            "làm sao",
            "giúp tôi",
            "how to",
            "write",
            "create",
            "build",
            "steal",
            "attack",
        ]
        return any(term in normalized_question for term in harmful_intent)

    def _needs_user_memory(self, normalized_question: str, runtime_context: dict[str, Any]) -> bool:
        if any(hint in normalized_question for hint in self._MEMORY_HINTS):
            return True
        return bool(runtime_context.get("personal_memories"))

    def _infer_domain(self, normalized_question: str) -> str | None:
        technical_terms = ["api", "backend", "frontend", "database", "sql", "code", "bug", "deploy", "docker"]
        policy_terms = ["chính sách", "quy định", "điều khoản", "policy", "compliance"]
        product_terms = ["sản phẩm", "gói", "giá", "tính năng", "product", "pricing", "feature"]

        if any(term in normalized_question for term in technical_terms):
            return "technical"
        if any(term in normalized_question for term in policy_terms):
            return "policy"
        if any(term in normalized_question for term in product_terms):
            return "product"
        return "general"

    def _infer_intent(self, normalized_question: str) -> str:
        if any(term in normalized_question for term in ["so sánh", "khác nhau", "compare", "difference"]):
            return "comparison"
        if any(term in normalized_question for term in ["liệt kê", "danh sách", "list"]):
            return "list_or_enumeration"
        if any(term in normalized_question for term in ["tóm tắt", "summary", "summarize"]):
            return "summarization"
        if any(term in normalized_question for term in ["hướng dẫn", "làm sao", "how to"]):
            return "how_to"
        return "knowledge_lookup"

    def _smalltalk_answer(self, question: str, language: str) -> str:
        if language == "en":
            return "Hi! I can help answer questions using your documents, knowledge base, and conversation context."
        if "cảm ơn" in self._normalize_question(question):
            return "Rất vui được hỗ trợ bạn. Bạn cứ gửi tiếp câu hỏi hoặc tài liệu cần tra cứu nhé."
        if "tạm biệt" in self._normalize_question(question):
            return "Tạm biệt bạn. Khi cần tra cứu tài liệu hay tiếp tục phiên này, cứ quay lại nhé."
        return "Xin chào! Mình có thể hỗ trợ hỏi đáp dựa trên tài liệu, knowledge base và ngữ cảnh hội thoại của bạn."

    def _direct_answer(self, question: str, language: str) -> str:
        normalized_question = self._normalize_question(question)
        if language == "en":
            return "I am an AI assistant for document-grounded Q&A. Send me a question and I will look for the most relevant context before answering."
        if "bạn là ai" in normalized_question:
            return "Mình là trợ lý AI của hệ thống, chuyên hỗ trợ hỏi đáp dựa trên tài liệu, knowledge base và lịch sử hội thoại."
        if "cách dùng" in normalized_question or "hướng dẫn" in normalized_question:
            return "Bạn chỉ cần gửi câu hỏi cụ thể. Nếu câu hỏi liên quan đến tài liệu, mình sẽ tra context phù hợp rồi trả lời kèm nguồn khi có."
        return "Mình có thể trả lời câu hỏi đơn giản trực tiếp, hoặc tra knowledge base khi câu hỏi cần dữ liệu từ tài liệu."

    def _clarify_answer(self, question: str, language: str) -> str:
        if language == "en":
            return "Could you clarify the object or scope you want me to answer about?"
        if not question.strip():
            return "Bạn muốn hỏi về nội dung nào? Hãy gửi thêm câu hỏi hoặc tài liệu cần tra cứu nhé."
        return "Bạn có thể nói rõ hơn đối tượng hoặc phạm vi cần trả lời không? Nếu có tài liệu liên quan, hãy bổ sung để mình tra cứu chính xác hơn."

    def _safety_answer(self, language: str) -> str:
        if language == "en":
            return "I cannot help with harmful or unauthorized actions. I can still help with defensive, educational, or policy-compliant guidance."
        return "Mình không thể hỗ trợ yêu cầu gây hại, vượt quyền hoặc xâm phạm bảo mật. Nếu mục tiêu là phòng thủ hoặc kiểm tra an toàn, hãy mô tả bối cảnh hợp pháp để mình hỗ trợ theo hướng an toàn."

    def _insufficient_context_answer(self, language: str) -> str:
        if language == "en":
            return "I do not have enough retrieved context to answer confidently. Please add relevant documents or clarify the scope."
        return "Mình chưa tìm thấy đủ context trong knowledge base để trả lời chắc chắn. Bạn có thể bổ sung tài liệu liên quan hoặc làm rõ phạm vi câu hỏi."

    def _extract_context_snippets(self, selected_context: str, max_items: int = 5) -> list[str]:
        blocks = [block.strip() for block in re.split(r"\n{2,}", selected_context or "") if block.strip()]
        snippets: list[str] = []
        for block in blocks:
            clean = re.sub(r"^\[\d+\][^\n]*\n?", "", block).strip()
            clean = re.sub(r"\s+", " ", clean)
            if not clean:
                continue
            sentence_match = re.match(r"(.{40,260}?[.!?。]|.{40,260})(?:\s|$)", clean)
            snippet = sentence_match.group(1).strip() if sentence_match else clean[:260].strip()
            snippets.append(compact_text(snippet, 280))
            if len(snippets) >= max_items:
                break
        return snippets

    def _citation_marker(self, index: int, citations: list[dict[str, Any]]) -> str:
        return f" [{index + 1}]" if index < len(citations) else ""

    def _clamp_int(self, value: Any, minimum: int, maximum: int, default: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(maximum, number))

    def parse_json_object(self, raw_text: str) -> dict[str, Any]:
        """Parse a JSON object from a provider response if one is added later."""
        text = (raw_text or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                return {}
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return parsed if isinstance(parsed, dict) else {}


llm_service = LLMService()
