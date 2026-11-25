"""VBM main graph: from the free-text request to the meeting-prep report (spec sections 3-4)."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from vbm.application.ports import Ports
from vbm.infrastructure.wiring import default_ports
from vbm.infrastructure.workflow.nodes import (
    analyze, confirm_terms, debrief, fan_out, findings_review, make_parse_request, make_write_report, plan_simulations,
    route_after_confirm, route_after_review, route_after_verify, route_start, verify_report,
)
from vbm.infrastructure.workflow.state import MainInput, MainState
from vbm.infrastructure.workflow.subgraph import build_subgraph


# checkpointer בזיכרון, שמורשה לשחזר את מחלקות ה-pydantic שלנו מה-State
def memory_checkpointer() -> InMemorySaver:
    """InMemorySaver that explicitly allows Offer and BuyerDecision in saved state."""
    allowed = [("vbm.domain.schemas", "Offer"), ("vbm.application.dto", "BuyerDecision")]
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowed))


# בניית הגרף הראשי; run_cli מעביר checkpointer, ו-Studio משתמש בגרסה בלי; ה-ports מוזרקים (ברירת מחדל: OpenAI)
def build_graph(checkpointer=None, ports: Ports | None = None):
    """Compile the main graph, optionally with a checkpointer (needed for the interrupts outside Studio)."""
    ports = ports or default_ports()
    builder = StateGraph(MainState, input_schema=MainInput)
    builder.add_node("parse_request", make_parse_request(ports.parser))
    builder.add_node("confirm_terms", confirm_terms)
    builder.add_node("plan_simulations", plan_simulations)
    builder.add_node("negotiate", build_subgraph(ports.buyer_decider))
    builder.add_node("analyze", analyze)
    builder.add_node("findings_review", findings_review)
    builder.add_node("write_report", make_write_report(ports.report_writer))
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
