import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.prompts.answer_prompt import ANSWER_SYSTEM_PROMPT
from app.prompts.direct_answer_prompt import DIRECT_ANSWER_SYSTEM_PROMPT
from app.prompts.precheck_prompt import PRECHECK_SYSTEM_PROMPT as ROUTER_PRECHECK_SYSTEM_PROMPT
from app.prompts.profile_prompt import PROFILE_EXTRACTION_SYSTEM_PROMPT
from app.prompts.smalltalk_prompt import SMALLTALK_SYSTEM_PROMPT
from app.prompts.summary_prompt import SUMMARY_SYSTEM_PROMPT
from app.services.cache_service import cache_service

TokenSink = Callable[[str], Awaitable[None]]
PRECHECK_CACHE_VERSION = 5

SIMPLE_GREETING_PATTERNS = (
    # Chào hỏi thuần túy, cho phép cách gọi và từ đệm thông dụng.
    re.compile(
        r"^(?:hi|hello|hey|(?:xin )?chao)"
        r"(?: (?:ban|bot|tro ly|ad|admin|minh|nhe|a|oi))*$"
    ),
    # Hỏi chatbot có thể giúp/làm/hỗ trợ gì; có thể có lời chào phía trước.
    re.compile(
        r"^(?:(?:hi|hello|hey|(?:xin )?chao)(?: (?:ban|bot|tro ly|oi|nhe))* )?"
        r"(?:(?:ban|bot|tro ly) )?(?:co the )?"
        r"(?:giup(?: (?:toi|minh|em))?(?: duoc)? gi|lam(?: duoc)? gi|"
        r"ho tro(?: (?:toi|minh|em))?(?: duoc)? gi)$"
    ),
)

DEFAULT_GREETING_ANSWER = (
    "Xin chào! Mình có thể giúp bạn giải đáp câu hỏi, tra cứu tài liệu và tư vấn "
    "dựa trên kho kiến thức của hệ thống. Bạn muốn hỏi điều gì?"
)


