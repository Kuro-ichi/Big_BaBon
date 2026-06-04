async def smalltalk_answer_node(state):
    state["answer"] = "Xin chào! Mình có thể hỗ trợ bạn hỏi đáp dựa trên tài liệu, lịch sử hội thoại và knowledge base."
    state["confidence"] = 1.0
    return state

async def direct_answer_node(state):
    state["answer"] = "Đây là câu trả lời trực tiếp cho câu hỏi đơn giản."
    state["confidence"] = 0.8
    return state

async def clarify_response_node(state):
    state["answer"] = "Bạn có thể nói rõ hơn yêu cầu hoặc bổ sung thêm ngữ cảnh không?"
    state["confidence"] = 0.3
    return state

async def safety_response_node(state):
    state["answer"] = "Mình không thể hỗ trợ yêu cầu này theo hướng hiện tại."
    state["confidence"] = 0.2
    return state
