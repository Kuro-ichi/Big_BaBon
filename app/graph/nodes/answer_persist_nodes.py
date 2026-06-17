from app.services.llm_service import llm_service
from app.services.persist_service import persist_service
from app.core.config import settings


def _ensure_answer_subject(answer: str, subject: str | None) -> str:
    if subject and subject.lower() not in (answer or "").lower():
        return f"{subject}: {answer}"
    return answer


SAFETY_RESPONSES = {
    "acute_hypoglycemia": (
        "Tình huống này có thể là hạ đường huyết, đặc biệt nếu bạn đang dùng insulin hoặc thuốc nhóm sulfonylurea như gliclazide. "
        "Không nên tiếp tục nhịn ăn, detox hoặc tập luyện để “hạ đường”. Hãy xử trí theo kế hoạch bác sĩ đã dặn; nếu có lú lẫn, ngất, co giật, không nuốt được, hoặc triệu chứng nặng lên thì cần gọi cấp cứu/người chăm sóc ngay. "
        "Sau khi ổn định, hãy liên hệ bác sĩ để điều chỉnh thuốc và bữa ăn cho an toàn."
    ),
    "insulin_detox": (
        "Mình không khuyến nghị detox, nhịn ăn, bỏ bữa hoặc chỉ uống nước gạo lứt rang khi đang dùng insulin hoặc thuốc có nguy cơ gây hạ đường huyết. "
        "Việc thay đổi lượng carbohydrate đột ngột có thể làm tăng nguy cơ hạ đường huyết. Bạn không nên tự ý giảm, bỏ hoặc đổi liều thuốc; hãy trao đổi với bác sĩ/chuyên gia dinh dưỡng và theo dõi đường huyết theo kế hoạch điều trị."
    ),
    "cancer_treatment_replacement": (
        "Mình không thể lập phác đồ ăn để thay hóa trị, xạ trị, phẫu thuật hoặc điều trị ung thư chuẩn. "
        "Không có bằng chứng đủ tin cậy để coi thực dưỡng là phương pháp làm hết ung thư. Dinh dưỡng có thể hỗ trợ duy trì cân nặng, khối cơ và khả năng dung nạp điều trị, nhưng nên phối hợp với bác sĩ điều trị hoặc chuyên gia dinh dưỡng ung bướu."
    ),
    "cancer_cachexia_restrictive": (
        "Khi đang điều trị ung thư mà có sụt cân, ăn kém hoặc mệt nhiều, chế độ ăn quá hạn chế, detox, nhịn ăn hoặc ăn sống hoàn toàn có thể làm tăng nguy cơ thiếu năng lượng và protein. "
        "Ưu tiên lúc này thường là ăn đủ năng lượng, đủ protein, an toàn vệ sinh thực phẩm và phù hợp với điều trị. Bạn nên trao đổi với bác sĩ/chuyên gia dinh dưỡng ung bướu trước khi áp dụng chế độ ăn kiêng nghiêm."
    ),
    "ckd_potassium_or_fasting": (
        "Với bệnh thận, lọc máu hoặc kali máu cao, bạn không nên tự dùng muối thay thế giàu kali, nhịn ăn hoặc detox nếu chưa có chỉ định y khoa. "
        "Chế độ ăn cho bệnh thận cần cá nhân hóa theo eGFR, kali, phospho, huyết áp, tình trạng phù/dịch và thuốc đang dùng. Hãy hỏi bác sĩ trước khi thay đổi."
    ),
    "ckd_personalize": (
        "Với bệnh thận mạn, chế độ ăn cần cá nhân hóa theo eGFR, kali, phospho, huyết áp, tình trạng phù/dịch, thuốc đang dùng, cân nặng và mục tiêu điều trị. "
        "Bạn nên trao đổi với bác sĩ hoặc chuyên gia dinh dưỡng thận trước khi áp dụng thực dưỡng nghiêm."
    ),
    "hypertension_sodium": (
        "Với tăng huyết áp, cần rất thận trọng với muối mè, miso, tamari, nước tương, dưa muối và các món nhiều natri. "
        "Những món này không nên được xem là cách thay thuốc huyết áp. Bạn nên kiểm soát tổng lượng natri trong ngày và trao đổi với bác sĩ nếu muốn thay đổi chế độ ăn hoặc thuốc."
    ),
    "severe_allergy": (
        "Nếu có khó thở, sưng môi/mặt, nổi mề đay lan rộng, choáng hoặc nghi sốc phản vệ sau khi ăn, đây là tình huống cần xử trí y tế khẩn cấp. "
        "Hãy tránh thực phẩm nghi gây dị ứng và không tự kiểm tra lại tại nhà. Liên hệ cấp cứu/bác sĩ dị ứng nếu triệu chứng nặng hoặc tái diễn."
    ),
    "restrictive_diet_vulnerable_group": (
        "Mình không khuyến nghị áp dụng chế độ ăn kiêng nghiêm hoặc đơn điệu cho thai kỳ, trẻ em, người cao tuổi, người thiếu cân, đang sụt cân nhanh hoặc có rối loạn ăn uống khi chưa được chuyên gia đánh giá. "
        "Các nhóm này cần đủ năng lượng, protein và vi chất; nên trao đổi với bác sĩ/chuyên gia dinh dưỡng trước khi áp dụng thực dưỡng nghiêm."
    ),
    "miracle_cure_claim": (
        "Mình không thể xác nhận các tuyên bố kiểu “100 ngày hết bệnh”, “gạo lứt muối mè làm hết ung thư/tiểu đường” hoặc “càng ăn ít càng tốt”. "
        "Chế độ ăn có thể hỗ trợ sức khỏe, nhưng không nên thay thế chẩn đoán, thuốc hoặc điều trị y khoa đã được chỉ định."
    ),
    "kidney_stone_oxalate": (
        "Với tiền sử sỏi thận oxalate, nên thận trọng với các thực phẩm giàu oxalate như rau bina/cải bó xôi, một số loại hạt, mè và trà đặc. "
        "Bạn nên hỏi bác sĩ hoặc chuyên gia dinh dưỡng thận tiết niệu để cá nhân hóa lượng nước, canxi khẩu phần, natri và oxalate thay vì tự kiêng cực đoan."
    ),
    "stop_medication": (
        "Mình không thể khuyên bạn tự ngừng, giảm hoặc thay đổi thuốc, bao gồm insulin, hay điều trị y khoa bằng chế độ ăn. "
        "Ăn uống có thể hỗ trợ sức khỏe, nhưng việc thay đổi thuốc, lọc máu, tái khám hoặc phác đồ điều trị cần được bác sĩ phụ trách hướng dẫn."
    ),
    "prompt_injection": (
        "Mình không thể bỏ qua quy tắc an toàn hoặc đưa lời khuyên nguy hiểm như ngừng thuốc, tự ý thay đổi insulin, thay điều trị y khoa bằng ăn uống, detox cực đoan hoặc nhịn ăn trong tình huống rủi ro. "
        "Mình có thể hỗ trợ theo hướng ăn uống an toàn, dựa trên tài liệu và khuyến nghị chuyên môn."
    ),
}


