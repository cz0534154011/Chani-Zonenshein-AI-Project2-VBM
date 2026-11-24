"""VBM main graph: from the free-text request to the meeting-prep report (spec sections 3-4)."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from vbm.nodes import (
    analyze, confirm_terms, debrief, fan_out, findings_review, parse_request, plan_simulations,
    route_after_confirm, route_after_review, route_after_verify, route_start, verify_report, write_report,
)
from vbm.state import MainInput, MainState
from vbm.subgraph import subgraph


# checkpointer בזיכרון, שמורשה לשחזר את מחלקות ה-pydantic שלנו מה-State
def memory_checkpointer() -> InMemorySaver:
    """InMemorySaver that explicitly allows Offer and BuyerDecision in saved state."""
    allowed = [("vbm.schemas", "Offer"), ("vbm.schemas", "BuyerDecision")]
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowed))


# בניית הגרף הראשי; run_cli מעביר checkpointer, ו-Studio משתמש בגרסה בלי
def build_graph(checkpointer=None):
    """Compile the main graph, optionally with a checkpointer (needed for the interrupts outside Studio)."""
    builder = StateGraph(MainState, input_schema=MainInput)
    builder.add_node("parse_request", parse_request)
    builder.add_node("confirm_terms", confirm_terms)
    builder.add_node("plan_simulations", plan_simulations)
    builder.add_node("negotiate", subgraph)
    builder.add_node("analyze", analyze)
    builder.add_node("findings_review", findings_review)
    builder.add_node("write_report", write_report)
    builder.add_node("verify_report", verify_report)
    builder.add_node("debrief", debrief)
    builder.add_conditional_edges(START, route_start, ["parse_request", "plan_simulations"])
    builder.add_edge("parse_request", "confirm_terms")
    builder.add_conditional_edges("confirm_terms", route_after_confirm, ["plan_simulations", "parse_request"])
    builder.add_conditional_edges("plan_simulations", fan_out, ["negotiate"])
    builder.add_edge("negotiate", "analyze")
    builder.add_edge("analyze", "findings_review")
    builder.add_conditional_edges("findings_review", route_after_review,
                                  ["write_report", "plan_simulations", "findings_review"])
    builder.add_edge("write_report", "verify_report")
    builder.add_conditional_edges("verify_report", route_after_verify, ["debrief", "write_report"])
    builder.add_edge("debrief", END)
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
