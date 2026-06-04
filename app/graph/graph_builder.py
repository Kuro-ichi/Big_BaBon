from langgraph.graph import StateGraph, END
from app.schemas.state_schema import ChatState
from app.graph.nodes.load_context_node import load_runtime_context_node
from app.graph.nodes.smart_precheck_node import smart_precheck_node, route_after_precheck
from app.graph.nodes.simple_answer_nodes import (
    smalltalk_answer_node,
    direct_answer_node,
    clarify_response_node,
    safety_response_node,
)
from app.graph.nodes.retrieval_node import parallel_retrieval_node
from app.graph.nodes.rerank_trim_node import rerank_trim_node
from app.graph.nodes.context_guard_nodes import rule_context_check_node, lightweight_guard_node
from app.graph.nodes.answer_persist_nodes import answer_generation_node, persist_async_node


def build_chat_graph():
    graph = StateGraph(ChatState)

    graph.add_node("load_runtime_context", load_runtime_context_node)
    graph.add_node("smart_precheck", smart_precheck_node)
    graph.add_node("smalltalk_answer", smalltalk_answer_node)
    graph.add_node("direct_answer", direct_answer_node)
    graph.add_node("clarify_response", clarify_response_node)
    graph.add_node("safety_response", safety_response_node)
    graph.add_node("parallel_retrieval", parallel_retrieval_node)
    graph.add_node("rerank_trim", rerank_trim_node)
    graph.add_node("rule_context_check", rule_context_check_node)
    graph.add_node("answer_generation", answer_generation_node)
    graph.add_node("lightweight_guard", lightweight_guard_node)
    graph.add_node("persist_async", persist_async_node)

    graph.set_entry_point("load_runtime_context")
    graph.add_edge("load_runtime_context", "smart_precheck")

    graph.add_conditional_edges(
        "smart_precheck",
        route_after_precheck,
        {
            "smalltalk_answer": "smalltalk_answer",
            "direct_answer": "direct_answer",
            "clarify_response": "clarify_response",
            "safety_response": "safety_response",
            "parallel_retrieval": "parallel_retrieval",
        },
    )

    graph.add_edge("parallel_retrieval", "rerank_trim")
    graph.add_edge("rerank_trim", "rule_context_check")
    graph.add_edge("rule_context_check", "answer_generation")
    graph.add_edge("answer_generation", "lightweight_guard")
    graph.add_edge("lightweight_guard", "persist_async")

    graph.add_edge("smalltalk_answer", "persist_async")
    graph.add_edge("direct_answer", "persist_async")
    graph.add_edge("clarify_response", "persist_async")
    graph.add_edge("safety_response", "persist_async")
    graph.add_edge("persist_async", END)

    return graph.compile()