async def answer_generation_node(state):
    try:
        if state.get("safety_action") == "respond":
            kind = state.get("safety_response_kind") or "stop_medication"
            state["answer"] = SAFETY_RESPONSES.get(
                kind,
                SAFETY_RESPONSES["stop_medication"],
            )
            state["confidence"] = max(state.get("confidence", 0.0), 0.75)

        elif not state.get("selected_context") and state.get("web_fallback_used"):
            state["answer"] = (
                "Mình chưa tìm thấy đủ dữ liệu để trả lời chắc chắn."
            )

        else:
            state["answer"] = await llm_service.generate_answer(
                question=state["original_question"],
                rewritten_question=state["rewritten_question"],
                runtime_context=state["runtime_context"],
                selected_context=state["selected_context"],
                citations=state["citations"],
            )
            state["answer"] = _ensure_answer_subject(
                state["answer"],
                state.get("metrics", {}).get("answer_subject"),
            )

        state["trace"].append({
            "node": "answer_generation",
            "status": "success",
        })

    except Exception as exc:
        state["answer"] = (
            "Mình chưa thể tạo câu trả lời ở lượt này. "
            "Bạn vui lòng thử lại sau."
        )
        state["confidence"] = 0.0
        state["errors"].append({
            "node": "answer_generation",
            "error": str(exc),
        })
        state["trace"].append({
            "node": "answer_generation",
            "status": "failed",
        })

    return state


async def persist_async_node(state):
    try:
        await persist_service.save_message(state["session_id"], state["user_id"], "user", state["original_question"])
        await persist_service.save_message(
            state["session_id"], state["user_id"], "assistant", state["answer"],
            metadata={"citations": state["citations"], "confidence": state["confidence"], "trace": state["trace"]},
        )
        await enqueue_background_jobs(state)
    except Exception as exc:
        state["errors"].append({"node": "persist_async", "error": str(exc)})
    state["metrics"]["trace_length"] = len(state["trace"])
    return state


async def enqueue_background_jobs(state):
    if not settings.WORKER_TASKS_ENABLED:
        return

    queued = []
    try:
        from app.workers.memory_worker import extract_user_memory

        extract_user_memory.delay(state["user_id"], state["session_id"])
        queued.append("extract_user_memory")
    except Exception as exc:
        state["errors"].append({"node": "persist_async", "background_task": "extract_user_memory", "error": str(exc)})

    try:
        from app.workers.summary_worker import summarize_session

        message_count = await persist_service.count_messages_since_latest_summary(state["session_id"])
        if message_count >= settings.SUMMARY_TRIGGER_MESSAGE_COUNT:
            summarize_session.delay(state["session_id"])
            queued.append("summarize_session")
    except Exception as exc:
        state["errors"].append({"node": "persist_async", "background_task": "summarize_session", "error": str(exc)})

    state["metrics"]["background_tasks_queued"] = queued
