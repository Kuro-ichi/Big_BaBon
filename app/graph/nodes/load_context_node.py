from app.services.memory_service import memory_service

async def load_runtime_context_node(state):
    recent_messages = await memory_service.get_recent_messages(state["session_id"], limit=8)
    session_summary = await memory_service.get_latest_summary(state["session_id"])
    user_profile = await memory_service.get_relevant_profile_fields(state["user_id"], state["original_question"])

    state["runtime_context"] = {
        "session_summary": session_summary,
        "recent_messages": recent_messages,
        "user_profile": user_profile,
        "personal_memories": [],
    }
    state["trace"].append({"node": "load_runtime_context", "status": "success"})
    return state