class LLMService:
    def __init__(self):
        self._provider = settings.LLM_PROVIDER.lower()
        self._url = settings.OLLAMA_URL.rstrip("/")
        self._model_light = settings.LLM_MODEL_LIGHT
        self._model_heavy = settings.LLM_MODEL_HEAVY
        self._model_router = settings.LLM_MODEL_ROUTER or settings.LLM_MODEL_LIGHT
        self._client: httpx.AsyncClient | None = None
        self._client_loop = None

    @property
    def _use_local(self) -> bool:
        return self._provider in ("local", "ollama")

    def _get_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        # Celery có thể tạo event loop mới cho mỗi task; không tái sử dụng
        # HTTP client đã gắn với loop cũ hoặc loop đã đóng.
        if self._client is not None and (
            self._client_loop is not loop or self._client_loop.is_closed()
        ):
            self._client = None
            self._client_loop = None

        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=3.0,
                    read=settings.LLM_ANSWER_TIMEOUT,
                    write=10.0,
                    pool=3.0,
                )
            )
            self._client_loop = loop
        return self._client

    async def _chat(
        self,
        model: str,
        messages: list,
        json_mode: bool = False,
        timeout: float | None = None,
        token_sink: TokenSink | None = None,
        options: dict | None = None,
    ) -> str:
        should_stream = token_sink is not None and not json_mode
        payload = {"model": model, "messages": messages, "stream": should_stream}
        if options:
            payload["options"] = options
        if json_mode:
            payload["format"] = "json"
        client = self._get_client()
        request_timeout = timeout or settings.LLM_ANSWER_TIMEOUT

        if not should_stream:
            resp = await client.post(
                f"{self._url}/api/chat",
                json=payload,
                timeout=request_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

        chunks = []
        async with client.stream(
            "POST",
            f"{self._url}/api/chat",
            json=payload,
            timeout=request_timeout,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError(event["error"])
                content = event.get("message", {}).get("content", "")
                if content:
                    chunks.append(content)
                    await token_sink(content)
                if event.get("done"):
                    break

        return "".join(chunks)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _format_runtime_context(self, runtime_context: dict) -> str:
        recent = runtime_context.get("recent_messages", []) if runtime_context else []
        if not recent:
            return "Không có lịch sử gần đây."
        lines = []
        # 8 message = tối đa 4 lượt user/assistant, đủ cho các chuỗi follow-up
        # 3-4 câu mà không phải phụ thuộc vào việc model tự nhắc lại dữ kiện.
        for item in recent[-8:]:
            role = item.get("role", "unknown")
            content = str(item.get("content", "")).strip()[:300]
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines) or "Không có lịch sử gần đây."

    @staticmethod
    def _normalize_short_text(text: str) -> str:
        replacements = str.maketrans({
            "à": "a", "á": "a", "ạ": "a", "ả": "a", "ã": "a",
            "â": "a", "ầ": "a", "ấ": "a", "ậ": "a", "ẩ": "a", "ẫ": "a",
            "ă": "a", "ằ": "a", "ắ": "a", "ặ": "a", "ẳ": "a", "ẵ": "a",
            "è": "e", "é": "e", "ẹ": "e", "ẻ": "e", "ẽ": "e",
            "ê": "e", "ề": "e", "ế": "e", "ệ": "e", "ể": "e", "ễ": "e",
            "ì": "i", "í": "i", "ị": "i", "ỉ": "i", "ĩ": "i",
            "ò": "o", "ó": "o", "ọ": "o", "ỏ": "o", "õ": "o",
            "ô": "o", "ồ": "o", "ố": "o", "ộ": "o", "ổ": "o", "ỗ": "o",
            "ơ": "o", "ờ": "o", "ớ": "o", "ợ": "o", "ở": "o", "ỡ": "o",
            "ù": "u", "ú": "u", "ụ": "u", "ủ": "u", "ũ": "u",
            "ư": "u", "ừ": "u", "ứ": "u", "ự": "u", "ử": "u", "ữ": "u",
            "ỳ": "y", "ý": "y", "ỵ": "y", "ỷ": "y", "ỹ": "y", "đ": "d",
        })
        normalized = text.lower().translate(replacements)
        return " ".join(re.findall(r"[a-z0-9]+", normalized))

    def _simple_greeting_answer(self, question: str) -> str | None:
        normalized = self._normalize_short_text(question)
        if len(normalized) <= 100 and any(
            pattern.fullmatch(normalized) for pattern in SIMPLE_GREETING_PATTERNS
        ):
            return DEFAULT_GREETING_ANSWER
        return None

    def _format_session_summary(self, runtime_context: dict) -> str:
        summary = str((runtime_context or {}).get("session_summary") or "").strip()
        return summary[:800] if summary else "Chưa có tóm tắt phiên."

    def _format_citations(self, citations: list) -> str:
        if not citations:
            return "Không có metadata nguồn."
        lines = []
        for index, citation in enumerate(citations[:8], start=1):
            reference_id = citation.get("reference_id") or index
            title = str(citation.get("title") or "Tài liệu").strip()[:200]
            source_type = str(citation.get("source_type") or "không xác định").strip()[:100]
            source = str(citation.get("source") or "").strip()[:300]
            suffix = f" | {source}" if source else ""
            lines.append(f"[{reference_id}] {title} | {source_type}{suffix}")
        return "\n".join(lines)

    def _default_precheck(self, question: str) -> dict:
        return {
            "route": "rag",
            "risk_level": "normal",
            "risk_domain": "none",
            "risk_action": "none",
            "route_confidence": 0.0,
            "needs_clarification": False,
            "rewritten_query": question,
            "search_plan": {
                "need_kb": True,
                "need_user_memory": False,
                "need_web": False,
                "domain": None,
                "language": "vi",
                "top_k_vector": 8,
                "top_k_keyword": 5,
                "top_k_memory": 3,
            },
        }

    async def smart_precheck(self, question: str, runtime_context: dict):
        q = question.lower().strip()
        if self._simple_greeting_answer(question):
            return {"route": "smalltalk", "risk_level": "normal", "rewritten_query": question, "search_plan": {}}

        router_context = self._format_runtime_context(runtime_context)
        cache_material = f"{q}\n{router_context}"
        cache_key = f"precheck:v{PRECHECK_CACHE_VERSION}:" + hashlib.sha256(
            cache_material.encode("utf-8")
        ).hexdigest()
        cached = await cache_service.get_json(cache_key)
        if cached is not None:
            return cached

        if not self._use_local:
            # mock fallback
            q = question.lower().strip()
            if q in ["hi", "hello", "xin chào", "chào"]:
                return {"route": "smalltalk", "risk_level": "normal", "rewritten_query": question, "search_plan": {}}
            result = self._default_precheck(question)
            await cache_service.set_json(cache_key, result)
            return result

        messages = [
            {"role": "system", "content": ROUTER_PRECHECK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"[Lịch sử gần đây]\n{router_context}\n\n"
                    f"[Câu hỏi hiện tại]\n{question}"
                ),
            },
        ]
        try:
            raw = await self._chat(
                self._model_router,
                messages,
                json_mode=True,
                timeout=settings.LLM_ROUTER_TIMEOUT,
            )
            parsed = json.loads(raw)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            return self._default_precheck(question)

        # merge với default để đảm bảo đủ field
        result = self._default_precheck(question)
        result.update({k: v for k, v in parsed.items() if v is not None})
        if isinstance(parsed.get("search_plan"), dict):
            result["search_plan"] = {**result["search_plan"], **parsed["search_plan"]}
        result["rewritten_query"] = parsed.get("rewritten_query") or question
        await cache_service.set_json(cache_key, result)
        return result

    async def generate_smalltalk(
        self,
        question: str,
        runtime_context: dict,
        token_sink: TokenSink | None = None,
    ):
        greeting_answer = self._simple_greeting_answer(question)
        if greeting_answer:
            if token_sink is not None:
                await token_sink(greeting_answer)
            return greeting_answer

        if not self._use_local:
            return DEFAULT_GREETING_ANSWER

        messages = [
            {"role": "system", "content": SMALLTALK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"[Lịch sử gần đây]\n{self._format_runtime_context(runtime_context)}\n\n"
                    f"[Người dùng]\n{question}"
                ),
            },
        ]
        try:
            answer = await self._chat(
                self._model_light,
                messages,
                timeout=settings.LLM_ROUTER_TIMEOUT,
                options={"temperature": 0.3, "num_predict": 200},
            )
            # Smalltalk rất ngắn: kiểm tra toàn bộ trước khi gửi để không stream ra
            # câu trả lời lẫn chữ Trung do model đa ngôn ngữ sinh nhầm.
            if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", answer):
                answer = DEFAULT_GREETING_ANSWER
            if token_sink is not None:
                await token_sink(answer)
            return answer
        except httpx.HTTPError:
            return DEFAULT_GREETING_ANSWER

    async def generate_direct_answer(
        self,
        question: str,
        runtime_context: dict,
        token_sink: TokenSink | None = None,
    ):
        if not self._use_local:
            return "Mình có thể trả lời trực tiếp các câu hỏi đơn giản, ổn định và không cần tra cứu tài liệu."

        messages = [
            {"role": "system", "content": DIRECT_ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"[Lịch sử gần đây]\n{self._format_runtime_context(runtime_context)}\n\n"
                    f"[Câu hỏi]\n{question}"
                ),
            },
        ]
        try:
            answer = await self._chat(
                self._model_light,
                messages,
                timeout=settings.LLM_ROUTER_TIMEOUT,
                options={"temperature": 0.1, "num_predict": 300},
            )
            if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", answer):
                answer = await self._chat(
                    self._model_light,
                    [
                        {
                            "role": "system",
                            "content": (
                                "Viết lại nội dung bằng tiếng Việt thuần túy. Giữ nguyên mọi "
                                "endpoint, method, status code, field và số liệu. Không giải thích thêm."
                            ),
                        },
                        {"role": "user", "content": answer},
                    ],
                    timeout=settings.LLM_ROUTER_TIMEOUT,
                    options={"temperature": 0.0, "num_predict": 300},
                )
            if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", answer):
                answer = "Mình chưa thể tạo câu trả lời hoàn toàn bằng tiếng Việt ở lượt này."
            if token_sink is not None:
                await token_sink(answer)
            return answer
        except httpx.HTTPError as exc:
            return f"[LLM error] Không gọi được model local cho direct-answer: {type(exc).__name__}: {exc}"

    async def generate_answer(
        self,
        question: str,
        rewritten_question: str,
        runtime_context: dict,
        selected_context: str,
        citations: list,
        token_sink: TokenSink | None = None,
    ):
        if not selected_context:
            return ("Mình chưa tìm thấy đủ context trong knowledge base để trả lời chắc chắn. "
                    "Bạn cần thêm tài liệu hoặc bật web fallback cho câu hỏi này.")

        if not self._use_local:
            return f"Dựa trên context đã truy xuất, câu hỏi đã làm rõ là: {rewritten_question or question}\n\nContext:\n{selected_context[:1200]}"

        user_content = (
            f"[Câu hỏi gốc]\n{question}\n\n"
            f"[Câu hỏi đã làm rõ]\n{rewritten_question or question}\n\n"
            f"[Tóm tắt phiên - chỉ dùng để hiểu ngữ cảnh]\n"
            f"{self._format_session_summary(runtime_context)}\n\n"
            f"[Trao đổi gần đây - chỉ dùng để hiểu ngữ cảnh]\n"
            f"{self._format_runtime_context(runtime_context)}\n\n"
            f"[Tài liệu truy xuất - nguồn sự thật duy nhất]\n{selected_context}\n\n"
            f"[Metadata nguồn]\n{self._format_citations(citations)}\n\n"
            "Trả lời ngắn gọn, chính xác. Nêu nguồn [n] cho các khẳng định quan trọng khi có metadata tương ứng."
        )
        messages = [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            return await self._chat(
                self._model_heavy,
                messages,
                timeout=settings.LLM_ANSWER_TIMEOUT,
                token_sink=token_sink,
                options={"temperature": 0.2},
            )
        except httpx.HTTPError as exc:
            return f"[LLM error] Không gọi được model local: {type(exc).__name__}: {exc}"


    async def summarize_session(self, messages: list[dict]) -> str:
        if not messages:
            return ""

        transcript = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in messages
            if item.get("content")
        )
        if not transcript:
            return ""

        if not self._use_local:
            return transcript[-1500:]

        prompt = (
            "Tóm tắt hội thoại sau bằng tiếng Việt, ngắn gọn, giữ lại mục tiêu, sở thích, "
            "ràng buộc sức khỏe/dị ứng và các quyết định quan trọng. Không bịa thêm.\n\n"
            f"{transcript}"
        )
        try:
            return await self._chat(
                self._model_light,
                [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except httpx.HTTPError:
            return transcript[-1500:]

    async def extract_profile_fields(self, messages: list[dict], existing_profile: dict | None = None) -> dict:
        transcript = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in messages
            if item.get("content")
        )
        if not transcript:
            return existing_profile or {}

        heuristic_profile = self._extract_profile_heuristics(transcript)
        if not self._use_local:
            return self._merge_profiles(existing_profile or {}, heuristic_profile)

        prompt = {
            "existing_profile": existing_profile or {},
            "transcript": transcript[-6000:],
            "schema": {
                "name": "string|null",
                "language": "string|null",
                "goals": ["string"],
                "conditions": ["string"],
                "allergies": ["string"],
                "preferences": ["string"],
                "avoidances": ["string"],
                "notes": ["string"],
            },
        }
        try:
            raw = await self._chat(
                self._model_light,
                [
                    {"role": "system", "content": PROFILE_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                json_mode=True,
            )
            parsed = json.loads(raw)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError):
            return self._merge_profiles(existing_profile or {}, heuristic_profile)

        return self._merge_profiles(self._merge_profiles(existing_profile or {}, parsed), heuristic_profile)

    def _merge_profiles(self, base: dict, incoming: dict) -> dict:
        merged = dict(base or {})
        for key, value in (incoming or {}).items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list):
                current = merged.get(key, [])
                if not isinstance(current, list):
                    current = [current]
                merged[key] = sorted({str(item).strip() for item in current + value if str(item).strip()})
            else:
                merged[key] = value
        return merged

    def _extract_profile_heuristics(self, transcript: str) -> dict:
        text = transcript.lower()
        profile = {"conditions": [], "allergies": [], "goals": [], "avoidances": []}

        if "tiểu đường type 2" in text or "đái tháo đường type 2" in text or "diabetes type 2" in text:
            profile["conditions"].append("tiểu đường type 2")
        elif "tiểu đường" in text or "đái tháo đường" in text or "diabetes" in text:
            profile["conditions"].append("tiểu đường")

        if re.search(r"dị ứng.{0,40}(đậu phộng|lạc)", text) or re.search(r"(đậu phộng|lạc).{0,40}dị ứng", text):
            profile["allergies"].append("đậu phộng")
            profile["avoidances"].append("đậu phộng")

        if "ít đường" in text or "giảm đường" in text or "kiểm soát đường" in text:
            profile["goals"].append("giảm/kiểm soát đường")

        return {key: value for key, value in profile.items() if value}


llm_service = LLMService()
